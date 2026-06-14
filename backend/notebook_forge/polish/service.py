"""LLM polish orchestration.

Flow:
  1. Extract polishable (id, kind, text) from doc.blocks via textmap.
  2. Snapshot the document (always — cheap and predictable).
  3. Chunk the polishable blocks.
  4. Run all chunks (injectable runner for tests).
  5. Fidelity-guard each result + footnote-marker hard check.
  6. Apply clean (typography-only, no marker mismatch) blocks via
     services.save_blocks (only if ≥1 changed).
  7. Record the polish run metadata in the change log (always).
  8. Return the report: polished count, unchanged count, flagged list,
     failed chunks, and model name.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import services
from ..models import Document, Setting
from .chunker import chunk_blocks
from .fidelity import check_block_fidelity, diff_segments
from .runner import POLISH_MODEL, GeminiPolishRunner, run_chunks
from .textmap import polish_text_to_content, polishable_blocks


def polish_settings(session: Session) -> dict[str, Any]:
    """Operator-controlled polish settings (defaults: gemini-2.5-flash, no extra rules)."""
    row = session.get(Setting, "polish")
    value = dict(row.value) if row else {}
    return {
        "model": value.get("model") or POLISH_MODEL,
        "extra_rules": value.get("extra_rules") or "",
    }


def polish_document(
    session: Session,
    workspace: Path,
    doc: Document,
    *,
    runner: GeminiPolishRunner | None = None,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the polish pass over doc and return the report.

    runner can be injected in tests (e.g. an httpx.MockTransport-backed
    GeminiPolishRunner).  When None the real Gemini runner is constructed
    from the keychain key; RuntimeError is raised (→ 409) if no key.
    """
    cfg = polish_settings(session)

    # 1. Polishable text list
    poly = polishable_blocks(doc.blocks)

    # 2. Snapshot always — cheap, predictable, makes Restore work
    services.snapshot_document(session, doc, note="before polish")

    if not poly:
        services.record_change(
            session, doc, "edit", "polish: no polishable blocks",
            detail={"model": cfg["model"], "chunks": 0, "blocks_changed": 0,
                    "flagged": 0, "flagged_ids": [], "polishable": 0, "failed_chunks": 0},
        )
        return {
            "blocks_polished": 0,
            "blocks_unchanged": 0,
            "flagged": [],
            "failed_chunks": [],
            "model": cfg["model"],
        }

    # 3. Chunk
    chunks = chunk_blocks(poly)
    if progress is not None:
        progress["total"] = len(chunks)

    # 4. Run (real or injected)
    if runner is None:
        from .runner import make_runner
        runner = make_runner(cfg["model"])

    def _on_chunk_done(failed: bool) -> None:
        if progress is not None:
            progress["done"] += 1
            if failed:
                progress["failed"] += 1

    results, failed_chunks = run_chunks(
        chunks, runner, extra_rules=cfg["extra_rules"], on_chunk_done=_on_chunk_done,
    )

    # 5. Fidelity guard
    orig_by_id = {bid: text for bid, _kind, text in poly}
    clean_updates: dict[str, list[dict[str, Any]]] = {}
    flagged: list[dict[str, Any]] = []

    for block_id, polished_text in results.items():
        original = orig_by_id.get(block_id, "")
        if polished_text == original:
            continue  # verbatim → skip entirely
        verdict = check_block_fidelity(original, polished_text, block_id)
        if verdict.is_clean:
            clean_updates[block_id] = polish_text_to_content(polished_text)
        else:
            flagged.append({
                "block_id": block_id,
                "original": original,
                "polished": polished_text,
                "summary": verdict.summary,
                "polished_content": polish_text_to_content(polished_text),
                "diff": diff_segments(original, polished_text),
            })

    # 6. Apply clean updates
    n_changed = len(clean_updates)
    if n_changed > 0:
        new_blocks = copy.deepcopy(doc.blocks)
        for block in new_blocks:
            if block["id"] in clean_updates:
                block["content"] = clean_updates[block["id"]]
        services.save_blocks(
            session, doc, new_blocks,
            summary=f"polish: {n_changed} block{'s' if n_changed != 1 else ''} cleaned",
        )

    # 7. Record run metadata
    n_unchanged = len(poly) - n_changed - len(flagged)
    model_name = runner.model if hasattr(runner, "model") else cfg["model"]
    services.record_change(
        session, doc, "edit",
        f"polish run: {n_changed} cleaned, {len(flagged)} flagged"
        + (f", {len(failed_chunks)} chunk(s) failed" if failed_chunks else ""),
        detail={
            "model": model_name,
            "chunks": len(chunks),
            "blocks_changed": n_changed,
            "flagged": len(flagged),
            "flagged_ids": [f["block_id"] for f in flagged],
            "polishable": len(poly),
            "failed_chunks": len(failed_chunks),
        },
    )

    return {
        "blocks_polished": n_changed,
        "blocks_unchanged": n_unchanged,
        "flagged": flagged,
        "failed_chunks": failed_chunks,
        "model": model_name,
    }
