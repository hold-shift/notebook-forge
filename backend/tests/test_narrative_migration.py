"""M7: narrative migration — scan, apply, guard, CLI."""

from pathlib import Path

from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import FORGE_NARRATIVE, make_block, text_run
from notebook_forge.models import Setting, Snapshot
from notebook_forge.narrative_migration import MARKER_KEY, already_applied, apply, scan


def _italic_para(text: str) -> dict:
    return make_block("paragraph", content=[text_run(text, {"italic": True})])


def _plain_para(text: str) -> dict:
    return make_block("paragraph", content=[text_run(text)])


# ── scan ──

def test_scan_finds_fully_italic_paragraphs(session: Session) -> None:
    services.create_document(
        session, "memoir-a", "Memoir A",
        [_italic_para("Looking back on those years I wonder how we managed.")],
    )
    services.create_document(
        session, "memoir-b", "Memoir B",
        [_plain_para("Ordinary prose with no italic.")],
    )
    session.flush()

    rows = scan(session)
    slugs_with_count = {r["slug"]: r["count"] for r in rows}
    assert slugs_with_count.get("memoir-a", 0) == 1
    assert slugs_with_count.get("memoir-b", 0) == 0


def test_scan_excludes_homepage(session: Session) -> None:
    doc = services.create_document(
        session, "homepage", "Homepage", [], meta={"kind": "homepage"},
    )
    doc.kind = "homepage"
    session.flush()

    # Also add a memoir so scan has something to return
    services.create_document(
        session, "memoir-c", "Memoir C", [_plain_para("Plain text.")],
    )
    session.flush()

    rows = scan(session)
    assert all(r["slug"] != "homepage" for r in rows)


# ── already_applied ──

def test_already_applied_returns_none_initially(session: Session) -> None:
    assert already_applied(session) is None


def test_already_applied_returns_marker_after_apply(session: Session) -> None:
    services.create_document(
        session, "doc-x", "Doc X",
        [_italic_para("A reflective passage about those long years gone.")],
    )
    session.flush()
    apply(session)
    session.flush()

    marker = already_applied(session)
    assert marker is not None
    assert "applied_at" in marker
    assert "doc-x" in marker.get("converted", {})


# ── apply ──

def test_apply_converts_italic_paragraphs_and_snapshots(session: Session) -> None:
    doc = services.create_document(
        session, "memoir-d", "Memoir D",
        [_italic_para("Looking back on those years I wonder how we managed."),
         _plain_para("After.")],
    )
    session.flush()

    applied = apply(session)
    session.flush()

    assert any(r["slug"] == "memoir-d" for r in applied)
    narrative = [b for b in doc.blocks if b["type"] == FORGE_NARRATIVE]
    assert len(narrative) == 1

    # Safety snapshot was taken
    snaps = session.query(Snapshot).filter_by(document_id=doc.id).all()
    assert any("before narrative migration" in (s.note or "") for s in snaps)


def test_apply_skips_docs_with_zero_conversions(session: Session) -> None:
    services.create_document(
        session, "memoir-e", "Memoir E", [_plain_para("Just plain text here.")],
    )
    session.flush()

    applied = apply(session)
    session.flush()

    assert all(r["slug"] != "memoir-e" for r in applied)


def test_apply_writes_marker_setting(session: Session) -> None:
    services.create_document(
        session, "memoir-f", "Memoir F",
        [_italic_para("A long reflective passage about the early years lived.")],
    )
    session.flush()
    apply(session)
    session.flush()

    s = session.get(Setting, MARKER_KEY)
    assert s is not None
    assert "applied_at" in s.value


def test_apply_makes_doc_dirty(session: Session, workspace: Path) -> None:
    """save_blocks changes the content hash, so docs go dirty for all targets."""
    from notebook_forge import services as svc
    from notebook_forge.importer import get_or_create_pages_target

    doc = services.create_document(
        session, "memoir-g", "Memoir G",
        [_italic_para("Reflective passage spanning at least twelve words here indeed.")],
    )
    target = get_or_create_pages_target(session, workspace)
    snap = svc.snapshot_document(session, doc, note="pre-apply")
    svc.mark_published(session, doc, target, snap, status="PUBLISHED")
    session.flush()

    assert not svc.is_dirty(session, doc, target)

    apply(session)
    session.flush()

    assert svc.is_dirty(session, doc, target)


# ── guard: --force is the escape hatch ──

def test_second_apply_is_refused_when_marker_present(session: Session) -> None:
    """The CLI enforces this guard, but we verify already_applied returns truthy."""
    services.create_document(
        session, "memoir-h", "Memoir H",
        [_italic_para("Long enough passage for the conversion rule to trigger here.")],
    )
    session.flush()
    apply(session)
    session.flush()

    assert already_applied(session) is not None  # guard would fire in CLI


# ── CLI integration ──

def test_cli_dry_run_writes_report(tmp_path: Path, session: Session) -> None:
    from notebook_forge.cli import main

    ws = session.get_bind().url.database  # sqlite path string
    ws_path = Path(ws).parent
    services.create_document(
        session, "memoir-i", "Memoir I",
        [_italic_para("A reflective passage that is long enough to convert to narrative.")],
    )
    session.commit()

    ret = main([
        "narrative-migrate", "--dry-run",
        "--workspace", str(ws_path),
        "--reports", str(tmp_path),
    ])
    assert ret == 0
    report = (tmp_path / "narrative_migration.md").read_text()
    assert "memoir-i" in report
    assert "dry-run" in report
    # Documents NOT converted (dry-run)
    refreshed = services.get_document(session, "memoir-i")
    assert all(b["type"] != FORGE_NARRATIVE for b in (refreshed.blocks if refreshed else []))


def test_cli_apply_converts_and_blocks_second_run(
    tmp_path: Path, session: Session
) -> None:
    from notebook_forge.cli import main

    ws = session.get_bind().url.database
    ws_path = Path(ws).parent
    services.create_document(
        session, "memoir-j", "Memoir J",
        [_italic_para("A reflective passage long enough to convert with the rule applied.")],
    )
    session.commit()

    ret = main([
        "narrative-migrate", "--apply",
        "--workspace", str(ws_path),
        "--reports", str(tmp_path),
    ])
    assert ret == 0

    # Second apply is blocked
    ret2 = main([
        "narrative-migrate", "--apply",
        "--workspace", str(ws_path),
        "--reports", str(tmp_path),
    ])
    assert ret2 == 1

    # --force allows it
    ret3 = main([
        "narrative-migrate", "--apply", "--force",
        "--workspace", str(ws_path),
        "--reports", str(tmp_path),
    ])
    assert ret3 == 0
