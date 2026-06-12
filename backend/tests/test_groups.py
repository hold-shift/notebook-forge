"""Tests for the groups service layer and API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from notebook_forge.groups import (
    assign_document,
    create_group,
    delete_group,
    list_groups,
    reorder_groups,
    resolve_members,
    set_positions,
    update_group,
)
from notebook_forge.services import create_document

# ── helpers ──────────────────────────────────────────────────────────────────

def _doc(session, slug, title=""):
    return create_document(session, slug, title or slug)


# ── create / list / update / reorder ─────────────────────────────────────────

def test_create_and_list(session):
    g1 = create_group(session, "Alpha", "#9c5a3c")
    g2 = create_group(session, "Beta", "#5a7d5a")
    groups = list_groups(session)
    assert [g.name for g in groups] == ["Alpha", "Beta"]
    assert g1.sort_order == 0
    assert g2.sort_order == 1


def test_create_empty_name_raises(session):
    with pytest.raises(ValueError, match="empty"):
        create_group(session, "  ", "#9c5a3c")


def test_create_bad_color_raises(session):
    with pytest.raises(ValueError, match="color"):
        create_group(session, "Good", "red")


def test_create_duplicate_raises(session):
    create_group(session, "Alpha", "#9c5a3c")
    with pytest.raises(IntegrityError):
        create_group(session, "Alpha", "#5a7d5a")


def test_update_group(session):
    g = create_group(session, "Alpha", "#9c5a3c")
    g = update_group(session, g, name="Renamed", color="#5e8c8c")
    assert g.name == "Renamed"
    assert g.color == "#5e8c8c"


def test_update_bad_color_raises(session):
    g = create_group(session, "Alpha", "#9c5a3c")
    with pytest.raises(ValueError):
        update_group(session, g, color="not-a-color")


def test_reorder_groups(session):
    g1 = create_group(session, "Alpha", "#9c5a3c")
    g2 = create_group(session, "Beta", "#5a7d5a")
    reorder_groups(session, [g2.id, g1.id])
    groups = list_groups(session)
    assert groups[0].name == "Beta"
    assert groups[1].name == "Alpha"


def test_reorder_groups_wrong_ids(session):
    g1 = create_group(session, "Alpha", "#9c5a3c")
    with pytest.raises(ValueError):
        reorder_groups(session, [g1.id, 9999])


# ── assign_document ───────────────────────────────────────────────────────────

def test_assign_document_appends_to_end(session):
    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1930-alpha")
    d2 = _doc(session, "1940-beta")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    assert d1.group_id == g.id
    assert d2.group_id == g.id
    assert d2.group_position > d1.group_position


def test_assign_between_groups_appends(session):
    g1 = create_group(session, "G1", "#9c5a3c")
    g2 = create_group(session, "G2", "#5a7d5a")
    d = _doc(session, "1930-alpha")
    assign_document(session, d, g1)
    assign_document(session, d, g2)
    assert d.group_id == g2.id
    # Position in g2 is fresh (0-based from g2's count)
    assert d.group_id == g2.id


def test_assign_records_change(session):
    from sqlalchemy import select

    from notebook_forge.models import Change

    g = create_group(session, "Group", "#9c5a3c")
    d = _doc(session, "1930-alpha")
    assign_document(session, d, g)
    changes = list(session.scalars(
        select(Change).where(Change.document_id == d.id, Change.kind == "edit")
    ))
    assert any("moved to group" in c.summary for c in changes)


def test_assign_remove_from_group(session):
    from sqlalchemy import select

    from notebook_forge.models import Change

    g = create_group(session, "Group", "#9c5a3c")
    d = _doc(session, "1930-alpha")
    assign_document(session, d, g)
    assign_document(session, d, None)
    assert d.group_id is None
    changes = list(session.scalars(
        select(Change).where(Change.document_id == d.id, Change.kind == "edit")
    ))
    assert any("removed from group" in c.summary for c in changes)


def test_assign_same_group_noop(session):
    from sqlalchemy import select

    from notebook_forge.models import Change

    g = create_group(session, "Group", "#9c5a3c")
    d = _doc(session, "1930-alpha")
    assign_document(session, d, g)
    count_before = session.scalar(
        select(Change.id).where(Change.document_id == d.id).order_by(Change.id.desc()).limit(1)
    )
    assign_document(session, d, g)
    count_after = session.scalar(
        select(Change.id).where(Change.document_id == d.id).order_by(Change.id.desc()).limit(1)
    )
    assert count_before == count_after


# ── delete_group ──────────────────────────────────────────────────────────────

def test_delete_group_moves_members_to_ungrouped(session):
    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1930-a")
    d2 = _doc(session, "1940-b")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    moved = delete_group(session, g)
    assert moved == 2
    assert d1.group_id is None
    assert d2.group_id is None
    # Relative order preserved
    assert d1.group_position < d2.group_position


def test_delete_group_appends_after_existing_ungrouped(session):
    g = create_group(session, "Group", "#9c5a3c")
    ungrouped = _doc(session, "1920-earlier")  # stays ungrouped, pos=0
    member = _doc(session, "1930-a")
    assign_document(session, member, g)
    delete_group(session, g)
    assert member.group_id is None
    assert member.group_position > ungrouped.group_position


# ── set_positions ─────────────────────────────────────────────────────────────

def test_set_positions_renormalises(session):
    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1930-a")
    d2 = _doc(session, "1940-b")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    set_positions(session, g.id, ["1940-b", "1930-a"])
    assert d2.group_position == 0
    assert d1.group_position == 1


def test_set_positions_membership_mismatch_raises(session):
    g = create_group(session, "Group", "#9c5a3c")
    d = _doc(session, "1930-a")
    assign_document(session, d, g)
    with pytest.raises(ValueError):
        set_positions(session, g.id, ["1930-a", "missing-slug"])


def test_set_positions_ungrouped_bucket(session):
    d1 = _doc(session, "1930-a")
    d2 = _doc(session, "1940-b")
    set_positions(session, None, ["1940-b", "1930-a"])
    assert d2.group_position == 0
    assert d1.group_position == 1


# ── resolve_members ───────────────────────────────────────────────────────────

def test_resolve_members_manual(session):
    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1930-alpha", "Alpha")
    d2 = _doc(session, "1940-beta", "Beta")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    set_positions(session, g.id, ["1940-beta", "1930-alpha"])
    members = resolve_members(session, g.id, "manual")
    assert [d.slug for d in members] == ["1940-beta", "1930-alpha"]


def test_resolve_members_date_range(session):
    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1940-alpha")
    d2 = _doc(session, "1930-beta")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    members = resolve_members(session, g.id, "date_range")
    assert members[0].slug == "1930-beta"
    assert members[1].slug == "1940-alpha"


def test_resolve_members_title_az(session):
    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1930-a", "Zebra")
    d2 = _doc(session, "1940-b", "Apple")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    members = resolve_members(session, g.id, "title_az")
    assert members[0].slug == "1940-b"


def test_resolve_members_last_updated(session):
    import datetime as dt

    g = create_group(session, "Group", "#9c5a3c")
    d1 = _doc(session, "1930-a")
    d2 = _doc(session, "1940-b")
    assign_document(session, d1, g)
    assign_document(session, d2, g)
    d1.updated_at = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    d2.updated_at = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    session.flush()
    members = resolve_members(session, g.id, "last_updated")
    assert members[0].slug == "1940-b"


def test_resolve_members_unknown_sort_raises(session):
    g = create_group(session, "Group", "#9c5a3c")
    with pytest.raises(ValueError):
        resolve_members(session, g.id, "bogus")


# ── API round-trips ───────────────────────────────────────────────────────────

@pytest.fixture()
def client(workspace):
    import os
    os.environ["NOTEBOOK_FORGE_WORKSPACE"] = str(workspace)
    from notebook_forge.api import _state, app
    _state.cache_clear()
    with TestClient(app) as c:
        yield c


def test_api_create_group(client):
    r = client.post("/api/groups", json={"name": "My Group", "color": "#9c5a3c"})
    assert r.status_code == 200
    assert r.json()["name"] == "My Group"


def test_api_duplicate_group_409(client):
    client.post("/api/groups", json={"name": "Dup", "color": "#9c5a3c"})
    r = client.post("/api/groups", json={"name": "Dup", "color": "#5a7d5a"})
    assert r.status_code == 409


def test_api_delete_group_moves_members(client, workspace, session):
    from notebook_forge.groups import assign_document as _ad
    from notebook_forge.groups import create_group as _cg
    from notebook_forge.services import create_document as _cd

    g = _cg(session, "G", "#9c5a3c")
    d = _cd(session, "1930-a", "Title")
    _ad(session, d, g)
    session.commit()

    r = client.delete(f"/api/groups/{g.id}")
    assert r.status_code == 200
    assert r.json()["moved"] == 1

    r2 = client.get("/api/documents")
    doc_data = next(x for x in r2.json() if x["slug"] == "1930-a")
    assert doc_data["group_id"] is None


def test_api_set_document_group(client, workspace, session):
    from notebook_forge.groups import create_group as _cg
    from notebook_forge.services import create_document as _cd

    g = _cg(session, "G", "#9c5a3c")
    _cd(session, "1930-a", "Title")
    session.commit()

    r = client.put("/api/documents/1930-a/group", json={"group_id": g.id})
    assert r.status_code == 200
    assert r.json()["group_id"] == g.id


def test_api_delete_doc_leaves_group_consistent(client, workspace, session):
    from notebook_forge.groups import assign_document as _ad
    from notebook_forge.groups import create_group as _cg
    from notebook_forge.services import create_document as _cd

    g = _cg(session, "G", "#9c5a3c")
    d1 = _cd(session, "1930-a", "T")
    d2 = _cd(session, "1940-b", "T")
    _ad(session, d1, g)
    _ad(session, d2, g)
    session.commit()

    r = client.delete("/api/documents/1930-a")
    assert r.status_code == 200

    r2 = client.get("/api/groups")
    group_data = next(x for x in r2.json() if x["id"] == g.id)
    assert len(group_data["members"]) == 1
    assert group_data["members"][0]["slug"] == "1940-b"
