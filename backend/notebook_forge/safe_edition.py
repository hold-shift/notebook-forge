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

from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy.orm import Session

from .assets import asset_path
from .blocks import FORGE_FOOTNOTE, FORGE_IMAGE, FORGE_NARRATIVE
from .models import Asset, Document

_INLINE_IMG_MAX_PX = 1024
_INLINE_IMG_JPEG_QUALITY = 80


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

    fig_n = 0
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
        elif btype == "divider":
            lines += ["---", ""]

    if meta.get("footer_html"):
        footer = html_fragment_to_md(meta["footer_html"]).strip()
        lines += ["---", "", f"*{footer}*", ""]
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

    # Workspace-wide footer / licence notice; html_fragment_to_md turns the
    # licence anchor into a Markdown link for the Google Doc.
    from .footer import footer_html

    meta = dict(doc.meta)
    meta["footer_html"] = footer_html(session)
    return render_safe_markdown(meta, doc.blocks, sketch_src)
