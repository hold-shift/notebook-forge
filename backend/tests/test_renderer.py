"""M3 gate: render(parse(x)) idempotent on all fixtures (normalised DOM
equality), full-page round trip against the real published memoir, plus the
index renderer."""

from pathlib import Path

import pytest

from notebook_forge.blocks import content_hash
from notebook_forge.domcompare import compare
from notebook_forge.parser import parse_fragment, parse_page
from notebook_forge.renderer import build_jsonld, render_document, render_index

FIXTURES = Path(__file__).parent / "fixtures"

FRAGMENTS = [
    "figure_landscape.html",
    "figure_portrait.html",
    "headings_paras.html",
    "para_em.html",
    "para_strong.html",
    "footnote_pair.html",
    "footnote_em.html",
    "lead_para.html",
]


def _image_src_from(images: dict[str, str]):
    return lambda block, n: images.get(block["id"], "")


@pytest.mark.parametrize("name", FRAGMENTS)
def test_fragment_round_trip_is_idempotent(name: str) -> None:
    """parse → render → parse must be a fixed point at block level, and the
    two rendered pages must be DOM-equal."""
    src = (FIXTURES / name).read_text()
    blocks1, images = parse_fragment(src)
    html1 = render_document({"title": "T", "show_toc": False}, blocks1, _image_src_from(images))
    page2 = parse_page(html1)
    assert content_hash(page2.blocks) == content_hash(blocks1)
    html2 = render_document(
        {"title": "T", "show_toc": False}, page2.blocks, _image_src_from(page2.images)
    )
    result = compare(html1, html2)
    assert result.equal, [d.expected for d in result.diffs]


def test_full_page_render_matches_published_dom() -> None:
    """The strong round trip: parse the real published page, re-render, and
    require normalised-DOM equality with the published bytes."""
    src = (FIXTURES / "full_page_in_the_navy.html").read_text()
    page = parse_page(src)
    rendered = render_document(page.meta, page.blocks, _image_src_from(page.images))
    result = compare(src, rendered)
    # Known upstream artefact: figure 14's alt attribute in the PUBLISHED
    # page contains raw unescaped double quotes (MemoirForge bug), which
    # HTML parsers recover from by spilling the alt text into junk
    # attributes. Our render emits a well-formed (truncated-at-the-quote)
    # alt instead. Any diff that touches that one <img> is expected;
    # anything else is a real regression.
    unexpected = [
        d
        for d in result.diffs
        if not any("figure-14-original" in t for t in d.expected + d.actual)
    ]
    if unexpected:
        for d in unexpected[:8]:
            print(d.op, "EXPECTED:", d.expected[:3], "ACTUAL:", d.actual[:3])
    assert result.similarity > 0.997
    assert not unexpected


def test_synthetic_blocks_round_trip() -> None:
    """Blocks with no corpus presence (quote/list/table/divider) survive
    render → parse unchanged."""
    fragment = (
        "<blockquote><p>a quote</p></blockquote>"
        "<ul><li>one</li><li>two<ul><li>two-a</li></ul></li></ul>"
        "<hr>"
        "<table><tr><td>a</td><td>b</td></tr></table>"
    )
    blocks1, _ = parse_fragment(fragment)
    html = render_document({"title": "T", "show_toc": False}, blocks1, lambda b, n: "")
    page = parse_page(html)
    assert content_hash(page.blocks) == content_hash(blocks1)


def test_jsonld_refreshes_edited_fields() -> None:
    meta = {
        "jsonld": {"@context": "https://schema.org", "@type": "Article",
                   "headline": "Old", "description": "Old desc", "datePublished": "2026-06-09"},
        "title": "New Title",
        "standfirst": "New standfirst",
    }
    script = build_jsonld(meta)
    assert '"headline":"New Title"' in script
    assert '"description":"New standfirst"' in script
    assert '"datePublished":"2026-06-09"' in script  # provenance preserved


def test_index_renderer() -> None:
    html = render_index(
        title="The Skitch Family Archive",
        welcome="A collection of the writings of Robert Francis Skitch.",
        dedication="",
        entries=[
            {
                "years": "1934–1945",
                "title": "Junior",
                "description": "Early years.",
                "url": "rfs/1934-1945_junior.html",
                "word_count": 12000,
                "reading_time": "48 min",
            }
        ],
        footer_text="© Christopher M.R. Skitch",
    )
    assert "The Skitch Family Archive" in html
    assert 'href="rfs/1934-1945_junior.html"' in html
    assert "12,000 words" in html
    assert "48 min" in html
