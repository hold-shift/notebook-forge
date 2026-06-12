"""LLM polish: textmap round-trip, chunker, serializer, fidelity, service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import make_block, text_run
from notebook_forge.models import Change, Snapshot
from notebook_forge.polish.chunker import BlockRef, Chunk
from notebook_forge.polish.fidelity import check_block_fidelity
from notebook_forge.polish.serializer import (
    SerializationError,
    coverage_ratio,
    parse_polished_jsonl,
    serialize_chunk_for_prompt,
)
from notebook_forge.polish.service import polish_document, polish_settings
from notebook_forge.polish.textmap import (
    block_to_polish_text,
    polish_text_to_content,
    polishable_blocks,
)

# ------------------------------------------------------------------ helpers

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "frontend" / "src" / "test" / "fixtures" / "junior.blocks.json"
)


def para(txt: str, block_id: str = "test-para") -> dict[str, Any]:
    return make_block("paragraph", content=[text_run(txt)]) | {"id": block_id}


def styled_para(runs: list[dict], block_id: str = "test-styled") -> dict[str, Any]:
    return make_block("paragraph", content=runs) | {"id": block_id}


def heading(level: int, txt: str, block_id: str = "test-h") -> dict[str, Any]:
    return make_block("heading", {"level": level}, [text_run(txt)]) | {"id": block_id}


def make_chunk(blocks_data: list[tuple[str, str, str]]) -> Chunk:
    refs = [BlockRef(block_id=bid, idx=i, kind=k, text=t)
            for i, (bid, k, t) in enumerate(blocks_data)]
    return Chunk(idx=0, blocks=refs)


def doc_with_blocks(session: Session, blocks: list[dict]) -> Any:
    return services.create_document(session, "test-doc", "Test", blocks)


# ------------------------------------------------------------------ textmap

class TestBlockToPolishText:
    def test_plain_text_round_trips(self) -> None:
        block = para("Hello world.", "p1")
        text = block_to_polish_text(block)
        assert text == "Hello world."
        assert polish_text_to_content(text) == [text_run("Hello world.")]

    def test_bold_round_trips(self) -> None:
        block = styled_para([text_run("very ", {}), text_run("bold", {"bold": True})], "b1")
        text = block_to_polish_text(block)
        assert text == "very **bold**"
        content = polish_text_to_content(text)
        assert content == [text_run("very "), text_run("bold", {"bold": True})]

    def test_italic_round_trips(self) -> None:
        block = styled_para([text_run("an ", {}), text_run("italic", {"italic": True}),
                             text_run(" word")], "i1")
        text = block_to_polish_text(block)
        assert text == "an *italic* word"
        content = polish_text_to_content(text)
        assert content == [text_run("an "), text_run("italic", {"italic": True}),
                           text_run(" word")]

    def test_bold_italic_round_trips(self) -> None:
        block = styled_para([text_run("both", {"bold": True, "italic": True})], "bi1")
        text = block_to_polish_text(block)
        assert text == "***both***"
        content = polish_text_to_content(text)
        assert content == [text_run("both", {"bold": True, "italic": True})]

    def test_fnref_becomes_caret_marker(self) -> None:
        block = styled_para([text_run("word"), text_run("1", {"fnRef": True})], "fn1")
        text = block_to_polish_text(block)
        assert text == "word[^1]"
        content = polish_text_to_content(text)
        assert content == [text_run("word"), text_run("1", {"fnRef": True})]

    def test_link_round_trips(self) -> None:
        block = make_block("paragraph", content=[
            {"type": "link", "href": "https://example.com", "content": [text_run("Example")]},
        ]) | {"id": "lnk1"}
        text = block_to_polish_text(block)
        assert text == "[Example](https://example.com)"
        content = polish_text_to_content(text)
        assert content == [{"type": "link", "href": "https://example.com",
                            "content": [text_run("Example")]}]

    def test_heading_kind(self) -> None:
        h = heading(2, "Chapter One", "h2a")
        poly = polishable_blocks([h])
        assert poly[0][1] == "h2"
        assert poly[0][2] == "Chapter One"

    def test_forgeImage_excluded(self) -> None:
        blocks = [
            make_block("forgeImage", {"assetId": "abc", "sketchAssetId": ""}),
            para("Some prose", "p1"),
        ]
        poly = polishable_blocks(blocks)
        assert len(poly) == 1
        assert poly[0][2] == "Some prose"

    def test_empty_block_excluded(self) -> None:
        block = make_block("paragraph", content=[text_run("   ")]) | {"id": "blank"}
        assert polishable_blocks([block]) == []

    def test_forge_narrative_is_polishable(self) -> None:
        """forgeNarrative block participates in polish (D16): typo is reachable."""
        block = (
            make_block("forgeNarrative", content=[text_run("Lookng back on those yeras.")])
            | {"id": "narr1"}
        )
        poly = polishable_blocks([block])
        assert len(poly) == 1
        bid, kind, text = poly[0]
        assert bid == "narr1"
        assert kind == "p"  # narrative serialises as kind p (existing else-branch)
        assert "yeras" in text  # the typo is present
        # round-trip: correcting the text and applying back works
        corrected = polish_text_to_content("Looking back on those years.")
        assert any(r["text"] == "Looking back on those years." for r in corrected)


class TestJuniorRoundTrip:
    """Every paragraph/heading in the Junior fixture must survive the round-trip."""

    @pytest.fixture(scope="class")
    def junior_blocks(self) -> list[dict]:
        if not FIXTURE_PATH.exists():
            pytest.skip("junior fixture not found")
        return json.loads(FIXTURE_PATH.read_text())

    def test_round_trip_all_polishable(self, junior_blocks: list[dict]) -> None:
        poly = polishable_blocks(junior_blocks)
        assert len(poly) > 0, "No polishable blocks found in Junior fixture"
        for bid, _kind, text in poly:
            recovered = polish_text_to_content(text)
            # Round-trip: re-serialise the recovered content and compare text
            recovered_text = block_to_polish_text({"content": recovered})
            assert recovered_text == text, (
                f"Round-trip failed for block {bid!r}: "
                f"got {recovered_text!r}, expected {text!r}"
            )


# ------------------------------------------------------------------ serializer

class TestSerializer:
    def _make_chunk(self, n: int = 2) -> Chunk:
        return make_chunk([
            (f"uuid-{i:04d}", "p", f"Block {i} text here.")
            for i in range(n)
        ])

    def test_well_formed_response_parses(self) -> None:
        chunk = self._make_chunk(2)
        raw = json.dumps([
            {"id": "b000", "kind": "p", "text": "Block 0 text here."},
            {"id": "b001", "kind": "p", "text": "Block 1 text here."},
        ])
        result = parse_polished_jsonl(raw, chunk)
        assert result == {"uuid-0000": "Block 0 text here.", "uuid-0001": "Block 1 text here."}

    def test_fenced_code_block_stripped(self) -> None:
        chunk = self._make_chunk(1)
        raw = '```json\n[{"id":"b000","kind":"p","text":"Fine."}]\n```'
        result = parse_polished_jsonl(raw, chunk)
        assert result["uuid-0000"] == "Fine."

    def test_coverage_ratio_full(self) -> None:
        chunk = self._make_chunk(2)
        parsed = {"uuid-0000": "a", "uuid-0001": "b"}
        assert coverage_ratio(parsed, chunk) == 1.0

    def test_coverage_ratio_partial(self) -> None:
        chunk = self._make_chunk(2)
        parsed = {"uuid-0000": "a"}
        assert coverage_ratio(parsed, chunk) == 0.5

    def test_missing_block_raises(self) -> None:
        chunk = self._make_chunk(2)
        raw = json.dumps([{"id": "b000", "kind": "p", "text": "Only first."}])
        with pytest.raises(SerializationError, match="missing polished output"):
            parse_polished_jsonl(raw, chunk)

    def test_unexpected_id_raises(self) -> None:
        chunk = self._make_chunk(1)
        raw = json.dumps([
            {"id": "b000", "kind": "p", "text": "Fine."},
            {"id": "b999", "kind": "p", "text": "Extra."},
        ])
        with pytest.raises(SerializationError, match="unexpected id"):
            parse_polished_jsonl(raw, chunk)

    def test_context_block_slipping_through_is_silently_dropped(self) -> None:
        refs = [BlockRef(block_id="ctx-id", idx=0, kind="p", text="Context."),
                BlockRef(block_id="main-id", idx=1, kind="p", text="Main.")]
        chunk = Chunk(idx=0, blocks=[refs[1]], context_block=refs[0])
        raw = json.dumps([
            {"id": "ctx", "kind": "p", "text": "Context."},
            {"id": "b000", "kind": "p", "text": "Main."},
        ])
        result = parse_polished_jsonl(raw, chunk)
        assert "ctx-id" not in result
        assert result["main-id"] == "Main."

    def test_serialize_chunk_has_preamble_and_lines(self) -> None:
        chunk = self._make_chunk(2)
        prompt = serialize_chunk_for_prompt(chunk)
        assert "MECHANICAL polish" in prompt
        assert "POLISH " in prompt
        assert "b000" in prompt
        assert "b001" in prompt
        assert "uuid-0000" not in prompt  # full UUIDs must not appear in prompt

    def test_extra_rules_appear_in_prompt(self) -> None:
        chunk = self._make_chunk(1)
        prompt = serialize_chunk_for_prompt(chunk, extra_rules="Never shorten sentences.")
        assert "Never shorten sentences." in prompt


# ------------------------------------------------------------------ fidelity

class TestFidelity:
    def test_identical_text_is_clean(self) -> None:
        v = check_block_fidelity("Hello world.", "Hello world.", "b1")
        assert v.is_clean
        assert v.typography_only
        assert v.summary == "typography only"

    def test_smart_quote_fix_is_clean(self) -> None:
        v = check_block_fidelity('She said "hello".', "She said “hello”.", "b1")
        assert v.is_clean
        assert v.typography_only

    def test_double_space_fix_is_clean(self) -> None:
        v = check_block_fidelity("word  here", "word here", "b1")
        assert v.is_clean

    def test_word_insertion_flags(self) -> None:
        v = check_block_fidelity("Hello world.", "Hello beautiful world.", "b1")
        assert not v.is_clean
        assert v.word_inserts == 1

    def test_word_deletion_flags(self) -> None:
        v = check_block_fidelity("Hello beautiful world.", "Hello world.", "b1")
        assert not v.is_clean
        assert v.word_deletes == 1

    def test_word_replacement_flags(self) -> None:
        v = check_block_fidelity("sailers", "sailors", "b1")
        assert not v.is_clean
        assert v.word_replaces >= 1

    def test_hyphen_space_collapse_is_clean(self) -> None:
        # "re setting" → "re-setting" is a typography change (same letters)
        v = check_block_fidelity("re setting", "re-setting", "b1")
        assert v.is_clean

    def test_emphasis_marker_move_is_clean(self) -> None:
        # Emphasis markers removed from both sides in normalisation
        v = check_block_fidelity("**hello** world", "hello world", "b1")
        assert v.is_clean

    def test_fnref_dropped_flags_regardless_of_words(self) -> None:
        # Marker dropped → must flag regardless of whether word diff catches it.
        # (In this case the word diff also catches "1" disappearing; we check
        # that marker_mismatch is set too so it would catch the quieter case
        # of a marker moving inside punctuation where word tokens stay equal.)
        v = check_block_fidelity("word[^1] here", "word here", "b1")
        assert not v.is_clean
        assert v.marker_mismatch

    def test_fnref_added_flags(self) -> None:
        v = check_block_fidelity("word here", "word[^1] here", "b1")
        assert not v.is_clean
        assert v.marker_mismatch

    def test_fnref_preserved_is_clean(self) -> None:
        # Smart-quote fix around a footnote marker is still clean
        v = check_block_fidelity('word[^1] "here"', "word[^1] “here”", "b1")
        assert v.is_clean
        assert not v.marker_mismatch


# ------------------------------------------------------------------ service

class MockRunner:
    """Scriptable runner that returns pre-canned {block_id: polished_text}."""
    def __init__(self, responses: list[dict[str, str]]) -> None:
        self.responses = list(responses)
        self.model = "mock-gemini"
        self.call_count = 0

    def run_chunk(self, chunk: Chunk, *, extra_rules: str = "") -> dict[str, str]:
        result = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return result


class FailingRunner:
    """Runner that raises on the first call, succeeds on subsequent calls."""
    def __init__(self, fail_count: int = 1) -> None:
        self.fail_count = fail_count
        self.model = "mock-gemini"
        self.call_count = 0

    def run_chunk(self, chunk: Chunk, *, extra_rules: str = "") -> dict[str, str]:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError("mock transport error")
        return {b.id: b.text for b in chunk.blocks}


class AlwaysFailRunner:
    def __init__(self) -> None:
        self.model = "mock-gemini"

    def run_chunk(self, chunk: Chunk, *, extra_rules: str = "") -> dict[str, str]:
        raise RuntimeError("always fails")


class TestService:
    def _make_doc(self, session: Session, text: str = "Hello world.") -> Any:
        blocks = [make_block("paragraph", content=[text_run(text)])]
        return services.create_document(session, "test-doc", "Test", blocks)

    def test_snapshot_always_taken(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session)
        runner = MockRunner([{b["id"]: "Hello world." for b in doc.blocks}])
        polish_document(session, workspace, doc, runner=runner)
        snaps = list(session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(Snapshot)
            .where(Snapshot.document_id == doc.id)
        ))
        assert len(snaps) >= 1
        assert snaps[0].note == "before polish"

    def test_echo_model_no_block_change(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session, "Hello world.")
        block_id = doc.blocks[0]["id"]
        runner = MockRunner([{block_id: "Hello world."}])
        report = polish_document(session, workspace, doc, runner=runner)
        assert report["blocks_polished"] == 0
        assert report["flagged"] == []
        # Doc blocks must be untouched
        assert doc.blocks[0]["content"][0]["text"] == "Hello world."

    def test_typography_fix_auto_applied(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session, 'She said "hello".')
        block_id = doc.blocks[0]["id"]
        # Smart-quote fix is typography-only → auto-applied
        runner = MockRunner([{block_id: "She said “hello”."}])
        report = polish_document(session, workspace, doc, runner=runner)
        assert report["blocks_polished"] == 1
        assert report["flagged"] == []
        # Block content updated in place
        from notebook_forge.polish.textmap import block_to_polish_text
        assert block_to_polish_text(doc.blocks[0]) == "She said “hello”."
        # Change log must have entries (snapshot + save_blocks + record_change)
        from sqlalchemy import select
        changes = list(session.scalars(
            select(Change).where(Change.document_id == doc.id).order_by(Change.id)
        ))
        summaries = [c.summary for c in changes]
        assert any("polish" in s and "cleaned" in s for s in summaries)

    def test_word_change_flagged_not_applied(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session, "sailers went home.")
        block_id = doc.blocks[0]["id"]
        runner = MockRunner([{block_id: "sailors went home."}])
        report = polish_document(session, workspace, doc, runner=runner)
        assert report["blocks_polished"] == 0
        assert len(report["flagged"]) == 1
        f = report["flagged"][0]
        assert f["block_id"] == block_id
        assert f["original"] == "sailers went home."
        assert f["polished"] == "sailors went home."
        assert "polished_content" in f
        # Block NOT updated in the doc
        assert doc.blocks[0]["content"][0]["text"] == "sailers went home."

    def test_empty_doc_no_runner_call(self, session: Session, workspace: Path) -> None:
        # Only forgeImage blocks → no polishable content
        blocks = [make_block("forgeImage", {"assetId": "abc", "sketchAssetId": ""})]
        doc = services.create_document(session, "img-only", "Img", blocks)
        runner = MockRunner([])
        report = polish_document(session, workspace, doc, runner=runner)
        assert report["blocks_polished"] == 0
        assert runner.call_count == 0

    def test_failed_chunk_reported(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session, "Some text.")
        runner = AlwaysFailRunner()
        report = polish_document(session, workspace, doc, runner=runner)
        assert len(report["failed_chunks"]) >= 1
        assert report["blocks_polished"] == 0


class TestPolishSettings:
    def test_defaults(self, session: Session) -> None:
        from notebook_forge.polish.runner import POLISH_MODEL
        cfg = polish_settings(session)
        assert cfg["model"] == POLISH_MODEL
        assert cfg["extra_rules"] == ""

    def test_override(self, session: Session) -> None:
        from notebook_forge.models import Setting
        session.add(Setting(key="polish", value={
            "model": "gemini-2.5-flash-lite",
            "extra_rules": "Never shorten.",
        }))
        session.flush()
        cfg = polish_settings(session)
        assert cfg["model"] == "gemini-2.5-flash-lite"
        assert cfg["extra_rules"] == "Never shorten."


# ------------------------------------------------------------------ diff_segments

class TestDiffSegments:
    def _segs(self, orig: str, pol: str):
        from notebook_forge.polish.fidelity import diff_segments
        return diff_segments(orig, pol)

    def _roundtrip(self, orig: str, pol: str) -> None:
        segs = self._segs(orig, pol)
        assert "".join(s["a"] for s in segs) == orig
        assert "".join(s["b"] for s in segs) == pol

    def test_identical_is_all_equal(self) -> None:
        segs = self._segs("Hello world.", "Hello world.")
        assert all(s["op"] == "equal" for s in segs)
        self._roundtrip("Hello world.", "Hello world.")

    def test_word_replace_detected(self) -> None:
        segs = self._segs("sailers went home.", "sailors went home.")
        ops = [s["op"] for s in segs]
        assert "replace" in ops
        self._roundtrip("sailers went home.", "sailors went home.")

    def test_insert_at_end(self) -> None:
        segs = self._segs("Hello world.", "Hello beautiful world.")
        ops = [s["op"] for s in segs]
        assert "insert" in ops
        self._roundtrip("Hello world.", "Hello beautiful world.")

    def test_smart_quote_change_shows_as_replace(self) -> None:
        # Smart-quote change is NOT normalised away here (unlike fidelity check)
        orig = 'She said "hello".'
        pol = "She said “hello”."
        segs = self._segs(orig, pol)
        ops = [s["op"] for s in segs]
        assert "replace" in ops
        self._roundtrip(orig, pol)

    def test_round_trip_various(self) -> None:
        cases = [
            ("Hello world.", "Hello world."),
            ("sailers", "sailors"),
            ("Hello world.", "Hello beautiful world."),
            ("Hello world extra.", "Hello world."),
            ("word[^1] here", "word[^1] here"),
        ]
        for orig, pol in cases:
            self._roundtrip(orig, pol)


# ------------------------------------------------------------------ progress tracking

class TestProgressTracking:
    def _make_doc(self, session: Session, text: str = "Hello world.") -> Any:
        blocks = [make_block("paragraph", content=[text_run(text)])]
        return services.create_document(session, "prog-doc", "Prog", blocks)

    def test_progress_total_set_to_chunk_count(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session)
        block_id = doc.blocks[0]["id"]
        runner = MockRunner([{block_id: "Hello world."}])
        progress: dict = {"running": True, "done": 0, "total": 0, "failed": 0}
        polish_document(session, workspace, doc, runner=runner, progress=progress)
        assert progress["total"] > 0
        assert progress["done"] == progress["total"]
        assert progress["failed"] == 0

    def test_progress_failed_incremented_on_chunk_error(
        self, session: Session, workspace: Path,
    ) -> None:
        doc = self._make_doc(session, "Some text.")
        runner = AlwaysFailRunner()
        progress: dict = {"running": True, "done": 0, "total": 0, "failed": 0}
        polish_document(session, workspace, doc, runner=runner, progress=progress)
        assert progress["total"] > 0
        assert progress["failed"] > 0
        assert progress["done"] == progress["total"]

    def test_progress_none_does_not_raise(self, session: Session, workspace: Path) -> None:
        doc = self._make_doc(session)
        block_id = doc.blocks[0]["id"]
        runner = MockRunner([{block_id: "Hello world."}])
        # No progress dict — must work exactly as before
        report = polish_document(session, workspace, doc, runner=runner, progress=None)
        assert report["blocks_polished"] == 0


# ------------------------------------------------------------------ diff in flagged blocks

class TestFlaggedBlockDiff:
    def test_flagged_block_carries_diff(self, session: Session, workspace: Path) -> None:
        blocks = [make_block("paragraph", content=[text_run("sailers went home.")])]
        doc = services.create_document(session, "diff-doc", "Diff", blocks)
        block_id = doc.blocks[0]["id"]
        runner = MockRunner([{block_id: "sailors went home."}])
        report = polish_document(session, workspace, doc, runner=runner)
        assert len(report["flagged"]) == 1
        f = report["flagged"][0]
        assert "diff" in f
        segs = f["diff"]
        assert isinstance(segs, list)
        assert len(segs) > 0
        # Round-trip: a-concat == original, b-concat == polished
        assert "".join(s["a"] for s in segs) == f["original"]
        assert "".join(s["b"] for s in segs) == f["polished"]
        # The replace segment is present
        assert any(s["op"] == "replace" for s in segs)

    def test_auto_applied_blocks_have_no_diff(self, session: Session, workspace: Path) -> None:
        # Typography-only change is auto-applied, not in flagged, so no diff expected there
        blocks = [make_block("paragraph", content=[text_run('She said "hello".')])]
        doc = services.create_document(session, "nodiff-doc", "NoDiff", blocks)
        block_id = doc.blocks[0]["id"]
        runner = MockRunner([{block_id: "She said “hello”."}])
        report = polish_document(session, workspace, doc, runner=runner)
        assert report["blocks_polished"] == 1
        assert report["flagged"] == []
