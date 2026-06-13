"""forgeNarrative: the author's reflective voice (full-italic source
paragraphs become a semantic block, rendered upright in a tinted panel).

Rule B (locked): a paragraph converts iff its ENTIRE text content is
italic, ignoring runs with no alphanumeric character and fnRef marker
runs. Paragraph blocks only — headings, quotes, list items, captions and
footnotes are excluded by construction.
"""

from __future__ import annotations

import copy
from typing import Any

from .blocks import FORGE_NARRATIVE, inline_text

FLAG_WORDS = 12  # conversions under this word count are flagged for review


def _has_word(text: str) -> bool:
    """Return True if the string contains at least one alphanumeric character."""
    return any(c.isalnum() for c in text)


def _runs_all_italic(content: list[dict[str, Any]]) -> tuple[bool, bool]:
    """Return (all_italic, saw_italic_word).

    Iterates over runs in *content*:
    - text runs with no alphanumeric chars → ignored (whitespace/punctuation)
    - text runs styled fnRef → ignored
    - text runs with a word char → must have italic=True
    - link runs → recurse into run["content"]
    - unknown run types → conservative: not italic
    """
    all_italic = True
    saw_italic_word = False

    for run in content or []:
        kind = run.get("type")
        if kind == "text":
            text = run.get("text", "")
            styles = run.get("styles") or {}
            if styles.get("fnRef"):
                continue
            if not _has_word(text):
                continue
            if styles.get("italic"):
                saw_italic_word = True
            else:
                all_italic = False
        elif kind == "link":
            inner_all, inner_saw = _runs_all_italic(run.get("content") or [])
            if not inner_all:
                all_italic = False
            if inner_saw:
                saw_italic_word = True
        else:
            all_italic = False

    return all_italic, saw_italic_word


def is_fully_italic(content: list[dict[str, Any]] | None) -> bool:
    """Return True iff content is entirely italic with at least one italic word run."""
    all_italic, saw_italic_word = _runs_all_italic(content or [])
    return all_italic and saw_italic_word


def strip_italic(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy runs removing 'italic' from every styles dict.

    Links recurse; fnRef runs returned unchanged (their styles are not
    modified). Other styles (bold, etc.) are preserved.
    """
    result = []
    for run in content:
        run = copy.deepcopy(run)
        kind = run.get("type")
        if kind == "text":
            styles = dict(run.get("styles") or {})
            if not styles.get("fnRef"):
                styles.pop("italic", None)
            run["styles"] = styles
        elif kind == "link":
            run["content"] = strip_italic(run.get("content") or [])
        result.append(run)
    return result


def add_italic(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy runs adding italic=True to every text run, except fnRef runs.

    This is the inverse of strip_italic for the editor convert-back path.
    Links recurse.
    """
    result = []
    for run in content:
        run = copy.deepcopy(run)
        kind = run.get("type")
        if kind == "text":
            styles = dict(run.get("styles") or {})
            if not styles.get("fnRef"):
                styles["italic"] = True
            run["styles"] = styles
        elif kind == "link":
            run["content"] = add_italic(run.get("content") or [])
        result.append(run)
    return result


def conversion_report_entry(block: dict[str, Any]) -> dict[str, Any]:
    """Build a conversion report entry for a paragraph being converted (D18)."""
    plain = inline_text(block.get("content"))
    words = len(plain.split()) if plain.strip() else 0
    preview = plain[:90] + ("…" if len(plain) > 90 else "")
    return {
        "words": words,
        "preview": preview,
        "flagged": words < FLAG_WORDS,
    }


def convert_full_italic_paragraphs(
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert fully-italic paragraph blocks to forgeNarrative (rule B).

    Returns (new_blocks, conversions).  Non-mutating; converted blocks keep
    their existing id.  Top-level only — children are never visited.
    Running twice equals running once (idempotent: forgeNarrative blocks
    pass through unchanged).
    """
    new_blocks = []
    conversions: list[dict[str, Any]] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "paragraph" and is_fully_italic(block.get("content")):
            entry = conversion_report_entry(block)
            new_blocks.append(
                {
                    **block,
                    "type": FORGE_NARRATIVE,
                    "props": {},
                    "content": strip_italic(block.get("content") or []),
                }
            )
            conversions.append(entry)
        else:
            new_blocks.append(block)
    return new_blocks, conversions


def narrative_label_setting(session: Any) -> str:
    """Return the workspace-level narrative label from the Setting row.

    Missing row or missing key → empty string.
    """
    from .models import Setting

    row = session.get(Setting, "narrative")
    if row is None:
        return ""
    return (row.value or {}).get("label", "")


def effective_narrative_label(session: Any, doc: Any) -> str:
    """Resolve the effective label for a document (D9 key-presence tri-state).

    If 'narrative_label' key is present in doc.meta (even as ""), use it.
    Otherwise inherit the workspace setting.
    """
    if "narrative_label" in doc.meta:
        return str(doc.meta["narrative_label"])
    return narrative_label_setting(session)
