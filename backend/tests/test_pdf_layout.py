"""Layout recovery from PDFs of scanned/transcribed documents.

Covers the four failures found on "ANNEXES combined.pdf" (a 97-page bundle of
typewritten operation orders): ruled tables flattened into run-on paragraphs,
numbered sequences glued together, annex headings emitted twice because each
annex has a divider page, and section labels levelled below their own titles.
"""

from __future__ import annotations

from notebook_forge.ingest_vendor.clean import (
    _dedupe_repeated_headings,
    _merge_table_continuations,
    _promote_section_labels,
)
from notebook_forge.ingest_vendor.extract_pdf import (
    _FOOTNOTE_LEAD_RE,
    _key_notes_by_printed_number,
    _resolve_marker_placeholders,
    _split_orphan_footnotes,
    _unbind_unknown_refs,
)
from notebook_forge.ingest_vendor.footnotes import bind_legacy_digit_refs
from notebook_forge.ingest_vendor.model import DocumentDraft
from notebook_forge.ingest_vendor.polish import polish_body
from notebook_forge.ingestion import table_block
from notebook_forge.renderer import _table_html


def draft(body: list[dict]) -> DocumentDraft:
    return DocumentDraft(source_file="x.pdf", source_sha256="0" * 64, body=body)


# ------------------------------------------------------------------ tables


def test_table_block_pads_ragged_rows() -> None:
    """A merged header cell comes back short; the renderer addresses cells by
    position, so every row is padded to the widest."""
    block = table_block([["UNIT", "MAPS"], ["HQ 1ATF", "10", "20"]])
    rows = block["content"]["rows"]
    assert [len(r["cells"]) for r in rows] == [3, 3]
    assert rows[0]["cells"][2]["content"] == []


def test_table_html_detects_header_row() -> None:
    """Labels on top → the first row is a <thead>. '1:5,000' is a map scale
    used as a column label, so it must not read as a bare quantity."""
    html = _table_html(table_block([["UNIT", "1:5,000"], ["HQ 1ATF", "10"]]))
    assert "<thead><tr><th>UNIT</th><th>1:5,000</th></tr></thead>" in html
    assert "<td>HQ 1ATF</td>" in html
    assert html.startswith('<div class="table-wrap">')


def test_table_html_no_header_when_first_row_is_a_continuation() -> None:
    """A table continued from the previous page opens mid-data — no header."""
    html = _table_html(table_block([["20", "OPERATION SMITHFIELD"], ["21", "TOLEDO"]]))
    assert "<thead>" not in html
    assert "<th>" not in html


def test_page_split_table_is_stitched_back_together() -> None:
    """Same width + adjacency = one table broken by a page boundary. A leading
    row with a blank first cell is the split row's tail, not a row of its own."""
    body = _merge_table_continuations([
        {"table_rows": [["MAP NO", "TITLE"], ["19", "Overlay marked"]]},
        {"table_rows": [["", "map 19 over SMITHFIELD"], ["20", "SMITHFIELD"]]},
    ])
    assert len(body) == 1
    assert body[0]["table_rows"] == [
        ["MAP NO", "TITLE"],
        ["19", "Overlay marked map 19 over SMITHFIELD"],
        ["20", "SMITHFIELD"],
    ]


def test_tables_of_different_widths_are_left_alone() -> None:
    body = _merge_table_continuations([
        {"table_rows": [["a", "b"]]},
        {"table_rows": [["a", "b", "c"]]},
    ])
    assert len(body) == 2


def test_polish_leaves_table_entries_untouched() -> None:
    """polish_body adds a 'text' key to everything it walks; a table has none
    and must pass through whole."""
    out = polish_body([{"table_rows": [["a", "b"]]}, {"kind": "p", "text": "x"}])
    assert out[0] == {"table_rows": [["a", "b"]]}


# ------------------------------------------------------------- paragraphing


def test_numbered_items_are_not_glued_into_one_paragraph() -> None:
    """Operation orders are written in clauses that rarely end in a full stop,
    so the plain 'no terminator → broken sentence' rule merged whole numbered
    sequences. An enumerator on the next paragraph means the break was real."""
    out = polish_body([
        {"kind": "p", "text": "(i) Establish eccentric positions near base of lighthouse"},
        {"kind": "p", "text": "(ii) Measure circumference of lighthouse"},
        {"kind": "p", "text": "c. Tasks"},
        {"kind": "p", "text": "3.EXEC"},
    ])
    assert [e["text"] for e in out] == [
        "(i) Establish eccentric positions near base of lighthouse",
        "(ii) Measure circumference of lighthouse",
        "c. Tasks",
        "3.EXEC",
    ]


