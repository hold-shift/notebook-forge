"""Block tree → house-style HTML (M3). The inverse of parser.py.

The page template is ported verbatim from MemoirForge (templates/page.html.j2
— the generator of the published family-history pages), so rendering a
parsed page reproduces the published markup. All derived furniture —
heading anchors, figure numbers/anchors, the ToC nav tree, the lead
paragraph, JSON-LD — is recomputed here from the block tree + metadata.
"""

from __future__ import annotations

import html as html_mod
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from slugify import slugify

from .blocks import FORGE_FOOTNOTE, FORGE_IMAGE, FORGE_NARRATIVE, inline_text

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Default ToC policy for documents that don't carry an explicit show_toc
# (imported docs store the published page's value).
TOC_HEADING_THRESHOLD = 15

# Wrapper order matters for byte-fidelity: the corpus nests <em><strong>…
_STYLE_TAGS = [
    ("italic", "em"),
    ("bold", "strong"),
    ("underline", "u"),
    ("strike", "s"),
    ("code", "code"),
]


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _escape(text: str) -> str:
    return html_mod.escape(text, quote=False)


def inline_html(content: list[dict[str, Any]] | None) -> str:
    """Inline runs → HTML string (escaped text, style wrappers, fn markers)."""
    out: list[str] = []
    for run in content or []:
        kind = run.get("type")
        if kind == "link":
            href = html_mod.escape(run.get("href", ""), quote=True)
            out.append(f'<a href="{href}">{inline_html(run.get("content"))}</a>')
            continue
        if kind != "text":
            continue
        styles = run.get("styles") or {}
        text = _escape(run.get("text", ""))
        if styles.get("fnRef"):
            out.append(f'<sup class="fn-ref">{text}</sup>')
            continue
        for key, tag in reversed(_STYLE_TAGS):
            if styles.get(key):
                text = f"<{tag}>{text}</{tag}>"
        out.append(text)
    return "".join(out)


