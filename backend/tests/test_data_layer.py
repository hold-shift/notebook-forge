"""M1 gate: create / edit / snapshot / dirty / rollback paths."""

from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.assets import asset_path, ingest_file
from notebook_forge.blocks import content_hash, make_block, plain_text, text_run
from notebook_forge.config import ASSET_KINDS
from notebook_forge.db import fts_search
from notebook_forge.models import Change, Target


def para(txt: str) -> dict:
    return make_block("paragraph", content=[text_run(txt)])


def sample_blocks() -> list[dict]:
    return [
        make_block("heading", {"level": 2}, [text_run("A chapter")]),
        para("The quick brown fox jumps over the lazy dog."),
        make_block(
            "forgeImage",
            {
                "assetId": "abc123",
                "sketchAssetId": "def456",
                "caption": "A fox mid-jump",
                "altText": "A fox jumping over a dog",
                "approval": "approved",
                "displayWidth": "full",
            },
        ),
        make_block("forgeFootnote", {"marker": "1", "text": "Foxes rarely jump dogs."}),
    ]


def test_workspace_bootstrap(workspace: Path, session: Session) -> None:
    for kind in ASSET_KINDS:
        assert (workspace / "assets" / kind).is_dir()
    assert (workspace / "exports").is_dir()
    assert (workspace / "forge.db").exists()
    mode = session.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"


def test_create_and_fts(session: Session) -> None:
    doc = services.create_document(session, "fox-doc", "Fox Doc", sample_blocks())
    session.commit()

    assert services.get_document(session, "fox-doc") is not None
    hits = fts_search(session, "quick brown")
    assert hits and hits[0]["slug"] == "fox-doc"
    # captions and footnote text are indexed too
    assert fts_search(session, "rarely jump")
    assert "A fox mid-jump" in plain_text(doc.blocks)


def test_edit_logs_change_and_updates_fts(session: Session) -> None:
    doc = services.create_document(session, "d", "D", sample_blocks())
    session.commit()

    blocks = doc.blocks[:1] + [para("An entirely new paragraph about wombats.")]
    services.save_blocks(session, doc, blocks)
    session.commit()

    kinds = [c.kind for c in session.scalars(select(Change).order_by(Change.id))]
    assert kinds == ["import", "edit"]
    assert fts_search(session, "wombats")
    assert not fts_search(session, "quick brown")

    # saving identical content again must NOT add a change-log entry
    services.save_blocks(session, doc, blocks)
    session.commit()
    assert [c.kind for c in session.scalars(select(Change))].count("edit") == 1


def test_snapshot_dirty_publish_rollback(session: Session) -> None:
    doc = services.create_document(session, "d", "D", sample_blocks())
    target = Target(name="pages", kind="github-pages", config={})
    session.add(target)
    session.commit()

    # never published → dirty
    assert services.is_dirty(session, doc, target)

    snap = services.snapshot_document(session, doc, note="first publish")
    services.mark_published(session, doc, target, snap)
    session.commit()
    assert not services.is_dirty(session, doc, target)

    # edit → dirty for that target
    original_hash = content_hash(doc.blocks, doc.meta)
    services.save_blocks(session, doc, doc.blocks + [para("Late addition.")])
    session.commit()
    assert services.is_dirty(session, doc, target)
    assert content_hash(doc.blocks, doc.meta) != original_hash

    # rollback restores content and clears dirtiness
    services.rollback_to_snapshot(session, doc, snap)
    session.commit()
    assert content_hash(doc.blocks, doc.meta) == original_hash
    assert not services.is_dirty(session, doc, target)
    kinds = [c.kind for c in session.scalars(select(Change).order_by(Change.id))]
    assert kinds[-1] == "rollback"


def test_content_hash_ignores_block_ids() -> None:
    a = [para("same text")]
    b = [para("same text")]
    assert a[0]["id"] != b[0]["id"]
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash([para("different text")])


def test_asset_store_content_addressed(workspace: Path, session: Session, tmp_path: Path) -> None:
    f1 = tmp_path / "photo.jpg"
    f1.write_bytes(b"not really a jpeg but stable bytes")
    a1 = ingest_file(session, workspace, f1, "originals")
    session.commit()

    stored = asset_path(workspace, a1)
    assert stored.exists()
    assert stored.parent.name == "originals"
    assert a1.sha256 in stored.name

    # same bytes under another name → same asset row, no duplicate
    f2 = tmp_path / "copy.jpg"
    f2.write_bytes(f1.read_bytes())
    a2 = ingest_file(session, workspace, f2, "originals")
    assert a2.sha256 == a1.sha256
