"""NotebookLM-safe edition: block tree → self-contained Markdown.

This is the Drive/NotebookLM deliverable: every figure embeds the SKETCH
(faceless rendition) inline as a base64 data URI, and its caption links out
to the original photo on the live page (`…#figure-N` — the PRD link
contract). Footnotes are co-located blockquotes with plain `[N]` ties (no
`[^N]` syntax — Docs would try to resolve it). No ToC (Docs builds its own
outline; spec: HTML output only).

Format ported from MemoirForge's document.md.j2 + assemble._data_uri:
images are downscaled (≤1024px longest edge, JPEG q80, PNG when alpha) so
the .md stays under Drive's ~50 MB conversion ceiling.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy.orm import Session

from .assets import asset_path
from .blocks import (
    FORGE_ATTACHMENT,
    FORGE_FOOTNOTE,
    FORGE_IMAGE,
    FORGE_NARRATIVE,
    attachment_published_path,
    ext_label,
    format_bytes,
)
from .models import Asset, Document

_INLINE_IMG_MAX_PX = 1024
_INLINE_IMG_JPEG_QUALITY = 80

# Operator-editable preamble inserted after the title block of every safe
# edition that actually contains figures. It exists because the substitution is
# invisible in the Doc itself: a reader (or NotebookLM) sees sketches with no
# explanation of why the photographs are missing. Editable in Settings.
DEFAULT_ILLUSTRATIONS_NOTE = """## A note on the illustrations

The figures in this document are sketches, not photographs. Where a
photograph in the original memoir shows a person, this edition carries a
drawn substitute in its place, with the caption unchanged.

This is not an editorial or stylistic choice, and it is not about privacy.
NotebookLM removes images containing identifiable people during ingestion,
so photographs of Bob and his family would simply be absent from this
edition. The sketches survive ingestion where the photographs do not.

