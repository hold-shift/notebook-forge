"""Prompt assembly and JSON parsing for the report pass.

The three prompt constants (SYSTEM_RULES, CHAPTER_INSTRUCTION,
CONSOLIDATE_INSTRUCTION) are ported verbatim from the validated standalone
`notebook_forge_reports.py` — they ARE the locked behavioural spec (single-
source isolation, [INFERENCE] tagging, exact-spelling preservation,
surface-don't-resolve). Only the transport differs in-app (Gemini, not the
Anthropic client).

Operator `rules` (the Setting-stored extra guidance, mirroring polish
`extra_rules`) are appended to the system prompt.
"""
from __future__ import annotations

import json
import re
from typing import Any

# --------------------------------------------------------------------------- #
# Shared fidelity rules (ported verbatim from notebook_forge_reports.py)
# --------------------------------------------------------------------------- #

SYSTEM_RULES = """You are a meticulous family historian and military archivist building a \
navigational index of a single memoir. Your register is that of a careful biographer, \
but register governs tone ONLY — never facts.

PRIME DIRECTIVE — SINGLE-SOURCE ISOLATION. Work strictly from the chapter text you are \
given. Never import facts from other documents, other chapters, outside/world knowledge, \
or your own assumptions. If the text does not state or clearly imply something, do not add it.

CONVENTIONS:
- Tag every interpretive statement (anything not stated or directly evidenced in the text) \
with a leading [INFERENCE], and anchor it to where in the text it is grounded.
- Preserve the author's exact spellings, including variant spellings of the same name or \
place. Do not silently normalise them; surface variants as inconsistencies instead.
- Do not resolve contradictions — surface them.
- Be faithful and specific. Do not embellish, dramatise, or invent detail, names, or dates.
- Scale your output to how much the chapter actually contains; do not pad."""

# --------------------------------------------------------------------------- #
# Per-chapter instruction (strict JSON contract) — verbatim
# --------------------------------------------------------------------------- #

CHAPTER_INSTRUCTION = """Below is ONE chapter of the memoir "{source_name}", titled \
"{chapter_title}". Produce a structured digest of THIS chapter only.

Return ONLY a single valid JSON object (no markdown fences, no commentary) with these keys:

{{
  "digest_md": "Markdown for the section-by-section digest of THIS chapter. For each of the \
chapter's own section headings (use the headings exactly as they appear in the text; if the \
chapter has no sub-headings, use the chapter title once), emit:\\n\\n**<section heading>**\\n\
<a 2-5 sentence faithful digest of that section>\\n*People:* <comma-separated names that \
appear in the section, or omit this line if none>\\n*Inferences:* [INFERENCE] <reading, or \
omit this line if none>\\n\\nSeparate sections with a blank line.",
  "people": [{{"section": "...", "name": "...", "role": "exact role/relationship as stated"}}],
  "geo": [{{"section": "...", "place": "...", "what": "what occurred there", \
"arrival": "how/when arrived or moved, or '-'"}}],
  "glossary": [{{"section": "...", "term": "...", \
"meaning": "concise meaning as used in the text"}}],
  "chronology": [{{"section": "...", "marker": "date or time marker as given", \
"event": "what happened"}}],
  "interpersonal_stated": ["short factual statements about relationships/dynamics \
explicitly in the text"],
  "interpersonal_inference": ["[INFERENCE] <reading> (Anchored to <section>.)"],
  "inconsistencies": ["internal contradictions, spelling variants, \
or open questions in THIS chapter"],
  "anchors": [{{"section": "...", "quote": "a short verbatim quote of <=25 words", \
"attribution": "who/what context"}}]
}}

Rules for the rows:
- Every array may be empty. Include a person/place/term/date only if it genuinely appears.
- Quotes in "anchors" must be verbatim and <=25 words. Offer your best 1-4 candidates; final \
selection happens later.
- Keep "role", "meaning", "event" etc. faithful and concise. Use the author's spellings.

CHAPTER TEXT:
---
{chapter_text}
---"""

# --------------------------------------------------------------------------- #
# Consolidation instruction — verbatim
# --------------------------------------------------------------------------- #

CONSOLIDATE_INSTRUCTION = """You are finalising the whole-document layer of the report for the \
memoir "{source_name}" (period {years}). Below are the per-chapter digests in order, then all \
candidate verbatim anchors gathered from every chapter.

Return ONLY a single valid JSON object (no fences, no commentary):

{{
  "executive_summary": "<=150 words: a faithful overview of the whole memoir's arc \
and scope, in the biographer register. No new facts beyond what the digests contain.",
  "anchors": [{{"section": "...", "quote": "<=25 words verbatim", "attribution": "..."}}],
  "interpersonal_stated": ["the most significant stated relationship dynamics, grouped by \
relationship and proportional to the document — NOT an exhaustive restatement of every line"],
  "interpersonal_inference": ["[INFERENCE] <the most significant readings only> \
(Anchored to <section>.)"],
  "inconsistencies": ["genuine open questions and contradictions, one per line; collapse \
routine spelling/typo variants into a SINGLE grouped line, e.g. 'Spelling variants: \
Withall/Withell, Jesse/Jessie, Alec/Alex, Griffin/Griffen'"]
}}

For "anchors": SELECT the 5-8 strongest from the candidates below (vivid, characteristic, or \
pivotal). Do not invent or alter quotes; copy a candidate verbatim. Keep variety across \
the document.

For "interpersonal_stated", "interpersonal_inference", "inconsistencies": SYNTHESISE the raw \
per-chapter material below — do NOT copy it wholesale. Be proportional to the document, not \
exhaustive. Preserve the author's exact spellings inside the grouped variant line. Add no new \
facts beyond the supplied material, and keep every [INFERENCE] tag.

PER-CHAPTER DIGESTS:
---
{digests}
---

ANCHOR CANDIDATES (JSON):
{anchor_candidates}

RAW PER-CHAPTER MATERIAL TO SYNTHESISE (do not copy wholesale):
Stated relationship dynamics:
{raw_stated}

Interpersonal inferences:
{raw_inference}

Inconsistencies / open questions:
{raw_inconsistencies}"""

