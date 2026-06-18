"""FastAPI layer (M5). Thin orchestration over services; the core stays
importable and UI-free."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import services
from .assets import asset_path
from .config import bootstrap_workspace, workspace_path
from .db import fts_search, make_engine, make_session_factory
from .groups import (
    assign_document,
    catalogue_descriptions,
    create_group,
    delete_group,
    group_member_dict,
    list_groups,
    reorder_groups,
    set_positions,
    update_group,
)
from .models import Asset, Change, Group, Snapshot, SyncState, Target, utcnow


@lru_cache(maxsize=1)
def _state() -> dict[str, Any]:
    ws = bootstrap_workspace(workspace_path())
    engine = make_engine(ws)
    factory = make_session_factory(engine)
    with factory() as session:
        from .homepage_migration import ensure_homepage
        ensure_homepage(session)
        session.commit()
    return {"workspace": ws, "engine": engine, "factory": factory}


def _drive_doc_url(session: Session, doc, target: Target) -> str | None:  # noqa: ANN001
    """The stable Google Doc URL from the most recent drive publish."""
    rows = session.scalars(
        select(Change)
        .where(Change.document_id == doc.id, Change.kind == "publish")
        .order_by(Change.id.desc())
        .limit(20)
    )
    for change in rows:
        detail = change.detail or {}
        if detail.get("target") == target.name and detail.get("file_id"):
            return f"https://docs.google.com/document/d/{detail['file_id']}/edit"
    return None


def _target_url(session: Session, doc, target: Target) -> str | None:  # noqa: ANN001
    if target.kind == "github-pages":
        return doc.meta.get("canonical_url") or None
    if target.kind == "local-folder":
        filename = "index.html" if doc.kind == "homepage" else f"{doc.slug}.html"
        return f"/site/{filename}"  # served by the /site mount below
    if target.kind == "drive":
        return _drive_doc_url(session, doc, target)
    return None


def get_session():
    factory = _state()["factory"]
    with factory() as session:
        yield session
        session.commit()


app = FastAPI(title="Notebook Forge", version="0.3.0")

# Serve the local-folder export so its pages are one click away in the UI
# (browsers refuse file:// links from http pages).
_site_dir = _state()["workspace"] / "exports" / "site"
_site_dir.mkdir(parents=True, exist_ok=True)
app.mount("/site", StaticFiles(directory=_site_dir, html=True), name="site")

# In-process progress registry for in-flight polish runs, keyed by doc slug.
# Written by the /polish worker via its progress dict, read by /polish/progress.
# GIL-safe dict mutations; not persisted — purely for the live chunk counter.
_polish_progress: dict[str, dict] = {}

# In-process job registry for bulk sketch generation.
# Key: "{slug}:{job_id}" — GIL-safe dict mutations; not persisted.
_sketch_jobs: dict[str, dict] = {}

# In-process progress registry for in-flight report generation, keyed by doc
# slug. Written by the /report/generate worker, read by /report/progress.
_report_progress: dict[str, dict] = {}


class SaveBlocksBody(BaseModel):
    blocks: list[dict[str, Any]]
    meta: dict[str, Any] | None = None
    summary: str = "edited in editor"


class RollbackBody(BaseModel):
    snapshot_id: int


class GroupBody(BaseModel):
    name: str
    color: str = "#9c5a3c"


class GroupPatchBody(BaseModel):
    name: str | None = None
    color: str | None = None


class GroupOrderBody(BaseModel):
    ids: list[int]


class DocGroupBody(BaseModel):
    group_id: int | None


class PositionsBody(BaseModel):
    group_id: int | None
    slugs: list[str]


def _target_states(session: Session, doc) -> list[dict[str, Any]]:  # noqa: ANN001
    out = []
    for target in session.scalars(select(Target)):
        if doc.kind == "homepage" and target.kind == "drive":
            continue
        state = session.scalar(
            select(SyncState).where(
                SyncState.document_id == doc.id, SyncState.target_id == target.id
            )
        )
        dirty = services.is_dirty(session, doc, target)
        published = bool(state and state.status == "PUBLISHED")
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
                "url": _target_url(session, doc, target) if published else None,
            }
        )
    return out


@app.get("/api/groups")
def list_groups_route(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    descs = catalogue_descriptions(session)
    return [group_member_dict(session, g, descs) for g in list_groups(session)]


@app.post("/api/groups")
def create_group_route(
    body: GroupBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        group = create_group(session, body.name, body.color)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, f"group name '{body.name}' already in use") from None
    return {
        "id": group.id, "name": group.name,
        "color": group.color, "sort_order": group.sort_order,
    }


@app.put("/api/groups/order")
def reorder_groups_route(
    body: GroupOrderBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        reorder_groups(session, body.ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@app.put("/api/groups/{group_id}")
def update_group_route(
    group_id: int, body: GroupPatchBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    group = session.get(Group, group_id)
    if group is None:
        raise HTTPException(404, f"no group {group_id}")
    try:
        group = update_group(session, group, name=body.name, color=body.color)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "group name already in use") from None
    return {
        "id": group.id, "name": group.name,
        "color": group.color, "sort_order": group.sort_order,
    }


@app.delete("/api/groups/{group_id}")
def delete_group_route(
    group_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    group = session.get(Group, group_id)
    if group is None:
        raise HTTPException(404, f"no group {group_id}")
    moved = delete_group(session, group)
    return {"ok": True, "moved": moved}


@app.put("/api/documents/positions")
def set_positions_route(
    body: PositionsBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        set_positions(session, body.group_id, body.slugs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@app.get("/api/documents")
def list_documents(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    docs = [d for d in services.list_documents(session) if d.kind == "memoir"]
    out = []
    for d in docs:
        figs = [b for b in d.blocks if b.get("type") == "forgeImage"]
        source_file = d.meta.get("source_file", "")
        source_type = Path(source_file).suffix.lstrip(".").upper() if source_file else "HTML"
        out.append(
            {
                "slug": d.slug,
                "title": d.title,
                "year_display": d.meta.get("year_display", ""),
                "standfirst": d.meta.get("standfirst", ""),
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                "source_type": source_type or "HTML",
                "figures": len(figs),
                "sketched": sum(
                    1 for b in figs if b.get("props", {}).get("sketchAssetId")
                ),
                "pending_review": sum(
                    1 for b in figs if b.get("props", {}).get("approval") == "pending"
                ),
                "group_id": d.group_id,
                "group_position": d.group_position,
                "date_confirmed": d.meta.get("date_confirmed", True) is not False,
                "targets": _target_states(session, d),
            }
        )
    return out


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
        "kind": doc.kind,
        "blocks": doc.blocks,
        "meta": doc.meta,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
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


class RenameBody(BaseModel):
    new_slug: str


@app.post("/api/documents/{slug}/rename")
def rename_document(
    slug: str, body: RenameBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Rename the document slug. Updates canonical_url in meta to match.
    The old URL becomes a dead link until the operator re-publishes."""
    from re import fullmatch

    new_slug = body.new_slug.strip()
    if not new_slug:
        raise HTTPException(400, "new_slug must not be empty")
    if not fullmatch(r"[a-z0-9][a-z0-9\-_]*", new_slug):
        raise HTTPException(
            400, "slug may only contain lowercase letters, digits, hyphens and underscores"
        )
    if services.get_document(session, new_slug) is not None:
        raise HTTPException(409, f"slug '{new_slug}' is already in use")

    doc = _get_doc(session, slug)
    if doc.kind == "homepage":
        raise HTTPException(409, "the homepage slug is fixed")
    old_slug = doc.slug
    doc.slug = new_slug

    meta = dict(doc.meta)
    meta["slug"] = new_slug
    if meta.get("canonical_url"):
        meta["canonical_url"] = str(meta["canonical_url"]).replace(
            f"/{old_slug}.", f"/{new_slug}."
        )
    doc.meta = meta

    services.record_change(session, doc, "edit", f"renamed slug from {old_slug} to {new_slug}")
    services.reindex(session, doc)
    return {"ok": True, "slug": new_slug}


