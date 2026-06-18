"""Analytical report pipeline: chunker, csvbuild, serializer, runner, service."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import make_block, text_run
from notebook_forge.models import Report, ReportTrack
from notebook_forge.reports.chunker import OPENING_TITLE, ReportChunk, chunk_document
from notebook_forge.reports.csvbuild import (
    TRACK_HEADERS,
    csv_block,
    validate_widths,
    write_csv,
)
from notebook_forge.reports.render import ReportData, render_report
from notebook_forge.reports.runner import GeminiReportRunner, run_chunks
from notebook_forge.reports.serializer import (
    ReportParseError,
    build_chapter_prompt,
    build_system_rules,
    parse_chapter_json,
    parse_consolidate_json,
)
from notebook_forge.reports.service import (
    generate_report,
    get_report,
    report_is_stale,
)

# ------------------------------------------------------------------ helpers

def heading(level: int, txt: str) -> dict[str, Any]:
    return make_block("heading", {"level": level}, [text_run(txt)])


def para(txt: str) -> dict[str, Any]:
    return make_block("paragraph", content=[text_run(txt)])


# ------------------------------------------------------------------ chunker

class TestChunker:
    def test_splits_on_level_2_headings(self) -> None:
        blocks = [
            heading(2, "Chapter One"),
            para("First body."),
            heading(2, "Chapter Two"),
            para("Second body."),
        ]
        chunks = chunk_document(blocks)
        assert [c.title for c in chunks] == ["Chapter One", "Chapter Two"]
        assert "## Chapter One" in chunks[0].text
        assert "First body." in chunks[0].text
        assert "Second body." not in chunks[0].text

    def test_leading_content_becomes_opening_chunk(self) -> None:
        blocks = [
            para("An untitled opening vignette."),
            heading(2, "Chapter One"),
            para("Body."),
        ]
        chunks = chunk_document(blocks)
        assert chunks[0].title == OPENING_TITLE
        assert "An untitled opening vignette." in chunks[0].text
        assert chunks[1].title == "Chapter One"

    def test_no_leading_chunk_when_doc_starts_with_heading(self) -> None:
        blocks = [heading(2, "Chapter One"), para("Body.")]
        chunks = chunk_document(blocks)
        assert len(chunks) == 1
        assert chunks[0].title == "Chapter One"

    def test_level_3_headings_become_sections(self) -> None:
        blocks = [
            heading(2, "Chapter One"),
            heading(3, "Interviews"),
            para("Interviewed at the barracks."),
            heading(3, "Attestation"),
            para("Took the oath."),
        ]
        chunks = chunk_document(blocks)
        assert chunks[0].sections == ["Interviews", "Attestation"]
        # Section headings are present in the serialized text for the model.
        assert "### Interviews" in chunks[0].text
        assert "### Attestation" in chunks[0].text

    def test_figure_caption_included_image_data_excluded(self) -> None:
        fig = make_block(
            "forgeImage",
            {
                "assetId": "sha-abc",
                "caption": "Recruits at <em>Kapooka</em>",
                "altText": "alt",
            },
        )
        blocks = [heading(2, "Chapter One"), fig, para("Body.")]
        chunks = chunk_document(blocks)
        text = chunks[0].text
        assert "Recruits at Kapooka" in text  # HTML stripped, caption kept
        assert "sha-abc" not in text  # asset id / image data never leaks in

    def test_narrative_and_footnote_text_included(self) -> None:
        narrative = make_block("forgeNarrative", content=[text_run("Editorial aside.")])
        footnote = make_block("forgeFootnote", {"marker": "1", "text": "A clarifying note."})
        blocks = [heading(2, "Chapter One"), narrative, footnote, para("Body.")]
        text = chunk_document(blocks)[0].text
        assert "Editorial aside." in text
        assert "A clarifying note." in text

    def test_chapter_with_no_body_still_chunked(self) -> None:
        blocks = [heading(2, "Empty Chapter"), heading(2, "Real Chapter"), para("Body.")]
        chunks = chunk_document(blocks)
        assert [c.title for c in chunks] == ["Empty Chapter", "Real Chapter"]

    def test_empty_document(self) -> None:
        assert chunk_document([]) == []


# ------------------------------------------------------------------ csvbuild

class TestCsvBuild:
    def test_embedded_comma_and_quote_round_trip(self) -> None:
        header = TRACK_HEADERS["people"]
        rows = [
            ["src", "Attestation", "Max Haworth", 'Korea ("K Force") veteran, older'],
            ["src", "Joining Up", "Tiger", "stepfather; supportive"],
        ]
        text = write_csv(header, rows)
        parsed = list(csv.reader(io.StringIO(text)))
        assert parsed[0] == header
        assert parsed[1] == rows[0]  # comma + embedded quotes survive intact
        assert parsed[2] == rows[1]

    def test_every_row_has_uniform_width(self) -> None:
        header = TRACK_HEADERS["geo"]
        rows = [["s", "sec", 'place, with comma', "what", "arrival"]]
        text = write_csv(header, rows)
        assert validate_widths(text) == len(header)

    def test_validate_widths_raises_on_mismatch(self) -> None:
        bad = "a,b,c\n1,2\n"
        try:
            validate_widths(bad)
        except ValueError as exc:
            assert "mismatch" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected a width mismatch")

    def test_csv_block_is_fenced(self) -> None:
        block = csv_block(TRACK_HEADERS["glossary"], [["s", "sec", "term", "meaning"]])
        assert block.startswith("```csv\n")
        assert block.endswith("\n```")
        # The inner CSV still validates.
        inner = block[len("```csv\n") : -len("\n```")]
        assert validate_widths(inner) == 4


# ------------------------------------------------------------------ serializer

CHAPTER_JSON = {
    "digest_md": "**Joining Up**\nHe enlisted.",
    "people": [{"section": "Joining Up", "name": "Tiger", "role": "stepfather"}],
    "geo": [],
    "glossary": [],
    "chronology": [],
    "interpersonal_stated": [],
    "interpersonal_inference": [],
    "inconsistencies": [],
    "anchors": [{"section": "Joining Up", "quote": "a way out", "attribution": "Bob"}],
}


class TestSerializer:
    def test_system_rules_append_operator_extra(self) -> None:
        base = build_system_rules()
        assert "SINGLE-SOURCE ISOLATION" in base
        assert "ADDITIONAL OPERATOR RULES" not in base
        with_extra = build_system_rules("Prefer ranks spelled out.")
        assert "ADDITIONAL OPERATOR RULES" in with_extra
        assert "Prefer ranks spelled out." in with_extra

    def test_chapter_prompt_embeds_title_and_text(self) -> None:
        prompt = build_chapter_prompt("1955_army", "Joining Up", "## Joining Up\nHe enlisted.")
        assert '"1955_army"' in prompt
        assert "Joining Up" in prompt
        assert "He enlisted." in prompt

    def test_parse_chapter_fills_defaults(self) -> None:
        data = parse_chapter_json(json.dumps({"digest_md": "**X**\nsome digest"}))
        for key in ("people", "geo", "glossary", "chronology", "anchors"):
            assert data[key] == []

    def test_parse_chapter_tolerates_code_fence(self) -> None:
        raw = "```json\n" + json.dumps(CHAPTER_JSON) + "\n```"
        data = parse_chapter_json(raw)
        assert data["people"][0]["name"] == "Tiger"

    def test_parse_chapter_recovers_from_surrounding_prose(self) -> None:
        raw = "Sure, here you go:\n" + json.dumps(CHAPTER_JSON) + "\nHope that helps!"
        data = parse_chapter_json(raw)
        assert data["digest_md"].startswith("**Joining Up**")

    def test_parse_chapter_rejects_bad_json(self) -> None:
        with pytest.raises(ReportParseError):
            parse_chapter_json("not json at all")

    def test_parse_chapter_rejects_missing_digest(self) -> None:
        with pytest.raises(ReportParseError):
            parse_chapter_json(json.dumps({"people": []}))

    def test_parse_consolidate_uses_fallback_anchors(self) -> None:
        fallback = [{"section": "s", "quote": "q", "attribution": "a"}]
        data = parse_consolidate_json(json.dumps({"executive_summary": "Overview."}), fallback)
        assert data["executive_summary"] == "Overview."
        assert data["anchors"] == fallback


# ------------------------------------------------------------------ runner

def chapter_chunk(idx: int = 0, title: str = "Joining Up") -> ReportChunk:
    return ReportChunk(idx=idx, title=title, sections=[], text=f"## {title}\nbody")


def gemini_transport(replies: list[str], calls: list) -> httpx.MockTransport:
    """Return canned text replies in order; record each request body."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        text = replies[min(len(calls) - 1, len(replies) - 1)]
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
        )

    return httpx.MockTransport(handler)


