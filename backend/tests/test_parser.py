"""M2 gate: parser unit tests against fragments cut from the real published
memoirs (backend/tests/fixtures/, extracted from the family-history Pages
repo). Tables / lists / blockquotes / hrs never occur in the published
corpus, so those cases use minimal synthetic fragments (flagged as such).
"""

from pathlib import Path

import pytest

from notebook_forge.blocks import inline_text
from notebook_forge.parser import parse_fragment, parse_page

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_landscape_figure_to_forge_image() -> None:
    blocks, images = parse_fragment(fixture("figure_landscape.html"))
    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "forgeImage"
    assert block["props"]["displayWidth"] == "full"
    assert block["props"]["caption"].startswith("This plaque is mounted")
    assert "supreme sacrifice" in block["props"]["caption"]
    assert "Figure 1." not in block["props"]["caption"]  # fignum span stripped
    assert block["props"]["altText"].startswith("This plaque")
    assert block["props"]["approval"] == "approved"
    assert images[block["id"]] == "1953-1954_in-the-navy_assets/figure-1-original.jpeg"


def test_portrait_figure_display_width() -> None:
    blocks, _ = parse_fragment(fixture("figure_portrait.html"))
    assert blocks[0]["props"]["displayWidth"] == "portrait"
    assert blocks[0]["props"]["caption"] == "Pvt. Robert. F. Skitch."


def test_headings_and_paragraphs() -> None:
    blocks, _ = parse_fragment(fixture("headings_paras.html"))
    kinds = [(b["type"], b["props"].get("level")) for b in blocks]
    assert kinds[0] == ("heading", 2)
    assert ("heading", 3) in kinds
    assert any(b["type"] == "paragraph" for b in blocks)
    # no empty blocks from pretty-printed whitespace
    for b in blocks:
        if b["type"] in ("paragraph", "heading"):
            assert inline_text(b["content"]).strip()


def test_nested_inline_marks() -> None:
    # real fragment: <p><em><strong>Dining In The Mess</strong></em></p>
    blocks, _ = parse_fragment(fixture("para_em.html"))
    [para] = blocks
    [run] = para["content"]
    assert run["text"] == "Dining In The Mess"
    assert run["styles"] == {"italic": True, "bold": True}


def test_footnote_pair_marker_and_aside() -> None:
    blocks, _ = parse_fragment(fixture("footnote_pair.html"))
    assert [b["type"] for b in blocks] == ["paragraph", "forgeFootnote"]
    para, note = blocks
    fn_runs = [r for r in para["content"] if r.get("styles", {}).get("fnRef")]
    assert fn_runs and fn_runs[0]["text"] == note["props"]["marker"]
    assert note["props"]["text"]


def test_footnote_with_inline_markup_preserved() -> None:
    blocks, _ = parse_fragment(fixture("footnote_em.html"))
    [note] = blocks
    assert note["type"] == "forgeFootnote"
    assert note["props"]["marker"] == "2"
    assert note["props"]["text"].startswith("<em>I wrote four short accounts")
    assert note["props"]["text"].endswith("</em>")


def test_lead_paragraph_class_is_derived_not_content() -> None:
    blocks, _ = parse_fragment(fixture("lead_para.html"))
    [para] = blocks
    assert para["type"] == "paragraph"
    assert "lead" not in para["props"]  # lead is recomputed at render time


@pytest.mark.parametrize(
    ("html", "expected_type"),
    [
        ("<blockquote><p>quoted text</p></blockquote>", "quote"),  # synthetic
        ("<hr>", "divider"),  # synthetic
    ],
)
def test_quote_and_divider(html: str, expected_type: str) -> None:
    blocks, _ = parse_fragment(html)
    assert blocks[0]["type"] == expected_type


def test_lists_nested() -> None:  # synthetic: corpus has no lists
    blocks, _ = parse_fragment(
        "<ul><li>one</li><li>two<ul><li>two-a</li></ul></li></ul><ol><li>first</li></ol>"
    )
    assert [b["type"] for b in blocks] == [
        "bulletListItem",
        "bulletListItem",
        "numberedListItem",
    ]
    assert inline_text(blocks[1]["content"]) == "two"
    assert blocks[1]["children"][0]["type"] == "bulletListItem"
    assert inline_text(blocks[1]["children"][0]["content"]) == "two-a"


def test_table() -> None:  # synthetic: corpus has no tables
    blocks, _ = parse_fragment(
        "<table><tr><th>h1</th><th>h2</th></tr><tr><td>a</td><td><em>b</em></td></tr></table>"
    )
    [table] = blocks
    assert table["type"] == "table"
    rows = table["content"]["rows"]
    assert len(rows) == 2
    assert inline_text(rows[1]["cells"][1]["content"]) == "b"
    assert rows[1]["cells"][1]["content"][0]["styles"] == {"italic": True}


def test_parse_full_page_metadata_and_content() -> None:
    page = parse_page(fixture("full_page_in_the_navy.html"))
    meta = page.meta
    assert meta["title"] == "In The Navy"
    assert meta["author"] == "R.F. Skitch"
    assert meta["year_display"] == "1953–1954"
    assert meta["overline"] == "The Skitch Family Archive · Family History"
    assert meta["standfirst"].startswith("A recollection of a unique")
    assert meta["meta_description"] == meta["standfirst"]
    assert meta["canonical_url"].endswith("rfs/1953-1954_in-the-navy.html")
    assert meta["homepage_url"].endswith("family-history/index.html")
    assert meta["show_toc"] is True
    assert meta["date_published"].startswith("2026-")
    assert meta["nav_prev"]["title"] == "The Years Between"
    assert meta["nav_next"]["title"].startswith("The Army Years - Part 1")
    assert "CC BY-NC-ND 4.0" in meta["footer_html"]

    # content inventory matches the published article exactly
    by_type: dict[str, int] = {}
    for b in page.blocks:
        by_type[b["type"]] = by_type.get(b["type"], 0) + 1
    assert by_type["forgeImage"] == 15
    assert by_type["forgeFootnote"] == 1
    assert by_type["heading"] == 52  # 5 h2 + 47 h3
    assert by_type["paragraph"] == 55
    assert len(page.images) == 15

    # the ToC nav, masthead and docnav must NOT leak into content
    all_text = " ".join(inline_text(b.get("content") or []) for b in page.blocks)
    assert "Filter sections" not in all_text
    assert "← Previous" not in all_text
    assert "The Skitch Family Archive" not in all_text
