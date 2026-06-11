"""renumber_footnotes extracted from MemoirForge llm_polish/validate.py."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .footnotes import MARKER_RE as _INLINE_FOOTNOTE_RE
from .model import DocumentDraft


@dataclass
class OrphanRef:
    n: int
    block_id: str
    snippet: str


@dataclass
class RenumberResult:
    """Outcome of renumber_footnotes()."""
    renumbered: bool                       # True if anything actually changed
    old_to_new: dict[int, int] = field(default_factory=dict)
    notes_dropped: list[int] = field(default_factory=list)  # had no inline ref
    refs_dropped: list[OrphanRef] = field(default_factory=list)  # ref to no note



def renumber_footnotes(draft: DocumentDraft) -> RenumberResult:
    """Re-sequence footnotes 1..N based on order of first inline reference.

    Mutates draft.body and draft.footnotes in place. Idempotent on a
    clean doc (no renumbering occurs when refs and notes already line
    up). Operators should run validate_global() first to see what
    needs fixing.

    Strategy:
        1. Walk body in order; record the first appearance of each
           inline marker number.
        2. Build old→new mapping: the first new'd footnote gets 1,
           next gets 2, etc.
        3. Rewrite every inline marker via the mapping. Markers
           pointing at numbers with no corresponding footnote are
           recorded but otherwise left in place — the operator can
           decide whether to delete them.
        4. Rewrite draft.footnotes to use the new numbers, in the new
           order. Notes never referenced are dropped from the
           footnotes list (recorded in `notes_dropped`).
    """
    known_notes = {int(fn["n"]): fn for fn in draft.footnotes if "n" in fn}

    # First appearance of each (valid) footnote number.
    first_seen: list[int] = []
    refs_dropped: list[OrphanRef] = []
    text_idx = 0
    for entry in draft.body:
        if "kind" not in entry:
            continue
        block_id = f"b{text_idx:04d}"
        text_idx += 1
        text = entry.get("text", "") or ""
        for match in _INLINE_FOOTNOTE_RE.finditer(text):
            n = int(match.group(1))
            if n in known_notes:
                if n not in first_seen:
                    first_seen.append(n)
            else:
                # Inline ref to a note that doesn't exist — record but
                # don't include in renumber mapping.
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                refs_dropped.append(OrphanRef(
                    n=n, block_id=block_id, snippet=text[start:end].strip(),
                ))

    old_to_new = {old: i + 1 for i, old in enumerate(first_seen)}
    notes_dropped = sorted(set(known_notes) - set(first_seen))

    # No-op shortcut: if the mapping is identity (1→1, 2→2, …) AND no
    # notes_dropped AND no refs_dropped, nothing needs to change.
    is_identity = all(old == new for old, new in old_to_new.items())
    if is_identity and not notes_dropped and not refs_dropped:
        return RenumberResult(renumbered=False, old_to_new=old_to_new)

    # Rewrite body markers.
    def _repl(match: re.Match) -> str:
        old = int(match.group(1))
        new = old_to_new.get(old)
        if new is None:
            return match.group(0)  # leave orphan refs untouched
        return f"[^{new}]"

    for entry in draft.body:
        if "kind" not in entry:
            continue
        text = entry.get("text", "") or ""
        entry["text"] = _INLINE_FOOTNOTE_RE.sub(_repl, text)

    # Rewrite draft.footnotes — drop orphans, renumber, sort by new n.
    new_footnotes: list[dict[str, Any]] = []
    for old, new in old_to_new.items():
        original = known_notes[old]
        new_footnotes.append({**original, "n": new})
    new_footnotes.sort(key=lambda fn: fn["n"])
    draft.footnotes = new_footnotes

    return RenumberResult(
        renumbered=True,
        old_to_new=old_to_new,
        notes_dropped=notes_dropped,
        refs_dropped=refs_dropped,
    )

