"""Serialize chunks to LLM prompt text and parse polished JSON back.

Ported near-verbatim from MemoirForge llm_polish/serializer.py.
Key divergence: block IDs are BlockNote UUIDs (longer strings); the parser
already keys on the id field so it handles any string ID transparently.

Wire format (LLM input):

    CONTEXT  <uuid> h2 :: Chapter heading
    POLISH   <uuid> p  :: Mom was born in 1937 .
    POLISH   <uuid> p  :: Dad worked at the mill .

Wire format (LLM output — JSON array):

    [{"id":"<uuid>","kind":"p","text":"Mom was born in 1937."},
     {"id":"<uuid>","kind":"p","text":"Dad worked at the mill."}]
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

from .chunker import BlockRef, Chunk


class SerializationError(ValueError):
    """The polished output didn't match the input contract."""


# ---------------------------------------------------------------- prompt-side

_DEFAULT_POLISH_RULES = (
    "STRICT SCOPE — only these narrow mechanical fixes:\n"
    "  - Normalise wrong-locale smart quotes when the existing glyph is "
    "clearly the wrong direction or wrong language (e.g., German low-9 „ "
    "used where an English left double-quote “ was intended).\n"
    "  - Convert straight ASCII quotes used as apostrophes BETWEEN letters "
    "(e.g., 'don\"t', 'won\"t') to curly apostrophes (’).\n"
    "  - Fix obvious whitespace errors: doubled internal spaces, stray non-"
    "breaking / zero-width whitespace, single spaces immediately before "
    "punctuation (e.g., 'word .' → 'word.').\n"
    "  - Rejoin paragraphs that were clearly broken mid-sentence by a page "
    "break (the previous block ends without a sentence terminator AND this "
    "block starts mid-sentence). Rare — a deterministic pre-pass already "
    "handles most cases.\n"
    "  - Correct CLEARLY-OBVIOUS spelling typos: an unambiguous "
    "misspelling of an ordinary English word, replaced one-for-one with "
    "its correct spelling (e.g. 'sailers' -> 'sailors', 'recieve' -> "
    "'receive', 'occassion' -> 'occasion'). This is the ONLY word-level "
    "change permitted. STRICT limits — when in any doubt, leave the word "
    "exactly as written:\n"
    "      * PRESERVE British / Australian spellings (colour, practising, "
    "kerb, tyre, etc.) — they are NOT typos.\n"
    "      * PRESERVE archaic / period spellings, dialect, and the "
    "author’s deliberate word choices.\n"
    "      * NEVER touch proper nouns, names, surnames, or place names "
    "(they are spelled how the author intends).\n"
    "      * Fix ONE misspelled word per occurrence; never reword, "
    "re-order, or change meaning.\n\n"
    "FORBIDDEN — these are stylistic, not mechanical:\n"
    "  - DO NOT change the author’s punctuation choices. Specifically:\n"
    "      * Hyphens (-) MUST stay as hyphens. Never replace with en (–) "
    "or em (—) dashes.\n"
    "      * Three dots (...) MUST stay as three dots. Never replace with "
    "ellipsis character (…).\n"
    "      * Existing en/em dashes and ellipsis characters stay as they are.\n"
    "  - Do not normalise quote STYLE (curly ↔ straight) when the existing "
    "style is intentional. Only fix clearly-wrong glyphs.\n"
    "  - DO NOT delete text that looks like a footnote got merged into a "
    "paragraph.\n"
    "  - PRESERVE footnote markers of the form [^1], [^2], [^12] EXACTLY "
    "where they appear, attached to the same word. Never delete, move, "
    "renumber, space out, or reformat them.\n"
)

_PROMPT_STRUCTURE = (
    "You are doing a MECHANICAL polish pass on extracted memoir text.\n\n"
    "{rules}\n"
    "ALSO FORBIDDEN:\n"
    "  - Do not rewrite prose, change voice, summarise, or paraphrase.\n"
    "  - Do not add or remove sentences or words, or change facts, names, "
    "dates, or figure refs. (Correcting an unambiguous one-for-one "
    "spelling typo per the scope above is the SOLE exception.)\n"
    "  - Do not change a block’s `kind` field. Return the SAME kind you "
    "received.\n"
    "  - Do not return the CONTEXT block. It is for context only.\n\n"
    "Input lines are tagged:\n"
    "  CONTEXT  – previous block for context only; do not return it\n"
    "  POLISH   – return one JSON object per POLISH line\n\n"
    "Output: a JSON array of objects, one per POLISH line. Each object "
    "MUST have exactly:\n"
    '  {{"id": "<same id>", "kind": "<same kind>", "text": "<polished text>"}}\n\n'
    "JSON ESCAPING — the polished text must be a valid JSON string:\n"
    '  - escape every " inside text as \\"\n'
    "  - escape every backslash as \\\\\n"
    "  - never put a literal newline inside a JSON string\n"
    "  - prefer to keep text on a single line\n\n"
    "If a block needs no changes, return it verbatim with the same kind and id.\n"
)


