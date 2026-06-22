"""Per-document narration record: read, save, and SSML-manifest export.

Thin orchestration over `narration.py` and the DocumentNarration model. The
panel reads `narration_view` (record + live sync status) on load; the operator
pastes the S3 base URL and edits the lexicon (`save_narration`); `export_manifest`
builds the manifest.zip, stamps the exported hash set, and records the change.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from sqlalchemy.orm import Session

from . import narration, services
from .models import Document, DocumentNarration, utcnow


def _get(session: Session, doc: Document) -> DocumentNarration | None:
    return (
        session.query(DocumentNarration)
        .filter(DocumentNarration.document_id == doc.id)
        .one_or_none()
    )


def get_or_create(session: Session, doc: Document) -> DocumentNarration:
    """The document's narration row, created with defaults on first access."""
    rec = _get(session, doc)
    if rec is not None:
        return rec
    rec = DocumentNarration(document_id=doc.id)
    session.add(rec)
    session.flush()
    return rec


def narration_view(session: Session, doc: Document) -> dict[str, Any]:
    """Narration record + live sync status for the panel."""
    rec = get_or_create(session, doc)
    live = narration.live_hashes(
        doc.blocks, voice=rec.voice, model=rec.model, lexicon=rec.lexicon or [],
        meta=doc.meta,
    )
    status = narration.sync_status(rec.audio_base_url, rec.exported_hashes or [], live)
    return {
        "audio_base_url": rec.audio_base_url,
        "voice": rec.voice,
        "model": rec.model,
        "lexicon": rec.lexicon or [],
        "exported_hashes": rec.exported_hashes or [],
        "last_exported_at": rec.last_exported_at.isoformat() if rec.last_exported_at else None,
        "status": status,
        "live_block_count": len(live),
        "tts_enabled": narration.tts_enabled(session),
    }


def save_narration(
    session: Session,
    doc: Document,
    *,
    audio_base_url: str | None = None,
    lexicon: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist the operator-entered audio base URL and/or lexicon."""
    rec = get_or_create(session, doc)
    if audio_base_url is not None:
        rec.audio_base_url = audio_base_url.strip()
    if lexicon is not None:
        rec.lexicon = [
            {
                "phrase": str(e.get("phrase", "")).strip(),
                "replacement": str(e.get("replacement", "")),
            }
            for e in lexicon
            if str(e.get("phrase", "")).strip()
        ]
    session.flush()
    return narration_view(session, doc)


def export_manifest(session: Session, doc: Document) -> tuple[bytes, str]:
    """Build the manifest.zip, store the exported hash set + timestamp, and
    record the change. Returns (zip_bytes, download_filename)."""
    rec = get_or_create(session, doc)
    blocks = narration.extract_blocks(
        doc.blocks, voice=rec.voice, model=rec.model, lexicon=rec.lexicon or [],
        meta=doc.meta,
    )
    slug = doc.meta.get("slug", doc.slug)
    manifest = narration.build_manifest(
        slug=slug,
        title=doc.meta.get("title") or doc.title,
        voice=rec.voice,
        model=rec.model,
        blocks=blocks,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    rec.exported_hashes = [b["hash"] for b in blocks]
    rec.last_exported_at = utcnow()
    session.flush()
    services.record_change(
        session,
        doc,
        "edit",
        f"exported SSML manifest ({len(blocks)} block(s))",
        detail={"blocks": len(blocks), "voice": rec.voice, "model": rec.model},
    )
    return buf.getvalue(), f"{slug}.manifest.zip"


def has_audio(session: Session, doc: Document) -> bool:
    """True when this document has a populated audio base URL (independent of
    the global toggle — callers gate on tts_enabled separately)."""
    rec = _get(session, doc)
    return bool(rec and (rec.audio_base_url or "").strip())


def player_context(session: Session, doc: Document) -> dict[str, Any] | None:
    """Render context for the published-page player, or None when it should not
    appear. The player renders ONLY when the global TTS toggle is on AND this
    document has a populated audio base URL (§7)."""
    if not narration.tts_enabled(session):
        return None
    rec = _get(session, doc)
    if rec is None or not (rec.audio_base_url or "").strip():
        return None
    return {
        "audio_base_url": rec.audio_base_url.rstrip("/"),
        "slug": doc.meta.get("slug", doc.slug),
        "title": doc.meta.get("title") or doc.title,
        "author": doc.meta.get("author", ""),
    }


def audio_state(session: Session, doc: Document) -> dict[str, bool]:
    """{has_audio, audio_stale} for list serializers (admin + published)."""
    rec = _get(session, doc)
    if rec is None or not (rec.audio_base_url or "").strip():
        return {"has_audio": False, "audio_stale": False}
    live = narration.live_hashes(
        doc.blocks, voice=rec.voice, model=rec.model, lexicon=rec.lexicon or [],
        meta=doc.meta,
    )
    stale = set(rec.exported_hashes or []) != set(live)
    return {"has_audio": True, "audio_stale": stale}
