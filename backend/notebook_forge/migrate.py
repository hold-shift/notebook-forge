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


def run_migrations(engine: Engine, db_file: Path) -> None:
    with engine.connect() as conn:
        existing = _columns(conn, "documents")

    pending = [
        ddl for ddl in _DOCUMENTS_MIGRATIONS if _COLUMN_FOR[ddl] not in existing
    ]
    if not pending:
        return

    if db_file.exists():
        backup = db_file.with_name("forge.db.bak-pre-groups")
        if not backup.exists():
            shutil.copy2(db_file, backup)

    with engine.begin() as conn:
        for ddl in pending:
            conn.execute(text(ddl))
