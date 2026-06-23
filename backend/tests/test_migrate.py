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


def test_legacy_narration_engine_column_dropped(tmp_path: Path) -> None:
    """A document_narration table from the Polly era has a NOT NULL `engine`
    column and no `model`/`audio_duration_seconds`. After migration, `engine` is
    gone, the new columns exist, and a fresh row can be inserted (the ORM no
    longer writes engine — which previously failed the NOT NULL constraint)."""
    db_file = tmp_path / "forge.db"
    old = create_engine(f"sqlite:///{db_file}")
    with old.begin() as conn:
        # documents table already migrated (so only the narration block runs).
        conn.execute(text(
            "CREATE TABLE documents ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT DEFAULT '', "
            "blocks JSON DEFAULT '[]', meta JSON DEFAULT '{}', "
            "kind TEXT NOT NULL DEFAULT 'memoir', group_id INTEGER, "
            "group_position INTEGER NOT NULL DEFAULT 0, "
            "created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(text(
            "CREATE TABLE document_narration ("
            "id INTEGER PRIMARY KEY, document_id INTEGER, audio_base_url TEXT DEFAULT '', "
            "exported_hashes JSON DEFAULT '[]', last_exported_at DATETIME, "
            "voice TEXT DEFAULT 'Brian', engine TEXT NOT NULL DEFAULT 'generative', "
            "lexicon JSON DEFAULT '[]')"
        ))
        conn.execute(text(
            "INSERT INTO document_narration (document_id, voice, engine) "
            "VALUES (1, 'Brian', 'generative')"
        ))
    old.dispose()

    run_migrations(old, db_file)

    engine = create_engine(f"sqlite:///{db_file}")
    cols = _columns(engine, "document_narration")
    assert "engine" not in cols
    assert "model" in cols
    assert "audio_duration_seconds" in cols
    with engine.begin() as conn:
        # Legacy voice normalised, and a NEW row inserts without `engine`.
        v = conn.execute(text("SELECT voice FROM document_narration WHERE document_id=1")).scalar()
        assert v == "fjnwTZkKtQOJaYzGLa6n"
        conn.execute(text(
            "INSERT INTO document_narration (document_id, audio_base_url, exported_hashes, "
            "voice, model, lexicon) VALUES (2, '', '[]', 'fjnwTZkKtQOJaYzGLa6n', 'eleven_v3', '[]')"
        ))
    engine.dispose()


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
