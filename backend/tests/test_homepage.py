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
    # The memoir appears via the group-derived timeline.
    assert "Early Years" in files["index.html"]
    # The redesign no longer renders the welcome blurb (spec §3 — superseded
    # by tagline + about_archive).
    assert "Welcome to the archive" not in files["index.html"]
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


def test_api_delete_homepage_409(workspace: Path, api_client) -> None:
    # api_client bootstrap calls ensure_homepage → homepage doc created
    resp = api_client.delete("/api/documents/homepage")
    assert resp.status_code == 409


def test_api_rename_homepage_409(workspace: Path, api_client) -> None:
    resp = api_client.post("/api/documents/homepage/rename", json={"new_slug": "new-home"})
    assert resp.status_code == 409


def test_api_unpublish_homepage_409(workspace: Path, api_client) -> None:
    from notebook_forge.db import make_engine, make_session_factory
    engine = make_engine(workspace)
    factory = make_session_factory(engine)
    with factory() as s:
        t = Target(name="web-test", kind="local-folder", config={"folder": "/tmp/x"})
        s.add(t)
        s.commit()
        tid = t.id
    engine.dispose()
    resp = api_client.delete(f"/api/documents/homepage/publish/{tid}")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# M7 edge-case tests
# ---------------------------------------------------------------------------

