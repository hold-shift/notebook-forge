"""Analytical report pipeline: chunker, csvbuild (more to follow per build step)."""

from __future__ import annotations

import csv
import io
from typing import Any

from notebook_forge.blocks import make_block, text_run
from notebook_forge.reports.chunker import OPENING_TITLE, chunk_document
from notebook_forge.reports.csvbuild import (
    TRACK_HEADERS,
    csv_block,
    validate_widths,
    write_csv,
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
