"""Publish orchestration: render → adapter → snapshot + sync_state, atomically.

The DB writes happen only after the adapter succeeds, inside the caller's
transaction, so a failed transfer leaves sync_state untouched. Rollback
re-points the document at a prior snapshot and re-renders/republishes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import services
from ..assets import asset_path
from ..blocks import FORGE_IMAGE
from ..models import Asset, Document, Snapshot, Target
from ..renderer import render_document
from .base import BundleAsset, PublishBundle, PublishTarget
from .drive import DriveTarget, MockDriveClient
from .git_pages import GitPagesTarget
from .local_folder import LocalFolderTarget


def build_bundle(session: Session, workspace: Path, doc: Document) -> PublishBundle:
    """Render the document and collect its assets under published naming
    (figure-{n}-original.* / figure-{n}-silhouette.*, n per unique image)."""
    slug = doc.meta.get("slug", doc.slug)
    assets: list[BundleAsset] = []
    n_for_asset: dict[str, int] = {}
    ext_for_asset: dict[str, str] = {}
    next_n = 0

    for block in doc.blocks:
        if block.get("type") != FORGE_IMAGE:
            continue
        asset_id = block.get("props", {}).get("assetId", "")
        if not asset_id or asset_id in n_for_asset:
            continue
        next_n += 1
        n_for_asset[asset_id] = next_n
        original = session.get(Asset, asset_id)
        if original is None:
            continue
        ext_for_asset[asset_id] = original.ext
        assets.append(
            BundleAsset(
                name=f"figure-{next_n}-original{original.ext}",
                path=asset_path(workspace, original),
                sha256=original.sha256,
            )
        )
        sketch_id = block.get("props", {}).get("sketchAssetId", "")
        sketch = session.get(Asset, sketch_id) if sketch_id else None
        if sketch is not None:
            assets.append(
                BundleAsset(
                    name=f"figure-{next_n}-silhouette{sketch.ext}",
                    path=asset_path(workspace, sketch),
                    sha256=sketch.sha256,
                )
            )

    def image_src(block: dict[str, Any], n: int) -> str:
        asset_id = block.get("props", {}).get("assetId", "")
        ext = ext_for_asset.get(asset_id, ".jpeg")
        return f"{slug}_assets/figure-{n}-original{ext}"

    html = render_document(doc.meta, doc.blocks, image_src)
    return PublishBundle(slug=slug, html=html, assets=assets)


def make_adapter(target: Target, workspace: Path) -> PublishTarget:
    """Adapter from a target row. github-pages requires an explicit
    `push_url` in config — the imported live-site target doesn't have one,
    so live pushes are impossible tonight by construction."""
    config = target.config or {}
    if target.kind == "local-folder":
        folder = config.get("folder") or str(workspace / "exports" / "site")
        return LocalFolderTarget(Path(folder))
    if target.kind == "github-pages":
        push_url = config.get("push_url", "")
        if not push_url:
            raise PermissionError(
                "live publishing is disabled this sprint: target "
                f"'{target.name}' has no push_url (fixture-only)"
            )
        return GitPagesTarget(
            push_url=push_url,
            clones_dir=workspace / "git-clones" / target.name,
            branch=config.get("branch", "main"),
            subdir=config.get("subdir", ""),
        )
    if target.kind == "drive":
        # Real OAuth lands next sprint; the mocked client keeps the flow
        # exercisable end to end.
        return DriveTarget(MockDriveClient(), config.get("folder_id", "mock-folder"))
    raise ValueError(f"unknown target kind '{target.kind}'")


def publish_document(
    session: Session,
    workspace: Path,
    doc: Document,
    target: Target,
    adapter: PublishTarget | None = None,
) -> dict[str, Any]:
    adapter = adapter or make_adapter(target, workspace)
    bundle = build_bundle(session, workspace, doc)
    result = adapter.publish(bundle)  # raises on failure → no DB writes
    snap = services.snapshot_document(session, doc, note=f"publish to {target.name}")
    services.mark_published(session, doc, target, snap)
    services.record_change(
        session,
        doc,
        "publish",
        f"published to {target.name}",
        detail={
            "target": target.name,
            "snapshot_id": snap.id,
            "assets_written": result.assets_written,
            "assets_skipped": result.assets_skipped,
            **result.detail,
        },
    )
    return {"snapshot_id": snap.id, **result.detail}


def rollback_and_republish(
    session: Session,
    workspace: Path,
    doc: Document,
    target: Target,
    snapshot: Snapshot,
    adapter: PublishTarget | None = None,
) -> dict[str, Any]:
    """Re-point the document at a prior snapshot, then re-render and
    republish so the target reflects the restored content."""
    services.rollback_to_snapshot(session, doc, snapshot)
    return publish_document(session, workspace, doc, target, adapter=adapter)