@app.put("/api/documents/{slug}/group")
def set_document_group(
    slug: str, body: DocGroupBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    doc = _get_doc(session, slug)
    if doc.kind == "homepage":
        raise HTTPException(409, "the homepage cannot be grouped")
    group = None
    if body.group_id is not None:
        group = session.get(Group, body.group_id)
        if group is None:
            raise HTTPException(404, f"no group {body.group_id}")
    assign_document(session, doc, group)
    return {"ok": True, "group_id": doc.group_id, "group_position": doc.group_position}


@app.delete("/api/documents/{slug}")
def delete_document(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Remove a document and its snapshots/sync/changes (cascade). Assets
    stay — the store is content-addressed and may be shared."""
    from sqlalchemy import text as sql_text

    doc = _get_doc(session, slug)
    if doc.kind == "homepage":
        raise HTTPException(409, "the homepage cannot be deleted")
    session.execute(sql_text("DELETE FROM doc_fts WHERE rowid = :rid").bindparams(rid=doc.id))
    session.delete(doc)
    return {"ok": True, "deleted": slug}


class CreateDocumentBody(BaseModel):
    title: str = "Untitled"


@app.post("/api/documents")
def create_document_route(
    body: CreateDocumentBody | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Create a new empty document from scratch (no source file)."""
    from .ingestion import create_blank_document

    detail = create_blank_document(session, body.title if body else "Untitled")
    return {"ok": True, **detail}


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


@app.post("/api/documents/{slug}/reingest")
def reingest(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Re-run extraction from the archived source file. Text is replaced;
    figure work (sketches, approvals, caption edits) carries over by
    content-addressed match. A snapshot is taken first."""
    from .ingestion import reingest_document

    doc = _get_doc(session, slug)
    try:
        detail = reingest_document(session, _state()["workspace"], doc)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "detail": detail, "targets": _target_states(session, doc)}


class GenerateSketchBody(BaseModel):
    prompt: str | None = None
    force: bool = False  # regenerate: bypass the cache for a fresh variation


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
            force=body.force if body else False,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:  # no key configured / face gate blocked
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "detail": detail, "targets": _target_states(session, doc)}


@app.post("/api/documents/{slug}/figures/upload-image")
def upload_figure_image(
    slug: str,
    file: UploadFile,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Upload a photo as a new figure asset. Returns the asset SHA for use as assetId."""
    import shutil
    import tempfile

    from .assets import ingest_file

    _get_doc(session, slug)  # ensures doc exists
    suffix = Path(file.filename or "upload").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        asset = ingest_file(session, _state()["workspace"], tmp_path, "figures")
        asset.filename = file.filename or f"upload{suffix}"
        session.commit()
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"assetId": asset.sha256}


@app.post("/api/documents/{slug}/figures/{block_id}/upload-sketch")
def upload_sketch(
    slug: str,
    block_id: str,
    file: UploadFile,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Attach an operator-supplied sketch to a figure (escape hatch when the
    image model refuses). Persists the block and returns the new sketchAssetId."""
    import shutil
    import tempfile

    from .sketch_service import upload_sketch_for_block

    doc = _get_doc(session, slug)
    suffix = Path(file.filename or "sketch").suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        detail = upload_sketch_for_block(
            session, _state()["workspace"], doc, block_id, tmp_path
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"ok": True, "detail": detail, "targets": _target_states(session, doc)}


@app.post("/api/documents/{slug}/figures/{block_id}/generate-caption")
def generate_caption(
    slug: str,
    block_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    from .sketch_service import generate_caption_for_block

    doc = _get_doc(session, slug)
    try:
        caption = generate_caption_for_block(session, _state()["workspace"], doc, block_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"caption": caption}


class GenerateAllSketchesBody(BaseModel):
    batch_face_gate: str = "warn"  # warn | block; overrides global setting for this run


@app.post("/api/documents/{slug}/figures/generate-all-sketches")
def generate_all_sketches(
    slug: str,
    body: GenerateAllSketchesBody | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Start a sequential bulk-sketch job for all eligible figures.

    Returns immediately with a job_id.  Poll
    GET /api/documents/{slug}/figures/generate-all-sketches/status?job_id=…
    for progress.  Eligibility: has an original photo AND sketch not yet
    approved (guards against clobbering approved work).
    """
    import threading
    import uuid

    from .sketch_service import eligible_figure_block_ids, generate_sketch_for_block

    if body is None:
        body = GenerateAllSketchesBody()
    if body.batch_face_gate not in ("warn", "block"):
        raise HTTPException(422, "batch_face_gate must be 'warn' or 'block'")

    doc = _get_doc(session, slug)
    block_ids = eligible_figure_block_ids(list(doc.blocks))
    job_id = uuid.uuid4().hex[:12]
    key = f"{slug}:{job_id}"
    job: dict[str, Any] = {
        "status": "running",
        "done": 0,
        "total": len(block_ids),
        "failed": 0,
        "results": [],
    }
    _sketch_jobs[key] = job

    workspace = _state()["workspace"]
    factory = _state()["factory"]
    face_gate = body.batch_face_gate

    def _run() -> None:
        for bid in block_ids:
            if job.get("status") == "cancelled":
                break
            try:
                with factory() as s:
                    fresh_doc = s.get(type(doc), doc.id)
                    if fresh_doc is None:
                        raise LookupError("document deleted")
                    result = generate_sketch_for_block(
                        s, workspace, fresh_doc, bid,
                        generator=_make_batch_generator(workspace, s, face_gate),
                    )
                    s.commit()
                job["results"].append({
                    "block_id": bid,
                    "ok": True,
                    "face_gate": result.get("face_gate", "n/a"),
                })
            except Exception as exc:  # noqa: BLE001
                job["failed"] += 1
                job["results"].append({"block_id": bid, "ok": False, "error": str(exc)})
            finally:
                job["done"] += 1
        job["status"] = "done"

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "eligible": len(block_ids)}


def _make_batch_generator(workspace: Path, session: Session, face_gate: str):  # noqa: ANN202
    """Return a sketch generator with the batch face-gate override applied."""
    from .sketch_gen import make_generator
    from .sketch_service import sketch_settings

    cfg = sketch_settings(session)
    return make_generator(
        workspace / "sketch-cache",
        model=cfg["model"],
        face_gate=face_gate,
    )


@app.get("/api/documents/{slug}/figures/generate-all-sketches/status")
def generate_all_sketches_status(
    slug: str,
    job_id: str,
) -> dict[str, Any]:
    """Poll for bulk-sketch job progress."""
    key = f"{slug}:{job_id}"
    job = _sketch_jobs.get(key)
    if job is None:
        raise HTTPException(404, f"no job '{job_id}' for document '{slug}'")
    return dict(job)


@app.post("/api/documents/{slug}/polish")
def polish(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Run the mechanical LLM polish pass and return the report.

    Typography-only fixes are applied automatically; word-level changes are
    returned as flagged blocks for per-block review in the editor.
    A snapshot is taken first so Restore can undo the whole pass.
    """
    from .polish.service import polish_document

    doc = _get_doc(session, slug)
    if doc.kind == "homepage":
        raise HTTPException(409, "polish does not run on the homepage")
    prog: dict = {"running": True, "done": 0, "total": 0, "failed": 0}
    _polish_progress[slug] = prog
    try:
        detail = polish_document(session, _state()["workspace"], doc, progress=prog)
    except RuntimeError as exc:  # no key configured
        raise HTTPException(409, str(exc)) from exc
    finally:
        prog["running"] = False
    return {"ok": True, **detail, "targets": _target_states(session, doc)}


@app.get("/api/documents/{slug}/polish/progress")
def polish_progress(slug: str) -> dict[str, Any]:
    """Live progress for an in-flight polish run. The frontend polls this
    while the synchronous POST is pending so the operator sees chunk movement.
    Returns the zero shape for unknown slugs — the poll can race the POST.
    """
    p = _polish_progress.get(slug)
    if not p:
        return {"running": False, "done": 0, "total": 0, "failed": 0}
    return dict(p)


@app.get("/api/documents/{slug}/polish/last")
def polish_last(slug: str, session: Session = Depends(get_session)) -> dict[str, Any] | None:
    """Return metadata from the most recent polish run for this document, or null."""
    doc = _get_doc(session, slug)
    row = session.scalar(
        select(Change)
        .where(
            Change.document_id == doc.id,
            Change.kind == "edit",
            Change.summary.startswith("polish"),
        )
        .order_by(Change.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    d = row.detail or {}
    polishable = d.get("polishable", 0)
    blocks_changed = d.get("blocks_changed", 0)
    flagged_count = d.get("flagged", 0)
    blocks_unchanged = max(0, polishable - blocks_changed - flagged_count)
    # Freshness anchor: when the review was resolved (applying the flagged
    # changes is part of polishing, not a later edit), else the run time.
    at = d.get("resolved_at") or (row.created_at.isoformat() if row.created_at else None)
    return {
        "at": at,
        "model": d.get("model", ""),
        "blocks_changed": blocks_changed,
        "blocks_unchanged": blocks_unchanged,
        "flagged_ids": d.get("flagged_ids", []),
        "chunks": d.get("chunks", 0),
        "failed_chunks": d.get("failed_chunks", 0),
    }


@app.post("/api/documents/{slug}/polish/resolve-flags")
def polish_resolve_flags(
    slug: str, session: Session = Depends(get_session)
) -> dict[str, Any] | None:
    """Mark the most recent polish run's flagged changes as reviewed.

    The flagged list is a record of what a run held back for review; once the
    operator finishes the review (applies and/or skips), those flags are no
    longer pending. Clearing the run's `flagged_ids` keeps the polish badge
    from staying stuck on "flagged" forever. Document content is untouched —
    this only updates the change-log metadata."""
    doc = _get_doc(session, slug)
    row = session.scalar(
        select(Change)
        .where(
            Change.document_id == doc.id,
            Change.kind == "edit",
            Change.summary.startswith("polish"),
        )
        .order_by(Change.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    detail = dict(row.detail or {})
    detail["flagged_ids"] = []
    detail["flags_resolved"] = True
    # Re-anchor polish freshness to the review-completion time so applying the
    # flagged changes doesn't immediately read back as "stale".
    detail["resolved_at"] = utcnow().isoformat()
    row.detail = detail
    return polish_last(slug, session)


# ---------------------------------------------------------------- reports

def _report_state(session: Session, doc) -> dict[str, Any]:  # noqa: ANN001
    """Status payload for a document's analytical report (None → never run)."""
    from .models import ReportTrack
    from .reports.service import get_report, report_is_stale

    report = get_report(session, doc)
    if report is None:
        return {"exists": False, "stale": False, "status": "never-run"}
    counts = dict(
        session.execute(
            select(ReportTrack.track_type, func.count())
            .where(ReportTrack.document_id == doc.id)
            .group_by(ReportTrack.track_type)
        ).all()
    )
    return {
        "exists": True,
        "status": report.status,
        "stale": report_is_stale(session, doc, report),
        "model": report.model,
        "source_name": report.source_name,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "pushed_at": report.pushed_at.isoformat() if report.pushed_at else None,
        "drive_file_id": report.drive_file_id,
        "tracks": {tt: counts.get(tt, 0) for tt in ("people", "geo", "glossary", "chronology")},
    }


@app.post("/api/documents/{slug}/report/generate")
def report_generate(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Generate (or regenerate) the analytical report and return its status.

    Runs synchronously; the frontend polls /report/progress for chunk movement.
    """
    from .reports.service import generate_report

    doc = _get_doc(session, slug)
    if doc.kind == "homepage":
        raise HTTPException(409, "the homepage has no analytical report")
    prog: dict = {"running": True, "done": 0, "total": 0, "failed": 0}
    _report_progress[slug] = prog
    try:
        detail = generate_report(session, _state()["workspace"], doc, progress=prog)
    except RuntimeError as exc:  # no Gemini key configured
        raise HTTPException(409, str(exc)) from exc
    finally:
        prog["running"] = False
    return {"ok": True, "detail": detail, "report": _report_state(session, doc)}


@app.get("/api/documents/{slug}/report/progress")
def report_progress(slug: str) -> dict[str, Any]:
    """Live progress for an in-flight report run (polled during generation)."""
    p = _report_progress.get(slug)
    if not p:
        return {"running": False, "done": 0, "total": 0, "failed": 0}
    return dict(p)


@app.get("/api/documents/{slug}/report")
def report_get(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Report status plus the rendered body (body is "" when never generated)."""
    from .reports.service import get_report

    doc = _get_doc(session, slug)
    report = get_report(session, doc)
    return {**_report_state(session, doc), "body_md": report.body_md if report else ""}


# ---------------------------------------------------------------- master tracks

_MASTER_SETTING = "reports_master"


def _master_status(session: Session) -> dict[str, Any]:
    """Master track stats plus last-built / last-pushed metadata."""
    from .models import Setting
    from .reports.master import master_stats

    row = session.get(Setting, _MASTER_SETTING)
    meta = dict(row.value) if row else {}
    return {
        **master_stats(session),
        "built_at": meta.get("built_at"),
        "pushed_at": meta.get("pushed_at"),
        "drive_file_ids": meta.get("drive_file_ids", {}),
    }


@app.get("/api/reports/master")
def report_master_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Master reference-track status: N documents · N rows · last built."""
    return _master_status(session)


@app.post("/api/reports/master/generate")
def report_master_generate(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Rebuild the four master CSVs from current ReportTrack rows.

    Validates each CSV's column widths before recording the build. The Drive
    push is layered on in the publish step.
    """
    from .models import Setting
    from .reports.csvbuild import validate_widths
    from .reports.master import build_master_csvs

    csvs = build_master_csvs(session)
    for text in csvs.values():
        validate_widths(text)  # self-check — raises on a width mismatch

    meta = {"built_at": utcnow().isoformat()}
    row = session.get(Setting, _MASTER_SETTING)
    if row is None:
        session.add(Setting(key=_MASTER_SETTING, value=meta))
    else:
        row.value = {**row.value, **meta}
    return {"ok": True, "master": _master_status(session)}


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


@app.delete("/api/documents/{slug}/publish/{target_name}")
def unpublish(
    slug: str, target_name: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .publish.service import unpublish_document

    doc = _get_doc(session, slug)
    if doc.kind == "homepage":
        raise HTTPException(409, "unpublishing the site index is not supported")
    target = session.scalar(select(Target).where(Target.name == target_name))
    if target is None:
        raise HTTPException(404, f"no target '{target_name}'")
    try:
        detail = unpublish_document(session, _state()["workspace"], doc, target)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "detail": detail, "targets": _target_states(session, doc)}


@app.get("/api/targets")
def list_targets(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [
        {"id": t.id, "name": t.name, "kind": t.kind, "config": t.config}
        for t in session.scalars(select(Target))
    ]


@app.get("/api/settings")
def get_settings(session: Session = Depends(get_session)) -> dict[str, Any]:
    from .footer import footer_setting
    from .narrative import narrative_label_setting
    from .polish.service import polish_settings
    from .publish.drive_client import have_credentials
    from .reports.service import report_settings
    from .secrets_store import get_secret
    from .sketch_service import sketch_settings

    return {
        "sketch": sketch_settings(session),
        "polish": polish_settings(session),
        "reports": report_settings(session),
        "narrative": {"label": narrative_label_setting(session)},
        "footer": footer_setting(session),
        "secrets": {
            "gemini-api-key": bool(get_secret("gemini-api-key", env="GEMINI_API_KEY")),
            "github-pat": bool(get_secret("github-pat", env="GITHUB_PAT")),
            "drive-oauth": have_credentials(),
        },
        "targets": [
            {"name": t.name, "kind": t.kind, "config": t.config}
            for t in session.scalars(select(Target))
        ],
    }


class SketchSettingsBody(BaseModel):
    model: str
    default_prompt: str
    face_gate: str = "block"


@app.put("/api/settings/sketch")
def save_sketch_settings(
    body: SketchSettingsBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .models import Setting

    if body.face_gate not in ("block", "warn"):
        raise HTTPException(422, "face_gate must be 'block' or 'warn'")
    value = {
        "model": body.model.strip(),
        "default_prompt": body.default_prompt.strip(),
        "face_gate": body.face_gate,
    }
    setting = session.get(Setting, "sketch")
    if setting is None:
        session.add(Setting(key="sketch", value=value))
    else:
        setting.value = value
    return {"ok": True, "sketch": value}


class PolishSettingsBody(BaseModel):
    model: str
    extra_rules: str = ""


@app.put("/api/settings/polish")
def save_polish_settings(
    body: PolishSettingsBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .models import Setting

    value = {"model": body.model.strip(), "extra_rules": body.extra_rules}
    setting = session.get(Setting, "polish")
    if setting is None:
        session.add(Setting(key="polish", value=value))
    else:
        setting.value = value
    return {"ok": True, "polish": value}


class ReportSettingsBody(BaseModel):
    model: str
    rules: str = ""


@app.put("/api/settings/reports")
def save_report_settings(
    body: ReportSettingsBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .models import Setting

    value = {"model": body.model.strip(), "rules": body.rules}
    setting = session.get(Setting, "reports")
    if setting is None:
        session.add(Setting(key="reports", value=value))
    else:
        setting.value = value
    return {"ok": True, "reports": value}


class NarrativeSettingsBody(BaseModel):
    label: str = ""


@app.put("/api/settings/narrative")
def save_narrative_settings(
    body: NarrativeSettingsBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .models import Setting

    value = {"label": body.label.strip()}
    setting = session.get(Setting, "narrative")
    if setting is None:
        session.add(Setting(key="narrative", value=value))
    else:
        setting.value = value
    return {"ok": True, "narrative": value}


class FooterSettingsBody(BaseModel):
    notice: str = ""
    license_label: str = ""
    license_url: str = ""


@app.put("/api/settings/footer")
def save_footer_settings(
    body: FooterSettingsBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from .models import Setting

    url = body.license_url.strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(422, "license_url must be an http(s) URL")
    value = {
        "notice": body.notice.strip(),
        "license_label": body.license_label.strip(),
        "license_url": url,
    }
    setting = session.get(Setting, "footer")
    if setting is None:
        session.add(Setting(key="footer", value=value))
    else:
        setting.value = value
    return {"ok": True, "footer": value}


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
