"""Per-block fidelity guard for the LLM polish output.

Ported near-verbatim from MemoirForge llm_polish/fidelity.py.

Two additions for NotebookForge:
1. Emphasis markers (**  *) are normalised away BEFORE the typography
   pairs so a marker move (e.g. *italic* → italic) never counts as a
   word change — our polish text carries Markdown markers, the reference's
   plain text didn't.
2. Footnote-marker hard check: multisets of [^N] markers are compared
   on the RAW text before any normalisation.  A dropped or added marker
   flags the block regardless of the word diff (rule: the marker ties a
   passage to its note; a position change cannot be silently accepted).
"""
from __future__ import annotations

import difflib
import re
import string
from dataclasses import dataclass, field

# ---------------------------------------------------------------- normalisation

_TYPOGRAPHY_NORMALISATION = [
    # Emphasis markers first — strip before comparing word tokens so a
    # **bold** ↔ bold style move is not counted as a word change.
    ("***", ""),
    ("**", ""),
    ("*", ""),
    # Smart-quote / dash / nbsp normalisation (MemoirForge verbatim)
    ("“", '"'), ("”", '"'),   # " " → "
    ("‘", "'"), ("’", "'"),   # ' ' → '
    ("„", '"'), ("‚", "'"),   # „ ‚ (low-9) → " '
    ("…", "..."),                  # … → ...
    ("—", "-"), ("–", "-"),   # — – → -
    (" ", " "),                    # NBSP → SPACE
]

# Used only for the footnote-marker hard check — raw text, no normalisation.
_MARKER_RE = re.compile(r"\[\^\d+\]")


def _normalise(text: str) -> str:
    for bad, good in _TYPOGRAPHY_NORMALISATION:
        text = text.replace(bad, good)
    return text


def _tokenize_words(text: str) -> list[str]:
    norm = _normalise(text)
    out: list[str] = []
    for w in norm.split():
        stripped = w.strip(string.punctuation)
        if stripped:
            out.append(stripped)
    return out


def _is_hyphen_space_collapse(orig_run: list[str], pol_run: list[str]) -> bool:
    """True when a replace op only rearranges hyphens/spaces, same letters."""
    a = "".join(orig_run).replace("-", "")
    b = "".join(pol_run).replace("-", "")
    return a != "" and a == b


def _extract_markers(text: str) -> list[str]:
    """Sorted list of [^N] markers in text (multiset comparison)."""
    return sorted(_MARKER_RE.findall(text))


# ---------------------------------------------------------------- verdict

@dataclass
class FidelityVerdict:
    """The result of comparing one block's original vs polished text."""
    block_id: str
    typography_only: bool
    word_inserts: int
    word_deletes: int
    word_replaces: int
    char_diff: int
    summary: str
    marker_mismatch: bool = field(default=False)

    @property
    def changed_words(self) -> int:
        return self.word_inserts + self.word_deletes + self.word_replaces

    @property
    def is_clean(self) -> bool:
        """Safe to auto-apply without operator review."""
        return self.typography_only and not self.marker_mismatch


def check_block_fidelity(
    original: str, polished: str, block_id: str,
) -> FidelityVerdict:
    """Compare original vs polished text and produce a verdict.

    A verdict is "clean" iff the polish only changed typography / whitespace
    AND no footnote markers were dropped or added.
    """
    # Hard check: footnote marker multiset must be identical.
    marker_mismatch = _extract_markers(original) != _extract_markers(polished)

    orig_words = _tokenize_words(original)
    pol_words = _tokenize_words(polished)

    sm = difflib.SequenceMatcher(a=orig_words, b=pol_words, autojunk=False)
    inserts = 0
    deletes = 0
    replaces = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "insert":
            inserts += j2 - j1
        elif op == "delete":
            deletes += i2 - i1
        elif op == "replace":
            if _is_hyphen_space_collapse(orig_words[i1:i2], pol_words[j1:j2]):
                continue
            replaces += max(i2 - i1, j2 - j1)

    typography_only = inserts == 0 and deletes == 0 and replaces == 0
    char_diff = len(polished) - len(original)

    if not typography_only:
        parts = []
        if inserts:
            parts.append(f"+{inserts} word{'s' if inserts != 1 else ''}")
        if deletes:
            parts.append(f"-{deletes} word{'s' if deletes != 1 else ''}")
        if replaces:
            parts.append(f"~{replaces} word{'s' if replaces != 1 else ''} replaced")
        summary = ", ".join(parts) if parts else "no word changes"
    elif marker_mismatch:
        summary = "footnote marker changed"
    else:
        summary = "typography only" + (f" ({char_diff:+d} chars)" if char_diff else "")

    return FidelityVerdict(
        block_id=block_id,
        typography_only=typography_only,
        word_inserts=inserts,
        word_deletes=deletes,
        word_replaces=replaces,
        char_diff=char_diff,
        summary=summary,
        marker_mismatch=marker_mismatch,
    )


def diff_segments(original: str, polished: str) -> list[dict[str, str]]:
    """Word-level diff of the RAW texts for display highlighting.

    Returns [{"op": "equal"|"delete"|"insert"|"replace", "a": str, "b": str}]
    where the concatenation of all "a" == original and all "b" == polished.
    Uses raw text (no typography normalisation) — the smart-quote changes it
    strips are exactly what the reviewer needs to see.
    """
    orig_tokens = re.findall(r"\S+\s*", original)
    pol_tokens = re.findall(r"\S+\s*", polished)
    sm = difflib.SequenceMatcher(a=orig_tokens, b=pol_tokens, autojunk=False)
    segments = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        segments.append({
            "op": op,
            "a": "".join(orig_tokens[i1:i2]),
            "b": "".join(pol_tokens[j1:j2]),
        })
    return segments
