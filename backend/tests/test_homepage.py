"""M4 homepage backend tests: homepage_body, fingerprint/dirty, publish flow, guards."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from notebook_forge.blocks import FORGE_DEDICATION, FORGE_DOC_GROUP, make_block, text_run
from notebook_forge.collection import root_files
from notebook_forge.groups import assign_document, create_group
from notebook_forge.homepage import homepage_body
from notebook_forge.models import Document, Target
from notebook_forge.services import (
    effective_content_hash,
    is_dirty,
    snapshot_document,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hp(session: Session, blocks: list | None = None) -> Document:
    doc = Document(slug="homepage", title="Homepage", kind="homepage", blocks=blocks or [])
    session.add(doc)
    session.flush()
    return doc


def _memoir(session: Session, slug: str, title: str, **meta) -> Document:
    doc = Document(slug=slug, title=title, kind="memoir", blocks=[], meta=meta)
    session.add(doc)
    session.flush()
    return doc


def _group_block(gid: int, sort: str = "date_range", **props) -> dict:
    return make_block(FORGE_DOC_GROUP, {"groupId": str(gid), "sort": sort, **props})


# ---------------------------------------------------------------------------
# homepage_body: heading extraction
# ---------------------------------------------------------------------------

def test_h1_becomes_derived_title(session: Session) -> None:
    hp = _hp(session, [
        make_block("heading", {"level": 1}, [text_run("My Archive")]),
    ])
    _, _, derived = homepage_body(session, hp)
    assert derived["title"] == "My Archive"


def test_non_h1_heading_becomes_seclabel(session: Session) -> None:
    hp = _hp(session, [
        make_block("heading", {"level": 2}, [text_run("Section One")]),
    ])
    entries, _, _ = homepage_body(session, hp)
    assert any(e["kind"] == "seclabel" and e["text"] == "Section One" for e in entries)


def test_paragraphs_become_intro_first_gets_lead(session: Session) -> None:
    hp = _hp(session, [
        make_block("paragraph", content=[text_run("First paragraph")]),
        make_block("paragraph", content=[text_run("Second paragraph")]),
    ])
    entries, _, _ = homepage_body(session, hp)
    intro = [e for e in entries if e["kind"] == "intro"]
    assert intro[0].get("lead") is True
    assert not intro[1].get("lead")


def test_dedication_block(session: Session) -> None:
    hp = _hp(session, [
        make_block(FORGE_DEDICATION, {"text": "For the family"}),
    ])
    entries, _, _ = homepage_body(session, hp)
    assert any(e["kind"] == "dedication" and e["text"] == "For the family" for e in entries)


def test_divider_becomes_hr(session: Session) -> None:
    hp = _hp(session, [make_block("divider")])
    entries, _, _ = homepage_body(session, hp)
    assert any(e["kind"] == "hr" for e in entries)


def test_missing_group_skipped_with_warning(session: Session) -> None:
    hp = _hp(session, [_group_block(999)])
    entries, warnings, _ = homepage_body(session, hp)
    assert not any(e.get("kind") == "group" for e in entries)
    assert any("group" in w.lower() for w in warnings)


def test_empty_group_skipped_with_warning(session: Session) -> None:
    g = create_group(session, "Empty", "#9c5a3c")
    hp = _hp(session, [_group_block(g.id)])
    entries, warnings, _ = homepage_body(session, hp)
    assert not any(e.get("kind") == "group" for e in entries)
    assert any("empty" in w.lower() for w in warnings)


def test_unsupported_block_type_warning(session: Session) -> None:
    hp = _hp(session, [make_block("quote", content=[text_run("some quote")])])
    _, warnings, _ = homepage_body(session, hp)
    assert any("quote" in w for w in warnings)


def test_group_block_resolves_members(session: Session) -> None:
    g = create_group(session, "Memoirs", "#9c5a3c")
    m = _memoir(session, "1950-1960_early-years", "Early Years", year_display="1950–1960",
                canonical_url="https://example.org/1950-1960_early-years.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id)])
    entries, warnings, _ = homepage_body(session, hp)
    groups = [e for e in entries if e["kind"] == "group"]
    assert len(groups) == 1
    assert groups[0]["label"] == "Memoirs"
    assert len(groups[0]["entries"]) == 1
    assert warnings == []


def test_show_blurbs_false_omits_description(session: Session) -> None:
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_slug", "Title", canonical_url="https://x.com/t.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id, showBlurbs=False)])
    entries, _, _ = homepage_body(session, hp)
    card = entries[0]["entries"][0]
    assert "description" not in card


def test_show_word_counts_false_omits_counts(session: Session) -> None:
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_slug", "Title", canonical_url="https://x.com/t.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id, showWordCounts=False)])
    entries, _, _ = homepage_body(session, hp)
    card = entries[0]["entries"][0]
    assert "word_count" not in card


def test_compact_grid_layout_flows_through(session: Session) -> None:
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_slug", "Title", canonical_url="https://x.com/t.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id, layout="compact_grid")])
    entries, _, _ = homepage_body(session, hp)
    group_entry = next(e for e in entries if e["kind"] == "group")
    assert group_entry["layout"] == "compact_grid"


def test_default_title_when_no_h1(session: Session) -> None:
    hp = _hp(session, [])
    _, _, derived = homepage_body(session, hp)
    assert derived["title"] == "The Family Archive"


# ---------------------------------------------------------------------------
# Fingerprint / dirty detection
# ---------------------------------------------------------------------------

def test_effective_content_hash_differs_for_homepage(session: Session) -> None:
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_a", "A", canonical_url="https://x.com/a.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id)])
    session.flush()
    h1 = effective_content_hash(session, hp)

    # Adding a member changes the fingerprint
    m2 = _memoir(session, "1970-1980_b", "B", canonical_url="https://x.com/b.html")
    assign_document(session, m2, g)
    h2 = effective_content_hash(session, hp)
    assert h1 != h2


def test_effective_content_hash_stable_for_memoir(session: Session) -> None:
    doc = _memoir(session, "1960-1970_a", "A")
    h1 = effective_content_hash(session, doc)
    h2 = effective_content_hash(session, doc)
    assert h1 == h2


def test_is_dirty_after_member_change(session: Session) -> None:
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_a", "A", canonical_url="https://x.com/a.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id)])
    session.flush()

    target = Target(name="web", kind="local-folder", config={"folder": "/tmp/x"})
    session.add(target)
    session.flush()

    snap = snapshot_document(session, hp)
    from notebook_forge.services import mark_published
    mark_published(session, hp, target, snap)

    # Not dirty yet
    assert not is_dirty(session, hp, target)

    # Add another member → group fingerprint changes → dirty
    m2 = _memoir(session, "1970-1980_b", "B", canonical_url="https://x.com/b.html")
    assign_document(session, m2, g)
    assert is_dirty(session, hp, target)


def test_color_excluded_from_fingerprint(session: Session) -> None:
    """Group color changes must NOT mark the homepage dirty (D6)."""
    from notebook_forge.groups import update_group
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_a", "A", canonical_url="https://x.com/a.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id)])
    session.flush()
    h1 = effective_content_hash(session, hp)

    update_group(session, g, color="#5a7d5a")
    h2 = effective_content_hash(session, hp)
    assert h1 == h2


# ---------------------------------------------------------------------------
# root_files with homepage doc
# ---------------------------------------------------------------------------

def test_root_files_uses_homepage_body_when_present(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_early", "Early Years",
                canonical_url="https://example.org/1960-1970_early.html")
    assign_document(session, m, g)
    _hp(session, [
        make_block("paragraph", content=[text_run("Welcome to the archive.")]),
        _group_block(g.id),
    ])
    session.flush()

    files, warnings = root_files(session, base_url="https://example.org/archive")
    assert "Early Years" in files["index.html"]
    assert "Welcome to the archive" in files["index.html"]
    assert warnings == []


def test_root_files_legacy_when_no_homepage(session: Session) -> None:
    """Legacy path used when no homepage document exists."""
    files, warnings = root_files(session, base_url="https://example.org/archive")
    assert "index.html" in files
    assert warnings == []


# ---------------------------------------------------------------------------
# Publish flow for homepage
# ---------------------------------------------------------------------------

def test_homepage_publish_writes_root_files(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_early", "Early Years",
                canonical_url="https://example.org/1960-1970_early.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id)])
    session.flush()
    session.commit()

    from notebook_forge.publish import publish_document
    result = publish_document(session, workspace, hp, target)
    session.commit()

    for name in ("index.html", "catalogue.json", "sitemap.xml", "robots.txt", "llms.txt"):
        assert (out / name).exists(), name
    assert "snapshot_id" in result


def test_homepage_publish_to_drive_raises(session: Session, workspace: Path) -> None:
    target = Target(name="drive", kind="drive", config={"mock": True, "folder_id": "x"})
    session.add(target)
    hp = _hp(session)
    session.flush()

    from notebook_forge.publish import publish_document
    with pytest.raises(PermissionError, match="homepage"):
        publish_document(session, workspace, hp, target)


# ---------------------------------------------------------------------------
# API guards: delete/rename/unpublish/polish homepage → 409
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(workspace: Path):
    import os
    os.environ["NOTEBOOK_FORGE_WORKSPACE"] = str(workspace)
    from fastapi.testclient import TestClient

    from notebook_forge.api import _state, app
    _state.cache_clear()
    with TestClient(app) as c:
        yield c


def test_api_delete_homepage_409(workspace: Path, session: Session, api_client) -> None:
    _hp(session)
    session.commit()
    resp = api_client.delete("/api/documents/homepage")
    assert resp.status_code == 409


def test_api_rename_homepage_409(workspace: Path, session: Session, api_client) -> None:
    _hp(session)
    session.commit()
    resp = api_client.post("/api/documents/homepage/rename", json={"new_slug": "new-home"})
    assert resp.status_code == 409


def test_api_unpublish_homepage_409(workspace: Path, session: Session, api_client) -> None:
    _hp(session)
    target = Target(name="web", kind="local-folder", config={"folder": "/tmp/x"})
    session.add(target)
    session.commit()
    resp = api_client.delete(f"/api/documents/homepage/publish/{target.id}")
    assert resp.status_code == 409
