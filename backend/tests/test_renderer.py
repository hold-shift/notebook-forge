"""M3 gate: render(parse(x)) idempotent on all fixtures (normalised DOM
equality), full-page round trip against the real published memoir, plus the
index renderer."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from notebook_forge.blocks import FORGE_NARRATIVE, content_hash, make_block, text_run
from notebook_forge.domcompare import compare
from notebook_forge.parser import parse_fragment, parse_inline, parse_page
from notebook_forge.renderer import (
    TEMPLATES_DIR,
    build_jsonld,
    inline_html,
    render_document,
    render_index,
)

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
    "narrative_panel.html",
    "narrative_merged.html",
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
    # likewise, diffs on the <style> element are expected when the template
    # CSS is intentionally updated (e.g. adding --narr-bg narrative tokens).
    unexpected = [
        d
        for d in result.diffs
        if not any("figure-14-original" in t for t in d.expected + d.actual)
        and not any(":root{" in t or "--narr-bg" in t for t in d.expected + d.actual)
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


def test_narrative_merge() -> None:
    """Three consecutive forgeNarrative blocks → one div.narrative with three <p>;
    split by a forgeFootnote → two panels."""
    def _narr(text: str) -> dict:
        return make_block(FORGE_NARRATIVE, content=[text_run(text)])

    blocks_merged = [_narr("First."), _narr("Second."), _narr("Third.")]
    html = render_document({"title": "T", "show_toc": False}, blocks_merged, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")
    panels = soup.find_all("div", class_="narrative")
    assert len(panels) == 1
    paragraphs = panels[0].find_all("p")
    assert len(paragraphs) == 3

    # Split by forgeFootnote → two panels
    from notebook_forge.blocks import FORGE_FOOTNOTE
    blocks_split = [
        _narr("Before footnote."),
        make_block(FORGE_FOOTNOTE, {"marker": "1", "text": "A note."}),
        _narr("After footnote."),
    ]
    html2 = render_document({"title": "T", "show_toc": False}, blocks_split, lambda b, n: "")
    soup2 = BeautifulSoup(html2, "lxml")
    assert len(soup2.find_all("div", class_="narrative")) == 2


def test_narrative_label_rendered() -> None:
    """narrative_label in meta → p.narrative-label inside div.narrative; absent → no label."""
    block = make_block(FORGE_NARRATIVE, content=[text_run("A reflective passage.")])
    html_with = render_document(
        {"title": "T", "show_toc": False, "narrative_label": "From the author"},
        [block],
        lambda b, n: "",
    )
    soup = BeautifulSoup(html_with, "lxml")
    label_el = soup.find("p", class_="narrative-label")
    assert label_el is not None
    assert "From the author" in label_el.get_text()

    html_without = render_document(
        {"title": "T", "show_toc": False, "narrative_label": ""},
        [block],
        lambda b, n: "",
    )
    soup2 = BeautifulSoup(html_without, "lxml")
    assert soup2.find("p", class_="narrative-label") is None


def test_narrative_footnote_contrast() -> None:
    """Contrast proof (plan M2, mandatory): narrative and footnote differ on
    size, tint, and marker. Writes reports/narrative_contrast.html."""
    from notebook_forge.blocks import FORGE_FOOTNOTE

    blocks = [
        make_block("paragraph", content=[text_run("An ordinary paragraph.")]),
        make_block(FORGE_NARRATIVE, content=[text_run("A reflective author voice passage.")]),
        make_block(FORGE_FOOTNOTE, {"marker": "1", "text": "A numbered footnote note."}),
    ]
    html = render_document({"title": "Contrast proof", "show_toc": False}, blocks, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")

    # (a) Narrative panel has no fn-num/marker; footnote aside has one
    narrative_div = soup.find("div", class_="narrative")
    assert narrative_div is not None
    assert narrative_div.find("span", class_="fn-num") is None

    footnote_aside = soup.find("aside", class_="footnote")
    assert footnote_aside is not None
    assert footnote_aside.find("span", class_="fn-num") is not None

    # (b) Assert CSS text from the template
    template_css = (TEMPLATES_DIR / "page.html.j2").read_text()
    # Narrative: warm background, 3px left border, no font-size rule
    assert "div.narrative{" in template_css
    assert "background:var(--narr-bg)" in template_css
    assert "border-left:3px solid var(--narr-border)" in template_css
    # Footnote: .86rem font-size, no background
    assert "aside.footnote{" in template_css
    assert "font-size:.86rem" in template_css
    # The narrative block itself must not set a font-size (body-size by inheritance)
    narr_block_start = template_css.index("div.narrative{")
    narr_block_end = template_css.index("div.narrative .narrative-label{")
    narr_core_css = template_css[narr_block_start:narr_block_end]
    assert "font-size" not in narr_core_css

    # (c) Write the committed visual fixture
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "narrative_contrast.html").write_text(html)
    assert (reports_dir / "narrative_contrast.html").exists()


# ---------------------------------------------------------------------------
# Soft line-break tests
# ---------------------------------------------------------------------------


def test_inline_html_newline_becomes_br() -> None:
    runs = [text_run("first\nsecond")]
    assert inline_html(runs) == "first<br>second"


def test_inline_html_crlf_becomes_single_br() -> None:
    runs = [text_run("first\r\nsecond")]
    assert inline_html(runs) == "first<br>second"


def test_inline_html_newline_not_double_escaped() -> None:
    """The <br> tag must not be escaped to &lt;br&gt;."""
    runs = [text_run("a\nb")]
    result = inline_html(runs)
    assert "<br>" in result
    assert "&lt;" not in result


def test_inline_html_newline_with_styles() -> None:
    runs = [{"type": "text", "text": "bold\nbreak", "styles": {"bold": True}}]
    result = inline_html(runs)
    assert "<br>" in result
    assert "<strong>" in result


def _make_br_soup(html_fragment: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(f"<p>{html_fragment}</p>", "lxml").find("p")


def test_parser_br_to_newline() -> None:
    """Parser: <br> → '\\n' in inline text run."""
    soup = _make_br_soup("first<br>second")
    runs = parse_inline(soup)
    combined = "".join(r.get("text", "") for r in runs if r.get("type") == "text")
    assert "\n" in combined


def test_soft_break_round_trip_paragraph() -> None:
    """\\n in paragraph content → <br> in HTML → back to \\n via parser."""
    blocks = [make_block("paragraph", content=[text_run("line one\nline two")])]
    html = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")
    p = soup.find("p", class_="lead") or soup.find("p")
    assert p is not None
    assert p.find("br") is not None, "rendered HTML must contain <br>"
    # Parse back
    runs = parse_inline(p)
    text = "".join(r.get("text", "") for r in runs if r.get("type") == "text")
    assert "\n" in text, "parser must restore \\n from <br>"


def test_soft_break_round_trip_quote() -> None:
    """\\n in blockquote content survives render→parse."""
    blocks = [make_block("quote", content=[text_run("first line\nsecond line")])]
    html = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")
    bq = soup.find("blockquote")
    assert bq is not None
    assert bq.find("br") is not None
    runs = parse_inline(bq)
    text = "".join(r.get("text", "") for r in runs if r.get("type") == "text")
    assert "\n" in text


def test_soft_break_round_trip_narrative() -> None:
    """\\n in narrative block content survives render→parse."""
    blocks = [make_block(FORGE_NARRATIVE, content=[text_run("voice line one\nvoice line two")])]
    html = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "")
    soup = BeautifulSoup(html, "lxml")
    div = soup.find("div", class_="narrative")
    assert div is not None
    assert div.find("br") is not None
    runs = parse_inline(div)
    text = "".join(r.get("text", "") for r in runs if r.get("type") == "text")
    assert "\n" in text