Every original photograph is published at history.skitch.me, linked from
the caption of each figure below."""


def illustrations_note(session: Session) -> str:
    """The workspace note, as Markdown.

    Key-presence tri-state (as with the narrative label): a missing row or
    missing key inherits the default; a key explicitly set to "" means the
    operator turned the note off."""
    from .models import Setting

    row = session.get(Setting, "safe_edition")
    value = (row.value or {}) if row is not None else {}
    if "illustrations_note" not in value:
        return DEFAULT_ILLUSTRATIONS_NOTE
    return str(value.get("illustrations_note") or "")


def data_uri(path: Path) -> str:
    """Downscaled base64 data URI (raw-bytes fallback if Pillow can't read)."""
    try:
        from PIL import Image

        im = Image.open(path)
        im.load()
        has_alpha = im.mode in ("RGBA", "LA") or (
            im.mode == "P" and "transparency" in im.info
        )
        if max(im.size) > _INLINE_IMG_MAX_PX:
            im.thumbnail((_INLINE_IMG_MAX_PX, _INLINE_IMG_MAX_PX))
        buf = io.BytesIO()
        if has_alpha:
            im.convert("RGBA").save(buf, format="PNG", optimize=True)
            mime = "image/png"
        else:
            im.convert("RGB").save(
                buf, format="JPEG", quality=_INLINE_IMG_JPEG_QUALITY, optimize=True
            )
            mime = "image/jpeg"
        data = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp",
        }.get(path.suffix.lower(), "application/octet-stream")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _table_md(block: dict[str, Any]) -> list[str]:
    """A `table` block as GitHub-flavoured Markdown.

    GFM has no header-less table, so the first row is always the header —
    tables carried over from a scanned source open with their column labels.
    Cell text is single-line (a newline would end the row) and pipes are
    escaped."""
    rows = (block.get("content") or {}).get("rows") or []
    if not rows:
        return []
    width = max((len(r.get("cells") or []) for r in rows), default=0)

    def cells_of(row: dict[str, Any]) -> list[str]:
        cells = row.get("cells") or []
        out = []
        for i in range(width):
            text = inline_md(cells[i].get("content")) if i < len(cells) else ""
            out.append(" ".join(text.split()).replace("|", r"\|"))
        return out

    lines = ["| " + " | ".join(cells_of(rows[0])) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    lines += ["| " + " | ".join(cells_of(row)) + " |" for row in rows[1:]]
    return [*lines, ""]


def inline_md(content: list[dict[str, Any]] | None) -> str:
    """Inline runs → Markdown. fnRef markers become plain [N] visual ties."""
    out: list[str] = []
    for run in content or []:
        kind = run.get("type")
        if kind == "link":
            out.append(f"[{inline_md(run.get('content'))}]({run.get('href', '')})")
            continue
        if kind != "text":
            continue
        styles = run.get("styles") or {}
        text = run.get("text", "").replace("\r\n", "\n").replace("\n", "  \n")
        if styles.get("fnRef"):
            out.append(f"[{text}]")
            continue
        if styles.get("code"):
            text = f"`{text}`"
        if styles.get("bold") and styles.get("italic"):
            text = f"***{text}***"
        elif styles.get("bold"):
            text = f"**{text}**"
        elif styles.get("italic"):
            text = f"*{text}*"
        out.append(text)
    return "".join(out)


def html_fragment_to_md(fragment: str) -> str:
    """Captions / footnote bodies hold minimal inline HTML (em/strong/a).
    Convert to Markdown for the safe edition."""
    if "<" not in (fragment or ""):
        return fragment or ""
    soup = BeautifulSoup(f"<x>{fragment}</x>", "lxml").find("x")

    def walk(node: Tag) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                inner = walk(child)
                if child.name in ("em", "i"):
                    parts.append(f"*{inner}*")
                elif child.name in ("strong", "b"):
                    parts.append(f"**{inner}**")
                elif child.name == "a":
                    parts.append(f"[{inner}]({child.get('href', '')})")
                else:
                    parts.append(inner)
        return "".join(parts)

    return walk(soup)


def render_safe_markdown(
    meta: dict[str, Any],
    blocks: list[dict[str, Any]],
    sketch_src: Any,  # Callable[[dict, int], str] — figure block, n → image src
) -> str:
    """Render the safe edition. A labelled metadata block (Title / Standfirst /
    Author / Years covered / Source name), a rule, then the body with
    co-located footnote blockquotes and sketch figures whose captions link to
    the live anchors."""
    doc_url = meta.get("canonical_url", "")

    # Metadata header — one bold-labelled line each, hard-broken so they stack
    # tightly (two trailing spaces = a Markdown line break within one block).
    from .collection import count_words  # local import avoids an import cycle

    fields = [
        ("Title", meta.get("title", "")),
        ("Standfirst", meta.get("standfirst", "")),
        ("Author", meta.get("author", "")),
        ("Years covered", meta.get("year_display", "")),
        ("Source name", meta.get("slug", "") or meta.get("source_file", "")),
        ("Word count", f"{count_words(blocks):,}"),
    ]
    lines: list[str] = [f"**{label}:** {value}  " for label, value in fields if value]
    lines += ["", "---", ""]

    # The illustrations note sits between the title block and the body, and only
    # when this document actually carries figures in the safe edition — a
    # text-only memoir needs no explanation of sketches it doesn't contain.
    note = (meta.get("illustrations_note") or "").strip()
    has_figures = any(
        b.get("type") == FORGE_IMAGE and (b.get("props") or {}).get("safeMode") != "omit"
        for b in blocks
    )
    if note and has_figures:
        lines += [note, "", "---", ""]

    fig_n = 0
    att_n = 0
    prev_narrative = False
    seen_assets: dict[str, tuple[int, str]] = {}
    for block in blocks:
        btype = block.get("type")
        props = block.get("props", {})
        if btype == FORGE_NARRATIVE:
            text = inline_md(block.get("content")).strip()
            if text:
                if prev_narrative and lines and lines[-1] == "":
                    lines[-1] = ">"
                lines += [f"> {text}", ""]
                prev_narrative = True
            continue
        prev_narrative = False
        if btype == FORGE_IMAGE:
            asset_key = props.get("assetId") or ""
            if asset_key and asset_key in seen_assets:
                n, src = seen_assets[asset_key]
            else:
                fig_n += 1
                n = fig_n
                src = sketch_src(block, n)
                if asset_key:
                    seen_assets[asset_key] = (n, src)
            # safeMode: "sketch" (default) embeds the sketch; "original"
            # embeds the real photo (maps/diagrams that silhouetting only
            # degrades); "omit" drops the figure from the safe edition
            # entirely. The figure NUMBER is consumed either way so the
            # numbering stays aligned with the HTML edition's anchors.
            if props.get("safeMode") == "omit":
                continue
            alt = (props.get("altText") or f"Figure {n}").replace("\n", " ")
            caption = html_fragment_to_md(props.get("caption", "")).replace("\n", " ").strip()
            lines += [f"![{alt}]({src})", ""]
            link = f" — [View original photo]({doc_url}#figure-{n})" if doc_url else ""
            lines += [f"**Figure {n}.** {caption}{link}", ""]
        elif btype == FORGE_ATTACHMENT:
            # A PDF can't be inlined into a Google Doc, so the safe edition
            # links out to the copy hosted beside the published page — the
            # same contract as a figure caption's "View original photo".
            att_n += 1
            filename = str(props.get("filename", ""))
            rel = attachment_published_path(
                str(props.get("name", "")), filename, str(props.get("path", ""))
            )
            base = (meta.get("pages_base_url") or "").rstrip("/")
            href = f"{base}/{rel}" if base else (urljoin(doc_url, f"/{rel}") if doc_url else rel)
            name = str(props.get("name", "")) or filename or f"Attachment {att_n}"
            kind = ext_label(filename, str(props.get("mime", "")))
            size = format_bytes(int(props.get("sizeBytes") or 0))
            detail = f"{kind}, {size}" if size else kind
            lines += [f"**Attachment {att_n}.** [{name}]({href}) — {detail}", ""]
            description = str(props.get("description", "")).strip()
            if description:
                lines += [description, ""]
        elif btype == FORGE_FOOTNOTE:
            text = html_fragment_to_md(props.get("text", "")).strip()
            lines += [f"> **[{props.get('marker', '')}]** {text}", ""]
        elif btype == "heading":
            text = inline_md(block.get("content")).strip()
            if not text:
                continue
            level = 3 if int(props.get("level", 2)) >= 3 else 2
            lines += [f"{'#' * level} {text}", ""]
        elif btype == "paragraph":
            text = inline_md(block.get("content")).strip()
            if text:
                lines += [text, ""]
        elif btype == "quote":
            text = inline_md(block.get("content")).strip()
            if text:
                lines += [f"> {text}", ""]
        elif btype in ("bulletListItem", "numberedListItem"):
            marker = "1." if btype == "numberedListItem" else "-"
            lines += [f"{marker} {inline_md(block.get('content')).strip()}"]
        elif btype == "table":
            lines += _table_md(block)
        elif btype == "divider":
            lines += ["---", ""]

    # The footer is a block document; build_safe_markdown renders it to
    # Markdown via footer_markdown and passes it here as meta["footer_md"].
    # (Legacy direct callers may still pass an inline footer_html fragment.)
    footer = (meta.get("footer_md") or "").strip()
    if not footer and meta.get("footer_html"):
        footer = html_fragment_to_md(meta["footer_html"]).strip()
    if footer:
        lines += ["---", "", footer, ""]
    return "\n".join(lines).rstrip() + "\n"


def build_safe_markdown(session: Session, workspace: Path, doc: Document) -> str:
    """Safe edition for a stored document: sketches resolved from the asset
    store and inlined as data URIs (original photo as fallback when a
    figure has no sketch — and that gap is worth surfacing upstream)."""

    def sketch_src(block: dict[str, Any], n: int) -> str:
        props = block.get("props", {})
        if props.get("safeMode") == "original":
            keys = ("assetId",)  # maps/diagrams: the real image, deliberately
        else:
            keys = ("sketchAssetId", "assetId")
        for key in keys:
            asset = session.get(Asset, props.get(key) or "")
            if asset is not None:
                path = asset_path(workspace, asset)
                if path.exists():
                    return data_uri(path)
        return ""

    # Workspace-wide footer / licence notice, rendered straight from its block
    # document to Markdown for the Google Doc.
    from .collection import pages_base_url
    from .footer import footer_markdown

    meta = dict(doc.meta)
    meta["footer_md"] = footer_markdown(session)
    # Attachment links are absolute (the file sits at the site root, and a Doc
    # in Drive has no relative base at all).
    meta["pages_base_url"] = pages_base_url(session)
    meta["illustrations_note"] = illustrations_note(session)
    return render_safe_markdown(meta, doc.blocks, sketch_src)
