"""TTS narration: turn a document's block tree into a per-block payload manifest.

NotebookForge produces NO audio. This module is the "smart" half of the TTS
split (see docs/TTS_Spec_0_Overview.md): it walks the block tree, decides how
each block should be spoken, emits an ElevenLabs-dialect payload per block, and
hashes each block so the generator (forge-narrator, on the Mac) can cache by hash
and so the panel can show an in-sync / stale dot. The generator stays dumb — it
just runs the payload it's given through ElevenLabs `/with-timestamps`.

Payload dialect = PLAIN TEXT (LOCKED for eleven_v3 — see docs/SSML_FINDINGS.md).
Provider switched from Amazon Polly to ElevenLabs. Production-confirmed: eleven_v3
does NOT strip unknown SSML — any `<break>` / `<speak>` / `<prosody>` leaks verbatim
into the `/with-timestamps` character alignment (and risks being read aloud),
producing garbage word marks like `Junior.<break` / `time="0.5s"/>`. So a block's
payload is the plain spoken text ONLY: no tags, no self-closing elements, no XML
entities — just words and ordinary sentence punctuation. Prosody/pacing come from
the voice + model and from sentence punctuation; ElevenLabs pauses naturally at
periods, and the generator synthesises each block separately and stitches the seams,
so the inter-block break is not load-bearing. The manifest field is still named
`ssml` for contract stability, but it holds plain text.

Reconciliation note: the spec text refers to headings coming from `forgeNarrative`
blocks "with a heading level". In this codebase headings are plain `heading` blocks
(props.level 2/3) and `forgeNarrative` is the author's reflective-voice paragraph
(props {}, see narrative.py). We narrate accordingly: `heading` → heading payload,
`forgeNarrative` → paragraph payload (it is spoken prose).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .blocks import (
    FORGE_DEDICATION,
    FORGE_DOC_GROUP,
    FORGE_FOOTNOTE,
    FORGE_IMAGE,
    FORGE_NARRATIVE,
)

# ElevenLabs voice_id (LOCKED — chosen by audition) + model.
DEFAULT_VOICE = "fjnwTZkKtQOJaYzGLa6n"
DEFAULT_MODEL = "eleven_v3"

# Block-type → narration treatment. Anything not listed is stripped.
_PARAGRAPH_TYPES = {
    "paragraph",
    FORGE_NARRATIVE,  # author's reflective voice — still spoken prose
    "quote",
    "bulletListItem",
    "numberedListItem",
}
_STRIP_TYPES = {FORGE_IMAGE, FORGE_DOC_GROUP, "divider", "table"}


def spoken_inline_text(content: list[dict[str, Any]] | str | None) -> str:
    """Flatten inline content to spoken text, like blocks.inline_text BUT
    skipping footnote-marker runs (``styles.fnRef``).

    The prose carries an inline superscript marker (e.g. "1") at each footnote
    reference; the footnote's actual text is a separate ``forgeFootnote`` block
    spoken as its own "Footnote. …" unit. So the marker digit must NOT be read
    aloud mid-sentence — strip it here. Links recurse."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        kind = item.get("type")
        if kind == "text":
            if (item.get("styles") or {}).get("fnRef"):
                continue  # footnote marker — not spoken inline
            parts.append(item.get("text", ""))
        elif kind == "link":
            parts.append(spoken_inline_text(item.get("content")))
    return "".join(parts)


def tts_enabled(session: Any) -> bool:
    """Workspace-level TTS master switch (Setting 'tts'). Default false."""
    from .models import Setting

    row = session.get(Setting, "tts")
    return bool((row.value or {}).get("enabled")) if row is not None else False


# ---- Payload construction (ElevenLabs dialect) -----------------------------


def apply_lexicon(text: str, lexicon: list[dict[str, Any]] | None) -> str:
    """Apply pronunciation fixes as plain-text substitution.

    Each entry is ``{phrase, replacement}`` — e.g. spell a place name phonetically.
    Longest phrases first so a longer phrase wins over a contained shorter one.
    Empty lexicon → text unchanged. (ElevenLabs takes natural text; the simplest
    v1 fix is substitution before send. Its own pronunciation dictionaries /
    ``<phoneme>`` are a possible future upgrade.)
    """
    entries = [
        (str(e.get("phrase", "")), str(e.get("replacement", "")))
        for e in (lexicon or [])
        if str(e.get("phrase", "")).strip()
    ]
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    for phrase, replacement in entries:
        text = text.replace(phrase, replacement)
    return text


def build_ssml(
    block_type: str,
    text: str,
    *,
    lexicon: list[dict[str, Any]] | None = None,
) -> str:
    """Build one block's payload: PLAIN spoken text, no markup (locked for
    eleven_v3 — see module docstring / docs/SSML_FINDINGS.md).

    ``block_type`` is the narration type ("heading" | "paragraph" | "footnote").
    Heading and paragraph are the text verbatim (after lexicon substitution);
    a footnote leads with the spoken cue "Footnote. ". No ``<break>`` /
    ``<speak>`` / ``<prosody>`` and no XML escaping — natural UTF-8 only."""
    inner = apply_lexicon(text, lexicon)
    if block_type == "footnote":
        return f"Footnote. {inner}"
    return inner


# Year range "1934–1945" (en/em-dash or hyphen) → "1934 to 1945" so it is read
# as a span, not a single mashed-together number.
_YEAR_RANGE = re.compile(r"(\d{4})\s*[-‒–—―]\s*(\d{4})")


