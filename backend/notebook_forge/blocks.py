"""Block-tree helpers: canonical hashing and plain-text extraction.

The canonical document format is BlockNote block JSON plus two custom blocks:

  forgeImage    props: { assetId, sketchAssetId?, caption, altText,
                         approval: "pending"|"approved", peopleCount?,
                         displayWidth: "full"|"portrait" }
  forgeFootnote props: { marker, text }

A block is { id, type, props, content, children }. Inline content items are
{ type: "text", text, styles } or { type: "link", href, content: [...] }.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

FORGE_IMAGE = "forgeImage"
FORGE_FOOTNOTE = "forgeFootnote"


def new_id() -> str:
    return str(uuid.uuid4())


def make_block(
    block_type: str,
    props: dict[str, Any] | None = None,
    content: list[dict[str, Any]] | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": new_id(),
        "type": block_type,
        "props": props or {},
        "content": content if content is not None else [],
        "children": children or [],
    }


def text_run(text: str, styles: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "text", "text": text, "styles": styles or {}}


def _strip_ids(node: Any) -> Any:
    """Recursively drop block ids so hashing reflects content, not identity."""
    if isinstance(node, dict):
        return {k: _strip_ids(v) for k, v in node.items() if k != "id"}
    if isinstance(node, list):
        return [_strip_ids(item) for item in node]
    return node


def content_hash(blocks: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    """Stable hash of a block tree (+ rendering-relevant meta). Block ids are
    excluded — two trees with the same content hash render identically."""
    payload = {"blocks": _strip_ids(blocks), "meta": meta or {}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def inline_text(content: list[dict[str, Any]] | str | None) -> str:
    """Flatten inline content to plain text (links recurse)."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind == "link":
            parts.append(inline_text(item.get("content")))
    return "".join(parts)


def plain_text(blocks: list[dict[str, Any]]) -> str:
    """Extract searchable plain text from a block tree (for FTS indexing)."""
    out: list[str] = []

    def walk(block: dict[str, Any]) -> None:
        btype = block.get("type")
        props = block.get("props", {})
        if btype == FORGE_IMAGE:
            for key in ("caption", "altText"):
                if props.get(key):
                    out.append(str(props[key]))
        elif btype == FORGE_FOOTNOTE:
            if props.get("text"):
                out.append(str(props["text"]))
        else:
            txt = inline_text(block.get("content"))
            if txt:
                out.append(txt)
        for child in block.get("children") or []:
            walk(child)

    for b in blocks:
        walk(b)
    return "\n".join(out)