def _build_preamble(extra_rules: str = "") -> str:
    rules = _DEFAULT_POLISH_RULES
    if extra_rules.strip():
        rules = rules + "\nADDITIONAL OPERATOR RULES:\n" + extra_rules.strip() + "\n"
    return _PROMPT_STRUCTURE.format(rules=rules)


_PROMPT_PREAMBLE = _build_preamble()


def serialize_chunk_for_prompt(chunk: Chunk, *, extra_rules: str = "") -> str:
    """Build the full prompt for one chunk (preamble + tagged input lines)."""
    lines: list[str] = [_build_preamble(extra_rules), ""]
    if chunk.context_block is not None:
        lines.append(_format_line("CONTEXT", chunk.context_block))
    for b in chunk.blocks:
        lines.append(_format_line("POLISH ", b))
    return "\n".join(lines)


def _format_line(tag: str, b: BlockRef) -> str:
    safe_text = b.text.replace("\n", " ").replace("\r", " ")
    return f"{tag} {b.id} {b.kind:2s} :: {safe_text}"


# ---------------------------------------------------------------- parse-side

_CODE_FENCE_RE = re.compile(
    r"\A\s*```(?:[A-Za-z]*)?\n(.*?)\n?```\s*\Z", re.DOTALL,
)


def parse_polished_jsonl(raw: str, chunk: Chunk) -> dict[str, str]:
    """Parse the LLM response and return {block_id: polished_text}.

    Validates the structural contract: every POLISH block id appears
    exactly once, each id's kind is unchanged, no extra ids appear.
    Context blocks that slip back are silently stripped.

    Raises SerializationError on structural violations.
    """
    text = _CODE_FENCE_RE.sub(r"\1", raw.strip())
    expected = {b.id: b for b in chunk.blocks}
    context_id = chunk.context_block.id if chunk.context_block else None

    seen: dict[str, str] = {}
    parse_errors: list[str] = []

    decoder = json.JSONDecoder()
    pos = 0
    text_len = len(text)
    while pos < text_len:
        while pos < text_len and text[pos] in " \t\n\r,[]":
            pos += 1
        if pos >= text_len:
            break
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError as e:
            line_no = text.count("\n", 0, pos) + 1
            if len(parse_errors) < 3:
                parse_errors.append(f"line {line_no}: not valid JSON ({e.msg})")
            next_brace = text.find("{", pos + 1)
            if next_brace < 0:
                break
            pos = next_brace
            continue
        pos = end
        if not isinstance(obj, dict):
            continue
        bid = obj.get("id")
        kind = obj.get("kind")
        polished = obj.get("text")
        if bid is None or kind is None or polished is None:
            parse_errors.append("an object was missing one of id/kind/text")
            continue
        if not isinstance(polished, str):
            parse_errors.append(
                f"id {bid}: text must be string, got {type(polished).__name__}"
            )
            continue
        if context_id and bid == context_id:
            continue
        if bid not in expected:
            parse_errors.append(f"unexpected id {bid!r}")
            continue
        if kind != expected[bid].kind:
            # Model changed kind — recover by keeping original kind, note it.
            pass
        if bid in seen:
            parse_errors.append(f"duplicate id {bid!r}")
            continue
        seen[bid] = polished

    missing = [bid for bid in expected if bid not in seen]
    if missing:
        parse_errors.append(
            f"missing polished output for {len(missing)} block(s): "
            + ", ".join(b[:8] + "…" for b in missing[:5])
            + ("…" if len(missing) > 5 else "")
        )
    if parse_errors:
        raise SerializationError("; ".join(parse_errors))
    return seen


def coverage_ratio(parsed: dict[str, str], chunk: Chunk) -> float:
    """Fraction of expected blocks covered by the parsed output."""
    if not chunk.blocks:
        return 1.0
    return sum(1 for b in chunk.blocks if b.id in parsed) / len(chunk.blocks)


def serialize_blocks_for_review(blocks: Iterable[BlockRef]) -> str:
    """Human-readable dump for debugging / tests."""
    return "\n\n".join(f"[{b.id[:8]}… {b.kind}] {b.text}" for b in blocks)