def _assign_heading_anchors(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unique slug anchors for non-blank H2/H3, in document order (same rule
    as the published corpus). Returns the flat ToC list."""
    used: set[str] = set()
    toc: list[dict[str, Any]] = []
    for entry in body:
        kind = entry.get("kind")
        if kind not in ("h2", "h3"):
            continue
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        base = slugify(text, separator="-", lowercase=True) or "section"
        anchor = base
        i = 2
        while anchor in used:
            anchor = f"{base}-{i}"
            i += 1
        used.add(anchor)
        entry["anchor"] = anchor
        toc.append({"level": int(kind[1]), "text": text, "anchor": anchor})
    return toc


def build_heading_tree(flat_toc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """H2 = group, H3 = kid; orphan H3 promoted to its own group."""
    tree: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in flat_toc:
        if item["level"] == 2:
            current = {"text": item["text"], "anchor": item["anchor"], "kids": []}
            tree.append(current)
        else:
            kid = {"text": item["text"], "anchor": item["anchor"]}
            if current is not None:
                current["kids"].append(kid)
            else:
                tree.append({"text": item["text"], "anchor": item["anchor"], "kids": []})
    return tree


ImageSrc = Callable[[dict[str, Any], int], str]


def build_body(
    blocks: list[dict[str, Any]],
    image_src: ImageSrc,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Block tree → template body entries + flat heading ToC.

    Figure numbering is sequential over forgeImage blocks in document
    order; anchors are figure-{n}. The first non-empty paragraph gets the
    lead flag (drop-cap). Empty paragraphs/headings are not emitted —
    matching the corpus generator, which skipped blank text blocks.
    """
    body: list[dict[str, Any]] = []
    fig_n = 0
    first_para_done = False
    # Figure numbering is per unique image, first-occurrence order: the
    # published corpus re-renders a repeated image as a verbatim copy of
    # its first figure (same n, anchor and src), so a duplicate assetId
    # reuses the original number instead of advancing the counter.
    seen_assets: dict[str, tuple[int, str]] = {}

    for block in blocks:
        btype = block.get("type")
        props = block.get("props", {})
        if btype == FORGE_IMAGE:
            asset_key = props.get("assetId") or ""
            if asset_key and asset_key in seen_assets:
                n, src = seen_assets[asset_key]
            else:
                fig_n += 1
                n = fig_n
                src = image_src(block, n)
                if asset_key:
                    seen_assets[asset_key] = (n, src)
            body.append(
                {
                    "kind": "figure",
                    "n": n,
                    "anchor": f"figure-{n}",
                    "src": src,
                    "alt": props.get("altText", ""),
                    "caption": Markup(props.get("caption", "")),
                    "portrait": props.get("displayWidth") == "portrait",
                }
            )
        elif btype == FORGE_FOOTNOTE:
            body.append(
                {
                    "kind": "footnote",
                    "n": props.get("marker", ""),
                    "text_html": props.get("text", ""),
                }
            )
        elif btype == "heading":
            text = inline_text(block.get("content"))
            if not text.strip():
                continue
            level = int(props.get("level", 2))
            level = 3 if level >= 3 else 2
            body.append(
                {
                    "kind": f"h{level}",
                    "text": text,
                    "text_html": inline_html(block.get("content")),
                }
            )
        elif btype == "paragraph":
            text = inline_text(block.get("content"))
            if not text.strip():
                continue
            entry = {
                "kind": "p",
                "text": text,
                "text_html": inline_html(block.get("content")),
            }
            if not first_para_done:
                entry["lead"] = True
                first_para_done = True
            body.append(entry)
        elif btype == FORGE_NARRATIVE:
            text = inline_text(block.get("content"))
            if not text.strip():
                continue
            body.append(
                {
                    "kind": "narrative",
                    "text": text,
                    "paragraphs": [Markup(inline_html(block.get("content")))],
                }
            )
        elif btype == "quote":
            body.append(
                {
                    "kind": "blockquote",
                    "text": inline_text(block.get("content")),
                    "text_html": inline_html(block.get("content")),
                }
            )
        elif btype in ("bulletListItem", "numberedListItem"):
            body.append(_list_entry(block))
        elif btype == "divider":
            body.append({"kind": "hr"})
        elif btype == "table":
            body.append({"kind": "table", "html": Markup(_table_html(block))})

    body = _group_list_items(body)
    body = _merge_narrative(body)
    toc = _assign_heading_anchors(body)
    return body, toc


def _list_entry(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "li",
        "ordered": block["type"] == "numberedListItem",
        "text_html": inline_html(block.get("content")),
        "children": [_list_entry(c) for c in block.get("children") or []],
    }


def _li_html(entry: dict[str, Any]) -> str:
    inner = entry["text_html"]
    kids = entry.get("children") or []
    if kids:
        tag = "ol" if kids[0]["ordered"] else "ul"
        inner += f"<{tag}>" + "".join(_li_html(k) for k in kids) + f"</{tag}>"
    return f"<li>{inner}</li>"


def _group_list_items(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse runs of consecutive list items into one list entry so the
    template can emit a single <ul>/<ol>."""
    out: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []

    def flush() -> None:
        if not run:
            return
        tag = "ol" if run[0]["ordered"] else "ul"
        html = f"<{tag}>" + "".join(_li_html(e) for e in run) + f"</{tag}>"
        out.append({"kind": "list", "html": Markup(html)})
        run.clear()

    for entry in body:
        if entry["kind"] == "li":
            if run and run[0]["ordered"] != entry["ordered"]:
                flush()
            run.append(entry)
        else:
            flush()
            out.append(entry)
    flush()
    return out


def _merge_narrative(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive narrative entries collapse into ONE panel (locked decision A)."""
    out: list[dict[str, Any]] = []
    for entry in body:
        if entry["kind"] == "narrative" and out and out[-1]["kind"] == "narrative":
            out[-1]["paragraphs"].extend(entry["paragraphs"])
        else:
            out.append(entry)
    return out


def _table_html(block: dict[str, Any]) -> str:
    rows_html = []
    for row in (block.get("content") or {}).get("rows", []):
        cells = "".join(f"<td>{inline_html(c.get('content'))}</td>" for c in row.get("cells", []))
        rows_html.append(f"<tr>{cells}</tr>")
    return "<table>" + "".join(rows_html) + "</table>"


def build_jsonld(meta: dict[str, Any]) -> str:
    """Re-emit JSON-LD. Imported docs carry the published object in
    meta['jsonld']; headline/description are refreshed from current fields
    so edits propagate. Compact separators match the published bytes."""
    base = dict(meta.get("jsonld") or {})
    if not base:
        base = {
            "@context": "https://schema.org",
            "@type": "Article",
            "inLanguage": "en",
        }
    if meta.get("title"):
        base["headline"] = meta["title"]
    description = meta.get("meta_description") or meta.get("standfirst") or ""
    if description:
        base["description"] = description
    if meta.get("canonical_url"):
        base["url"] = meta["canonical_url"]
    return (
        '<script type="application/ld+json">'
        + json.dumps(base, ensure_ascii=False, separators=(",", ":"))
        + "</script>"
    )


def render_document(
    meta: dict[str, Any],
    blocks: list[dict[str, Any]],
    image_src: ImageSrc,
) -> str:
    body, toc = build_body(blocks, image_src)
    heading_count = len(toc)
    show_toc = meta.get("show_toc")
    if show_toc is None:
        show_toc = heading_count > TOC_HEADING_THRESHOLD

    header = {
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "overline": meta.get("overline", ""),
        "standfirst": meta.get("standfirst", ""),
        "place": meta.get("place", ""),
    }
    tpl = _env().get_template("page.html.j2")
    return tpl.render(
        header=header,
        year_display=meta.get("year_display", ""),
        figures=[],
        body=body,
        toc=toc,
        toc_tree=build_heading_tree(toc),
        show_toc=bool(show_toc),
        show_lof=False,
        footer_text=meta.get("footer_html", ""),
        homepage_url=meta.get("homepage_url", ""),
        canonical_url=meta.get("canonical_url", ""),
        meta_description=meta.get("meta_description") or meta.get("standfirst", ""),
        og_image=meta.get("og_image", ""),
        jsonld_script=build_jsonld(meta),
        nav_prev=meta.get("nav_prev"),
        nav_next=meta.get("nav_next"),
        narrative_label=meta.get("narrative_label", ""),
    )


def render_index(
    *,
    title: str,
    welcome: str,
    dedication: str,
    entries: list[dict[str, Any]],
    footer_text: str = "",
    canonical_url: str = "",
    og_description: str = "",
    jsonld_script: str = "",
    body_entries: list[dict[str, Any]] | None = None,
) -> str:
    """Collection index page from document metadata."""
    tpl = _env().get_template("index.html.j2")
    return tpl.render(
        title=title,
        welcome=welcome,
        dedication=dedication,
        entries=entries,
        footer_text=footer_text,
        canonical_url=canonical_url,
        og_description=og_description,
        jsonld_script=jsonld_script,
        body_entries=body_entries,
    )
