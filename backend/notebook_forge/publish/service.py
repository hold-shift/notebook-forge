"""Publish orchestration: render → adapter → snapshot + sync_state, atomically.

The DB writes happen only after the adapter succeeds, inside the caller's
transaction, so a failed transfer leaves sync_state untouched. Rollback
re-points the document at a prior snapshot and re-renders/republishes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..assets import asset_path
from ..blocks import (
    FORGE_ATTACHMENT,
    FORGE_IMAGE,
    RESERVED_ROOT_FILES,
    attachment_published_path,
)
from ..models import Asset, Document, Snapshot, Target
from ..renderer import render_document
from .base import BundleAsset, PublishBundle, PublishTarget
from .drive import DriveTarget, MockDriveClient
from .git_pages import GitPagesTarget
from .local_folder import LocalFolderTarget


def _attachment_path(props: dict[str, Any]) -> str:
    """The site-root-relative path one attachment block publishes to."""
    return attachment_published_path(
        str(props.get("name", "")),
        str(props.get("filename", "")),
        str(props.get("path", "")),
    )


def attachment_paths_in_use(
    session: Session, exclude_doc_id: int | None = None
) -> dict[str, str]:
    """{published path: document title} for every OTHER document's attachments.

    Two documents pointing at the same path would silently overwrite each
    other's file on the site, and the loser would only be noticed as a wrong
    download — so a publish refuses instead."""
    used: dict[str, str] = {}
    for other in session.scalars(select(Document)).all():
        if other.id == exclude_doc_id or other.kind == "homepage":
            continue
        for block in other.blocks or []:
            if block.get("type") != FORGE_ATTACHMENT:
                continue
            used.setdefault(
                _attachment_path(block.get("props", {})), other.title or other.slug
            )
    return used


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

    # Attachments (PDFs and other documents) are published at a path the
    # operator controls, relative to the SITE root — not inside the document's
    # assets dir — so they get their own bundle list and absolute links.
    from ..collection import pages_base_url

    base_url = pages_base_url(session)
    root_assets: list[BundleAsset] = []
    paths: dict[str, str] = {}
    taken = attachment_paths_in_use(session, exclude_doc_id=doc.id)

    for block in doc.blocks:
        if block.get("type") != FORGE_ATTACHMENT:
            continue
        props = block.get("props", {})
        published = _attachment_path(props)
        label = str(props.get("name", "")) or str(props.get("filename", "")) or published
        if published in RESERVED_ROOT_FILES:
            raise PermissionError(
                f"attachment '{label}' would publish as '{published}', which is one of "
                "the site's own files — give it a different name or path."
            )
        if published in paths:
            raise PermissionError(
                f"attachments '{paths[published]}' and '{label}' would both publish to "
                f"'{published}' — give one of them a different name or path."
            )
        if published in taken:
            raise PermissionError(
                f"attachment '{label}' would publish to '{published}', which is already "
                f"used by the document '{taken[published]}' — give it a different name "
                "or path."
            )
        paths[published] = label
        asset = session.get(Asset, props.get("assetId") or "")
        if asset is None:
            continue
        root_assets.append(
            BundleAsset(
                name=published, path=asset_path(workspace, asset), sha256=asset.sha256
            )
        )

    def attachment_src(block: dict[str, Any], _n: int) -> str:
        """Absolute URL: the file sits at the site root, while the page sits in
        the pages subdir, and the same link has to work from the safe edition."""
        return f"{base_url}/{_attachment_path(block.get('props', {}))}"

    # prev/next docnav is DERIVED from the catalogue's chronological order
    # at publish time, so a neighbour's title fix propagates on republish.
    from ..collection import nav_for

    meta = dict(doc.meta)
    nav_prev, nav_next = nav_for(session, doc)
    if nav_prev or nav_next:
        meta["nav_prev"] = nav_prev
        meta["nav_next"] = nav_next

    from ..narrative import effective_narrative_label
    meta["narrative_label"] = effective_narrative_label(session, doc)

    # TTS player context — present only when the global toggle is on and the
    # document has an audio base URL (narration_service decides). The renderer
    # injects the player partial when this key is set.
    from ..narration_service import player_context
    meta["tts"] = player_context(session, doc)

    # Workspace-wide footer / licence notice, authoritative across all docs.
    from ..footer import footer_html
    meta["footer_html"] = footer_html(session)

    # Operator-supplied <head> HTML (e.g. an analytics script), injected into
    # every published page.
    from ..collection import (
        doc_homepage_url,
        favicon_url,
        site_head_html,
    )
    meta["head_html"] = site_head_html(session)

    # Internal "⌂ The Archive" links point at the homepage's CANONICAL url (the
    # site root). Derived fresh rather than read from the doc's frozen meta, so
    # a base-URL change — or the /index.html → / canonical fix — propagates on
    # the next publish without a meta migration.
    meta["homepage_url"] = doc_homepage_url(pages_base_url(session))

    # Site-wide favicon (absolute URL so it resolves from /rfs/ pages). The
    # binary is pushed to the site root by the homepage publish (see below).
    meta["favicon_url"] = favicon_url(session, pages_base_url(session))

    # Rich structured data + head tags (SEO/AEO plan §5–§6): assembled from
    # current DB state (report tracks, audio, group, first-figure fallback).
    # Its presence is what switches the renderer from the legacy single-Article
    # JSON-LD to the full @graph.
    from ..structured_data import build_context
    meta["seo"] = build_context(session, doc)

    html = render_document(meta, doc.blocks, image_src, attachment_src)
    return PublishBundle(slug=slug, html=html, assets=assets, root_assets=root_assets)


def make_adapter(target: Target, workspace: Path) -> PublishTarget:
    """Adapter from a target row. github-pages requires an explicit
    `push_url` in config — the imported live-site target doesn't have one,
    so live pushes are impossible tonight by construction."""
    config = target.config or {}
    if target.kind == "local-folder":
        folder = config.get("folder") or str(workspace / "exports" / "site")
        return LocalFolderTarget(Path(folder))
    if target.kind == "github-pages":
        # Explicit push_url wins (test fixtures use a local bare repo).
        # Otherwise build the authenticated URL from config.repo + a PAT
        # from the OS keychain (env GITHUB_PAT as fallback). The PAT is
        # injected at adapter-construction time only — never persisted in
        # target config, and GitPagesTarget redacts it from git errors.
        push_url = config.get("push_url", "")
        if not push_url:
            from ..secrets_store import get_secret

            repo = config.get("repo", "")
            pat = get_secret("github-pat", env="GITHUB_PAT")
            if repo and pat:
                push_url = f"https://x-access-token:{pat}@github.com/{repo}.git"
        if not push_url:
            raise PermissionError(
                f"live publishing needs credentials: target '{target.name}' has no "
                "push_url and no GitHub PAT was found (keychain: service "
                "'notebook-forge', name 'github-pat'; or env GITHUB_PAT)"
            )
        return GitPagesTarget(
            push_url=push_url,
            clones_dir=workspace / "git-clones" / target.name,
            branch=config.get("branch", "main"),
            subdir=config.get("subdir", ""),
            author_name=config.get("commit_author_name", "Chris Skitch"),
            author_email=config.get(
                "commit_author_email",
                "291326845+chris-skitch@users.noreply.github.com",
            ),
        )
    if target.kind == "drive":
        folder_id = config.get("folder_id", "")
        if config.get("mock"):
            return DriveTarget(MockDriveClient(), folder_id or "mock-folder")
        if not folder_id:
            raise PermissionError(f"drive target '{target.name}' has no folder_id configured")
        from .drive_client import GoogleDriveClient

        return DriveTarget(GoogleDriveClient(), folder_id)  # raises if unauthenticated
    raise ValueError(f"unknown target kind '{target.kind}'")


def publish_document(
    session: Session,
    workspace: Path,
    doc: Document,
    target: Target,
    adapter: PublishTarget | None = None,
) -> dict[str, Any]:
    from ..collection import pages_base_url, root_files
    from ..homepage import get_homepage, homepage_banner_assets

    base_url = pages_base_url(session)

    if doc.kind == "homepage":
        if target.kind == "drive":
            raise PermissionError("the homepage is not published to Drive targets")
        adapter = adapter or make_adapter(target, workspace)
        files, warnings = root_files(session, target=target, base_url=base_url)
        publish_fn = getattr(adapter, "publish_root_files", None)
        if publish_fn is None:
            raise PermissionError(
                f"target kind '{target.kind}' cannot publish the homepage"
            )
        # Banner images + the site-branding images (favicon, homepage OG image)
        # are copied as static files at/next to index.html so they resolve on the
        # published site (not via the dev /api/assets endpoint).
        from ..collection import site_image_assets

        root_assets = [
            BundleAsset(name=name, path=path, sha256=sha)
            for name, path, sha in (
                *homepage_banner_assets(session, workspace),
                *site_image_assets(session, workspace),
            )
        ]
        commit = publish_fn(files, root_assets)
        snap = services.snapshot_document(session, doc, note=f"publish to {target.name}")
        services.mark_published(session, doc, target, snap)
        services.record_change(
            session, doc, "publish", f"published homepage to {target.name}",
            detail={
                "target": target.name, "snapshot_id": snap.id,
                "files": sorted(files), "warnings": warnings,
                "commit": commit if isinstance(commit, str) else None,
            },
        )
        return {
            "snapshot_id": snap.id, "files": sorted(files),
            "warnings": warnings,
            "commit": commit if isinstance(commit, str) else None,
        }

    adapter = adapter or make_adapter(target, workspace)
    bundle = build_bundle(session, workspace, doc)
    if adapter.kind == "drive":
        from ..safe_edition import build_safe_markdown

        bundle.safe_md = build_safe_markdown(session, workspace, doc)
    bundle.root_files, root_warnings = root_files(
        session, target=target, publishing_slug=doc.slug, base_url=base_url
    )
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
            "warnings": root_warnings,
            **result.detail,
        },
    )
    # D14: if homepage was dirty for this target, mark it clean too
    hp = get_homepage(session)
    if hp is not None and target.kind != "drive" and services.is_dirty(session, hp, target):
        hp_snap = services.snapshot_document(
            session, hp, note=f"publish to {target.name} (with {doc.slug})"
        )
        services.mark_published(session, hp, target, hp_snap)
        services.record_change(
            session, hp, "publish",
            f"homepage refreshed by publish of {doc.slug} to {target.name}",
            detail={"target": target.name, "snapshot_id": hp_snap.id},
        )
    return {"snapshot_id": snap.id, "warnings": root_warnings, **result.detail}


def publish_all_pending(
    session: Session,
    workspace: Path,
    target: Target,
    force: bool = False,
    adapter: PublishTarget | None = None,
) -> dict[str, Any]:
    """Re-publish every memoir already live on an HTML target that has pending
    changes, in one pass — the bulk "republish the site" tool. Documents not
    currently published (drafts / never-published / unpublished) are excluded:
    bulk publish only pushes updates to docs already on the live site, it never
    publishes something for the first time. One adapter is built and reused
    across docs. Per-document failures are collected, not raised, so one bad doc
    doesn't abort the rest; the homepage rides along on the first memoir publish,
    so it's only published explicitly if still dirty afterwards."""
    from .. import services
    from ..homepage import get_homepage

    adapter = adapter or make_adapter(target, workspace)  # raises if creds missing
    memoirs = [d for d in services.list_documents(session) if d.kind == "memoir"]
    pending = [
        d
        for d in memoirs
        if services.is_published(session, d, target)
        and (force or services.is_dirty(session, d, target))
    ]

    published: list[str] = []
    failed: list[dict[str, str]] = []
    for doc in pending:
        try:
            publish_document(session, workspace, doc, target, adapter=adapter)
            published.append(doc.slug)
        except Exception as exc:  # noqa: BLE001 — bulk op: record + continue
            failed.append({"slug": doc.slug, "error": str(exc)})

    # The homepage rides along for HTML targets only — it isn't published to
    # Drive.
    homepage = get_homepage(session) if target.kind != "drive" else None
    if homepage is not None and (force or services.is_dirty(session, homepage, target)):
        try:
            publish_document(session, workspace, homepage, target, adapter=adapter)
            published.append(homepage.slug)
        except Exception as exc:  # noqa: BLE001
            failed.append({"slug": homepage.slug, "error": str(exc)})

    return {"published": published, "failed": failed}


def unpublish_document(
    session: Session,
    workspace: Path,
    doc: Document,
    target: Target,
    adapter: PublishTarget | None = None,
) -> dict[str, Any]:
    adapter = adapter or make_adapter(target, workspace)
    adapter.remove(doc.meta.get("slug", doc.slug))
    services.mark_unpublished(session, doc, target)
    services.record_change(
        session,
        doc,
        "unpublish",
        f"unpublished from {target.name}",
        detail={"target": target.name},
    )
    return {"target": target.name}


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
