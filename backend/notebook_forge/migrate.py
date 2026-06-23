"""Idempotent column migrations. create_all() only creates missing TABLES;
new columns on existing tables are added here, guarded by PRAGMA table_info.
A one-time pre-migration backup of forge.db is written next to it."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import Engine, text

_DOCUMENTS_MIGRATIONS = [
    "ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'memoir'",
    "ALTER TABLE documents ADD COLUMN group_id INTEGER REFERENCES groups(id)",
    "ALTER TABLE documents ADD COLUMN group_position INTEGER NOT NULL DEFAULT 0",
]

_COLUMN_FOR = {
    "ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'memoir'": "kind",
    "ALTER TABLE documents ADD COLUMN group_id INTEGER REFERENCES groups(id)": "group_id",
    "ALTER TABLE documents ADD COLUMN group_position INTEGER NOT NULL DEFAULT 0": "group_position",
}


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings()
    return {r["name"] for r in rows}


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t").bindparams(t=table)
    ).first()
    return row is not None


def _backup_once(db_file: Path, suffix: str) -> None:
    if db_file.exists():
        backup = db_file.with_name(f"forge.db.bak-{suffix}")
        if not backup.exists():
            shutil.copy2(db_file, backup)


def run_migrations(engine: Engine, db_file: Path) -> None:
    with engine.connect() as conn:
        existing = _columns(conn, "documents")
        narration_exists = _table_exists(conn, "document_narration")
        narration_cols = _columns(conn, "document_narration") if narration_exists else set()

    pending = [ddl for ddl in _DOCUMENTS_MIGRATIONS if _COLUMN_FOR[ddl] not in existing]

    if pending:
        _backup_once(db_file, "pre-groups")
        with engine.begin() as conn:
            for ddl in pending:
                conn.execute(text(ddl))

    # TTS narration: the table is created by create_all() with the current
    # schema on fresh DBs, so this only fires on a workspace whose table predates
    # the Polly→ElevenLabs switch — add the `model` column the ORM now reads, and
    # normalise the old "Brian" voice default to the locked ElevenLabs voice_id.
    if narration_exists and "model" not in narration_cols:
        _backup_once(db_file, "pre-tts-elevenlabs")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE document_narration "
                    "ADD COLUMN model TEXT NOT NULL DEFAULT 'eleven_v3'"
                )
            )
            conn.execute(
                text(
                    "UPDATE document_narration SET voice = :v WHERE voice = 'Brian'"
                ).bindparams(v="fjnwTZkKtQOJaYzGLa6n")
            )

    # Recording-length column (homepage tile label), added later than `model`.
    if narration_exists and "audio_duration_seconds" not in narration_cols:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE document_narration ADD COLUMN audio_duration_seconds REAL")
            )

    # Drop the orphaned Polly-era `engine` column. It was created NOT NULL with no
    # server default, so once the ORM stopped writing it, inserting a NEW narration
    # row failed the NOT NULL constraint — only documents with a pre-existing row
    # worked. (SQLite ≥3.35 supports DROP COLUMN.)
    if narration_exists and "engine" in narration_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE document_narration DROP COLUMN engine"))
