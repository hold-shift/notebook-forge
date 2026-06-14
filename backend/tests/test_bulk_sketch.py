"""Tests for bulk sketch generation: eligibility rule + endpoints."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from notebook_forge.sketch_service import eligible_figure_block_ids

# ---------------------------------------------------------------------------
# Eligibility rule unit tests
# ---------------------------------------------------------------------------


def _img(  # noqa: PLR0913
    block_id: str,
    asset_id: str = "sha1",
    sketch_id: str = "",
    approval: str = "pending",
) -> dict:
    return {
        "id": block_id,
        "type": "forgeImage",
        "props": {
            "assetId": asset_id,
            "sketchAssetId": sketch_id,
            "approval": approval,
        },
    }


def test_eligible_includes_no_sketch() -> None:
    blocks = [_img("b1", asset_id="sha1", sketch_id="", approval="pending")]
    assert eligible_figure_block_ids(blocks) == ["b1"]


def test_eligible_includes_unapproved_sketch() -> None:
    """Pending sketch: still eligible (not yet approved)."""
    blocks = [_img("b1", asset_id="sha1", sketch_id="sketch_sha", approval="pending")]
    assert eligible_figure_block_ids(blocks) == ["b1"]


def test_eligible_excludes_approved_sketch() -> None:
    """Approved sketch must NOT be overwritten."""
    blocks = [_img("b1", asset_id="sha1", sketch_id="sketch_sha", approval="approved")]
    assert eligible_figure_block_ids(blocks) == []


def test_eligible_excludes_no_asset() -> None:
    """Block without an original photo is not eligible."""
    blocks = [_img("b1", asset_id="", sketch_id="", approval="pending")]
    assert eligible_figure_block_ids(blocks) == []


def test_eligible_mixed_set() -> None:
    blocks = [
        _img("approved", asset_id="sha1", sketch_id="sk1", approval="approved"),
        _img("no_sketch", asset_id="sha2", sketch_id="", approval="pending"),
        _img("pending_sketch", asset_id="sha3", sketch_id="sk3", approval="pending"),
        _img("no_asset", asset_id="", sketch_id="", approval="pending"),
    ]
    assert eligible_figure_block_ids(blocks) == ["no_sketch", "pending_sketch"]


def test_eligible_ignores_non_image_blocks() -> None:
    blocks = [
        {"id": "p1", "type": "paragraph", "props": {}, "content": []},
        _img("b1", asset_id="sha1"),
    ]
    assert eligible_figure_block_ids(blocks) == ["b1"]


# ---------------------------------------------------------------------------
# API endpoint tests (using FastAPI TestClient + monkeypatching)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with patched _state() pointing at a real workspace."""
    from notebook_forge.api import app  # noqa: PLC0415
    from notebook_forge.db import make_engine, make_session_factory  # noqa: PLC0415
    from notebook_forge.models import Document  # noqa: PLC0415

    ws = tmp_path / "ws"
    engine = make_engine(ws)
    factory = make_session_factory(engine)

    with factory() as s:
        doc = Document(
            slug="testdoc",
            title="Test",
            blocks=[
                _img("fig1", asset_id="sha_a", sketch_id="", approval="pending"),
                _img("fig2", asset_id="sha_b", sketch_id="sk_b", approval="approved"),
                _img("fig3", asset_id="sha_c", sketch_id="sk_c", approval="pending"),
            ],
        )
        s.add(doc)
        s.commit()

    state = {"workspace": ws, "engine": engine, "factory": factory}
    monkeypatch.setattr("notebook_forge.api._state", lambda: state)

    return TestClient(app)


def test_generate_all_returns_job_id_and_eligible_count(client) -> None:
    resp = client.post("/api/documents/testdoc/figures/generate-all-sketches")
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["eligible"] == 2  # fig1 + fig3 (fig2 is approved)


def test_generate_all_rejects_unknown_face_gate(client) -> None:
    resp = client.post(
        "/api/documents/testdoc/figures/generate-all-sketches",
        json={"batch_face_gate": "explode"},
    )
    assert resp.status_code == 422


def test_status_endpoint_completes(client) -> None:
    """Job runs to 'done' even when generate fails (assets are missing in the
    test workspace).  The important invariant is that done == total."""
    resp = client.post("/api/documents/testdoc/figures/generate-all-sketches")
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status_resp = None
    for _ in range(50):
        status_resp = client.get(
            f"/api/documents/testdoc/figures/generate-all-sketches/status?job_id={job_id}"
        )
        assert status_resp.status_code == 200
        if status_resp.json()["status"] == "done":
            break
        time.sleep(0.1)

    data = status_resp.json()
    assert data["status"] == "done"
    assert data["total"] == 2
    # All eligible blocks attempted (either ok or failed)
    assert data["done"] == 2


def test_status_404_for_unknown_job(client) -> None:
    resp = client.get(
        "/api/documents/testdoc/figures/generate-all-sketches/status?job_id=notreal"
    )
    assert resp.status_code == 404


def test_generate_all_404_for_unknown_doc(client) -> None:
    resp = client.post("/api/documents/ghost/figures/generate-all-sketches")
    assert resp.status_code == 404
