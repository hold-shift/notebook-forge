"""Generate (or regenerate) the sketch for one forgeImage block.

On success the sketch bytes land in the content-addressed store (kind
"sketches"), the block gets sketchAssetId + approval reset to "pending"
(a fresh generation always needs a human look), and the change log records
the generation with the gate verdict.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from . import services
from .assets import asset_path, ingest_file
from .blocks import FORGE_IMAGE
from .models import Asset, Document, Setting
from .sketch import SILHOUETTE_PROMPT, SKETCH_MODEL, SketchGenerator
from .sketch_gen import GeminiSketchGenerator, make_generator

CAPTION_MODEL = "gemini-2.5-flash"
CAPTION_PROMPT = (
    "Write a brief, descriptive caption for this photograph as it would appear "
    "in a memoir or personal history book. Identify the main subjects, people, "
    "or scene clearly visible. 5 to 20 words. No period at the end. "
    "Output the caption text only, nothing else."
)


def eligible_figure_block_ids(blocks: list[dict]) -> list[str]:
    """Block IDs eligible for batch sketch generation.

    A figure is eligible if it has an original photo, its safe-edition mode
    still calls for a sketch, AND its sketch has not yet been approved. Figures
    set to Safe: original / Safe: omit never embed a sketch, so they're skipped
    (and approved sketches are skipped to avoid clobbering them).
    """
    out = []
    for b in blocks:
        if b.get("type") != "forgeImage":
            continue
        props = b.get("props", {})
        if not props.get("assetId"):
            continue
        if props.get("safeMode", "sketch") in ("original", "omit"):
            continue
        if props.get("sketchAssetId") and props.get("approval") == "approved":
            continue
        out.append(b["id"])
    return out


def sketch_settings(session: Session) -> dict:
    """Operator-controlled generation settings, with the production values
    as defaults (Settings screen edits these; stored in the settings table)."""
    row = session.get(Setting, "sketch")
    value = dict(row.value) if row else {}
    return {
        "model": value.get("model") or SKETCH_MODEL,
        "default_prompt": value.get("default_prompt") or SILHOUETTE_PROMPT,
        "face_gate": value.get("face_gate") or "block",
    }


def generate_sketch_for_block(
    session: Session,
    workspace: Path,
    doc: Document,
    block_id: str,
    prompt: str | None = None,
    force: bool = False,
    generator: SketchGenerator | None = None,
) -> dict[str, Any]:
    blocks = [dict(b) for b in doc.blocks]
    block = next(
        (b for b in blocks if b.get("id") == block_id and b.get("type") == FORGE_IMAGE), None
    )
    if block is None:
        raise LookupError(f"no forgeImage block '{block_id}' in {doc.slug}")

    original = session.get(Asset, block.get("props", {}).get("assetId", ""))
    if original is None:
        raise LookupError("figure has no original asset to sketch from")
    original_path = asset_path(workspace, original)

    cfg = sketch_settings(session)
    generator = generator or make_generator(
        workspace / "sketch-cache", model=cfg["model"], face_gate=cfg["face_gate"]
    )
    result = generator.generate(
        original_path.read_bytes(), original.mime or "image/jpeg",
        prompt or cfg["default_prompt"],
        force=force,
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(result.image_bytes)
        tmp_path = Path(tmp.name)
    try:
        sketch_asset = ingest_file(session, workspace, tmp_path, "sketches")
        sketch_asset.filename = f"{doc.slug}-{block_id[:8]}-sketch.png"
    finally:
        tmp_path.unlink(missing_ok=True)

    gate = getattr(generator, "last_gate", None)
    props = dict(block.get("props", {}))
    props["sketchAssetId"] = sketch_asset.sha256
    props["approval"] = "pending"  # fresh generations always need review
    props["faceGate"] = gate.status if gate else "n/a"
    block["props"] = props
    blocks[blocks.index(next(b for b in blocks if b.get("id") == block_id))] = block

    services.save_blocks(
        session, doc, blocks,
        summary=f"generated sketch for figure block {block_id[:8]}",
    )
    services.record_change(
        session, doc, "edit", "sketch generated",
        detail={
            "block_id": block_id,
            "sketch_asset": sketch_asset.sha256,
            "model": result.model,
            "prompt_overridden": prompt is not None,
            "face_gate": gate.status if gate else "n/a",
            "gate_attempts": gate.attempts if gate else 0,
            "cached": isinstance(generator, GeminiSketchGenerator) and gate is not None
            and gate.attempts == 0,
        },
    )
    return {
        "sketchAssetId": sketch_asset.sha256,
        "face_gate": gate.status if gate else "n/a",
        "model": result.model,
    }


def upload_sketch_for_block(
    session: Session,
    workspace: Path,
    doc: Document,
    block_id: str,
    src_path: Path,
) -> dict[str, Any]:
    """Attach an operator-supplied sketch to a figure — the escape hatch when
    the image model refuses (e.g. blockReason=OTHER). Stores the file in the
    sketches bucket, points the block at it, resets approval to pending, and
    clears any stale face-gate flag (a hand-supplied sketch isn't gated)."""
    blocks = list(doc.blocks)
    idx = next(
        (i for i, b in enumerate(blocks)
         if b.get("id") == block_id and b.get("type") == FORGE_IMAGE),
        None,
    )
    if idx is None:
        raise LookupError(f"no forgeImage block '{block_id}' in {doc.slug}")

    sketch_asset = ingest_file(session, workspace, src_path, "sketches")
    sketch_asset.filename = f"{doc.slug}-{block_id[:8]}-sketch-upload{src_path.suffix}"

    block = dict(blocks[idx])
    props = dict(block.get("props", {}))
    props["sketchAssetId"] = sketch_asset.sha256
    props["approval"] = "pending"
    props["faceGate"] = "n/a"
    block["props"] = props
    blocks[idx] = block

    services.save_blocks(
        session, doc, blocks,
        summary=f"uploaded sketch for figure block {block_id[:8]}",
    )
    services.record_change(
        session, doc, "edit", "sketch uploaded",
        detail={"block_id": block_id, "sketch_asset": sketch_asset.sha256},
    )
    return {"sketchAssetId": sketch_asset.sha256, "face_gate": "n/a"}


def generate_caption_for_block(
    session: Session,
    workspace: Path,
    doc: Document,
    block_id: str,
) -> str:
    """Return an AI-generated caption for the named forgeImage block.

    Does not persist anything — the editor updates the block via its normal
    onChange/autosave flow after receiving the caption text.
    """
    block = next(
        (b for b in doc.blocks if b.get("id") == block_id and b.get("type") == FORGE_IMAGE), None
    )
    if block is None:
        raise LookupError(f"no forgeImage block '{block_id}' in {doc.slug}")
    original = session.get(Asset, block.get("props", {}).get("assetId", ""))
    if original is None:
        raise LookupError("figure has no original asset")
    image_bytes = asset_path(workspace, original).read_bytes()
    return _gemini_caption(image_bytes, original.mime or "image/jpeg")


def _gemini_caption(image_bytes: bytes, mime: str) -> str:
    import base64

    import httpx

    from .sketch import get_gemini_key  # noqa: PLC0415

    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError("no Gemini API key configured")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "contents": [{
            "parts": [
                {"text": CAPTION_PROMPT},
                {"inline_data": {"mime_type": mime, "data": encoded}},
            ]
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 80},
    }
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{CAPTION_MODEL}:generateContent"
    )
    with httpx.Client(timeout=60) as client:
        resp = client.post(endpoint, headers={"x-goog-api-key": api_key}, json=body)
    resp.raise_for_status()
    for candidate in resp.json().get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                return part["text"].strip().strip('"').strip("'").rstrip(".")
    raise RuntimeError("Gemini returned no caption text")
