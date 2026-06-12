"""House-style HTML → BlockNote block tree (M2).

Parses pages produced by the MemoirForge house style (the published
family-history memoirs are the ground truth) into the canonical block tree.

Derived page furniture is stripped, not parsed: the ToC nav system (rail,
drawer, fab, nowbar), masthead, docnav, footer and scripts. Content comes
from <article> only; everything else feeds page *metadata*.

forgeImage blocks come back with empty assetId — the parser doesn't know the
asset store. Image srcs are returned in `images` keyed by block id; the
importer resolves them to content-addressed assets.

forgeFootnote.text and figure captions may carry minimal inline HTML
(<em>/<strong>/<a>) — the corpus has one <em> footnote — stored as an
inline-HTML string and re-emitted raw by the renderer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from .blocks import make_block, text_run

_STYLE_FOR_TAG = {
    "em": "italic",
    "i": "italic",
    "strong": "bold",
    "b": "bold",
    "u": "underline",
    "s": "strike",
    "del": "strike",
    "code": "code",
}


@dataclass
class ParsedPage:
    meta: dict[str, Any] = field(default_factory=dict)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)  # block id -> img src


def _merge_styles(styles: dict[str, Any], tag_name: str, classes: list[str]) -> dict[str, Any]:
    new = dict(styles)
    if tag_name == "sup" and "fn-ref" in classes:
        new["fnRef"] = True
    elif tag_name in _STYLE_FOR_TAG:
        new[_STYLE_FOR_TAG[tag_name]] = True
    return new


def parse_inline(node: Tag, styles: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Flatten an element's children into BlockNote inline content."""
    styles = styles or {}
    runs: list[dict[str, Any]] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if text:
                runs.append(text_run(text, dict(styles)))
        elif isinstance(child, Tag):
            if child.name == "br":
                runs.append(text_run("\n", dict(styles)))
            elif child.name == "a":
                content = parse_inline(child, styles)
                runs.append(
                    {"type": "link", "href": child.get("href", ""), "content": content}
                )
            else:
                runs.extend(
                    parse_inline(child, _merge_styles(styles, child.name, child.get("class") or []))
                )
    return _coalesce(runs)


