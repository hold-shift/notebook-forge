"""M1 gate: unit tests for narrative.py — rule B conversion logic and label resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from notebook_forge.blocks import FORGE_NARRATIVE, make_block, text_run
from notebook_forge.narrative import (
    add_italic,
    conversion_report_entry,
    convert_full_italic_paragraphs,
    effective_narrative_label,
    narrative_label_setting,
    strip_italic,
)


def _italic(text: str, **extra_styles) -> dict:
    return text_run(text, {"italic": True, **extra_styles})


def _plain(text: str) -> dict:
    return text_run(text)


def _fnref(text: str) -> dict:
    return text_run(text, {"fnRef": True})


def _para(content: list) -> dict:
    return make_block("paragraph", content=content)


def _narrative(content: list) -> dict:
    return make_block(FORGE_NARRATIVE, content=content)


# ── Test 1: fully italic single run converts; id preserved; italic stripped ──

def test_single_italic_run_converts() -> None:
    content = [_italic("Looking back on those years.")]
    block = _para(content)
    original_id = block["id"]
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert len(new_blocks) == 1
    nb = new_blocks[0]
    assert nb["type"] == FORGE_NARRATIVE
    assert nb["id"] == original_id
    assert nb["props"] == {}
    assert len(conversions) == 1
    # italic is stripped
    for run in nb["content"]:
        assert not run.get("styles", {}).get("italic")


# ── Test 2: italic runs split by punctuation-only run converts (D4) ──

def test_italic_with_punctuation_split_converts() -> None:
    content = [_italic("First part"), _plain(", "), _italic("second part")]
    block = _para(content)
    new_blocks, _ = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == FORGE_NARRATIVE


# ── Test 3: trailing whitespace-only run converts ──

def test_trailing_whitespace_run_converts() -> None:
    content = [_italic("Reflective passage here."), _plain("   ")]
    block = _para(content)
    new_blocks, _ = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == FORGE_NARRATIVE


# ── Test 4: one upright word among italics → does NOT convert ──

def test_mixed_upright_word_does_not_convert() -> None:
    content = [_italic("Mostly italic"), _plain(" but not this"), _italic(" word")]
    block = _para(content)
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == "paragraph"
    assert len(conversions) == 0


# ── Test 5: partly italic inline → does NOT convert (brief B) ──

def test_partial_italic_does_not_convert() -> None:
    content = [_plain("Normal "), _italic("italic word")]
    block = _para(content)
    new_blocks, _ = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == "paragraph"


# ── Test 6: italic + bold runs (pseudo-heading) → converts, bold preserved, flagged ──

def test_italic_bold_converts_and_flagged() -> None:
    content = [_italic("Dining In The Mess", bold=True)]  # <12 words
    block = _para(content)
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == FORGE_NARRATIVE
    # bold preserved; italic stripped
    run = new_blocks[0]["content"][0]
    assert run["styles"].get("bold") is True
    assert not run["styles"].get("italic")
    assert len(conversions) == 1
    assert conversions[0]["flagged"] is True


# ── Test 7: fnRef run amid italics → converts; fnRef run untouched ──

def test_fnref_run_amid_italics_converts() -> None:
    content = [_italic("A reflective passage"), _fnref("1"), _italic(" continued.")]
    block = _para(content)
    new_blocks, _ = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == FORGE_NARRATIVE
    # fnRef run unchanged
    fnref_run = new_blocks[0]["content"][1]
    assert fnref_run["styles"].get("fnRef") is True
    assert not fnref_run["styles"].get("italic")


def test_strip_italic_preserves_fnref() -> None:
    content = [_italic("text"), _fnref("1")]
    result = strip_italic(content)
    assert not result[0]["styles"].get("italic")
    assert result[1]["styles"].get("fnRef") is True
    assert not result[1]["styles"].get("italic")


# ── Test 8: fully italic link → converts; italic stripped inside link ──

def test_italic_link_converts() -> None:
    link_run = {
        "type": "link",
        "href": "https://example.com",
        "content": [_italic("Visit here")],
    }
    block = _para([link_run])
    new_blocks, _ = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == FORGE_NARRATIVE
    inner_run = new_blocks[0]["content"][0]["content"][0]
    assert not inner_run["styles"].get("italic")


# ── Test 9: empty or whitespace-only italic paragraph → does NOT convert (D4) ──

def test_empty_paragraph_does_not_convert() -> None:
    block = _para([])
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == "paragraph"
    assert len(conversions) == 0


def test_whitespace_only_italic_does_not_convert() -> None:
    block = _para([_italic("   ")])
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == "paragraph"
    assert len(conversions) == 0


# ── Test 10: heading, quote, bulletListItem with italic → NOT converted (D5) ──

def test_non_paragraph_types_not_converted() -> None:
    blocks = [
        make_block("heading", props={"level": 2}, content=[_italic("An italic heading")]),
        make_block("quote", content=[_italic("An italic quote")]),
        make_block("bulletListItem", content=[_italic("An italic list item")]),
    ]
    new_blocks, conversions = convert_full_italic_paragraphs(blocks)
    for b in new_blocks:
        assert b["type"] != FORGE_NARRATIVE
    assert len(conversions) == 0


# ── Test 11: existing forgeNarrative passes through; twice equals once ──

def test_forge_narrative_passes_through_unchanged() -> None:
    content = [text_run("Already converted.")]
    block = _narrative(content)
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert new_blocks[0]["type"] == FORGE_NARRATIVE
    assert len(conversions) == 0


def test_idempotent_double_conversion() -> None:
    italic_blocks = [_para([_italic("A full italic paragraph here for conversion.")])]
    once, _ = convert_full_italic_paragraphs(italic_blocks)
    twice, conversions2 = convert_full_italic_paragraphs(once)
    assert twice[0]["type"] == FORGE_NARRATIVE
    assert len(conversions2) == 0  # already narrative, not re-converted


# ── Test 12: add_italic(strip_italic(x)) restores italic; fnRef never gains italic ──

def test_round_trip_add_strip_italic() -> None:
    content = [_italic("word one"), _italic("word two", bold=True), _fnref("1")]
    stripped = strip_italic(content)
    restored = add_italic(stripped)
    for run in restored:
        if run["styles"].get("fnRef"):
            assert not run["styles"].get("italic")
        else:
            assert run["styles"].get("italic") is True


# ── Test 13: report entries — word count, 90-char preview, flag boundary ──

def test_conversion_report_entry_words_and_preview() -> None:
    plain_text = "A " * 5 + "word."  # 6 words
    block = _para([_italic(plain_text)])
    entry = conversion_report_entry(block)
    assert entry["words"] == 6
    assert entry["flagged"] is True  # < 12


def test_conversion_report_flag_boundary() -> None:
    # 11 words → flagged
    text_11 = " ".join(["word"] * 11)
    block_11 = _para([_italic(text_11)])
    assert conversion_report_entry(block_11)["flagged"] is True

    # 12 words → not flagged
    text_12 = " ".join(["word"] * 12)
    block_12 = _para([_italic(text_12)])
    assert conversion_report_entry(block_12)["flagged"] is False


def test_conversion_report_90_char_preview() -> None:
    long_text = "A" * 95
    block = _para([_italic(long_text)])
    entry = conversion_report_entry(block)
    assert entry["preview"].endswith("…")
    assert len(entry["preview"]) == 91  # 90 chars + ellipsis


def test_conversion_report_short_no_ellipsis() -> None:
    block = _para([_italic("Short text.")])
    entry = conversion_report_entry(block)
    assert "…" not in entry["preview"]


# ── Test 14: label resolution (D9 key-presence tri-state) ──

def _mock_session(label: str | None = None) -> MagicMock:
    """Return a mock session.get(Setting, 'narrative') returning a row with label."""
    session = MagicMock()
    if label is None:
        session.get.return_value = None
    else:
        row = MagicMock()
        row.value = {"label": label}
        session.get.return_value = row
    return session


def _mock_doc(meta: dict) -> MagicMock:
    doc = MagicMock()
    doc.meta = meta
    return doc


def test_label_no_setting_returns_empty() -> None:
    session = _mock_session(None)
    doc = _mock_doc({})
    assert narrative_label_setting(session) == ""
    assert effective_narrative_label(session, doc) == ""


def test_label_setting_inherited() -> None:
    session = _mock_session("From the author")
    doc = _mock_doc({})
    assert effective_narrative_label(session, doc) == "From the author"


def test_label_doc_meta_empty_string_beats_workspace() -> None:
    session = _mock_session("From the author")
    doc = _mock_doc({"narrative_label": ""})  # key present, even though ""
    assert effective_narrative_label(session, doc) == ""


def test_label_doc_meta_override() -> None:
    session = _mock_session("From the author")
    doc = _mock_doc({"narrative_label": "Reflection"})
    assert effective_narrative_label(session, doc) == "Reflection"


# ── M8 edge-case sweep ──

def test_empty_italic_paragraph_parse_fragment_no_convert() -> None:
    """Empty italic paragraph from HTML: parses to paragraph, never converts."""
    from notebook_forge.parser import parse_fragment

    blocks, _ = parse_fragment("<p><em> </em></p>")
    converted, conversions = convert_full_italic_paragraphs(blocks)
    assert len(conversions) == 0
    assert all(b["type"] != FORGE_NARRATIVE for b in converted)


def test_italic_list_item_not_converted_end_to_end() -> None:
    """Italic text inside list item: convert pass is a no-op end-to-end."""
    from notebook_forge.parser import parse_fragment

    blocks, _ = parse_fragment("<ul><li><em>An italic list item passage.</em></li></ul>")
    converted, conversions = convert_full_italic_paragraphs(blocks)
    assert len(conversions) == 0
    assert all(b["type"] != FORGE_NARRATIVE for b in converted)


def test_italic_paragraph_converts_and_add_italic_restores() -> None:
    """Italic paragraph converts to narrative; add_italic restores italic on all word runs."""
    content = [_italic("A reflective italic passage long enough to convert easily.")]
    block = _para(content)
    new_blocks, conversions = convert_full_italic_paragraphs([block])
    assert len(conversions) == 1
    assert new_blocks[0]["type"] == FORGE_NARRATIVE

    restored_content = add_italic(new_blocks[0]["content"])
    for run in restored_content:
        if run["type"] == "text" and not run["styles"].get("fnRef"):
            assert run["styles"].get("italic") is True


def test_narrative_first_block_no_lead_first_para_gets_lead() -> None:
    """Narrative as first block: no lead drop-cap on the panel; first paragraph gets lead."""
    from bs4 import BeautifulSoup

    from notebook_forge.renderer import render_document

    blocks = [
        _narrative([text_run("A reflective opening passage.")]),
        _para([text_run("The ordinary prose begins here after the narrative.")]),
    ]
    html = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")

    # Narrative panel has no class 'lead'
    narrative_div = soup.find("div", class_="narrative")
    assert narrative_div is not None
    assert "lead" not in (narrative_div.get("class") or [])

    # First paragraph gets the lead class
    lead_p = soup.find("p", class_="lead")
    assert lead_p is not None
    assert "ordinary prose" in lead_p.get_text()


def test_fnref_in_narrative_renders_sup_and_splits_panel() -> None:
    """fnRef inside narrative paragraph: sup.fn-ref inside panel; adjacent footnote splits panel."""
    from bs4 import BeautifulSoup

    from notebook_forge.blocks import FORGE_FOOTNOTE
    from notebook_forge.renderer import render_document

    blocks = [
        _narrative([text_run("Before the note."), _fnref("1"), text_run(" After.")]),
        make_block(FORGE_FOOTNOTE, {"marker": "1", "text": "The footnote text."}),
        _narrative([text_run("Second narrative paragraph after the footnote.")]),
    ]
    html = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")

    # Two panels (footnote splits them)
    panels = soup.find_all("div", class_="narrative")
    assert len(panels) == 2

    # fn-ref sup inside the first panel
    sup = panels[0].find("sup", class_="fn-ref")
    assert sup is not None


def test_narrative_plain_text_indexed_for_fts() -> None:
    """Narrative text appears in plain_text() output (FTS generic branch)."""
    from notebook_forge.blocks import plain_text

    blocks = [
        _narrative([text_run("A unique reflective canticle appearing in narrative.")]),
        _para([text_run("Ordinary prose paragraph.")]),
    ]
    result = plain_text(blocks)
    assert "unique reflective canticle" in result
