"""Tests for reimport.py — all 8 cases from REIMPORT_PLAN.md §4.

Fixture strategy: synthetic PNG bytes generated in-test, a fake ManifestInfo
built from those bytes, and a real SQLite workspace via the shared conftest
fixtures. No Gemini API key needed anywhere.

Tests 1-6: test seed_sketches directly (no real MemoirForge data required).
Test 7: find_memoir_manifest exclusion (fake temp manifest).
Test 8: dry_run no-write guarantee (needs MemoirForge work data).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.assets import asset_path, ingest_file, sha256_file
from notebook_forge.blocks import FORGE_IMAGE, make_block
from notebook_forge.reimport import (
    EXCLUDED_STEMS,
    FigureInfo,
    ManifestInfo,
    dry_run,
    find_memoir_manifest,
    seed_sketches,
)
from notebook_forge.sketch import SILHOUETTE_PROMPT, SKETCH_MODEL
from notebook_forge.sketch_gen import GeminiSketchGenerator, cache_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MF_WORK = Path("/Users/cs/ClaudeCode/MemoirForge/work")
MF_MANIFEST_DIR = Path("/Users/cs/ClaudeCode/MemoirForge/out")

needs_mf = pytest.mark.skipif(
    not MF_MANIFEST_DIR.exists(),
    reason="MemoirForge data not present",
)


def png_bytes(color: tuple = (200, 200, 200), size: tuple = (8, 8)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def make_figure_info(
    source_sha256: str,
    silhouette_file: Path,
    *,
    n: str = "1",
    caption: str = "Test caption.",
    included: bool = True,
    use_original: bool = False,
    prompt_override: str = "",
    silhouette_model: str = SKETCH_MODEL,
    silhouette_approved: bool = True,
) -> FigureInfo:
    return FigureInfo(
        n=n,
        anchor=f"figure-{n}",
        source_sha256=source_sha256,
        caption=caption,
        included=included,
        use_original=use_original,
        prompt_override=prompt_override,
        silhouette_file=silhouette_file,
        silhouette_file_raw=str(silhouette_file),
        silhouette_model=silhouette_model,
        silhouette_approved=silhouette_approved,
    )


def make_manifest(figures: list[FigureInfo]) -> ManifestInfo:
    return ManifestInfo(
        stem="test-doc",
        source_file="test.pdf",
        source_path=None,
        figures=figures,
        figures_by_hash={f.source_sha256: f for f in figures if f.source_sha256},
    )


def make_doc_with_figures(
    session: Session,
    workspace: Path,
    original_bytes_list: list[bytes],
    slug: str = "test-doc",
) -> tuple:
    """Create a document with one forgeImage block per original image.
    Returns (doc, [assetId, ...]).
    """
    asset_ids = []
    blocks = []
    for i, orig in enumerate(original_bytes_list):
        tmp = workspace / f"_tmp_orig_{i}.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(orig)
        asset = ingest_file(session, workspace, tmp, "originals")
        tmp.unlink()
        asset_ids.append(asset.sha256)
        blocks.append(make_block(FORGE_IMAGE, {
            "assetId": asset.sha256,
            "sketchAssetId": "",
            "caption": "",
            "altText": "",
            "approval": "pending",
            "displayWidth": "full",
        }))

    doc = services.create_document(session, slug=slug, title="Test", blocks=blocks)
    session.flush()
    return doc, asset_ids


# ---------------------------------------------------------------------------
# Test 1: hash matching → sketchAssetId, approval "approved", manifest caption
# ---------------------------------------------------------------------------

def test_seed_matched_figure_sets_sketch_and_approved(
    workspace: Path, session: Session, tmp_path: Path
) -> None:
    orig = png_bytes((10, 20, 30))
    sketch = png_bytes((200, 200, 200))
    sil_file = tmp_path / "sketch1.png"
    sil_file.write_bytes(sketch)

    doc, [asset_id] = make_doc_with_figures(session, workspace, [orig])
    assert asset_id == sha256_file(workspace / "assets" / "originals" / f"{asset_id}.png")

    fig = make_figure_info(
        source_sha256=asset_id,
        silhouette_file=sil_file,
        caption="Baby Junior.",
        silhouette_approved=True,
    )
    manifest = make_manifest([fig])
    result = seed_sketches(session, workspace, doc, manifest)
    session.flush()

    assert result["seeded"] == 1
    assert result["unmatched"] == []

    block = next(b for b in doc.blocks if b["type"] == FORGE_IMAGE)
    props = block["props"]
    assert props["sketchAssetId"] != ""
    assert props["approval"] == "approved"
    assert props["caption"] == "Baby Junior."
    assert props["altText"] == "Baby Junior."

    # Sketch bytes landed in the asset store.
    sketch_asset = session.get(
        __import__("notebook_forge.models", fromlist=["Asset"]).Asset,
        props["sketchAssetId"],
    )
    assert sketch_asset is not None
    assert sketch_asset.kind == "sketches"
    assert asset_path(workspace, sketch_asset).read_bytes() == sketch


# ---------------------------------------------------------------------------
# Test 2: props mapping — included/use_original/unapproved
# ---------------------------------------------------------------------------

def test_seed_props_mapping(workspace: Path, session: Session, tmp_path: Path) -> None:
    origs = [png_bytes((i, i, i)) for i in (10, 20, 30)]
    doc, asset_ids = make_doc_with_figures(session, workspace, origs)

    def sil(i: int) -> Path:
        p = tmp_path / f"sil{i}.png"
        p.write_bytes(png_bytes((100 + i, 100, 100)))
        return p

    figs = [
        make_figure_info(
            asset_ids[0], sil(0), n="1",
            included=False, silhouette_approved=True,
        ),
        make_figure_info(
            asset_ids[1], sil(1), n="2",
            use_original=True, silhouette_approved=True,
        ),
        make_figure_info(
            asset_ids[2], sil(2), n="3",
            silhouette_approved=False,
        ),
    ]
    manifest = make_manifest(figs)
    result = seed_sketches(session, workspace, doc, manifest)
    session.flush()

    assert result["seeded"] == 3

    fig_blocks = [b for b in doc.blocks if b["type"] == FORGE_IMAGE]
    props = {b["props"]["assetId"]: b["props"] for b in fig_blocks}

    assert props[asset_ids[0]]["safeMode"] == "omit"
    assert props[asset_ids[1]]["safeMode"] == "original"
    assert props[asset_ids[2]]["approval"] == "pending"
    assert props[asset_ids[0]]["approval"] == "approved"


# ---------------------------------------------------------------------------
# Test 3: unmatched figure leaves block untouched and is reported
# ---------------------------------------------------------------------------

def test_seed_unmatched_figure_is_reported(
    workspace: Path, session: Session, tmp_path: Path
) -> None:
    orig = png_bytes((50, 50, 50))
    doc, [asset_id] = make_doc_with_figures(session, workspace, [orig])

    # Manifest has a different hash — no match.
    sil_file = tmp_path / "sil.png"
    sil_file.write_bytes(png_bytes())
    fig = make_figure_info(source_sha256="a" * 64, silhouette_file=sil_file)
    manifest = make_manifest([fig])

    result = seed_sketches(session, workspace, doc, manifest)

    assert result["seeded"] == 0
    assert len(result["unmatched"]) == 1
    block = next(b for b in doc.blocks if b["type"] == FORGE_IMAGE)
    assert block["props"]["sketchAssetId"] == ""
    assert block["props"]["approval"] == "pending"


# ---------------------------------------------------------------------------
# Test 4: cache seeding — subsequent GeminiSketchGenerator hits without API
# ---------------------------------------------------------------------------

def test_seed_cache_seeded_and_generator_hits_without_api(
    workspace: Path, session: Session, tmp_path: Path
) -> None:
    orig = png_bytes((77, 77, 77))
    sketch = png_bytes((180, 180, 180))
    sil_file = tmp_path / "sketch.png"
    sil_file.write_bytes(sketch)

    doc, [asset_id] = make_doc_with_figures(session, workspace, [orig])
    fig = make_figure_info(
        source_sha256=asset_id,
        silhouette_file=sil_file,
        silhouette_model=SKETCH_MODEL,
        prompt_override="",
    )
    manifest = make_manifest([fig])

    result = seed_sketches(session, workspace, doc, manifest)
    session.flush()

    assert result["cache_seeded"] == 1

    # Verify the cache file exists at the exact key the generator would look up.
    orig_bytes = orig
    key = cache_key(orig_bytes, SILHOUETTE_PROMPT, SKETCH_MODEL)
    cache_file = workspace / "sketch-cache" / f"{key}.png"
    assert cache_file.exists()
    assert cache_file.read_bytes() == sketch

    # Generator with a poisoned _call_gemini returns the cached bytes.
    def _poison(*a, **kw):  # noqa: ANN202
        raise RuntimeError("Gemini must not be called — cache should hit")

    gen = GeminiSketchGenerator("fake-key", workspace / "sketch-cache")
    gen._call_gemini = _poison  # type: ignore[method-assign]

    res = gen.generate(orig_bytes, "image/png")
    assert res.image_bytes == sketch
    assert gen.last_gate.attempts == 0  # cache hit, no generation


# ---------------------------------------------------------------------------
# Test 5: existing figure work survives re-import (precedence)
# ---------------------------------------------------------------------------

def test_seed_existing_sketch_not_overwritten(
    workspace: Path, session: Session, tmp_path: Path
) -> None:
    orig = png_bytes((90, 90, 90))
    existing_sketch = png_bytes((1, 2, 3))
    manifest_sketch = png_bytes((4, 5, 6))

    # Set up a doc where the figure already has a sketch.
    doc, [asset_id] = make_doc_with_figures(session, workspace, [orig])

    existing_sil = tmp_path / "existing.png"
    existing_sil.write_bytes(existing_sketch)
    existing_asset = ingest_file(session, workspace, existing_sil, "sketches")
    session.flush()

    # Patch the block directly to simulate prior seeding.
    blocks = [dict(b) for b in doc.blocks]
    for b in blocks:
        if b["type"] == FORGE_IMAGE:
            b["props"]["sketchAssetId"] = existing_asset.sha256
            b["props"]["approval"] = "approved"
    services.save_blocks(session, doc, blocks)
    session.flush()

    # Manifest points to a different sketch.
    manifest_sil = tmp_path / "manifest.png"
    manifest_sil.write_bytes(manifest_sketch)
    fig = make_figure_info(
        source_sha256=asset_id, silhouette_file=manifest_sil, caption="New caption"
    )
    manifest = make_manifest([fig])

    result = seed_sketches(session, workspace, doc, manifest)

    # Existing sketch should survive — seeded == 0.
    assert result["seeded"] == 0
    block = next(b for b in doc.blocks if b["type"] == FORGE_IMAGE)
    assert block["props"]["sketchAssetId"] == existing_asset.sha256


# ---------------------------------------------------------------------------
# Test 6: missing silhouette file — figure reported, other figures continue
# ---------------------------------------------------------------------------

def test_seed_missing_silhouette_reported_and_continues(
    workspace: Path, session: Session, tmp_path: Path
) -> None:
    origs = [png_bytes((i * 10, 0, 0)) for i in (1, 2)]
    doc, asset_ids = make_doc_with_figures(session, workspace, origs)

    # Figure 1: silhouette file is missing.
    fig1 = make_figure_info(
        asset_ids[0], silhouette_file=None, n="1",
        silhouette_approved=True,
    )
    # Override silhouette_file_raw to simulate "was in manifest but file gone".
    fig1.silhouette_file_raw = "/nonexistent/path.png"
    fig1.silhouette_file = None  # confirmed missing

    # Figure 2: silhouette present.
    sil2 = tmp_path / "sil2.png"
    sil2.write_bytes(png_bytes((100, 100, 100)))
    fig2 = make_figure_info(asset_ids[1], silhouette_file=sil2, n="2")

    manifest = make_manifest([fig1, fig2])
    result = seed_sketches(session, workspace, doc, manifest)

    assert result["seeded"] == 1
    assert len(result["missing_silhouettes"]) == 1
    assert result["missing_silhouettes"][0]["n"] == "1"

    blocks_by_asset = {
        b["props"]["assetId"]: b["props"]
        for b in doc.blocks if b["type"] == FORGE_IMAGE
    }
    assert blocks_by_asset[asset_ids[0]]["sketchAssetId"] == ""  # not seeded
    assert blocks_by_asset[asset_ids[1]]["sketchAssetId"] != ""  # seeded


# ---------------------------------------------------------------------------
# Test 7: excluded stem refused by find_memoir_manifest and CLI
# ---------------------------------------------------------------------------

def test_excluded_stem_refused(tmp_path: Path) -> None:
    excluded = "1942-1954_national-service"
    assert excluded in EXCLUDED_STEMS

    # find_memoir_manifest raises for the excluded stem.
    with pytest.raises(LookupError, match="national-service"):
        find_memoir_manifest(excluded, mf_root=tmp_path)

    # A manifest that happens to be present doesn't override the exclusion.
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    (out_dir / f"{excluded}.manifest.json").write_text(
        json.dumps({"stem": excluded, "session_id": "x", "source_file": "f.pdf", "figures": []})
    )
    with pytest.raises(LookupError, match="national-service"):
        find_memoir_manifest(excluded, mf_root=tmp_path)


def test_excluded_stem_refused_by_cli(monkeypatch) -> None:  # noqa: ANN001
    from notebook_forge.cli import main

    ret = main(["reimport", "1942-1954_national-service"])
    assert ret == 1


# ---------------------------------------------------------------------------
# Test 8: dry-run leaves DB row counts and workspace tree untouched
# ---------------------------------------------------------------------------

@needs_mf
def test_dry_run_leaves_db_and_workspace_untouched(
    workspace: Path, session: Session
) -> None:
    from sqlalchemy import text

    # Snapshot DB state before.
    doc_count_before = session.execute(text("SELECT count(*) FROM documents")).scalar()
    asset_count_before = session.execute(text("SELECT count(*) FROM assets")).scalar()

    ws_files_before = set(workspace.rglob("*")) if workspace.exists() else set()

    # Run dry_run on Junior (9 figures, fast).
    report = dry_run("1934-1945_junior")

    # DB is unchanged.
    doc_count_after = session.execute(text("SELECT count(*) FROM documents")).scalar()
    asset_count_after = session.execute(text("SELECT count(*) FROM assets")).scalar()
    assert doc_count_after == doc_count_before
    assert asset_count_after == asset_count_before

    # Workspace tree is unchanged.
    ws_files_after = set(workspace.rglob("*")) if workspace.exists() else set()
    assert ws_files_after == ws_files_before

    # Report structure is sound.
    assert report["slug"] == "1934-1945_junior"
    assert report["figures_extracted"] > 0
    assert "match_rate" in report
    assert "unmatched" in report
    assert "missing_silhouettes" in report


# ---------------------------------------------------------------------------
# Bonus: verify dry_run match rates on all keeper memoirs
# ---------------------------------------------------------------------------

@needs_mf
@pytest.mark.parametrize("slug", [
    "1934-1945_junior",
    "1945-1955_the-years-between",
    "1953-1954_in-the-navy",
    "1955-1962_the-army-years-part-1-the-young-soldier-surveyor",
    "1961-1969_the-army-years-part-2-being-an-officer",
    "1969-1972_the-army-year-part-3-singapore",
    "1971-1975_the-army-years-part-4-now-a-major",
])
def test_dry_run_match_rate_full(slug: str) -> None:
    report = dry_run(slug)
    total = report["figures_extracted"]
    matched = report["matched"]
    assert total > 0, f"{slug}: no figures extracted"
    assert matched == total, (
        f"{slug}: {matched}/{total} matched — see unmatched: {report['unmatched']}"
    )
