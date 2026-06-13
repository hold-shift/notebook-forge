"""M3 gate: narrative label setting API, dirty fold, per-doc override, build_bundle."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import FORGE_NARRATIVE, make_block, text_run
from notebook_forge.models import Setting, Target
from notebook_forge.narrative import effective_narrative_label, narrative_label_setting


def _narrative_block() -> dict:
    return make_block(FORGE_NARRATIVE, content=[text_run("A reflective passage.")])


def _para_block() -> dict:
    return make_block("paragraph", content=[text_run("Ordinary prose.")])


def _make_target(session: Session) -> Target:
    t = Target(name="local", kind="local-folder", config={"folder": "/tmp/forge-test"})
    session.add(t)
    session.flush()
    return t


# ── Test 1: PUT/GET settings round-trip; label trimmed ──

def test_narrative_settings_round_trip(session: Session) -> None:
    # Initially no setting → empty
    assert narrative_label_setting(session) == ""

    # Save a label
    value = {"label": "  From the author  "}
    row = Setting(key="narrative", value={"label": value["label"].strip()})
    session.add(row)
    session.flush()
    assert narrative_label_setting(session) == "From the author"

    # Update
    setting = session.get(Setting, "narrative")
    assert setting is not None
    setting.value = {"label": "Reflections"}
    session.flush()
    assert narrative_label_setting(session) == "Reflections"


# ── Test 2: Dirty fold — narrative docs dirty when label changes; non-narrative unchanged ──

def test_dirty_fold_narrative_blocks(session: Session) -> None:
    target = _make_target(session)

    doc_with = services.create_document(
        session, "with-narrative", "With Narrative", [_narrative_block()]
    )
    doc_without = services.create_document(
        session, "no-narrative", "No Narrative", [_para_block()]
    )
    session.commit()

    # Mark both as published at the current state
    snap_with = services.snapshot_document(session, doc_with, note="published")
    services.mark_published(session, doc_with, target, snap_with)
    snap_without = services.snapshot_document(session, doc_without, note="published")
    services.mark_published(session, doc_without, target, snap_without)
    session.commit()

    # Both clean
    assert not services.is_dirty(session, doc_with, target)
    assert not services.is_dirty(session, doc_without, target)

    # Change the workspace narrative label
    session.add(Setting(key="narrative", value={"label": "From the author"}))
    session.commit()

    # doc_with has narrative blocks → dirty (label folds into hash)
    assert services.is_dirty(session, doc_with, target)
    # doc_without has no narrative blocks → NOT dirty (label not folded)
    assert not services.is_dirty(session, doc_without, target)


# ── Test 3: Per-doc override "" beats a non-empty workspace label ──

def test_per_doc_empty_override_beats_workspace(session: Session) -> None:
    session.add(Setting(key="narrative", value={"label": "From the author"}))
    session.flush()

    doc = services.create_document(
        session, "doc-override", "Override", [_narrative_block()],
        meta={"narrative_label": ""},  # explicit empty = suppress
    )
    label = effective_narrative_label(session, doc)
    assert label == ""


# ── Test 4: build_bundle html contains narrative-label when workspace label set ──

def test_build_bundle_renders_narrative_label(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    session.add(Setting(key="narrative", value={"label": "From the author"}))
    session.flush()

    doc = services.create_document(
        session, "narr-bundle", "Bundle Test", [_narrative_block()]
    )
    session.commit()

    from notebook_forge.publish.service import build_bundle

    bundle = build_bundle(session, workspace, doc)
    soup = BeautifulSoup(bundle.html, "lxml")
    label_el = soup.find("p", class_="narrative-label")
    assert label_el is not None
    assert "From the author" in label_el.get_text()