class TestRunner:
    def test_digest_chapter_sends_system_and_parses(self) -> None:
        calls: list = []
        runner = GeminiReportRunner(
            "test-key", transport=gemini_transport([json.dumps(CHAPTER_JSON)], calls)
        )
        data = runner.digest_chapter(chapter_chunk(), "1955_army")
        assert data["people"][0]["name"] == "Tiger"
        # SYSTEM_RULES travels as the Gemini systemInstruction.
        sent = calls[0]
        assert "SINGLE-SOURCE ISOLATION" in sent["systemInstruction"]["parts"][0]["text"]
        assert sent["generationConfig"]["temperature"] == 0

    def test_digest_chapter_retries_once_on_bad_json(self) -> None:
        calls: list = []
        replies = ["garbage, not json", json.dumps(CHAPTER_JSON)]
        runner = GeminiReportRunner("test-key", transport=gemini_transport(replies, calls))
        data = runner.digest_chapter(chapter_chunk(), "1955_army")
        assert len(calls) == 2  # one retry
        assert data["digest_md"].startswith("**Joining Up**")

    def test_digest_chapter_raises_after_two_bad_replies(self) -> None:
        calls: list = []
        runner = GeminiReportRunner(
            "test-key", transport=gemini_transport(["nope", "still nope"], calls)
        )
        with pytest.raises(Exception):  # noqa: B017 — runner wraps the parse error
            runner.digest_chapter(chapter_chunk(), "1955_army")

    def test_run_chunks_preserves_chapter_order_and_reports_progress(self) -> None:
        calls: list = []
        runner = GeminiReportRunner(
            "test-key", transport=gemini_transport([json.dumps(CHAPTER_JSON)], calls)
        )
        chunks = [chapter_chunk(0, "One"), chapter_chunk(1, "Two"), chapter_chunk(2, "Three")]
        done: list[bool] = []
        ordered, failed = run_chunks(
            chunks, runner, "1955_army", on_chunk_done=lambda f: done.append(f)
        )
        assert [t for t, _ in ordered] == ["One", "Two", "Three"]
        assert failed == []
        assert len(done) == 3

    def test_run_chunks_records_failed_chapter(self) -> None:
        calls: list = []
        runner = GeminiReportRunner(
            "test-key", transport=gemini_transport(["bad", "bad"], calls)
        )
        ordered, failed = run_chunks([chapter_chunk(0, "One")], runner, "1955_army")
        assert ordered == []
        assert len(failed) == 1
        assert "chapter 0" in failed[0]


