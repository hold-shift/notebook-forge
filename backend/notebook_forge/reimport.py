"""Re-import selected documents from their original DOCX/PDF sources,
reusing every already-generated sketch from MemoirForge — zero Gemini calls.

Operator migration tool; CLI-only. No API route, no frontend.

Flow:
  dry_run(slug)        — extract + hash-match against manifest; no writes.
  seed_sketches(...)   — attach manifest sketches to an existing doc.
  reimport_document()  — adopt source → reingest text → seed sketches.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from . import services
from .assets import asset_path, ingest_file, sha256_file
from .blocks import FORGE_IMAGE
from .models import Asset, Document
from .sketch_gen import cache_key

MF_ROOT = Path("/Users/cs/ClaudeCode/MemoirForge")
EXCLUDED_STEMS = frozenset({"1942-1954_national-service"})


@dataclass
class FigureInfo:
    n: str
    anchor: str
    source_sha256: str
    caption: str
    included: bool
    use_original: bool
    prompt_override: str
    silhouette_file: Path | None  # None when PNG doesn't exist on disk
    silhouette_file_raw: str      # original path string from the manifest
    silhouette_model: str
    silhouette_approved: bool


@dataclass
class ManifestInfo:
    stem: str
    source_file: str         # original filename e.g. "Junior.pdf"
    source_path: Path | None # work/<session_id>/source.* — None if missing
    figures: list[FigureInfo] = field(default_factory=list)
    figures_by_hash: dict[str, FigureInfo] = field(default_factory=dict)


def _parse_manifest(path: Path, *, mf_root: Path = MF_ROOT) -> ManifestInfo:
    data = json.loads(path.read_text(encoding="utf-8"))
    session_id = data.get("session_id", "")
    stem = data.get("stem", path.stem)
    source_file = data.get("source_file", "")

    work_dir = mf_root / "work" / session_id
    source_path: Path | None = None
    for ext in (".docx", ".pdf"):
        candidate = work_dir / f"source{ext}"
        if candidate.exists():
            source_path = candidate
            break

    figures: list[FigureInfo] = []
    for fig in data.get("figures", []):
        sil = fig.get("silhouette") or {}
        sil_raw = sil.get("file", "") or ""
        sil_file: Path | None = None
        if sil_raw:
            p = Path(sil_raw)
            sil_file = p if p.exists() else None

        figures.append(FigureInfo(
            n=str(fig.get("n", "")),
            anchor=fig.get("anchor", ""),
            source_sha256=fig.get("source_sha256", ""),
            caption=fig.get("caption", "") or "",
            included=bool(fig.get("included", True)),
            use_original=bool(fig.get("use_original", False)),
            prompt_override=fig.get("prompt_override", "") or "",
            silhouette_file=sil_file,
            silhouette_file_raw=sil_raw,
            silhouette_model=sil.get("model", "") or "",
            silhouette_approved=bool(sil.get("approved", False)),
        ))

    figures_by_hash = {f.source_sha256: f for f in figures if f.source_sha256}
    return ManifestInfo(
        stem=stem,
        source_file=source_file,
        source_path=source_path,
        figures=figures,
        figures_by_hash=figures_by_hash,
    )


def find_memoir_manifest(
    slug: str,
    *,
    manifest_path: Path | None = None,
    mf_root: Path = MF_ROOT,
) -> ManifestInfo:
    """Locate the MemoirForge manifest for *slug* (== stem).

    Raises `LookupError` for excluded stems or when no match is found.
    Pass `manifest_path` to bypass the glob scan (useful in tests).
    """
    if slug in EXCLUDED_STEMS:
        raise LookupError(
            f"'{slug}' is the national-service test run — never re-import it. "
            f"Use '1953-1954_in-the-navy' instead."
        )

    if manifest_path is not None:
        if not manifest_path.exists():
            raise LookupError(f"manifest file not found: {manifest_path}")
        return _parse_manifest(manifest_path, mf_root=mf_root)

    out_dir = mf_root / "out"
    available: list[str] = []
    for p in sorted(out_dir.glob("*.manifest.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        stem = data.get("stem", p.stem)
        if stem in EXCLUDED_STEMS:
            continue
        available.append(stem)
        if stem == slug:
            return _parse_manifest(p, mf_root=mf_root)

    raise LookupError(
        f"no MemoirForge manifest found for '{slug}'. "
        f"Available: {', '.join(available) if available else '(none)'}"
    )


def find_manifest_for_doc(
    doc: Document,
    *,
    mf_root: Path = MF_ROOT,
) -> ManifestInfo:
    """Find a manifest for a library doc: slug match first, source_file fallback.

    Handles docs ingested via '+ Add document' whose auto-detected slug
    differs from the MemoirForge stem (e.g. date detection chose a different
    start year).
    """
    try:
        return find_memoir_manifest(doc.slug, mf_root=mf_root)
    except LookupError:
        pass

    source_file = (doc.meta or {}).get("source_file", "")
    if source_file:
        out_dir = mf_root / "out"
        for p in sorted(out_dir.glob("*.manifest.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            stem = data.get("stem", p.stem)
            if stem in EXCLUDED_STEMS:
                continue
            if data.get("source_file", "") == source_file:
                return _parse_manifest(p, mf_root=mf_root)

    raise LookupError(
        f"'{doc.slug}': no MemoirForge manifest found — "
        f"tried slug match and source_file='{source_file}'"
    )


def list_manifest_slugs(*, mf_root: Path = MF_ROOT) -> list[str]:
    """All keeper stems from MemoirForge/out/ (excluded stems omitted)."""
    out_dir = mf_root / "out"
    slugs: list[str] = []
    for p in sorted(out_dir.glob("*.manifest.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        stem = data.get("stem", p.stem)
        if stem not in EXCLUDED_STEMS:
            slugs.append(stem)
    return slugs


def _resolve_img_src(src_str: str, media: Path) -> Path:
    """Mirror `resolve_src` from ingestion.draft_to_blocks."""
    p = Path(src_str)
    if p.is_absolute():
        return p
    for base in (media.parent.parent, media.parent, media):
        candidate = base / p
        if candidate.exists():
            return candidate
    return p  # caller must check .exists()


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(
    slug: str,
    *,
    manifest_path: Path | None = None,
    mf_root: Path = MF_ROOT,
) -> dict[str, Any]:
    """Extract images from the archived source and match against the manifest.

    No DB writes, no workspace writes. Returns a report dict.
    """
    manifest = find_memoir_manifest(slug, manifest_path=manifest_path, mf_root=mf_root)

    if manifest.source_path is None:
        return {
            "slug": slug,
            "source_file": manifest.source_file,
            "error": "archived source file missing from MemoirForge work/",
            "figures_extracted": 0,
            "figures_in_manifest": len(manifest.figures),
            "matched": 0,
            "match_rate": "0/0",
            "unmatched": [],
            "missing_silhouettes": _missing_silhouettes(manifest),
        }

    from .ingestion import _run_extraction

    with tempfile.TemporaryDirectory() as tmp:
        media = Path(tmp) / "media"
        media.mkdir()
        draft, _date_stem, _date_display = _run_extraction(
            manifest.source_path, manifest.source_file, media
        )

        extracted: list[dict[str, Any]] = []
        for img in draft.images:
            img_path = _resolve_img_src(img.src_path, media)
            if img_path.exists():
                h = sha256_file(img_path)
                matched_fig = manifest.figures_by_hash.get(h)
                extracted.append({
                    "order": img.order,
                    "sha256": h,
                    "matched": matched_fig is not None,
                    "manifest_n": matched_fig.n if matched_fig else None,
                })
            else:
                extracted.append({
                    "order": img.order,
                    "sha256": None,
                    "matched": False,
                    "manifest_n": None,
                    "error": "unresolvable path",
                })

    matched = sum(1 for e in extracted if e["matched"])
    unmatched = [e for e in extracted if not e["matched"]]

    return {
        "slug": slug,
        "source_file": manifest.source_file,
        "source_path": str(manifest.source_path),
        "figures_extracted": len(extracted),
        "figures_in_manifest": len(manifest.figures),
        "matched": matched,
        "match_rate": f"{matched}/{len(extracted)}" if extracted else "0/0",
        "unmatched": unmatched,
        "missing_silhouettes": _missing_silhouettes(manifest),
    }


def _missing_silhouettes(manifest: ManifestInfo) -> list[dict[str, str]]:
    return [
        {"n": f.n, "anchor": f.anchor, "expected_path": f.silhouette_file_raw}
        for f in manifest.figures
        if f.silhouette_file_raw and f.silhouette_file is None
    ]


# ---------------------------------------------------------------------------
# Sketch seeding
# ---------------------------------------------------------------------------

def seed_sketches(
    session: Session,
    workspace: Path,
    doc: Document,
    manifest: ManifestInfo,
) -> dict[str, Any]:
    """Attach MemoirForge sketches to forgeImage blocks with no sketchAssetId.

    Looks up each block's `assetId` (sha256 of the extracted original) in
    `manifest.figures_by_hash`. For each hit:
    - ingests the silhouette PNG as a "sketches" asset
    - sets sketchAssetId, approval, caption/altText, safeMode
    For each hit where cache-seeding applies, also writes the generation
    cache so future "Generate sketch" clicks are free cache hits.

    Blocks that already have a sketchAssetId are left unchanged (precedence).
    Saves once via services.save_blocks; returns a report dict.
    """
    from .sketch_service import sketch_settings

    cfg = sketch_settings(session)
    cache_dir = workspace / "sketch-cache"

    blocks = [dict(b) for b in doc.blocks]
    seeded = 0
    cache_seeded = 0
    carried_over = sum(
        1 for b in blocks
        if b.get("type") == FORGE_IMAGE and b.get("props", {}).get("sketchAssetId")
    )
    unmatched: list[dict[str, Any]] = []
    seeded_detail: list[dict[str, Any]] = []
    missing_sil: list[dict[str, Any]] = []

    for block in blocks:
        if block.get("type") != FORGE_IMAGE:
            continue
        props = dict(block.get("props", {}))
        if props.get("sketchAssetId"):
            continue  # already seeded; existing work takes precedence

        asset_id = props.get("assetId", "")
        fig = manifest.figures_by_hash.get(asset_id)
        if fig is None:
            unmatched.append({"block_id": block["id"][:8], "assetId": asset_id[:12] + "…"})
            continue

        if fig.silhouette_file is None:
            missing_sil.append({"n": fig.n, "anchor": fig.anchor})
            unmatched.append({
                "block_id": block["id"][:8],
                "assetId": asset_id[:12] + "…",
                "reason": "silhouette file missing on disk",
            })
            continue

        # Ingest the silhouette PNG into the workspace asset store.
        sketch_asset = ingest_file(
            session, workspace, fig.silhouette_file, "sketches"
        )
        sketch_asset.filename = f"{doc.slug}-fig{fig.n}-sketch.png"

        props["sketchAssetId"] = sketch_asset.sha256
        props["approval"] = "approved" if fig.silhouette_approved else "pending"

        # Caption: prefer manifest caption; keep block caption if manifest is empty.
        if fig.caption:
            props["caption"] = fig.caption
            props["altText"] = fig.caption

        # Safe-edition mode flags.
        if not fig.included:
            props["safeMode"] = "omit"
        elif fig.use_original:
            props["safeMode"] = "original"

        block["props"] = props
        seeded += 1
        seeded_detail.append({"n": fig.n, "asset": sketch_asset.sha256[:12] + "…"})

        # Seed the generation cache so "Generate sketch" is a free cache hit.
        if (
            not fig.prompt_override
            and fig.silhouette_model == cfg["model"]
        ):
            original = session.get(Asset, asset_id)
            if original is not None:
                orig_path = asset_path(workspace, original)
                if orig_path.exists():
                    orig_bytes = orig_path.read_bytes()
                    key = cache_key(orig_bytes, cfg["default_prompt"], cfg["model"])
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    dest = cache_dir / f"{key}.png"
                    if not dest.exists():
                        dest.write_bytes(fig.silhouette_file.read_bytes())
                    cache_seeded += 1

    if seeded > 0:
        services.save_blocks(
            session, doc, blocks,
            summary=f"seeded {seeded} sketch(es) from MemoirForge manifest",
        )
        services.record_change(
            session, doc, "edit", "sketch seeding from MemoirForge manifest",
            detail={
                "seeded": seeded,
                "cache_seeded": cache_seeded,
                "carried_over": carried_over,
                "unmatched": len(unmatched),
                "figures": seeded_detail,
            },
        )

    return {
        "slug": doc.slug,
        "figures": sum(1 for b in blocks if b.get("type") == FORGE_IMAGE),
        "carried_over": carried_over,
        "seeded": seeded,
        "cache_seeded": cache_seeded,
        "unmatched": unmatched,
        "missing_silhouettes": missing_sil,
    }


# ---------------------------------------------------------------------------
# Full re-import orchestration
# ---------------------------------------------------------------------------

def reimport_document(
    session: Session,
    workspace: Path,
    doc: Document,
    *,
    manifest: ManifestInfo | None = None,
    mf_root: Path = MF_ROOT,
) -> dict[str, Any]:
    """Re-import a document from its archived MemoirForge source.

    1. Adopt: if `meta.source_asset_id` is missing, ingest the archived
       source file and write it into `doc.meta`.
    2. Re-ingest: call `ingestion.reingest_document` (snapshots first).
       Existing figure work in the NotebookForge DB carries over by assetId
       and takes precedence over manifest seeding.
    3. Seed: call `seed_sketches` for every figure still lacking a sketch.

    Returns a combined report.
    """
    from .ingestion import reingest_document as _reingest

    if manifest is None:
        manifest = find_memoir_manifest(doc.slug, mf_root=mf_root)

    if manifest.source_path is None:
        raise LookupError(
            f"'{doc.slug}': archived source file not found in MemoirForge work/"
        )

    # 1. Adopt source into the workspace if not already recorded.
    if not doc.meta.get("source_asset_id"):
        source_asset = ingest_file(session, workspace, manifest.source_path, "sources")
        source_asset.filename = manifest.source_file  # original name e.g. "Junior.pdf"
        doc.meta = {
            **doc.meta,
            "source_asset_id": source_asset.sha256,
            "source_file": manifest.source_file,
        }
        session.flush()

    # 2. Re-ingest text; existing figure work carries over by assetId.
    reingest_result = _reingest(session, workspace, doc)

    # 3. Seed sketches for any figure that didn't carry over.
    seed_result = seed_sketches(session, workspace, doc, manifest)

    return {
        "slug": doc.slug,
        "text_blocks": reingest_result.get("blocks"),
        "figures": reingest_result.get("figures"),
        "figures_carried_over_by_assetid": reingest_result.get("figures_matched"),
        "seeded": seed_result["seeded"],
        "cache_seeded": seed_result["cache_seeded"],
        "unmatched": seed_result["unmatched"],
        "missing_silhouettes": seed_result["missing_silhouettes"],
    }
