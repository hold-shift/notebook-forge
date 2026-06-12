"""Second-pass clean over the canonical Document body.

Runs after extract + clean and BEFORE assembly so both HTML and MD see the
same polished text. Targets the recurring artefacts in Word-sourced memoirs:

  - Mid-sentence paragraph breaks (Word page breaks and soft returns that
    pandoc promoted to paragraph breaks): when a paragraph ends without a
    sentence terminator, fold it into the next paragraph.
  - Locale-wrong quote characters: docs authored with a German autocorrect
    setting come through with low-9 opening quotes (`„word"`) and use the
    closing curly double quote as an apostrophe (`Junior"s`, `won"t`).
    Normalise to English curly quotes.

Cleanup is conservative — it never deletes content and never crosses image
refs or headings.
"""

from __future__ import annotations

import re

# ---------- Smart-quote normalisation -----------------------------------

# Misplaced opening quotes → their English equivalents.
_OPEN_QUOTE_MAP = {
    "„": "“",   # „ DOUBLE LOW-9       → " LEFT DOUBLE QUOTATION MARK
    "‚": "‘",   # ‚ SINGLE LOW-9       → ' LEFT SINGLE QUOTATION MARK
    "‟": "”",   # ‟ DOUBLE HIGH-REVERSED-9 → " RIGHT DOUBLE QUOTATION MARK
    "‘‘": "“",  # `` → "
}

# Closing curly double quote between letters is an apostrophe gone wrong.
# Word's German locale autocorrect typesets apostrophes as U+201D.
_APOSTROPHE_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z])”(?=[A-Za-z])")
# Same for the straight ASCII double quote pasted as an apostrophe.
_ASCII_DQUOTE_BETWEEN_LETTERS = re.compile(r'(?<=[A-Za-z])"(?=[A-Za-z])')


def fix_smart_quotes(text: str) -> str:
    """Normalise locale-wrong curly quotes and broken apostrophes."""
    if not text:
        return text
    for bad, good in _OPEN_QUOTE_MAP.items():
        text = text.replace(bad, good)
    text = _APOSTROPHE_BETWEEN_LETTERS.sub("’", text)
    text = _ASCII_DQUOTE_BETWEEN_LETTERS.sub("’", text)
    return text


# ---------- Paragraph rejoining -----------------------------------------

# Characters at the end of a paragraph that mean "this paragraph really did
# end here" — don't merge with the next.
_SENTENCE_TERMINATORS = set(".?!…:")
_CLOSING_PUNCT = set("\"'’”)]}")


def _is_broken_break(cur: str, nxt: str) -> bool:
    # NotebookForge divergence: Markdown emphasis markers from the
    # style-preserving PDF extractor are transparent to the sentence-end
    # test — "…is best.*" really did end its sentence.
    cur_end = cur.rstrip().rstrip("*").rstrip()
    nxt_start = nxt.lstrip().lstrip("*").lstrip()
    if not cur_end or not nxt_start:
        return False
    last = cur_end[-1]
    if last in _SENTENCE_TERMINATORS or last in _CLOSING_PUNCT:
        return False
    # `; — – ,` and bare letters all count as broken. Be lenient.
    return True


def rejoin_paragraphs(body: list[dict]) -> list[dict]:
    """Fold consecutive paragraphs into one when the first didn't end a
    sentence. Skips merging across image refs and headings, which keeps
    figure-positions and section structure intact."""
    out: list[dict] = []
    i = 0
    while i < len(body):
        entry = body[i]
        if entry.get("kind") == "p":
            text = entry["text"]
            j = i + 1
            while j < len(body) and body[j].get("kind") == "p" and _is_broken_break(text, body[j]["text"]):
                text = text.rstrip() + " " + body[j]["text"].lstrip()
                j += 1
            merged = {"kind": "p", "text": text}
            out.append(merged)
            i = j
        else:
            out.append(entry)
            i += 1
    return out


# ---------- Apply --------------------------------------------------------

def polish_body(body: list[dict]) -> list[dict]:
    """Apply the second-pass clean steps in order: quotes, then rejoin."""
    polished: list[dict] = []
    for entry in body:
        if "image_ref" in entry:
            polished.append(entry)
        else:
            polished.append({
                **entry,
                "text": fix_smart_quotes(entry.get("text", "")),
            })
    return rejoin_paragraphs(polished)
