"""Canonical footnote model + inline-marker handling.

A footnote is `{"n": ref_number, "text": note_text, ...}` in
`DocumentDraft.footnotes`. Its *body position* is represented by an
inline marker `[^N]` embedded in the referencing paragraph's text —
markers travel with the text through LLM polish, manual edits, and
HTML→MD sync, so the position never goes stale the way a stored index
would.

Both source extractors normalise to this single model:
  - DOCX: pandoc emits `[^N]` refs + `[^N]:` definitions (it reads
    word/footnotes.xml internally); we lift the definitions into
    `draft.footnotes` and keep the refs in the body.
  - PDF: geometry/font detection finds the numbered lines at the page
    bottom; a binding pass converts the adjacent superscript digits in
    the body (PyMuPDF flattens `word^N` to `wordN`) into `[^N]`.

Output (assemble.py) renders each note as an INLINE, co-located block
right after the paragraph that first references it — never collected at
the end — so the tie survives the Markdown → Google Doc → NotebookLM
path without depending on anchor links.
"""

from __future__ import annotations

import re

# Canonical inline marker in draft.body text: `[^N]`. Unambiguous (a bare
# digit collides with years and counts), survives the chunked LLM polish,
# and is exactly what pandoc emits for DOCX so that path needs no
# conversion. Rendered to `<sup class="fn-ref">N</sup>` / `[N]` at output.
MARKER_RE = re.compile(r"\[\^(\d+)\]")

# A pandoc GFM footnote DEFINITION line: `[^N]: note text`. With
# `--wrap=none` each definition is a single paragraph.
DEFINITION_RE = re.compile(r"^\[\^(\d+)\]:\s*(.*)$", re.DOTALL)

# The legacy PDF reference form — a footnote digit flattened against the
# preceding word, e.g. `Vietnam1`. Used only by the PDF binding pass to
# convert these into canonical `[^N]` markers at extraction time.
#   (?<![\d])  not preceded by a digit
#   ([A-Za-z]) a letter (so `Vietnam1` matches, `in 1966` does not)
#   (\d{1,2})  the 1–2 digit footnote number
#   (?!\d)     not followed by another digit
LEGACY_DIGIT_RE = re.compile(r"(?<![\d])([A-Za-z])(\d{1,2})(?!\d)")


def referenced_numbers(text: str) -> list[int]:
    """Footnote numbers referenced in a paragraph, in first-seen order,
    de-duplicated. Drives co-located note placement (note goes after the
    FIRST reference; repeats just show the marker)."""
    seen: list[int] = []
    for m in MARKER_RE.finditer(text or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def bind_legacy_digit_refs(text: str, known: set[int]) -> str:
    """Convert legacy adjacent-digit refs (`Vietnam1`) into canonical
    `[^N]` markers, but only for numbers that actually have a footnote
    (so `in 1966` and incidental digits are left alone). Idempotent —
    `[^1]` won't re-match LEGACY_DIGIT_RE."""
    if not text or not known:
        return text

    def repl(m: re.Match) -> str:
        n = int(m.group(2))
        if n in known:
            return f"{m.group(1)}[^{n}]"
        return m.group(0)

    return LEGACY_DIGIT_RE.sub(repl, text)
