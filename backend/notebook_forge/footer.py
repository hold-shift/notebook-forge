"""Workspace-level footer / licence notice.

A single global Setting drives the footer that appears at the bottom of
every published HTML document, the homepage index, and every Google Doc
(safe edition). The footer is an editable BlockNote document (the same block
model as a memoir), stored under the Setting key ``footer`` as
``{"blocks": [...]}`` — so an operator gets full control over its contents
(paragraphs, headings, lists, links) from the Settings block editor.

The footer is authoritative workspace-wide: per-document ``footer_html``
meta is no longer consulted, so editing the message in Settings updates all
outputs on the next publish.
"""

from __future__ import annotations

from typing import Any

# Out-of-the-box default reproduces the archive's existing footer — the
# copyright notice and the Creative Commons licence as a link — as a single
# paragraph block. Legacy installs (the old notice/licence/url field trio)
# are migrated into equivalent blocks on read by `footer_blocks`.
DEFAULT_FOOTER: dict[str, str] = {
    "notice": "© Christopher M.R. Skitch · The Skitch Family Archive",
    "license_label": (
        "Licensed CC BY-NC-ND 4.0 — read and share with attribution; "
        "no commercial use or adaptations."
    ),
    "license_url": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
}


def _text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value, "styles": {}}


def _link(href: str, label: str) -> dict[str, Any]:
    return {"type": "link", "href": href, "content": [_text(label)]}


def _paragraph(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "paragraph", "props": {}, "content": content}


def _blocks_from_legacy(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a single paragraph block from the old notice/licence/url trio so
    an existing workspace keeps its footer verbatim after the upgrade."""
    notice = value.get("notice", DEFAULT_FOOTER["notice"]).strip()
    label = value.get("license_label", DEFAULT_FOOTER["license_label"]).strip()
    url = value.get("license_url", DEFAULT_FOOTER["license_url"]).strip()

    content: list[dict[str, Any]] = []
    if notice:
        content.append(_text(notice + (" · " if label else "")))
    if label:
        content.append(_link(url, label) if url else _text(label))
    return [_paragraph(content)] if content else []


def default_footer_blocks() -> list[dict[str, Any]]:
    return _blocks_from_legacy(DEFAULT_FOOTER)


def footer_blocks(session: Any) -> list[dict[str, Any]]:
    """The footer as a list of BlockNote blocks. Falls back to blocks built
    from the legacy notice/licence fields, then to the default footer."""
    from .models import Setting

    row = session.get(Setting, "footer")
    value = (row.value if row is not None else None) or {}
    blocks = value.get("blocks")
    if isinstance(blocks, list):
        return blocks
    if any(k in value for k in ("notice", "license_label", "license_url")):
        return _blocks_from_legacy(value)
    return default_footer_blocks()


def footer_setting(session: Any) -> dict[str, Any]:
    """The footer setting for the API: the block document the editor edits."""
    return {"blocks": footer_blocks(session)}


def footer_html(session: Any) -> str:
    """Render the footer blocks to an HTML fragment for the published pages
    and the homepage. Returns "" for an empty footer (templates emit none)."""
    from .renderer import render_fragment

    return render_fragment(footer_blocks(session))


def footer_markdown(session: Any) -> str:
    """Render the footer blocks to Markdown for the Google Doc (safe edition).
    Handles the block kinds a footer realistically uses: paragraphs, headings,
    quotes, list items and dividers."""
    from .safe_edition import inline_md

    lines: list[str] = []
    for block in footer_blocks(session):
        btype = block.get("type")
        props = block.get("props", {})
        text = inline_md(block.get("content")).strip()
        if btype == "paragraph":
            if text:
                lines.append(text)
        elif btype == "heading":
            if text:
                level = 3 if int(props.get("level", 2)) >= 3 else 2
                lines.append(f"{'#' * level} {text}")
        elif btype == "quote":
            if text:
                lines.append(f"> {text}")
        elif btype in ("bulletListItem", "numberedListItem"):
            if text:
                marker = "1." if btype == "numberedListItem" else "-"
                lines.append(f"{marker} {text}")
        elif btype == "divider":
            lines.append("---")
    return "\n".join(lines).strip()
