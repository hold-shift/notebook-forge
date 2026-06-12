"""Tests for the idempotent column migration runner."""

from pathlib import Path

from sqlalchemy import create_engine, text

from notebook_forge.db import make_engine
from notebook_forge.migrate import run_migrations


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings()
        return {r["name"] for r in rows}


def test_fresh_workspace_has_new_columns(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    engine = make_engine(ws)
    cols = _columns(engine, "documents")
    assert "kind" in cols
    assert "group_id" in cols
    assert "group_position" in cols
    assert "groups" in engine.dialect.get_table_names(engine.connect())
    engine.dispose()


def test_old_schema_gets_migrated(tmp_path: Path) -> None:
    db_file = tmp_path / "forge.db"
    # Build an old-schema DB without the new columns.
    old_engine = create_engine(f"sqlite:///{db_file}")
    with old_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE documents ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT DEFAULT '', "
            "blocks JSON DEFAULT '[]', meta JSON DEFAULT '{}', "
            "created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(text(
            "CREATE TABLE groups ("
            "id INTEGER PRIMARY KEY, name TEXT UNIQUE, color TEXT DEFAULT '#9c5a3c', "
            "sort_order INTEGER DEFAULT 0, created_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO documents (slug, title) VALUES ('test-doc', 'Test')"
        ))
    old_engine.dispose()

    run_migrations(old_engine, db_file)

    new_engine = create_engine(f"sqlite:///{db_file}")
    cols = _columns(new_engine, "documents")
    assert "kind" in cols
    assert "group_id" in cols
    assert "group_position" in cols

    with new_engine.connect() as conn:
        row = conn.execute(text("SELECT kind FROM documents WHERE slug='test-doc'")).fetchone()
    assert row[0] == "memoir"

    backup = db_file.with_name("forge.db.bak-pre-groups")
    assert backup.exists()
    new_engine.dispose()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    db_file = ws / "forge.db"
    engine = make_engine(ws)
    backup = db_file.with_name("forge.db.bak-pre-groups")
    assert not backup.exists()

    # Second call is a no-op.
    run_migrations(engine, db_file)
    assert not backup.exists()
    engine.dispose()
