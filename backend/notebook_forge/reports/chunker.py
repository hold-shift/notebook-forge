"""Group a document's block tree into per-chapter chunks for the report pass.

The locked report structure chunks on **top-level (level-2) heading blocks**:
one model call per chapter. Level-3 headings within a chapter delimit the
**sections** that become the digest keys and the `section` column value in the
reference tracks. Each chunk carries the chapter title, its ordered level-3
section headings, and a serialized text rendition fed to the model.

Divergences from the standalone `notebook_forge_reports.py` (which parsed the
exported Markdown):
- We read `doc.blocks` directly — no Markdown round-trip.
- Body content *before* the first level-2 heading is captured as its own
  "Opening" chunk rather than discarded as front-matter, so no prose is
  dropped (the standalone treated the pre-`##` span as the provenance header,
  which in-app comes from `Document.meta` instead).

The serialized text includes heading text, paragraph/quote/list text,
`forgeNarrative` text, `forgeFootnote` bodies, and figure **captions**; figure
image data is ignored. So the model sees the same `##`/`###` structure the
standalone fed it and can segment by section heading.
"""
from __future__ import annotations

import html as _htmllib
import re
from dataclasses import dataclass, field
from typing import Any

from ..blocks import (
    FORGE_FOOTNOTE,
    FORGE_IMAGE,
    FORGE_NARRATIVE,
    inline_text,
)

# Title for the synthetic chunk holding body content before the first chapter.
OPENING_TITLE = "Opening"

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ReportChunk:
    """One chapter bundled for a single per-chapter model call."""

    idx: int
    title: str  # level-2 heading text (or OPENING_TITLE for leading content)
    sections: list[str] = field(default_factory=list)  # level-3 headings, in order
    text: str = ""  # serialized chapter text for the prompt


def _strip_html(fragment: str) -> str:
    """Captions / footnote bodies hold minimal inline HTML; flatten to text."""
    if not fragment:
        return ""
    return _htmllib.unescape(_TAG_RE.sub("", fragment)).strip()


def _heading_level(block: dict[str, Any]) -> int:
    """BlockNote heading level lives in props.level (int, default 2)."""
    return min(3, max(1, int(block.get("props", {}).get("level", 2))))


def _block_lines(block: dict[str, Any]) -> list[str]:
    """Render one block (and its children) to text lines for the prompt.

    Returns [] for blocks that contribute no analysable text. Headings are
    handled by the caller (they drive chunk/section boundaries); this only
    renders body content.
    """
    btype = block.get("type", "")
    props = block.get("props", {})
    lines: list[str] = []

    if btype == FORGE_IMAGE:
        caption = _strip_html(props.get("caption", "")) or (props.get("altText") or "").strip()
        if caption:
            lines.append(f"[Figure: {caption}]")
    elif btype == FORGE_FOOTNOTE:
        body = _strip_html(props.get("text", ""))
        if body:
            marker = props.get("marker", "")
            lines.append(f"[{marker}] {body}" if marker else body)
    elif btype == FORGE_NARRATIVE:
        txt = inline_text(block.get("content")).strip()
        if txt:
            lines.append(f"> {txt}")
    elif btype in ("paragraph", "quote"):
        txt = inline_text(block.get("content")).strip()
        if txt:
            lines.append(f"> {txt}" if btype == "quote" else txt)
    elif btype in ("bulletListItem", "numberedListItem"):
        txt = inline_text(block.get("content")).strip()
        if txt:
            lines.append(f"- {txt}")

    for child in block.get("children") or []:
        if child.get("type") == "heading":
            continue  # nested headings are unusual; ignore for sectioning
        lines.extend(_block_lines(child))
    return lines


def chunk_document(blocks: list[dict[str, Any]]) -> list[ReportChunk]:
    """Split a block tree into per-chapter chunks at each level-2 heading.

    Leading body content before the first level-2 heading becomes an
    "Opening" chunk. Chunks whose text is empty (e.g. a heading with no body)
    are still returned so the chapter is represented in the digest.
    """
    chunks: list[ReportChunk] = []
    cur_title: str | None = None
    cur_sections: list[str] = []
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_title, cur_sections, cur_lines
        title = cur_title if cur_title is not None else OPENING_TITLE
        text = "\n".join(cur_lines).strip()
        # Skip an empty leading span (no opening prose before the first chapter).
        if cur_title is None and not text:
            cur_sections, cur_lines = [], []
            return
        header = f"## {title}"
        body = f"{header}\n{text}" if text else header
        chunks.append(
            ReportChunk(idx=len(chunks), title=title, sections=list(cur_sections), text=body)
        )
        cur_sections, cur_lines = [], []

    for block in blocks:
        if block.get("type") == "heading" and _heading_level(block) <= 2:
            flush()
            cur_title = inline_text(block.get("content")).strip() or "(untitled)"
            continue
        if block.get("type") == "heading" and _heading_level(block) == 3:
            sec = inline_text(block.get("content")).strip()
            if sec:
                cur_sections.append(sec)
                cur_lines.append(f"### {sec}")
            continue
        lines = _block_lines(block)
        if lines:
            cur_lines.extend(lines)

    flush()
    return chunks
