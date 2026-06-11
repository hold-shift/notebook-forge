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
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(result.image_bytes)
        tmp_path = Path(tmp.name)
    try:
        sketch_asset = ingest_file(session, workspace, tmp_path, "sketches")
        sketch_asset.filename = f"{doc.slug}-{block_id[:8]}-sketch.png"
    finally:
        tmp_path.unlink(missing_ok=True)

    props = dict(block.get("props", {}))
    props["sketchAssetId"] = sketch_asset.sha256
    props["approval"] = "pending"  # fresh generations always need review
    block["props"] = props
    blocks[blocks.index(next(b for b in blocks if b.get("id") == block_id))] = block

    gate = getattr(generator, "last_gate", None)
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
