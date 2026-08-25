"""Block-tree helpers: canonical hashing and plain-text extraction.

The canonical document format is BlockNote block JSON plus custom blocks:

  forgeImage     props: { assetId, sketchAssetId?, caption, altText,
                          approval: "pending"|"approved", peopleCount?,
                          displayWidth: "full"|"portrait" }
  forgeFootnote  props: { marker, text }
  forgeNarrative content: inline runs; props: {}
  forgeDedication props: { text }
  forgeDocGroup  props: { groupId, sort, showBlurbs, showWordCounts, layout }
  forgeAttachment props: { assetId, name, description, filename, mime,
                          sizeBytes, path }

A block is { id, type, props, content, children }. Inline content items are
{ type: "text", text, styles } or { type: "link", href, content: [...] }.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from slugify import slugify

FORGE_IMAGE = "forgeImage"
FORGE_FOOTNOTE = "forgeFootnote"
FORGE_DOC_GROUP = "forgeDocGroup"
FORGE_DEDICATION = "forgeDedication"
FORGE_NARRATIVE = "forgeNarrative"
FORGE_ATTACHMENT = "forgeAttachment"
HOMEPAGE_SLUG = "homepage"

# Longest slug we put in a published attachment filename (readability only —
# the operator controls the rest of the path).
_ATTACHMENT_SLUG_MAX = 60

# Site-root files the publish layer regenerates on every publish. An attachment
# may never take one of these names: it would be silently overwritten (or would
# overwrite the site's own furniture) on the next publish.
RESERVED_ROOT_FILES = frozenset(
    {"index.html", "catalogue.json", "sitemap.xml", "robots.txt", "llms.txt"}
    | {f"favicon{ext}" for ext in (".png", ".ico", ".svg", ".jpg", ".jpeg", ".webp")}
    | {f"og-image{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp")}
)

_SEPARATORS = re.compile(r"[\\/]+")


def _raw_segments(raw: str) -> list[str]:
    """Split an operator-typed path on either slash, dropping everything that
    could escape the site root — a leading slash, ``..``, ``.``, empty
    segments — so a typo can never write outside the published tree."""
    return [
        segment.strip()
        for segment in _SEPARATORS.split(raw or "")
        if segment.strip() and segment.strip() not in (".", "..")
    ]


def attachment_published_path(name: str, filename: str, path: str = "") -> str:
    """Where an attachment is published, relative to the SITE ROOT.

    ``path`` is the operator's field. Empty puts the file at the site root;
    ``rfs/vietnam/attachments`` puts it in that folder. A last segment that
    looks like a filename (it has a dot) names the file; otherwise the name is
    slugified into one. The extension always comes from the uploaded file, so
    a typed path can never change what the URL claims the file is.

    Shared by the publish bundle, the page renderer, the safe edition and the
    JSON-LD builder — they must agree byte for byte or the published link
    points at a file that isn't there."""
    ext = ""
    if "." in (filename or ""):
        ext = "." + filename.rsplit(".", 1)[1].lower()

    segments = _raw_segments(path)
    stem_source = ""
    if segments and "." in segments[-1]:
        stem_source = segments.pop().rsplit(".", 1)[0]
    if not stem_source:
        stem_source = (name or "").strip() or (filename or "").rsplit(".", 1)[0]

    folders = [slug for slug in (_slug(seg) for seg in segments) if slug]
    stem = _slug(stem_source)[:_ATTACHMENT_SLUG_MAX].strip("-") or "attachment"
    return "/".join([*folders, f"{stem}{ext}"])


def _slug(text: str) -> str:
    return slugify(text, separator="-", lowercase=True)


def ext_label(filename: str, mime: str) -> str:
    """Short type label for an attachment: 'PDF', 'DOCX', 'FILE'."""
    if "." in (filename or ""):
        ext = filename.rsplit(".", 1)[1].strip().upper()
        if ext:
            return ext[:5]
    if "/" in (mime or ""):
        return (mime.rsplit("/", 1)[1] or "file").upper()[:5]
    return "FILE"


def format_bytes(size: int | None) -> str:
    """Human file size for display: 2517621 -> '2.4 MB'. Powers of 1024, one
    decimal below 10 units, no decimal above."""
    if not size or size <= 0:
        return ""
    units = ("bytes", "KB", "MB", "GB")
    value = float(size)
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} bytes"
    return f"{value:.1f} {units[idx]}" if value < 10 else f"{value:.0f} {units[idx]}"


def new_id() -> str:
    return str(uuid.uuid4())


def make_block(
    block_type: str,
    props: dict[str, Any] | None = None,
    # Usually a list of inline runs; `table` blocks carry a tableContent dict.
    content: list[dict[str, Any]] | dict[str, Any] | None = None,
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


def inline_text(content: list[dict[str, Any]] | dict[str, Any] | str | None) -> str:
    """Flatten inline content to plain text (links recurse).

    A `table` block's content is a tableContent DICT rather than a list of
    runs, so it's flattened cell by cell — callers that walk every block
    (plain_text, for the search index) must not choke on one, and the text in
    a table is as searchable as any other."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        cells = (
            inline_text(cell.get("content"))
            for row in content.get("rows") or []
            for cell in row.get("cells") or []
        )
        return " ".join(text for text in cells if text.strip())
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
        elif btype == FORGE_ATTACHMENT:
            for key in ("name", "description"):
                if props.get(key):
                    out.append(str(props[key]))
        else:
            txt = inline_text(block.get("content"))
            if txt:
                out.append(txt)
        for child in block.get("children") or []:
            walk(child)

    for b in blocks:
        walk(b)
    return "\n".join(out)