def test_column_row_does_not_swallow_the_prose_beneath_it() -> None:
    out = polish_body([
        {"kind": "p", "text": "Lighthouse ecce      4 arcs"},
        {"kind": "p", "text": "NUI DAT              8 arcs"},
        {"kind": "p", "text": "and so the survey continued"},
    ])
    assert len(out) == 3


def test_wrapped_item_split_by_a_page_break_still_rejoins() -> None:
    """The guard is deliberately asymmetric: a continuation line is neither
    enumerated nor column-aligned, so genuine page-break repair survives."""
    out = polish_body([
        {"kind": "p", "text": "a. The following procedure will constitute a 3rd order"},
        {"kind": "p", "text": "tellurometer determination between station A & station B."},
    ])
    assert len(out) == 1
    assert out[0]["text"].endswith("station A & station B.")


def test_grid_reference_is_not_read_as_a_footnote_marker() -> None:
    """`N1,150,000` is a grid northing. Only a digit that isn't part of a
    grouped number binds to a footnote."""
    assert bind_legacy_digit_refs("grid line N1,150,000", {1}) == "grid line N1,150,000"
    assert bind_legacy_digit_refs("Vietnam1 was", {1}) == "Vietnam[^1] was"


# ----------------------------------------------------------------- outline


def test_divider_page_heading_echo_is_dropped() -> None:
    """Each annex has a divider page carrying the label and title, then prints
    both again on its first real page — with a stray line in between, so the
    label pass has to look past intervening content."""
    d = draft([
        {"kind": "h3", "text": "ANNEX D"},
        {"kind": "h3", "text": "SILK SCREEN REPRODUCTION FACILITY"},
        {"kind": "p", "text": "Letter to HQ AFV"},
        {"kind": "h3", "text": "ANNEX  D"},
        {"kind": "p", "text": "Int/29/66"},
    ])
    _dedupe_repeated_headings(d)
    assert [e.get("text") for e in d.body] == [
        "ANNEX D", "SILK SCREEN REPRODUCTION FACILITY", "Letter to HQ AFV", "Int/29/66",
    ]


def test_label_echo_matches_across_punctuation_drift() -> None:
    """The divider letters it 'ANNEX B1'; the annex itself 'ANNEX  B-1'."""
    d = draft([
        {"kind": "h3", "text": "ANNEX B1"},
        {"kind": "h3", "text": "SUMMARY OF CLOSURES"},
        {"kind": "h3", "text": "ANNEX  B-1"},
        {"kind": "h3", "text": "SUMMARY OF CLOSURES (continued)"},
    ])
    _dedupe_repeated_headings(d)
    assert [e["text"] for e in d.body] == [
        "ANNEX B1", "SUMMARY OF CLOSURES", "SUMMARY OF CLOSURES (continued)",
    ]


def test_a_genuinely_new_section_with_the_same_label_survives() -> None:
    """Only a REPEAT with no other label between the two is an echo."""
    d = draft([
        {"kind": "h3", "text": "ANNEX A"},
        {"kind": "p", "text": "body"},
        {"kind": "h3", "text": "ANNEX B"},
        {"kind": "p", "text": "body"},
        {"kind": "h3", "text": "ANNEX A"},
    ])
    _dedupe_repeated_headings(d)
    assert [e["text"] for e in d.body].count("ANNEX A") == 2


def test_section_label_becomes_the_parent_of_its_title() -> None:
    """Page geometry puts the corner-set label at h3 and the centred title at
    h2, which nests each annex under its own title in the site ToC."""
    d = draft([
        {"kind": "h3", "text": "ANNEX H-1"},
        {"kind": "h2", "text": "DISTRIBUTION TABLE"},
        {"kind": "p", "text": "body"},
    ])
    _promote_section_labels(d)
    assert [(e["kind"], e["text"]) for e in d.body[:2]] == [
        ("h2", "ANNEX H-1"), ("h3", "DISTRIBUTION TABLE"),
    ]


def test_a_title_that_merely_opens_with_the_word_annex_is_not_a_label() -> None:
    d = draft([{"kind": "h3", "text": "Annex A to Operation Order 2/66"}])
    _promote_section_labels(d)
    assert d.body[0]["kind"] == "h3"