# ------------------------------------------------------------------ render

class TestRender:
    def test_renders_locked_section_order_and_provenance(self) -> None:
        data = ReportData(
            title="Junior",
            author="R.F. Skitch",
            years="1934–1945",
            source_name="1934-1945_junior",
            word_count=25742,
            exec_summary="A childhood in Collie.",
            digest_md="**Preamble**\nBorn 1934.",
            stated=["Junior loved his Dad."],
            inferences=["[INFERENCE] domestic strain (Anchored to Mum.)"],
            inconsistencies=["Withall / Withell spelling variants."],
            anchors=[{"section": "The family", "quote": "tits look big", "attribution": "Junior"}],
            tracks={
                "people": [{"section": "Preamble", "name": "Tiger", "role": "stepfather"}],
                "geo": [],
                "glossary": [],
                "chronology": [],
            },
        )
        body = render_report(data)
        # Section order.
        for marker in (
            "# Analytical Report — *Junior*",
            "### 0. Provenance header",
            "### 1. Executive summary",
            "### 2. Section-by-section digest",
            "### 3. Interpersonal & familial dynamics",
            "### 4. Source inconsistencies & open questions",
            "### 5. Notable verbatim anchors",
            "### 6. Reference tracks",
        ):
            assert marker in body
        assert body.index("### 0.") < body.index("### 6.")
        # Provenance specifics.
        assert "**Source name (NotebookLM):** 1934-1945_junior" in body
        assert "25,742" in body  # word count formatted with thousands separator
        assert "the original memoir is authoritative" in body
        # §6 CSV blocks, one per track, with the locked headers.
        assert "**6a. People register**" in body
        assert "source,section,name,role_or_relationship" in body
        assert "1934-1945_junior,Preamble,Tiger,stepfather" in body

    def test_empty_sections_use_none_fallbacks(self) -> None:
        data = ReportData(
            title="T", author="A", years="", source_name="s", word_count=0,
            exec_summary="", digest_md="",
        )
        body = render_report(data)
        assert "- (none recorded)" in body  # stated
        assert "- (none identified)" in body  # inconsistencies
        assert "- (none selected)" in body  # anchors


