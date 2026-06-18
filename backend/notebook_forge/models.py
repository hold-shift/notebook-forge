"""SQLAlchemy models — the seven tables of the agreed ERD.

Block trees are stored as JSON columns (SQLite JSON1). A document is dirty
for a target when its current blocks/meta hash differs from the snapshot
recorded in that target's sync_state row.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    title: Mapped[str] = mapped_column(String, default="")
    blocks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Header/publication metadata that feeds rendering: author, overline,
    # standfirst, place, year display, date prefix, datePublished, …
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    kind: Mapped[str] = mapped_column(String, default="memoir")  # memoir | homepage
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    group_position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    sync_states: Mapped[list[SyncState]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    changes: Mapped[list[Change]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Asset(Base):
    """Content-addressed by SHA-256; the file lives in the workspace asset
    store at assets/{kind}/{sha256}{ext} — the DB stores metadata only."""

    __tablename__ = "assets"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # originals | sketches | sources
    filename: Mapped[str] = mapped_column(String, default="")  # original basename
    ext: Mapped[str] = mapped_column(String, default="")
    mime: Mapped[str] = mapped_column(String, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    blocks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="snapshots")


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)  # github-pages | local-folder | drive
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("document_id", "target_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"), index=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="NEVER_PUBLISHED")
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="sync_states")
    target: Mapped[Target] = relationship()
    snapshot: Mapped[Snapshot | None] = relationship()


class Change(Base):
    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # import | edit | publish | rollback
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="changes")


class Group(Base):
    """Library document groups (single-group membership, v1)."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    color: Mapped[str] = mapped_column(String, default="#9c5a3c")  # '#rrggbb'
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    """App settings. Secrets live in the OS keychain via `keyring`; this
    table records only which keys exist and their last-verified status."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Report(Base):
    """A derived analytical report for one document — a navigational index,
    not a primary record. Generated by a chunked LLM pass; `content_hash`
    pins the doc.blocks revision it was built from, so the report reads as
    stale once the document diverges. Regenerating replaces the row (and its
    ReportTrack rows) in place."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"), unique=True, index=True
    )
    source_name: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    exec_summary: Mapped[str] = mapped_column(Text, default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="generated")
    drive_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set explicitly on every (re)generation — NOT onupdate, so a later push
    # (which writes pushed_at) does not bump it. pushed_at < generated_at means
    # the current generation still needs pushing.
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    pushed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    document: Mapped[Document] = relationship()


class ReportTrack(Base):
    """One structured reference-track row (people | geo | glossary |
    chronology) extracted from a document. These rows are the single source
    of truth for both a per-doc report's §6 and the corpus-wide master
    tracks; `source_name` keeps every row traceable after pooling. Replaced
    wholesale (delete + insert) whenever the document's report is rebuilt, so
    the master rebuild stays idempotent by source."""

    __tablename__ = "report_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    source_name: Mapped[str] = mapped_column(String, default="", index=True)
    track_type: Mapped[str] = mapped_column(String)  # people | geo | glossary | chronology
    seq: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship()
