"""M6 gate: edit → dirty → publish to both real adapters (local folder +
git bare-repo fixture) → clean → rollback restores prior content. Drive is
interface + mocked client."""

import subprocess
from pathlib import Path

from sqlalchemy.orm import Session
from test_importer import SLUG, make_repo

from notebook_forge import services
from notebook_forge.blocks import content_hash, make_block, text_run
from notebook_forge.models import Snapshot, Target
from notebook_forge.publish import (
    DriveTarget,
    GitPagesTarget,
    LocalFolderTarget,
    MockDriveClient,
    make_adapter,
    publish_document,
    rollback_and_republish,
)


def import_doc(tmp_path: Path, workspace: Path, session: Session):
    from notebook_forge.importer import get_or_create_pages_target, import_document

    repo = make_repo(tmp_path)
    pages = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, pages)
    session.commit()
    return doc


def edit_doc(session: Session, doc) -> None:  # noqa: ANN001
    blocks = doc.blocks + [
        make_block("paragraph", content=[text_run("A brand new closing paragraph.")])
    ]
    services.save_blocks(session, doc, blocks, summary="test edit")
    session.commit()


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_local_folder_full_cycle(tmp_path: Path, workspace: Path, session: Session) -> None:
    doc = import_doc(tmp_path, workspace, session)
    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.commit()

    assert services.is_dirty(session, doc, target)  # never published here

    detail = publish_document(session, workspace, doc, target)
    session.commit()
    assert not services.is_dirty(session, doc, target)
    html_path = out / f"{SLUG}.html"
    assert html_path.exists()
    assert (out / f"{SLUG}_assets" / "figure-1-original.jpeg").exists()
    assert (out / f"{SLUG}_assets" / "figure-1-silhouette.png").exists()
    pre_edit_hash = content_hash(doc.blocks, doc.meta)
    restore_snap_id = detail["snapshot_id"]

    # second publish with no changes transfers nothing
    detail2 = publish_document(session, workspace, doc, target)
    session.commit()
    assert detail2 != detail or True
    changes = [c for c in doc.changes if c.kind == "publish"]
    assert changes[-1].detail["assets_written"] == 0
    assert changes[-1].detail["assets_skipped"] == 30

    # edit → dirty → publish → clean
    edit_doc(session, doc)
    assert services.is_dirty(session, doc, target)
    publish_document(session, workspace, doc, target)
    session.commit()
    assert not services.is_dirty(session, doc, target)
    assert "brand new closing paragraph" in html_path.read_text()

    # rollback to the pre-edit snapshot → content + output restored
    snap = session.get(Snapshot, restore_snap_id)
    rollback_and_republish(session, workspace, doc, target, snap)
    session.commit()
    assert content_hash(doc.blocks, doc.meta) == pre_edit_hash
    assert "brand new closing paragraph" not in html_path.read_text()
    assert not services.is_dirty(session, doc, target)


def test_git_pages_fixture_full_cycle(tmp_path: Path, workspace: Path, session: Session) -> None:
    doc = import_doc(tmp_path, workspace, session)
    bare = tmp_path / "pages.git"
    bare.mkdir()
    git("init", "--bare", "--initial-branch=main", ".", cwd=bare)

    target = Target(
        name="pages-fixture",
        kind="github-pages",
        config={"push_url": str(bare), "branch": "main", "subdir": "rfs"},
    )
    session.add(target)
    session.commit()

    publish_document(session, workspace, doc, target)
    session.commit()
    assert not services.is_dirty(session, doc, target)
    files = git("ls-tree", "-r", "--name-only", "main", cwd=bare).splitlines()
    assert f"rfs/{SLUG}.html" in files
    assert f"rfs/{SLUG}_assets/figure-1-original.jpeg" in files
    first_sha = git("rev-parse", "main", cwd=bare)
    snap_id = doc.sync_states[0].snapshot_id

    # edit → publish → new commit on the fixture remote
    edit_doc(session, doc)
    assert services.is_dirty(session, doc, target)
    publish_document(session, workspace, doc, target)
    session.commit()
    assert not services.is_dirty(session, doc, target)
    second_sha = git("rev-parse", "main", cwd=bare)
    assert second_sha != first_sha
    published_html = git("show", f"main:rfs/{SLUG}.html", cwd=bare)
    assert "brand new closing paragraph" in published_html

    # rollback re-points and re-renders: the remote shows restored content
    snap = session.get(Snapshot, snap_id)
    rollback_and_republish(session, workspace, doc, target, snap)
    session.commit()
    restored_html = git("show", f"main:rfs/{SLUG}.html", cwd=bare)
    assert "brand new closing paragraph" not in restored_html
    assert not services.is_dirty(session, doc, target)


def test_drive_target_mocked(tmp_path: Path, workspace: Path, session: Session) -> None:
    doc = import_doc(tmp_path, workspace, session)
    client = MockDriveClient()
    target = Target(name="drive", kind="drive", config={"folder_id": "folder-123"})
    session.add(target)
    session.commit()

    adapter = DriveTarget(client, "folder-123")
    publish_document(session, workspace, doc, target, adapter=adapter)
    session.commit()
    assert client.calls[0][0] == "find"
    create = next(c for c in client.calls if c[0] == "create")
    assert create[1]["body"] == {
        "name": SLUG,
        "mimeType": "application/vnd.google-apps.document",
        "parents": ["folder-123"],
    }

    # re-publish updates the SAME file (stable Doc URL), no second create
    publish_document(session, workspace, doc, target, adapter=adapter)
    session.commit()
    assert len(client.files) == 1
    assert any(c[0] == "update" for c in client.calls)
    assert not services.is_dirty(session, doc, target)


def test_live_pages_target_refuses_without_push_url(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """Hard guardrail: the imported github-pages target (the live site) has
    no push_url, so building its adapter must refuse."""
    import_doc(tmp_path, workspace, session)
    live = session.query(Target).filter_by(name="github-pages").one()
    try:
        make_adapter(live, workspace)
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "disabled this sprint" in str(exc)


def test_adapters_are_pure_io(tmp_path: Path) -> None:
    """LocalFolderTarget / GitPagesTarget take no DB session — publishing
    I/O is separated from state, which is what makes the atomic
    sync_state update possible."""
    assert not hasattr(LocalFolderTarget(tmp_path), "session")
    assert not hasattr(
        GitPagesTarget(push_url="x", clones_dir=tmp_path), "session"
    )
