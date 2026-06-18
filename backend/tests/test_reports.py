"""Analytical report pipeline: chunker, csvbuild, serializer, runner."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import httpx
import pytest

from notebook_forge.blocks import make_block, text_run
from notebook_forge.reports.chunker import OPENING_TITLE, ReportChunk, chunk_document
from notebook_forge.reports.csvbuild import (
    TRACK_HEADERS,
    csv_block,
    validate_widths,
    write_csv,
)
from notebook_forge.reports.runner import GeminiReportRunner, run_chunks
from notebook_forge.reports.serializer import (
    ReportParseError,
    build_chapter_prompt,
    build_system_rules,
    parse_chapter_json,
    parse_consolidate_json,
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