# --------------------------------------------------------------- footnotes


def test_notes_are_keyed_to_the_number_the_document_prints() -> None:
    """Ids are assigned sequentially as notes are found, but references carry
    the PRINTED number. One missed definition and every later reference
    resolves to its neighbour — so the ids are re-keyed to what was printed,
    which turns a missed definition into a single orphan instead of a
    cascade. Notes with no printed number park above the highest one."""
    notes = [
        {"n": 1, "local_num": 1, "text": "a"},
        {"n": 2, "local_num": 3, "text": "b"},   # 2 was never detected
        {"n": 3, "local_num": None, "text": "c"},  # number swallowed by the text
        {"n": 4, "local_num": 4, "text": "d"},
    ]
    _key_notes_by_printed_number(notes)
    assert [n["n"] for n in notes] == [1, 3, 5, 4]


def test_per_page_numbering_keeps_the_sequential_ids() -> None:
    """Repeating printed numbers mean per-page numbering — not a document-wide
    sequence — so re-keying would collide. Leave the ids alone."""
    notes = [
        {"n": 1, "local_num": 1, "text": "a"},
        {"n": 2, "local_num": 1, "text": "b"},
    ]
    _key_notes_by_printed_number(notes)
    assert [n["n"] for n in notes] == [1, 2]


def test_marker_placeholders_resolve_to_their_notes() -> None:
    body = [{"kind": "p", "text": "prose[^#1] and more[^#0]"}]
    _resolve_marker_placeholders(body, [{"n": 7}, {"n": 9}])
    assert body[0]["text"] == "prose[^9] and more[^7]"


def test_reference_without_a_note_reverts_to_a_plain_number() -> None:
    """Superscript detection is formatting-based, so it also catches a raised
    digit that is no reference at all — an exponent, the ring of a degree
    sign. Left as markers those would render as broken references."""
    body = [{"kind": "p", "text": "swing through 360[^0] and MACV[^4] reported"}]
    _unbind_unknown_refs(body, {4})
    assert body[0]["text"] == "swing through 3600 and MACV[^4] reported"


def test_footnote_number_zero_is_not_a_footnote() -> None:
    """Survey data — "0 º 24’ 27”.41" — was being lifted as footnote zero,
    which then made neighbouring digits look like live references."""
    assert _FOOTNOTE_LEAD_RE.match("1 ATF Artillery on the southern perimeter.")
    assert _FOOTNOTE_LEAD_RE.match("0 º 24’ 27”.41") is None


def test_orphan_split_ignores_a_number_beyond_the_sequence() -> None:
    """A footnote either fills a gap or extends the sequence by one. "24" in a
    document with ten notes is prose — "24 Construction Squadron" is a unit."""
    body = [{
        "kind": "p",
        "text": (
            "There was geometric detail work to be done. 24 Construction Squadron "
            "assisted with support personnel and accommodation."
        ),
    }]
    notes = [{"n": i, "local_num": i, "text": "x"} for i in range(1, 11)]
    _split_orphan_footnotes(body, notes, set())
    assert len(notes) == 10
    assert "[^" not in body[0]["text"]


def test_orphan_split_still_recovers_the_next_note_in_sequence() -> None:
    body = [{
        "kind": "p",
        "text": (
            "The party moved out at first light. 3 Warrant Officer Rollston "
            "later confirmed the timing from his own diary."
        ),
    }]
    notes = [{"n": i, "local_num": i, "text": "x"} for i in (1, 2)]
    _split_orphan_footnotes(body, notes, set())
    assert [n["n"] for n in notes] == [1, 2, 3]
    assert "light[^3]" in body[0]["text"]


def test_orphan_split_adds_no_marker_when_a_real_reference_exists() -> None:
    """Here the DEFINITION was merged into the prose but its superscript
    reference was found elsewhere — adding a marker would invent a second
    reference to the same note."""
    body = [{
        "kind": "p",
        "text": (
            "The party moved out at first light. 3 Warrant Officer Rollston "
            "later confirmed the timing from his own diary."
        ),
    }]
    notes = [{"n": i, "local_num": i, "text": "x"} for i in (1, 2)]
    _split_orphan_footnotes(body, notes, {3})
    assert len(notes) == 3          # the note is still recovered…
    assert "[^" not in body[0]["text"]   # …but no second reference to it