# ------------------------------------------------------------------ service

def chapter_digest(section: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "digest_md": f"**{section}**\nDigest of {section}.",
        "people": [],
        "geo": [],
        "glossary": [],
        "chronology": [],
        "interpersonal_stated": [],
        "interpersonal_inference": [],
        "inconsistencies": [],
        "anchors": [],
    }
    base.update(over)
    return base


class FakeReportRunner:
    """Returns a scripted digest per chapter title; trivial consolidation."""

    def __init__(self, by_title: dict[str, dict[str, Any]]) -> None:
        self.by_title = by_title
        self.model = "fake-report-model"

    def digest_chapter(
        self, chunk: ReportChunk, source_name: str, *, extra_rules: str = ""
    ) -> dict[str, Any]:
        return self.by_title[chunk.title]

    def consolidate(
        self, source_name: str, years: str, chapters_data, *, extra_rules: str = ""
    ) -> dict[str, Any]:
        cands = [a for _, d in chapters_data for a in d.get("anchors", [])]
        return {"executive_summary": "Whole-document overview.", "anchors": cands[:8]}


def make_doc(session: Session, blocks: list[dict[str, Any]], slug: str = "doc-1") -> Any:
    return services.create_document(
        session, slug, "Test Memoir", blocks, meta={"slug": slug, "author": "R.F. Skitch"}
    )


