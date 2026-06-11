"""FastAPI layer (M5). Thin orchestration over services; the core stays
importable and UI-free."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services
from .assets import asset_path
from .config import bootstrap_workspace, workspace_path
from .db import fts_search, make_engine, make_session_factory
from .models import Asset, Change, Snapshot, SyncState, Target


@lru_cache(maxsize=1)
def _state() -> dict[str, Any]:
    ws = bootstrap_workspace(workspace_path())
    engine = make_engine(ws)
    return {"workspace": ws, "engine": engine, "factory": make_session_factory(engine)}


def get_session():
    factory = _state()["factory"]
    with factory() as session:
        yield session
        session.commit()


app = FastAPI(title="Notebook Forge", version="0.1.0")


class SaveBlocksBody(BaseModel):
    blocks: list[dict[str, Any]]
    meta: dict[str, Any] | None = None
    summary: str = "edited in editor"


class RollbackBody(BaseModel):
    snapshot_id: int


def _target_states(session: Session, doc) -> list[dict[str, Any]]:  # noqa: ANN001
    out = []
    for target in session.scalars(select(Target)):
        state = session.scalar(
            select(SyncState).where(
                SyncState.document_id == doc.id, SyncState.target_id == target.id
            )
        )
        dirty = services.is_dirty(session, doc, target)
        out.append(
            {
                "target": target.name,
                "kind": target.kind,
                "status": state.status if state else "NEVER_PUBLISHED",
                "dirty": dirty,
                "published_at": state.published_at.isoformat()
                if state and state.published_at
                else None,
                "snapshot_id": state.snapshot_id if state else None,
            }
        )
    return out


@app.get("/api/documents")
def list_documents(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    docs = services.list_documents(session)
    return [
        {
            "slug": d.slug,
            "title": d.title,
            "year_display": d.meta.get("year_display", ""),
            "standfirst": d.meta.get("standfirst", ""),
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "targets": _target_states(session, d),
        }
        for d in docs
    ]


def _get_doc(session: Session, slug: str):  # noqa: ANN202
    doc = services.get_document(session, slug)
    if doc is None:
        raise HTTPException(404, f"no document '{slug}'")
    return doc


@app.get("/api/documents/{slug}")
def get_document(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    doc = _get_doc(session, slug)
    return {
        "slug": doc.slug,
        "title": doc.title,
        "blocks": doc.blocks,
        "meta": doc.meta,
        "targets": _target_states(session, doc),
    }


@app.put("/api/documents/{slug}/blocks")
def save_blocks(
    slug: str, body: SaveBlocksBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    doc = _get_doc(session, slug)
    services.save_blocks(session, doc, body.blocks, meta=body.meta, summary=body.summary)
    if body.meta and body.meta.get("title"):
        doc.title = body.meta["title"]
    return {"ok": True, "targets": _target_states(session, doc)}


@app.get("/api/documents/{slug}/changes")
def document_changes(slug: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    doc = _get_doc(session, slug)
    rows = session.scalars(
        select(Change).where(Change.document_id == doc.id).order_by(Change.id.desc()).limit(100)
    )
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "summary": c.summary,
            "detail": c.detail,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in rows
    ]


@app.get("/api/documents/{slug}/snapshots")
def document_snapshots(slug: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    doc = _get_doc(session, slug)
    rows = session.scalars(
        select(Snapshot).where(Snapshot.document_id == doc.id).order_by(Snapshot.id.desc())
    )
    return [
        {
            "id": s.id,
            "note": s.note,
            "content_hash": s.content_hash,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows
    ]


@app.post("/api/documents/{slug}/rollback")
def rollback(
    slug: str, body: RollbackBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    doc = _get_doc(session, slug)
    snap = session.get(Snapshot, body.snapshot_id)
    if snap is None or snap.document_id != doc.id:
        raise HTTPException(404, "snapshot not found for this document")
    services.rollback_to_snapshot(session, doc, snap)
    return {"ok": True, "targets": _target_states(session, doc)}


@app.delete("/api/documents/{slug}")
def delete_document(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Remove a document and its snapshots/sync/changes (cascade). Assets
    stay — the store is content-addressed and may be shared."""
    from sqlalchemy import text as sql_text

    doc = _get_doc(session, slug)
    session.execute(sql_text("DELETE FROM doc_fts WHERE rowid = :rid").bindparams(rid=doc.id))
    session.delete(doc)
    return {"ok": True, "deleted": slug}


@app.post("/api/ingest")
def ingest(
    file: UploadFile, session: Session = Depends(get_session)
) -> dict[str, Any]:
    import shutil
    import tempfile

    from .ingestion import ingest_document

    suffix = Path(file.filename or "upload").suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        detail = ingest_document(
            session, _state()["workspace"], tmp_path, original_filename=file.filename
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"ok": True, **detail}


class GenerateSketchBody(BaseModel):
    prompt: str | None = None


@app.post("/api/documents/{slug}/figures/{block_id}/generate-sketch")
def generate_sketch(
    slug: str,
    block_id: str,
    body: GenerateSketchBody | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    from .sketch_service import generate_sketch_for_block

    doc = _get_doc(session, slug)
    try:
        detail = generate_sketch_for_block(
            session, _state()["workspace"], doc, block_id,
            prompt=body.prompt if body else None,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:  # no key configured / face gate blocked
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "detail": detail, "targets": _target_states(session, doc)}


@app.post("/api/documents/{slug}/publish/{target_name}")
def publish(
    slug: str, target_name: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .publish import publish_document

    doc = _get_doc(session, slug)
    target = session.scalar(select(Target).where(Target.name == target_name))
    if target is None:
        raise HTTPException(404, f"no target '{target_name}'")
    try:
        detail = publish_document(session, _state()["workspace"], doc, target)
    except PermissionError as exc:  # live publishing disabled this sprint
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "detail": detail, "targets": _target_states(session, doc)}


@app.get("/api/targets")
def list_targets(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [
        {"id": t.id, "name": t.name, "kind": t.kind, "config": t.config}
        for t in session.scalars(select(Target))
    ]


@app.get("/api/search")
def search(q: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    if not q.strip():
        return []
    try:
        return fts_search(session, q)
    except Exception as exc:  # FTS5 raises on bad query syntax
        raise HTTPException(400, f"bad query: {exc}") from exc


@app.get("/api/assets/{sha}")
def serve_asset(sha: str, session: Session = Depends(get_session)) -> FileResponse:
    asset = session.get(Asset, sha)
    if asset is None:
        raise HTTPException(404, "no such asset")
    path = asset_path(_state()["workspace"], asset)
    if not path.exists():
        raise HTTPException(410, "asset file missing from workspace")
    return FileResponse(path, media_type=asset.mime or "application/octet-stream")
