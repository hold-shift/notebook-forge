"""Block-tree ↔ polishable Markdown text.

block_to_polish_text: inline runs → Markdown-ish string for the LLM.
    Bold/italic use **/***/*, [^N] for fnRef, [text](url) for links.

polish_text_to_content (alias _md_inline_runs): inverse — parse the
    polished string back to inline runs.  Shared with ingestion.py.

polishable_blocks: extract (id, kind, text) from a block tree.

Round-trip invariant:
    polish_text_to_content(block_to_polish_text(block)) == block.content
must hold for every polishable text block.
"""
from __future__ import annotations

import re
from typing import Any

from ..blocks import text_run

# Block types that the polish pass handles (forgeImage / forgeFootnote excluded v1).
POLISHABLE = frozenset({
    "paragraph", "heading", "quote", "bulletListItem", "numberedListItem",
})

# Matches ***both***, **bold**, or *italic* — longest marker wins (left-to-right).
_EMPH_RE = re.compile(r"(\*\*\*|\*\*|\*)(.+?)\1", re.DOTALL)

# Matches [^N] fnRef OR [text](url) link in a single pass (fnRef alternative
# is first so [^1] never collides with [^1](url) link syntax — not that
# memoir text would have such links, but defensive ordering is cheap).
_INLINE_RE = re.compile(
    r"\[\^(?P<marker>\d+)\]"
    r"|\[(?P<link_text>[^\]]*)\]\((?P<link_url>[^)]*)\)"
)


# --------------------------------------------------------------------------- #
#  Serialize: block → Markdown text                                            #
# --------------------------------------------------------------------------- #

def block_to_polish_text(block: dict[str, Any]) -> str:
    """Serialize a block's inline content to Markdown-ish polish text.

    fnRef runs emit [^N]; emphasis emits **/***/*, links emit [text](url).
    """
    return _runs_to_md(block.get("content") or [])


def _runs_to_md(content: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for run in content:
        kind = run.get("type")
        if kind == "link":
            inner = _runs_to_md(run.get("content") or [])
            out.append(f"[{inner}]({run.get('href', '')})")
            continue
        if kind != "text":
            continue
        styles = run.get("styles") or {}
        text = run.get("text", "")
        if styles.get("fnRef"):
            out.append(f"[^{text}]")
            continue
        if styles.get("code"):
            text = f"`{text}`"
        elif styles.get("bold") and styles.get("italic"):
            text = f"***{text}***"
        elif styles.get("bold"):
            text = f"**{text}**"
        elif styles.get("italic"):
            text = f"*{text}*"
        out.append(text)
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Deserialize: Markdown text → runs                                           #
# --------------------------------------------------------------------------- #

def polish_text_to_content(text: str) -> list[dict[str, Any]]:
    """Parse Markdown-ish polished text back to inline runs.

    Handles [^N] fnRef markers, [text](url) links, and ***/**/* emphasis.
    Shared with ingestion.py via the _md_inline_runs alias below.
    """
    runs: list[dict[str, Any]] = []

    def append_plain(segment: str) -> None:
        pos = 0
        for m in _EMPH_RE.finditer(segment):
            if m.start() > pos:
                runs.append(text_run(segment[pos:m.start()]))
            marks = m.group(1)
            styles: dict[str, Any] = {}
            if "**" in marks:
                styles["bold"] = True
            if marks in ("*", "***"):
                styles["italic"] = True
            runs.append(text_run(m.group(2), styles))
            pos = m.end()
        if pos < len(segment):
            runs.append(text_run(segment[pos:]))

    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            append_plain(text[pos:m.start()])
        if m.group("marker") is not None:
            runs.append(text_run(m.group("marker"), {"fnRef": True}))
        else:
            link_text = m.group("link_text") or ""
            link_url = m.group("link_url") or ""
            inner = polish_text_to_content(link_text) if link_text else []
            runs.append({"type": "link", "href": link_url, "content": inner})
        pos = m.end()
    if pos < len(text):
        append_plain(text[pos:])

    return [r for r in runs if r.get("text") or r.get("type") == "link"]


# Alias used by ingestion.py — single canonical home for the shared parser.
_md_inline_runs = polish_text_to_content


# --------------------------------------------------------------------------- #
#  polishable_blocks: extract (id, kind, text)                                 #
# --------------------------------------------------------------------------- #

def polishable_blocks(blocks: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return (block_id, kind, text) for every polishable text block.

    kind: h1/h2/h3 for headings, p for paragraphs/lists/quotes.
    Blocks with empty text are excluded.
    """
    out: list[tuple[str, str, str]] = []
    for block in blocks:
        btype = block.get("type", "")
        if btype not in POLISHABLE:
            continue
        text = block_to_polish_text(block)
        if not text.strip():
            continue
        if btype == "heading":
            level = min(3, max(1, int(block.get("props", {}).get("level", 2))))
            kind = f"h{level}"
        else:
            kind = "p"
        out.append((block["id"], kind, text))
    return out
