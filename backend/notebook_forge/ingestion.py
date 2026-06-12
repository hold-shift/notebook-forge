"""New-document ingest: PDF/DOCX → document in the library (Phase B).

Runs the vendored MemoirForge extraction (extract → normalise → date
detection), then adapts the draft to the canonical block tree: text blocks
become paragraphs/headings with `[^N]` markers converted to fnRef runs,
footnotes co-locate as forgeFootnote blocks after their first referencing
paragraph, and images become forgeImage blocks (approval **pending**, no
sketch yet — Generate sketch in the editor fills those in).

The detected date/title land in meta for the operator to confirm in the
editor before first publish (the hard-gate spirit of CP1, minus the modal).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from slugify import slugify
from sqlalchemy.orm import Session

from . import services
from .assets import ingest_file
from .blocks import FORGE_IMAGE, make_block
from .ingest_vendor import detect_year_range, extract_docx, extract_pdf, normalise
from .ingest_vendor.footnotes import referenced_numbers
from .polish.textmap import _md_inline_runs  # shared parser (canonical home)

DEFAULT_AUTHOR = "R.F. Skitch"
DEFAULT_OVERLINE = "The Skitch Family Archive · Family History"
PAGES_BASE = "https://chris-skitch.github.io/family-history"


def draft_to_blocks(
    draft, session: Session, workspace: Path, media_dir: Path  # noqa: ANN001
) -> list[dict[str, Any]]:
    def resolve_src(src: str) -> Path:
        p = Path(src)
        if p.is_absolute():
            return p
        # extract_docx records paths relative to media_dir.parent.parent
        # (MemoirForge's work/<session>/ layout)
        for base in (media_dir.parent.parent, media_dir.parent, media_dir):
            candidate = base / p
            if candidate.exists():
                return candidate
        return p

    img_by_order = {img.order: img for img in draft.images}
    fn_by_n = {int(fn["n"]): fn for fn in draft.footnotes if "n" in fn}
    emitted: set[int] = set()
    blocks: list[dict[str, Any]] = []

    for entry in draft.body:
        if "image_ref" in entry:
            img = img_by_order.get(entry["image_ref"])
            if img is None:
                continue
            asset = ingest_file(session, workspace, resolve_src(img.src_path), "originals")
            caption = draft.detected_captions.get(img.order, "") or img.nearby_caption or ""
            portrait = bool(img.height and img.width and img.height > img.width)
            blocks.append(
                make_block(
                    "forgeImage",
                    {
                        "assetId": asset.sha256,
                        "sketchAssetId": "",
                        "caption": caption,
                        "altText": caption,
                        "approval": "pending",
                        "displayWidth": "portrait" if portrait else "full",
                    },
                )
            )
            continue
        kind = entry.get("kind", "p")
        text = (entry.get("text") or "").strip()
        if not text or kind == "h1":  # the H1 is the title, not body content
            continue
        if kind in ("h2", "h3"):
            blocks.append(make_block("heading", {"level": int(kind[1])}, _md_inline_runs(text)))
        else:
            blocks.append(make_block("paragraph", content=_md_inline_runs(text)))
            # co-locate footnotes after the first referencing paragraph
            for n in referenced_numbers(text):
                if n in emitted or n not in fn_by_n:
                    continue
                emitted.add(n)
                note = (fn_by_n[n].get("text") or "").strip()
                blocks.append(make_block("forgeFootnote", {"marker": str(n), "text": note}))
    return blocks


def _extract_blocks(
    session: Session, workspace: Path, file_path: Path, name: str
) -> tuple[Any, list[dict[str, Any]], str, str]:
    """Shared extraction: source file → (draft, blocks, date_stem, display)."""
    suffix = Path(name).suffix.lower()
    with tempfile.TemporaryDirectory() as tmp:
        media = Path(tmp) / "media"
        media.mkdir()
        if suffix == ".docx":
            draft = extract_docx(file_path, media)
        elif suffix == ".pdf":
            draft = extract_pdf(file_path, media)
        else:
            raise ValueError(f"unsupported source type '{suffix}' (use .pdf or .docx)")
        draft.source_file = name
        draft = normalise(draft)
        date_stem, date_display = detect_year_range(draft)
        blocks = draft_to_blocks(draft, session, workspace, media)
    return draft, blocks, date_stem, date_display


def reingest_document(session: Session, workspace: Path, doc) -> dict[str, Any]:  # noqa: ANN001
    """Re-run extraction from the archived source file, REPLACING the text
    while carrying over all human figure work: matched by content-addressed
    original (same photo bytes → same assetId), each figure keeps its
    sketch, approval state and caption edits. A safety snapshot is taken
    first, so Restore undoes the whole thing."""
    from .assets import asset_path
    from .models import Asset

    source_id = doc.meta.get("source_asset_id", "")
    source = session.get(Asset, source_id) if source_id else None
    if source is None:
        raise LookupError(f"'{doc.slug}' has no archived source file to re-ingest from")
    source_path = asset_path(workspace, source)
    if not source_path.exists():
        raise LookupError("archived source file is missing from the workspace")
    name = source.filename or f"source{source.ext}"

    old_props_by_asset: dict[str, dict[str, Any]] = {}
    for block in doc.blocks:
        if block.get("type") == FORGE_IMAGE:
            asset_id = block.get("props", {}).get("assetId", "")
            if asset_id:
                old_props_by_asset.setdefault(asset_id, dict(block["props"]))

    _, blocks, _, _ = _extract_blocks(session, workspace, source_path, name)

    matched = 0
    for block in blocks:
        if block.get("type") != FORGE_IMAGE:
            continue
        asset_id = block.get("props", {}).get("assetId", "")
        if asset_id in old_props_by_asset:
            block["props"] = dict(old_props_by_asset[asset_id])
            matched += 1

    services.snapshot_document(session, doc, note="before re-ingest from source")
    services.save_blocks(
        session, doc, blocks,
        summary=f"re-ingested from {name} (figure work carried over)",
    )
    figures = sum(1 for b in blocks if b.get("type") == FORGE_IMAGE)
    return {
        "slug": doc.slug,
        "blocks": len(blocks),
        "figures": figures,
        "figures_matched": matched,
        "figures_new": figures - matched,
    }


def ingest_document(
    session: Session,
    workspace: Path,
    file_path: Path,
    original_filename: str | None = None,
) -> dict[str, Any]:
    """Extract, adapt and create the document. Returns slug + detection
    info for the operator to confirm."""
    name = original_filename or file_path.name
    draft, blocks, date_stem, date_display = _extract_blocks(
        session, workspace, file_path, name
    )

    title = (draft.detected_title or Path(name).stem).strip()
    slug_base = f"{date_stem}_{slugify(title)}" if date_stem else slugify(title)
    slug = slug_base
    i = 2
    while services.get_document(session, slug) is not None:
        slug = f"{slug_base}-{i}"
        i += 1

    source_asset = ingest_file(session, workspace, file_path, "sources")
    source_asset.filename = name

    meta = {
        "slug": slug,
        "title": title,
        "author": draft.detected_author or DEFAULT_AUTHOR,
        "overline": DEFAULT_OVERLINE,
        "standfirst": draft.detected_standfirst or "",
        "place": "",
        "year_display": date_display,
        "date_prefix": date_stem,
        "date_detected": date_stem,
        "date_confirmed": False,  # operator confirms in the editor
        "canonical_url": f"{PAGES_BASE}/rfs/{slug}.html",
        "homepage_url": f"{PAGES_BASE}/index.html",
        "meta_description": draft.detected_standfirst or "",
        "source_asset_id": source_asset.sha256,
        "source_file": name,
    }
    doc = services.create_document(
        session, slug=slug, title=title, blocks=blocks, meta=meta,
        log=f"ingested from {name}",
    )
    figures = sum(1 for b in blocks if b["type"] == "forgeImage")
    return {
        "slug": slug,
        "title": title,
        "detected_date": date_stem,
        "date_display": date_display,
        "figures": figures,
        "footnotes": len(draft.footnotes),
        "blocks": len(doc.blocks),
    }