def spoken_years(year_display: str) -> str:
    return _YEAR_RANGE.sub(r"\1 to \2", year_display)


def title_block(
    meta: dict[str, Any],
    *,
    lexicon: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build the spoken masthead preamble from document meta, e.g.
    "Junior. The boy I once knew but now remember. 1934 to 1945. By R.F Skitch."
    The masthead lives in meta (title / standfirst / year_display / author), not
    the block tree, so it would otherwise never be announced. Plain text — the
    sentence periods give the natural pauses between lines (no markup). Returns a
    heading-type block, or None when there is no title."""
    title = str((meta or {}).get("title", "")).strip()
    if not title:
        return None
    subtitle = str(meta.get("standfirst", "")).strip()
    years = spoken_years(str(meta.get("year_display", "")).strip())
    author = str(meta.get("author", "")).strip()

    segments = [title]
    if subtitle:
        segments.append(subtitle)
    if years:
        segments.append(years)
    if author:
        segments.append(f"By {author}")
    segments = [apply_lexicon(s, lexicon) for s in segments]

    text = ". ".join(segments) + "."
    return {
        "type": "heading",
        "text": text,
        "ssml": text,
        "highlightable": True,
    }


def block_hash(ssml: str, voice: str, model: str) -> str:
    """sha256 over {ssml, voice, model} — the spine of the whole system.

    Travels in the manifest; the generator caches synthesised audio + marks by it;
    the panel compares hash sets for staleness. Changing voice/model changes every
    hash → full regen, correctly."""
    raw = ssml + voice + model
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---- Block extraction ------------------------------------------------------


def extract_blocks(
    blocks: list[dict[str, Any]],
    *,
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL,
    lexicon: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Walk a block tree in reading order and emit one export block per
    narratable unit.

    Each export block is ``{index, type, text, ssml, hash, highlightable}``.
    When ``meta`` is given, a spoken masthead preamble (title / subtitle / dates /
    author) is announced first (see ``title_block``) — the masthead lives in meta,
    not the block tree, so it is otherwise never narrated. Footnotes are emitted
    in place (they already sit in reading order in the tree, immediately after the
    prose that references them) as their own ``footnote`` block,
    ``highlightable: False``. A dedication is spoken once, up front. Images,
    doc-groups, dividers and tables are stripped; empty text blocks are skipped
    (matching the renderer/plain_text walker)."""

    def emit(narr_type: str, text: str) -> dict[str, Any]:
        ssml = build_ssml(narr_type, text, lexicon=lexicon)
        return {
            "type": narr_type,
            "text": text,
            "ssml": ssml,
            "hash": block_hash(ssml, voice, model),
            "highlightable": narr_type != "footnote",
        }

    preamble: dict[str, Any] | None = None
    if meta:
        title = title_block(meta, lexicon=lexicon)
        if title is not None:
            title["hash"] = block_hash(title["ssml"], voice, model)
            preamble = title

    dedication: dict[str, Any] | None = None
    body: list[dict[str, Any]] = []

    for block in blocks:
        btype = block.get("type")
        if btype in _STRIP_TYPES:
            continue
        if btype == FORGE_DEDICATION:
            if dedication is None:  # spoken once, up front
                text = str(block.get("props", {}).get("text", "")).strip()
                if text:
                    dedication = emit("paragraph", text)
            continue
        if btype == FORGE_FOOTNOTE:
            text = str(block.get("props", {}).get("text", "")).strip()
            if text:
                body.append(emit("footnote", text))
            continue
        if btype == "heading":
            text = spoken_inline_text(block.get("content")).strip()
            if text:
                body.append(emit("heading", text))
            continue
        if btype in _PARAGRAPH_TYPES:
            text = spoken_inline_text(block.get("content")).strip()
            if text:
                body.append(emit("paragraph", text))
            continue
        # Unknown block type: strip (stay conservative — narrate nothing we
        # don't understand rather than risk garbled audio).

    ordered = (
        ([preamble] if preamble else [])
        + ([dedication] if dedication else [])
        + body
    )
    for i, b in enumerate(ordered):
        b["index"] = i
    return ordered


def build_manifest(
    *,
    slug: str,
    title: str,
    voice: str,
    model: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the manifest.json payload the generator consumes."""
    return {
        "document_slug": slug,
        "title": title,
        "voice": voice,
        "model": model,
        "blocks": [
            {
                "index": b["index"],
                "type": b["type"],
                "hash": b["hash"],
                "ssml": b["ssml"],
                "highlightable": b["highlightable"],
            }
            for b in blocks
        ],
    }


def live_hashes(
    blocks: list[dict[str, Any]],
    *,
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL,
    lexicon: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> list[str]:
    """The current block-hash list for a document (extraction without writing
    the zip) — cheap enough to run on every panel load."""
    return [
        b["hash"]
        for b in extract_blocks(
            blocks, voice=voice, model=model, lexicon=lexicon, meta=meta,
        )
    ]


def sync_status(audio_base_url: str, exported: list[str], live: list[str]) -> str:
    """'no_audio' (grey) | 'in_sync' (green) | 'stale' (amber).

    Compared as sets so block re-ordering with identical content stays in sync
    (the generator caches by hash, order-independent)."""
    if not (audio_base_url or "").strip():
        return "no_audio"
    return "in_sync" if set(exported or []) == set(live or []) else "stale"