# The chapter-object keys that must default to a list when absent.
_LIST_KEYS = (
    "people", "geo", "glossary", "chronology",
    "interpersonal_stated", "interpersonal_inference",
    "inconsistencies", "anchors",
)


class ReportParseError(ValueError):
    """The model reply could not be parsed into the chapter/consolidate contract."""


def build_system_rules(extra_rules: str = "") -> str:
    """SYSTEM_RULES plus any operator-appended guidance."""
    if extra_rules.strip():
        return SYSTEM_RULES + "\n\nADDITIONAL OPERATOR RULES:\n" + extra_rules.strip()
    return SYSTEM_RULES


def build_chapter_prompt(source_name: str, chapter_title: str, chapter_text: str) -> str:
    """The user-message body for one chapter's structured digest call."""
    return CHAPTER_INSTRUCTION.format(
        source_name=source_name, chapter_title=chapter_title, chapter_text=chapter_text
    )


def _bullet_block(items: list[str]) -> str:
    """Render a raw pooled list as bullets for the synthesis prompt."""
    return "\n".join(f"- {it}" for it in items) if items else "(none)"


def build_consolidate_prompt(
    source_name: str,
    years: str,
    digests: str,
    anchor_candidates: list[dict[str, Any]],
    raw_stated: list[str],
    raw_inference: list[str],
    raw_inconsistencies: list[str],
) -> str:
    """The user-message body for the single whole-document consolidation call.

    The raw pooled §3/§4 material is included for the model to SYNTHESISE
    (curate + group), not transcribe.
    """
    return CONSOLIDATE_INSTRUCTION.format(
        source_name=source_name,
        years=years,
        digests=digests,
        anchor_candidates=json.dumps(anchor_candidates, ensure_ascii=False),
        raw_stated=_bullet_block(raw_stated),
        raw_inference=_bullet_block(raw_inference),
        raw_inconsistencies=_bullet_block(raw_inconsistencies),
    )


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model reply, tolerating stray fences/prose.

    Ported from the standalone `extract_json`: strips a leading/trailing code
    fence, then falls back to the outermost {...} span.
    """
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(t[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ReportParseError(f"reply is not valid JSON: {exc.msg}") from exc
        else:
            raise ReportParseError("reply contained no JSON object") from None
    if not isinstance(obj, dict):
        raise ReportParseError(f"reply JSON was {type(obj).__name__}, expected object")
    return obj


def parse_chapter_json(raw: str) -> dict[str, Any]:
    """Parse one chapter reply into the contract, filling defensive defaults.

    Raises ReportParseError on unparseable JSON or when `digest_md` is missing
    or empty (a chapter with no digest is treated as a failed extraction so the
    runner retries).
    """
    data = extract_json(raw)
    for key in _LIST_KEYS:
        value = data.get(key)
        data[key] = value if isinstance(value, list) else []
    digest = data.get("digest_md")
    if not isinstance(digest, str) or not digest.strip():
        raise ReportParseError("reply had no 'digest_md'")
    data["digest_md"] = digest
    return data


def _str_list(value: Any) -> list[str]:
    """Coerce a parsed field to a list of non-empty strings (or [] if absent)."""
    if not isinstance(value, list):
        return []
    return [s.strip() for s in value if isinstance(s, str) and s.strip()]


def parse_consolidate_json(
    raw: str,
    fallback_anchors: list[dict[str, Any]],
    fallback_stated: list[str],
    fallback_inference: list[str],
    fallback_inconsistencies: list[str],
) -> dict[str, Any]:
    """Parse the consolidation reply (executive summary, anchors, and the
    curated §3/§4 lists).

    Each field falls back to the supplied raw material when the model omits it
    or returns it empty — so we degrade to the pre-curation behaviour rather
    than losing data (mirrors the existing anchor fallback).
    """
    data = extract_json(raw)
    summary = data.get("executive_summary")
    anchors = data.get("anchors")
    stated = _str_list(data.get("interpersonal_stated"))
    inference = _str_list(data.get("interpersonal_inference"))
    inconsistencies = _str_list(data.get("inconsistencies"))
    return {
        "executive_summary": summary.strip() if isinstance(summary, str) else "",
        "anchors": anchors if isinstance(anchors, list) and anchors else fallback_anchors[:8],
        "interpersonal_stated": stated or fallback_stated,
        "interpersonal_inference": inference or fallback_inference,
        "inconsistencies": inconsistencies or fallback_inconsistencies,
    }
