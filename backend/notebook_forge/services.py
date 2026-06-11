"""Document lifecycle: CRUD, snapshots, dirty-state, change log, rollback.

Dirty rule (locked decision): a document is dirty for a target when its
current blocks/meta content-hash differs from the snapshot recorded in that
target's sync_state row. No snapshot recorded → dirty by definition.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .blocks import content_hash, plain_text
from .db import fts_replace
from .models import Change, Document, Snapshot, SyncState, Target, utcnow


def create_document(
    session: Session,
    slug: str,
    title: str,
    blocks: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    log: str = "created",
) -> Document:
    doc = Document(slug=slug, title=title, blocks=blocks or [], meta=meta or {})
    session.add(doc)
    session.flush()
    record_change(session, doc, "import", log)
    reindex(session, doc)
    return doc


def get_document(session: Session, slug: str) -> Document | None:
    return session.scalar(select(Document).where(Document.slug == slug))


def list_documents(session: Session) -> list[Document]:
    return list(session.scalars(select(Document).order_by(Document.slug)))


def save_blocks(
    session: Session,
    doc: Document,
    blocks: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    summary: str = "edited in editor",
) -> Document:
    before = content_hash(doc.blocks, doc.meta)
    doc.blocks = blocks
    if meta is not None:
        doc.meta = meta
    doc.updated_at = utcnow()
    after = content_hash(doc.blocks, doc.meta)
    if before != after:
        record_change(
            session, doc, "edit", summary, detail={"hash_before": before, "hash_after": after}
        )
    reindex(session, doc)
    return doc


def record_change(
    session: Session,
    doc: Document,
    kind: str,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> Change:
    change = Change(document_id=doc.id, kind=kind, summary=summary, detail=detail or {})
    session.add(change)
    return change


def reindex(session: Session, doc: Document) -> None:
    fts_replace(session, doc.id, doc.slug, doc.title, plain_text(doc.blocks))


def snapshot_document(session: Session, doc: Document, note: str = "") -> Snapshot:
    snap = Snapshot(
        document_id=doc.id,
        blocks=doc.blocks,
        meta=doc.meta,
        content_hash=content_hash(doc.blocks, doc.meta),
        note=note,
    )
    session.add(snap)
    session.flush()
    return snap


def get_or_create_sync_state(session: Session, doc: Document, target: Target) -> SyncState:
    state = session.scalar(
        select(SyncState).where(
            SyncState.document_id == doc.id, SyncState.target_id == target.id
        )
    )
    if state is None:
        state = SyncState(document_id=doc.id, target_id=target.id)
        session.add(state)
        session.flush()
    return state


def is_dirty(session: Session, doc: Document, target: Target) -> bool:
    state = session.scalar(
        select(SyncState).where(
            SyncState.document_id == doc.id, SyncState.target_id == target.id
        )
    )
    if state is None or state.snapshot_id is None:
        return True
    snap = session.get(Snapshot, state.snapshot_id)
    if snap is None:
        return True
    return content_hash(doc.blocks, doc.meta) != snap.content_hash


def mark_published(
    session: Session, doc: Document, target: Target, snap: Snapshot, status: str = "PUBLISHED"
) -> SyncState:
    state = get_or_create_sync_state(session, doc, target)
    state.snapshot_id = snap.id
    state.status = status
    state.published_at = utcnow()
    return state


def rollback_to_snapshot(session: Session, doc: Document, snap: Snapshot) -> Document:
    if snap.document_id != doc.id:
        raise ValueError("snapshot does not belong to this document")
    doc.blocks = snap.blocks
    doc.meta = snap.meta
    doc.updated_at = utcnow()
    record_change(
        session, doc, "rollback", f"rolled back to snapshot {snap.id}",
        detail={"snapshot_id": snap.id, "content_hash": snap.content_hash},
    )
    reindex(session, doc)
    return doc