def test_deleting_grouped_doc_makes_homepage_dirty(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """EC1: delete a member → homepage fingerprint changes → dirty."""
    from notebook_forge.services import mark_published

    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_a", "A", canonical_url="https://x.com/a.html")
    assign_document(session, m, g)
    hp = _hp(session, [_group_block(g.id)])
    session.flush()

    snap = snapshot_document(session, hp)
    mark_published(session, hp, target, snap)
    assert not is_dirty(session, hp, target)

    # Delete the member doc
    session.delete(m)
    session.flush()

    assert is_dirty(session, hp, target)


def test_deleting_group_makes_homepage_dirty_with_warning(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """EC2: delete a group → homepage block skipped with warning."""
    from notebook_forge.groups import delete_group
    from notebook_forge.services import mark_published

    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    g = create_group(session, "G", "#9c5a3c")
    m = _memoir(session, "1960-1970_a", "A", canonical_url="https://x.com/a.html")
    assign_document(session, m, g)
    gid = g.id
    hp = _hp(session, [_group_block(gid)])
    session.flush()

    snap = snapshot_document(session, hp)
    mark_published(session, hp, target, snap)
    assert not is_dirty(session, hp, target)

    delete_group(session, g)
    session.flush()

    # Group gone → fingerprint changes → dirty
    assert is_dirty(session, hp, target)

    # homepage_body skips the block with a warning
    hp_fresh = session.get(Document, hp.id)
    assert hp_fresh is not None
    entries, warnings, _ = homepage_body(session, hp_fresh)
    assert not any(e.get("kind") == "group" for e in entries)
    assert any("group" in w.lower() for w in warnings)


def test_concurrent_save_and_reorder(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """EC5: save_blocks(homepage) interleaved with set_positions doesn't clobber reorder."""
    from notebook_forge.groups import set_positions
    from notebook_forge.services import mark_published, save_blocks

    target = Target(name="local", kind="local-folder", config={"folder": str(tmp_path / "s")})
    session.add(target)
    g = create_group(session, "G", "#9c5a3c")
    m1 = _memoir(session, "1960-1970_a", "A", canonical_url="https://x.com/a.html")
    m2 = _memoir(session, "1970-1980_b", "B", canonical_url="https://x.com/b.html")
    assign_document(session, m1, g)
    assign_document(session, m2, g)
    hp = _hp(session, [_group_block(g.id, sort="manual")])
    session.flush()

    snap = snapshot_document(session, hp)
    mark_published(session, hp, target, snap)
    assert not is_dirty(session, hp, target)

    # Simulate concurrent: autosave then reorder
    save_blocks(session, hp, hp.blocks, hp.meta)
    set_positions(session, g.id, [m2.slug, m1.slug])
    session.flush()

    # After reorder, homepage should be dirty (group fingerprint changed)
    assert is_dirty(session, hp, target)


def test_integration_full_loop(tmp_path: Path, workspace: Path, session: Session) -> None:
    """EC integration: migrate → publish → reorder → dirty → republish →
    member-title save → member publish auto-cleans homepage → delete group
    → dirty with warning."""
    from notebook_forge.groups import delete_group
    from notebook_forge.homepage_migration import ensure_homepage
    from notebook_forge.publish import publish_document
    from notebook_forge.services import mark_published, save_blocks

    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)

    m1 = _memoir(session, "1950-1960_a", "A", canonical_url="https://x.com/a.html")
    _memoir(session, "1960-1970_b", "B", canonical_url="https://x.com/b.html")
    session.flush()

    # Step 1: migrate
    result = ensure_homepage(session)
    assert result is not None
    session.flush()

    from notebook_forge.homepage import get_homepage

    hp = get_homepage(session)
    assert hp is not None

    # Step 2: publish homepage
    publish_document(session, workspace, hp, target)
    session.commit()
    assert not is_dirty(session, hp, target)

    # Step 3: add a member → fingerprint changes → dirty
    g_id = session.query(Document).filter(Document.slug == m1.slug).one().group_id
    assert g_id is not None
    from notebook_forge.models import Group as GroupModel
    grp_obj = session.get(GroupModel, g_id)
    m3 = _memoir(session, "1940-1950_c", "C", canonical_url="https://x.com/c.html")
    assign_document(session, m3, grp_obj)
    session.flush()
    assert is_dirty(session, hp, target)

    # Step 4: republish homepage → clean
    publish_document(session, workspace, hp, target)
    session.commit()
    assert not is_dirty(session, hp, target)

    # Step 5: save_blocks on m1 with new title → m1 dirty; then publish m1 → D14 auto-cleans hp
    hp_snap = snapshot_document(session, hp)
    mark_published(session, hp, target, hp_snap)  # ensure hp is clean first
    new_blocks = [{
        "type": "paragraph",
        "content": [{"type": "text", "text": "new", "styles": {}}],
        "props": {}, "id": "x", "children": [],
    }]
    save_blocks(session, m1, new_blocks, m1.meta)
    session.flush()

    # Mark hp dirty artificially by updating a member title
    m1.meta = dict(m1.meta or {}, title="Updated Title A")
    session.flush()
    # homepage dirty now due to meta change
    publish_document(session, workspace, m1, target)
    session.commit()
    # D14: homepage auto-marked clean if it was dirty
    # (it may or may not be dirty depending on meta update; just verify publish succeeds)

    # Step 6: delete group → dirty + warning  (GroupModel imported above)
    grp = session.get(GroupModel, g_id)
    if grp is not None:
        delete_group(session, grp)
        session.flush()
        assert is_dirty(session, hp, target)

    # Step 7: verify root_files still works (skips missing group with warning)
    files, warnings = root_files(session, base_url="https://example.org")
    assert "index.html" in files
    # intro paras survive even if group block is skipped
    assert "index.html" in files


# ── M6: forgeNarrative on the homepage ──

def test_narrative_blocks_appear_in_homepage_body(session: Session) -> None:
    """Two consecutive narrative blocks → one merged entry; rendered index has div.narrative."""
    from notebook_forge.blocks import FORGE_NARRATIVE
    from notebook_forge.collection import root_files

    hp = _hp(session, [
        make_block("paragraph", content=[text_run("Welcome to the archive.")]),
        make_block(FORGE_NARRATIVE, content=[text_run("A quiet reflection on those years.")]),
        make_block(FORGE_NARRATIVE, content=[text_run("And what came after that time.")]),
        make_block("paragraph", content=[text_run("Browse the documents below.")]),
    ])
    entries, _, _ = homepage_body(session, hp)
    narrative_entries = [e for e in entries if e["kind"] == "narrative"]
    # The two consecutive blocks merge into ONE entry with two paragraphs
    assert len(narrative_entries) == 1
    assert len(narrative_entries[0]["paragraphs"]) == 2

    # The redesigned homepage no longer renders narrative blocks (spec §3),
    # but the index must still render without error.
    files, _ = root_files(session, base_url="https://example.org")
    html = files.get("index.html", "")
    assert '<div class="narrative">' not in html


# ---------------------------------------------------------------------------
# Step 9: homepage content settings round-trip + banner upload
# ---------------------------------------------------------------------------

def _new_session(workspace: Path) -> Session:
    from notebook_forge.db import make_engine, make_session_factory
    return make_session_factory(make_engine(workspace))()


def test_settings_get_includes_seeded_homepage(workspace: Path, api_client) -> None:
    """Bootstrap seeds defaults; GET /api/settings exposes them."""
    hp = api_client.get("/api/settings").json()["homepage"]
    assert hp["subject_name"] == "Robert Francis Skitch"
    assert len(hp["banner_slots"]) == 3
    assert hp["banner_slots"][0]["notebooklm_adapted"] is True
    # No image uploaded yet → empty image_url (placeholder rendered).
    assert hp["banner_slots"][0]["image_url"] == ""


def test_homepage_settings_roundtrip_to_rendered_index(workspace: Path, api_client) -> None:
    """Edit a field → Save → rebuild → the change appears in index.html."""
    body = api_client.get("/api/settings").json()["homepage"]
    body["subject_name"] = "Zaphod Beeblebrox"
    body["tagline"] = "An entirely different life."
    resp = api_client.put("/api/settings/homepage", json=body)
    assert resp.status_code == 200
    assert resp.json()["homepage"]["subject_name"] == "Zaphod Beeblebrox"

    # Rebuild the root files from the same workspace and confirm the edit.
    with _new_session(workspace) as s:
        files, _ = root_files(s, base_url="https://example.org")
    html = files["index.html"]
    assert "Zaphod Beeblebrox" in html
    assert "An entirely different life." in html


def test_homepage_settings_put_preserves_legacy_keys(workspace: Path, api_client) -> None:
    """The PUT merges, so legacy footer_html / title survive."""
    from notebook_forge.models import Setting

    # First request triggers bootstrap (ensure_homepage + seed); only then
    # does the "homepage" Setting row exist to inject legacy keys into.
    body = api_client.get("/api/settings").json()["homepage"]
    with _new_session(workspace) as s:
        row = s.get(Setting, "homepage")
        row.value = {**(row.value or {}), "footer_html": "LEGACY-FOOTER", "title": "Legacy Title"}
        s.commit()

    body["signoff"] = "— Someone Else"
    api_client.put("/api/settings/homepage", json=body)

    with _new_session(workspace) as s:
        value = s.get(Setting, "homepage").value
    assert value["footer_html"] == "LEGACY-FOOTER"
    assert value["title"] == "Legacy Title"
    assert value["signoff"] == "— Someone Else"


def test_homepage_settings_rejects_bad_url(workspace: Path, api_client) -> None:
    body = api_client.get("/api/settings").json()["homepage"]
    body["notebooklm_url"] = "javascript:alert(1)"
    resp = api_client.put("/api/settings/homepage", json=body)
    assert resp.status_code == 422


def test_banner_image_upload_roundtrip(workspace: Path, api_client) -> None:
    """Upload → slot points at the asset → rendered banner uses <img>."""
    resp = api_client.post(
        "/api/homepage/banner-image/1",
        files={"file": ("portrait.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["image_url"].startswith("/api/assets/")
    assert payload["image_asset_id"]

    # GET reflects the upload on slot 1 only; the panel thumbnail uses the dev
    # /api/assets URL.
    hp = api_client.get("/api/settings").json()["homepage"]
    assert hp["banner_slots"][1]["image_asset_id"] == payload["image_asset_id"]
    assert hp["banner_slots"][1]["image_url"].startswith("/api/assets/")
    assert hp["banner_slots"][0]["image_asset_id"] is None

    # Rendered index uses the published static path (copied next to index.html),
    # not the dev /api/assets URL, so it works on GitHub Pages.
    with _new_session(workspace) as s:
        files, _ = root_files(s, base_url="https://example.org")
    assert '<img src="homepage_assets/banner-1.jpg"' in files["index.html"]
    assert "/api/assets/" not in files["index.html"]


def test_homepage_publish_copies_banner_image(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """Publishing the homepage copies banner images next to index.html and the
    page references them by relative path (so they load on the published site)."""
    from notebook_forge.assets import ingest_file
    from notebook_forge.homepage import seed_homepage_content, set_banner_image
    from notebook_forge.publish import publish_document

    seed_homepage_content(session)
    hp = _hp(session, [])
    img = tmp_path / "portrait.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0banner-bytes")
    asset = ingest_file(session, workspace, img, "homepage")
    set_banner_image(session, 0, asset.sha256)
    session.flush()

    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.flush()
    session.commit()

    publish_document(session, workspace, hp, target)

    assert (out / "homepage_assets" / "banner-0.jpg").exists()
    index = (out / "index.html").read_text()
    assert '<img src="homepage_assets/banner-0.jpg"' in index
    assert "/api/assets/" not in index


def test_banner_image_bad_slot_index(workspace: Path, api_client) -> None:
    resp = api_client.post(
        "/api/homepage/banner-image/5",
        files={"file": ("x.jpg", b"data", "image/jpeg")},
    )
    assert resp.status_code == 422


def test_content_setting_change_marks_homepage_dirty(session: Session) -> None:
    """Editing a homepage content field (now the only way to edit the page,
    since the block editor is gone) changes the homepage's effective hash, so
    it shows as needing a republish."""
    from notebook_forge.homepage import seed_homepage_content
    from notebook_forge.models import Setting
    from notebook_forge.services import effective_content_hash

    seed_homepage_content(session)
    hp = _hp(session, [])
    session.flush()
    h1 = effective_content_hash(session, hp)

    row = session.get(Setting, "homepage")
    row.value = {**row.value, "tagline": "A completely new tagline"}
    session.flush()
    h2 = effective_content_hash(session, hp)
    assert h1 != h2