def _coalesce(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent text runs with identical styles."""
    out: list[dict[str, Any]] = []
    for run in runs:
        if (
            out
            and run.get("type") == "text"
            and out[-1].get("type") == "text"
            and out[-1]["styles"] == run["styles"]
        ):
            out[-1]["text"] += run["text"]
        else:
            out.append(run)
    return out


def inner_inline_html(node: Tag) -> str:
    """Inner HTML of an element with minimal inline markup preserved."""
    return "".join(str(c) for c in node.children)


def _parse_figure(fig: Tag) -> tuple[dict[str, Any], str]:
    img = fig.find("img")
    src = img.get("src", "") if img else ""
    alt = img.get("alt", "") if img else ""
    caption = ""
    figcaption = fig.find("figcaption")
    if figcaption:
        cap = BeautifulSoup(str(figcaption), "lxml").find("figcaption")
        fignum = cap.find("span", class_="fignum")
        if fignum:
            fignum.decompose()
        caption = inner_inline_html(cap)
    classes = fig.get("class") or []
    block = make_block(
        "forgeImage",
        {
            "assetId": "",
            "sketchAssetId": "",
            "caption": caption,
            "altText": alt,
            "approval": "approved",
            "displayWidth": "portrait" if "portrait" in classes else "full",
        },
    )
    return block, src


def _parse_footnote(aside: Tag) -> dict[str, Any]:
    aside = BeautifulSoup(str(aside), "lxml").find("aside")
    marker = ""
    num = aside.find("span", class_="fn-num")
    if num:
        marker = num.get_text()
        num.decompose()
    return make_block("forgeFootnote", {"marker": marker, "text": inner_inline_html(aside).strip()})


def _parse_table(table: Tag) -> dict[str, Any]:
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["td", "th"]):
            cells.append({"type": "tableCell", "content": parse_inline(cell), "props": {}})
        rows.append({"cells": cells})
    return make_block("table", content={"type": "tableContent", "rows": rows})


def _parse_list(lst: Tag, ordered: bool) -> list[dict[str, Any]]:
    item_type = "numberedListItem" if ordered else "bulletListItem"
    items: list[dict[str, Any]] = []
    for li in lst.find_all("li", recursive=False):
        nested: list[dict[str, Any]] = []
        inline_parent = BeautifulSoup(str(li), "lxml").find("li")
        for sub in inline_parent.find_all(["ul", "ol"], recursive=False):
            nested.extend(_parse_list(sub, sub.name == "ol"))
            sub.decompose()
        items.append(make_block(item_type, content=parse_inline(inline_parent), children=nested))
    return items


def parse_article(article: Tag) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Parse the <article> element (or any container of body content)."""
    blocks: list[dict[str, Any]] = []
    images: dict[str, str] = {}

    for el in article.children:
        if isinstance(el, NavigableString):
            continue  # inter-block whitespace from pretty-printing
        if not isinstance(el, Tag):
            continue
        name = el.name
        classes = el.get("class") or []
        if name in ("h2", "h3"):
            blocks.append(
                make_block("heading", {"level": int(name[1])}, parse_inline(el))
            )
        elif name == "p":
            blocks.append(make_block("paragraph", content=parse_inline(el)))
        elif name == "figure":
            block, src = _parse_figure(el)
            blocks.append(block)
            if src:
                images[block["id"]] = src
        elif name == "aside" and "footnote" in classes:
            blocks.append(_parse_footnote(el))
        elif name == "blockquote":
            paragraphs = el.find_all("p", recursive=False)
            if paragraphs:
                for p in paragraphs:
                    blocks.append(make_block("quote", content=parse_inline(p)))
            else:
                blocks.append(make_block("quote", content=parse_inline(el)))
        elif name in ("ul", "ol"):
            blocks.extend(_parse_list(el, name == "ol"))
        elif name == "hr":
            blocks.append(make_block("divider"))
        elif name == "table":
            blocks.append(_parse_table(el))
        elif name == "div" and "narrative" in classes:
            for p in el.find_all("p", recursive=False):
                if "narrative-label" in (p.get("class") or []):
                    continue
                blocks.append(make_block("forgeNarrative", content=parse_inline(p)))
        elif name in ("div", "section", "article"):
            inner, inner_imgs = parse_article(el)
            blocks.extend(inner)
            images.update(inner_imgs)
        # nav/aside(non-footnote)/script/style: derived furniture — strip
    return blocks, images


_WS_RE = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _parse_meta(soup: BeautifulSoup) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    body = soup.find("body")
    meta["show_toc"] = bool(body and "has-toc" in (body.get("class") or []))

    h1 = soup.find("h1", class_="title")
    meta["title"] = _clean(h1.get_text()) if h1 else ""

    overline = soup.find("p", class_="overline")
    meta["overline"] = _clean(overline.get_text()) if overline else ""
    home = soup.find("a", class_="overline-home")
    meta["homepage_url"] = home.get("href", "") if home else ""

    byline = soup.find("p", class_="byline")
    meta["author"] = ""
    meta["year_display"] = ""
    meta["place"] = ""
    if byline:
        author = byline.find("span", class_="author")
        meta["author"] = _clean(author.get_text()) if author else ""
        plain = [
            _clean(s.get_text())
            for s in byline.find_all("span")
            if not (set(s.get("class") or []) & {"author", "dot"})
        ]
        if plain:
            meta["year_display"] = plain[0]
        if len(plain) > 1:
            meta["place"] = plain[1]

    standfirst = soup.find("p", class_="standfirst")
    meta["standfirst"] = _clean(standfirst.get_text()) if standfirst else ""

    desc = soup.find("meta", attrs={"name": "description"})
    meta["meta_description"] = desc.get("content", "") if desc else ""
    canonical = soup.find("link", rel="canonical")
    meta["canonical_url"] = canonical.get("href", "") if canonical else ""
    og_image = soup.find("meta", attrs={"property": "og:image"})
    meta["og_image"] = og_image.get("content", "") if og_image else ""

    meta["date_published"] = ""
    meta["jsonld"] = {}
    jsonld = soup.find("script", type="application/ld+json")
    if jsonld and jsonld.string:
        try:
            data = json.loads(jsonld.string)
            meta["jsonld"] = data
            meta["date_published"] = data.get("datePublished", "")
        except (ValueError, AttributeError):
            pass

    footer = soup.find("footer")
    if footer and footer.find("p"):
        meta["footer_html"] = "".join(str(c) for c in footer.find("p").children)
    else:
        meta["footer_html"] = ""

    meta["nav_prev"] = None
    meta["nav_next"] = None
    docnav = soup.find("nav", class_="docnav")
    if docnav:
        for cls in ("prev", "next"):
            a = docnav.find("a", class_=cls)
            if a:
                nm = a.find("div", class_="nm")
                meta[f"nav_{cls}"] = {
                    "url": a.get("href", ""),
                    "title": _clean(nm.get_text()) if nm else "",
                }
    return meta


def parse_page(html: str) -> ParsedPage:
    """Parse a full published page: metadata + article content."""
    soup = BeautifulSoup(html, "lxml")
    page = ParsedPage(meta=_parse_meta(soup))
    article = soup.find("article")
    if article is not None:
        page.blocks, page.images = parse_article(article)
    return page


def parse_fragment(html: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Parse a bare fragment of article content (unit-test convenience)."""
    soup = BeautifulSoup(f"<article>{html}</article>", "lxml")
    return parse_article(soup.find("article"))