class TestService:
    def _two_chapter_doc(self, session: Session) -> Any:
        return make_doc(
            session,
            [heading(2, "One"), para("Body one."), heading(2, "Two"), para("Body two.")],
        )

    def test_generate_persists_report_and_tracks(self, session: Session, workspace: Path) -> None:
        doc = self._two_chapter_doc(session)
        runner = FakeReportRunner({
            "One": chapter_digest(
                "One",
                people=[{"section": "One", "name": "Tiger", "role": "stepfather"}],
                chronology=[{"section": "One", "marker": "1955", "event": "enlisted"}],
                anchors=[{"section": "One", "quote": "a way out", "attribution": "Bob"}],
            ),
            "Two": chapter_digest(
                "Two",
                people=[{"section": "Two", "name": "Major Buckland", "role": "officer"}],
                chronology=[{"section": "Two", "marker": "1956", "event": "posted"}],
            ),
        })
        result = generate_report(session, workspace, doc, runner=runner)
        assert result["status"] == "generated"
        assert result["chapters"] == 2

        report = get_report(session, doc)
        assert report is not None
        assert report.source_name == "doc-1"
        assert report.model == "fake-report-model"
        assert report.exec_summary == "Whole-document overview."
        assert "### 6. Reference tracks" in report.body_md

        people = session.scalars(
            select(ReportTrack).where(
                ReportTrack.document_id == doc.id, ReportTrack.track_type == "people"
            )
        ).all()
        assert {r.data["name"] for r in people} == {"Tiger", "Major Buckland"}

    def test_intra_doc_dedup_keep_first_and_chronology_keep_all(
        self, session: Session, workspace: Path
    ) -> None:
        doc = self._two_chapter_doc(session)
        runner = FakeReportRunner({
            "One": chapter_digest(
                "One",
                people=[{"section": "One", "name": "Tiger", "role": "stepfather"}],
                geo=[{"section": "One", "place": "Perth", "what": "home", "arrival": "-"}],
                glossary=[{"section": "One", "term": "KD", "meaning": "khaki drill"}],
                chronology=[{"section": "One", "marker": "1955", "event": "enlisted"}],
                interpersonal_stated=["Tiger was supportive."],
            ),
            "Two": chapter_digest(
                "Two",
                # duplicate name / place / term (casefold) → dropped by keep-first
                people=[{"section": "Two", "name": "tiger", "role": "stepfather again"}],
                geo=[{"section": "Two", "place": "perth", "what": "revisited", "arrival": "-"}],
                glossary=[{"section": "Two", "term": "kd", "meaning": "khaki drill dup"}],
                # chronology is kept in full
                chronology=[{"section": "Two", "marker": "1956", "event": "posted"}],
                interpersonal_stated=["Tiger was supportive."],  # duplicate line dropped
            ),
        })
        generate_report(session, workspace, doc, runner=runner)

        def rows(track: str) -> list[ReportTrack]:
            return session.scalars(
                select(ReportTrack).where(
                    ReportTrack.document_id == doc.id, ReportTrack.track_type == track
                ).order_by(ReportTrack.seq)
            ).all()

        assert len(rows("people")) == 1  # keep first "Tiger"
        assert rows("people")[0].data["role"] == "stepfather"
        assert len(rows("geo")) == 1
        assert len(rows("glossary")) == 1
        assert len(rows("chronology")) == 2  # keep all
        report = get_report(session, doc)
        assert report.body_md.count("Tiger was supportive.") == 1  # §3 line deduped

    def test_regenerate_replaces_rows_idempotently(
        self, session: Session, workspace: Path
    ) -> None:
        doc = self._two_chapter_doc(session)
        runner = FakeReportRunner({
            "One": chapter_digest("One", people=[{"section": "One", "name": "Tiger", "role": "x"}]),
            "Two": chapter_digest("Two"),
        })
        generate_report(session, workspace, doc, runner=runner)
        generate_report(session, workspace, doc, runner=runner)

        # Exactly one Report row and no doubled track rows after a second run.
        reports = session.scalars(select(Report).where(Report.document_id == doc.id)).all()
        assert len(reports) == 1
        people = session.scalars(
            select(ReportTrack).where(
                ReportTrack.document_id == doc.id, ReportTrack.track_type == "people"
            )
        ).all()
        assert len(people) == 1

    def test_regenerate_one_doc_leaves_other_doc_rows_untouched(
        self, session: Session, workspace: Path
    ) -> None:
        doc_a = make_doc(
            session, [heading(2, "One"), para("a")], slug="doc-a"
        )
        doc_b = make_doc(
            session, [heading(2, "One"), para("b")], slug="doc-b"
        )
        runner = FakeReportRunner({
            "One": chapter_digest(
                "One", people=[{"section": "One", "name": "Person", "role": "r"}]
            ),
        })
        generate_report(session, workspace, doc_a, runner=runner)
        generate_report(session, workspace, doc_b, runner=runner)
        # Regenerating A must not delete B's rows.
        generate_report(session, workspace, doc_a, runner=runner)

        b_rows = session.scalars(
            select(ReportTrack).where(ReportTrack.document_id == doc_b.id)
        ).all()
        assert len(b_rows) == 1
        assert b_rows[0].source_name == "doc-b"

    def test_report_staleness_tracks_document_changes(
        self, session: Session, workspace: Path
    ) -> None:
        doc = self._two_chapter_doc(session)
        runner = FakeReportRunner({"One": chapter_digest("One"), "Two": chapter_digest("Two")})
        generate_report(session, workspace, doc, runner=runner)
        report = get_report(session, doc)
        assert report_is_stale(session, doc, report) is False

        services.save_blocks(session, doc, [*doc.blocks, para("A new paragraph.")])
        assert report_is_stale(session, doc, report) is True


