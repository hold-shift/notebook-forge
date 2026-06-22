"""TTS narration: turn a document's block tree into a per-block payload manifest.

NotebookForge produces NO audio. This module is the "smart" half of the TTS
split (see docs/TTS_Spec_0_Overview.md): it walks the block tree, decides how
each block should be spoken, emits an ElevenLabs-dialect payload per block, and
hashes each block so the generator (forge-narrator, on the Mac) can cache by hash
and so the panel can show an in-sync / stale dot. The generator stays dumb — it
just runs the payload it's given through ElevenLabs `/with-timestamps`.

Provider note (switched from Amazon Polly after A/B testing): ElevenLabs does NOT
honour `<prosody>`, and `<break>` support is light/model-dependent. So the payload
is essentially CLEAN TEXT plus an optional light `<break time="0.3s"/>` for
pacing — NOT a `<speak>`/`<prosody>` SSML document. Prosody/emphasis come from the
voice + model (`eleven_v3`), not from tags. The exact dialect is verified in the
forge-narrator build (`forge-narrator/docs/SSML_FINDINGS.md`); this module mirrors
it via the single `payload_mode` flag. The manifest field is still named `ssml`
for contract stability, but it holds the ElevenLabs-dialect string.

Reconciliation note: the spec text refers to headings coming from `forgeNarrative`
blocks "with a heading level". In this codebase headings are plain `heading` blocks
(props.level 2/3) and `forgeNarrative` is the author's reflective-voice paragraph
(props {}, see narrative.py). We narrate accordingly: `heading` → heading payload,
`forgeNarrative` → paragraph payload (it is spoken prose).

The inter-block `<break>` is NO LONGER load-bearing for word→block mapping: the
generator synthesises each block independently and shifts word times by the block's
stitch offset, so words map to blocks by construction. The break is kept only for
natural pacing / to avoid seam clipping.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .blocks import (
    FORGE_DEDICATION,
    FORGE_DOC_GROUP,
    FORGE_FOOTNOTE,
    FORGE_IMAGE,
    FORGE_NARRATIVE,
    inline_text,
)

# ElevenLabs voice_id (LOCKED — chosen by audition) + model.
DEFAULT_VOICE = "fjnwTZkKtQOJaYzGLa6n"
DEFAULT_MODEL = "eleven_v3"

# Light pacing breaks (ElevenLabs honours these on eleven_v3; seconds form).
HEADING_BREAK = '<break time="0.4s"/>'
PARAGRAPH_BREAK = '<break time="0.3s"/>'
FOOTNOTE_BREAK = '<break time="0.3s"/>'

# Block-type → narration treatment. Anything not listed is stripped.
_PARAGRAPH_TYPES = {
    "paragraph",
    FORGE_NARRATIVE,  # author's reflective voice — still spoken prose
    "quote",
    "bulletListItem",
    "numberedListItem",
}
_STRIP_TYPES = {FORGE_IMAGE, FORGE_DOC_GROUP, "divider", "table"}


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
    payload_mode: str = "breaks",
) -> str:
    """Build one block's ElevenLabs-dialect payload.

    ``block_type`` is the narration type ("heading" | "paragraph" | "footnote").
    The single ``payload_mode`` flag mirrors the verified dialect from
    ``SSML_FINDINGS.md``:
      - ``"breaks"`` (default): clean text + a light trailing ``<break>``.
      - ``"plain"``: clean text only (the generator inserts seam silence).
    No ``<speak>`` wrapper and no ``<prosody>`` — ElevenLabs ignores both.
    Returned text is natural UTF-8 (not XML-escaped); the only markup is the
    optional break tag we append.
    """
    inner = apply_lexicon(text, lexicon)
    if block_type == "footnote":
        # Spoken cue works regardless of dialect; plain text leads it.
        inner = f"Footnote. {inner}"
    if payload_mode == "plain":
        return inner
    if block_type == "heading":
        return f"{inner}{HEADING_BREAK}"
    if block_type == "footnote":
        return f"{inner}{FOOTNOTE_BREAK}"
    return f"{inner}{PARAGRAPH_BREAK}"


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
    payload_mode: str = "breaks",
) -> list[dict[str, Any]]:
    """Walk a block tree in reading order and emit one export block per
    narratable unit.

    Each export block is ``{index, type, text, ssml, hash, highlightable}``.
    Footnotes are emitted in place (they already sit in reading order in the
    tree, immediately after the prose that references them) as their own
    ``footnote`` block, ``highlightable: False``. A dedication is spoken once,
    up front. Images, doc-groups, dividers and tables are stripped; empty text
    blocks are skipped (matching the renderer/plain_text walker)."""

    def emit(narr_type: str, text: str) -> dict[str, Any]:
        ssml = build_ssml(narr_type, text, lexicon=lexicon, payload_mode=payload_mode)
        return {
            "type": narr_type,
            "text": text,
            "ssml": ssml,
            "hash": block_hash(ssml, voice, model),
            "highlightable": narr_type != "footnote",
        }

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
            text = inline_text(block.get("content")).strip()
            if text:
                body.append(emit("heading", text))
            continue
        if btype in _PARAGRAPH_TYPES:
            text = inline_text(block.get("content")).strip()
            if text:
                body.append(emit("paragraph", text))
            continue
        # Unknown block type: strip (stay conservative — narrate nothing we
        # don't understand rather than risk garbled audio).

    ordered = ([dedication] if dedication else []) + body
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
    payload_mode: str = "breaks",
) -> list[str]:
    """The current block-hash list for a document (extraction without writing
    the zip) — cheap enough to run on every panel load."""
    return [
        b["hash"]
        for b in extract_blocks(
            blocks, voice=voice, model=model, lexicon=lexicon, payload_mode=payload_mode
        )
    ]


def sync_status(audio_base_url: str, exported: list[str], live: list[str]) -> str:
    """'no_audio' (grey) | 'in_sync' (green) | 'stale' (amber).

    Compared as sets so block re-ordering with identical content stays in sync
    (the generator caches by hash, order-independent)."""
    if not (audio_base_url or "").strip():
        return "no_audio"
    return "in_sync" if set(exported or []) == set(live or []) else "stale"