# ------------------------------------------------------------------ API

class GenericFakeRunner:
    """A runner returning a digest for any chapter title (for endpoint tests)."""

    model = "fake-report-model"

    def digest_chapter(
        self, chunk: ReportChunk, source_name: str, *, extra_rules: str = ""
    ) -> dict[str, Any]:
        return chapter_digest(
            chunk.title,
            people=[{"section": chunk.title, "name": "Tiger", "role": "stepfather"}],
        )

    def consolidate(
        self, source_name: str, years: str, chapters_data, *, extra_rules: str = ""
    ) -> dict[str, Any]:
        return {"executive_summary": "Overview.", "anchors": []}


class TestReportApi:
    def _client(self, session: Session):  # noqa: ANN202
        from fastapi.testclient import TestClient

        from notebook_forge.api import app, get_session

        app.dependency_overrides[get_session] = lambda: session
        return TestClient(app)

    def test_get_report_never_run(self, session: Session) -> None:
        doc = make_doc(session, [heading(2, "One"), para("Body.")])
        client = self._client(session)
        data = client.get(f"/api/documents/{doc.slug}/report").json()
        assert data["exists"] is False
        assert data["body_md"] == ""

    def test_progress_zero_shape_for_unknown(self, session: Session) -> None:
        client = self._client(session)
        data = client.get("/api/documents/whatever/report/progress").json()
        assert data == {"running": False, "done": 0, "total": 0, "failed": 0}

    def test_settings_round_trip(self, session: Session) -> None:
        client = self._client(session)
        resp = client.put(
            "/api/settings/reports", json={"model": "gemini-3.5-flash", "rules": "Be terse."}
        )
        assert resp.status_code == 200
        settings = client.get("/api/settings").json()
        assert settings["reports"] == {"model": "gemini-3.5-flash", "rules": "Be terse."}

    def test_generate_409_without_key(self, session: Session, monkeypatch) -> None:
        # No Gemini key in the test env → make_runner raises RuntimeError → 409.
        def no_key(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("report generation is not configured")

        monkeypatch.setattr("notebook_forge.reports.runner.make_runner", no_key)
        doc = make_doc(session, [heading(2, "One"), para("Body.")])
        client = self._client(session)
        resp = client.post(f"/api/documents/{doc.slug}/report/generate")
        assert resp.status_code == 409

    def test_generate_happy_path_with_injected_runner(
        self, session: Session, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "notebook_forge.reports.runner.make_runner",
            lambda *_a, **_k: GenericFakeRunner(),
        )
        doc = make_doc(
            session,
            [heading(2, "One"), para("Body."), heading(2, "Two"), para("More.")],
        )
        client = self._client(session)
        resp = client.post(f"/api/documents/{doc.slug}/report/generate")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["ok"] is True
        assert payload["report"]["exists"] is True
        assert payload["report"]["stale"] is False
        assert payload["report"]["tracks"]["people"] == 1  # Tiger deduped across chapters

        body = client.get(f"/api/documents/{doc.slug}/report").json()["body_md"]
        assert "### 6. Reference tracks" in body
