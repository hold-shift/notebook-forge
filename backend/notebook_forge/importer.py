"""M4 — import the published memoirs and validate the round trip.

Sources:
  - a read-only clone of the published Pages repo (vendor-readonly/
    family-history): `rfs/{slug}.html` + `rfs/{slug}_assets/` are ground
    truth for content, original photos and sketches;
  - MemoirForge's out/ manifests + work/ sessions (read-only) for the
    original source documents (PDF/DOCX) and provenance.

Import seeds sync_state as PUBLISHED + CLEAN against a `github-pages`
target record so day one shows nothing pending, then re-renders every
document and DOM-diffs it against the published HTML (reports/roundtrip.md).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services
from .assets import ingest_file, sha256_file
from .blocks import FORGE_IMAGE
from .domcompare import CompareResult, compare
from .models import Asset, Setting, Target
from .parser import parse_page
from .renderer import render_document

FIG_SRC_RE = re.compile(r"figure-(\d+)-original")

PAGES_TARGET_NAME = "github-pages"
SIMILARITY_GATE = 0.99


@dataclass
class DocCoverage:
    slug: str
    figure_blocks: int = 0
    unique_images: int = 0
    originals_found: int = 0
    sketches_found: int = 0
    sketch_gaps: list[int] = field(default_factory=list)
    source_file: str = ""
    source_found: bool = False
    source_sha_ok: bool | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class DocRoundtrip:
    slug: str
    similarity: float
    result: CompareResult
    # Article-subtree-only comparison: isolates memoir CONTENT fidelity from
    # derived page furniture (ToC nav / CSS / JS), which drifts when a page
    # was published with an older template revision.
    content_similarity: float = 0.0
    content_diffs: int = 0


def discover_slugs(repo_root: Path, subdir: str = "rfs") -> list[str]:
    return sorted(
        p.stem for p in (repo_root / subdir).glob("*.html") if not p.name.startswith("index")
    )


def _find_manifest(mf_out: Path | None, slug: str) -> dict[str, Any] | None:
    if not mf_out:
        return None
    path = mf_out / f"{slug}.manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _published_n(src: str) -> int | None:
    m = FIG_SRC_RE.search(src)
    return int(m.group(1)) if m else None


def coverage_for(
    repo_root: Path,
    slug: str,
    mf_out: Path | None,
    mf_work: Path | None,
    subdir: str = "rfs",
) -> DocCoverage:
    """Expected-vs-found coverage, computed BEFORE any migration."""
    cov = DocCoverage(slug=slug)
    html = (repo_root / subdir / f"{slug}.html").read_text()
    page = parse_page(html)
    cov.figure_blocks = sum(1 for b in page.blocks if b["type"] == FORGE_IMAGE)
    srcs = list(page.images.values())
    cov.unique_images = len(set(srcs))
    assets_dir = repo_root / subdir / f"{slug}_assets"
    seen_ns: set[int] = set()
    for src in srcs:
        n = _published_n(src)
        if n is None or n in seen_ns:
            continue
        seen_ns.add(n)
        if (assets_dir / Path(src).name).exists():
            cov.originals_found += 1
        sketch = _find_sketch(assets_dir, n)
        if sketch:
            cov.sketches_found += 1
        else:
            cov.sketch_gaps.append(n)

    manifest = _find_manifest(mf_out, slug)
    if manifest:
        cov.source_file = manifest.get("source_file", "")
        source = _find_source(manifest, mf_work)
        if source:
            cov.source_found = True
            cov.source_sha_ok = sha256_file(source) == manifest.get("source_sha256")
    else:
        cov.notes.append("no MemoirForge manifest found")
    return cov


def _find_sketch(assets_dir: Path, n: int) -> Path | None:
    for ext in (".png", ".jpeg", ".jpg", ".webp"):
        p = assets_dir / f"figure-{n}-silhouette{ext}"
        if p.exists():
            return p
    return None


def _find_source(manifest: dict[str, Any], mf_work: Path | None) -> Path | None:
    if not mf_work:
        return None
    session_dir = mf_work / str(manifest.get("session_id", ""))
    for ext in (".pdf", ".docx", ".doc"):
        p = session_dir / f"source{ext}"
        if p.exists():
            return p
    return None


def get_or_create_local_target(session: Session, workspace: Path) -> Target:
    target = session.scalar(select(Target).where(Target.name == "local-folder"))
    if target is None:
        target = Target(
            name="local-folder",
            kind="local-folder",
            config={"folder": str(workspace / "exports" / "site")},
        )
        session.add(target)
        session.flush()
    return target


def get_or_create_pages_target(session: Session, repo_root: Path) -> Target:
    target = session.scalar(select(Target).where(Target.name == PAGES_TARGET_NAME))
    if target is None:
        target = Target(
            name=PAGES_TARGET_NAME,
            kind="github-pages",
            config={
                "repo": "chris-skitch/family-history",
                "branch": "main",
                "subdir": "rfs",
                "base_url": "https://chris-skitch.github.io/family-history",
                "note": "imported from read-only clone; live pushes out of scope this sprint",
                "clone_path": str(repo_root),
            },
        )
        session.add(target)
        session.flush()
    return target


def import_document(
    session: Session,
    workspace: Path,
    repo_root: Path,
    slug: str,
    target: Target,
    mf_out: Path | None = None,
    mf_work: Path | None = None,
    subdir: str = "rfs",
) -> tuple[Any, DocCoverage]:
    cov = coverage_for(repo_root, slug, mf_out, mf_work, subdir)
    html = (repo_root / subdir / f"{slug}.html").read_text()
    page = parse_page(html)
    assets_dir = repo_root / subdir / f"{slug}_assets"

    # Resolve each forgeImage to content-addressed assets. The published n
    # (from the src filename) drives sketch pairing.
    for block in page.blocks:
        if block["type"] != FORGE_IMAGE:
            continue
        src = page.images.get(block["id"], "")
        original = assets_dir / Path(src).name if src else None
        if original and original.exists():
            asset = ingest_file(session, workspace, original, "originals")
            block["props"]["assetId"] = asset.sha256
        else:
            cov.notes.append(f"original missing for src '{src}'")
            continue
        n = _published_n(src)
        sketch = _find_sketch(assets_dir, n) if n is not None else None
        if sketch:
            sk_asset = ingest_file(session, workspace, sketch, "sketches")
            block["props"]["sketchAssetId"] = sk_asset.sha256

    meta = dict(page.meta)
    meta["slug"] = slug
    meta["date_prefix"] = slug.split("_", 1)[0]

    manifest = _find_manifest(mf_out, slug)
    if manifest:
        source = _find_source(manifest, mf_work)
        if source:
            src_asset = ingest_file(session, workspace, source, "sources")
            # keep the human filename from the manifest, not "source.pdf"
            src_asset.filename = manifest.get("source_file", source.name)
            meta["source_asset_id"] = src_asset.sha256
            meta["source_file"] = src_asset.filename

    doc = services.create_document(
        session,
        slug=slug,
        title=meta.get("title", slug),
        blocks=page.blocks,
        meta=meta,
        log=f"imported from published HTML ({subdir}/{slug}.html)",
    )
    snap = services.snapshot_document(session, doc, note="import: published state")
    state = services.mark_published(session, doc, target, snap, status="PUBLISHED")
    published_at = _parse_iso(meta.get("date_published", ""))
    if published_at:
        state.published_at = published_at
    return doc, cov


def _parse_iso(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def import_homepage_settings(session: Session, repo_root: Path) -> None:
    """Capture the human-authored index content + catalogue for the index
    renderer (index editing UI is next sprint)."""
    index_html = repo_root / "index.html"
    homepage: dict[str, Any] = {}
    if index_html.exists():
        soup = BeautifulSoup(index_html.read_text(), "lxml")
        h1 = soup.find("h1", class_="title")
        homepage["title"] = h1.get_text().strip() if h1 else ""
        homepage["welcome"] = "\n\n".join(
            p.get_text().strip() for p in soup.find_all("p", class_="intro")
        )
        dedication = soup.find("p", class_="dedication")
        homepage["dedication"] = dedication.get_text().strip() if dedication else ""
        footer = soup.find("footer")
        if footer and footer.find("p"):
            homepage["footer_html"] = "".join(str(c) for c in footer.find("p").children)
    _upsert_setting(session, "homepage", homepage)

    catalogue_path = repo_root / "catalogue.json"
    if catalogue_path.exists():
        _upsert_setting(session, "catalogue", json.loads(catalogue_path.read_text()))


def _upsert_setting(session: Session, key: str, value: dict[str, Any]) -> None:
    setting = session.get(Setting, key)
    if setting is None:
        session.add(Setting(key=key, value=value))
    else:
        setting.value = value


def db_image_src(session: Session, doc) -> Any:  # noqa: ANN001
    """src resolver for re-rendering an imported document: figure-{n}-
    original{ext}, ext looked up from the asset row."""
    slug = doc.meta.get("slug", doc.slug)

    def resolver(block: dict[str, Any], n: int) -> str:
        asset_id = block.get("props", {}).get("assetId", "")
        asset = session.get(Asset, asset_id) if asset_id else None
        ext = asset.ext if asset else ".jpeg"
        return f"{slug}_assets/figure-{n}-original{ext}"

    return resolver


def _article_only(html: str) -> str:
    start = html.find("<article>")
    end = html.find("</article>")
    return html[start : end + len("</article>")] if start >= 0 <= end else html


def roundtrip_document(
    session: Session, repo_root: Path, doc, subdir: str = "rfs"  # noqa: ANN001
) -> DocRoundtrip:
    from .narrative import effective_narrative_label

    published = (repo_root / subdir / f"{doc.slug}.html").read_text()
    meta = {**doc.meta, "narrative_label": effective_narrative_label(session, doc)}
    rendered = render_document(meta, doc.blocks, db_image_src(session, doc))
    result = compare(published, rendered)
    content = compare(_article_only(published), _article_only(rendered))
    return DocRoundtrip(
        slug=doc.slug,
        similarity=result.similarity,
        result=result,
        content_similarity=content.similarity,
        content_diffs=len(content.diffs),
    )


def write_coverage_report(rows: list[DocCoverage], path: Path) -> None:
    lines = [
        "# Import coverage — published memoirs",
        "",
        "Computed against the read-only family-history clone BEFORE migration.",
        "",
        "| Document | Figure blocks | Unique images | Originals found | Sketches found |"
        " Sketch gaps | Source doc | Source found | SHA ok |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in rows:
        gaps = ", ".join(map(str, c.sketch_gaps)) if c.sketch_gaps else "—"
        sha = {True: "✓", False: "MISMATCH", None: "—"}[c.source_sha_ok]
        lines.append(
            f"| {c.slug} | {c.figure_blocks} | {c.unique_images} | {c.originals_found} "
            f"| {c.sketches_found} | {gaps} | {c.source_file or '—'} "
            f"| {'✓' if c.source_found else 'NOT FOUND'} | {sha} |"
        )
    notes = [f"- **{c.slug}**: {note}" for c in rows for note in c.notes]
    if notes:
        lines += ["", "## Notes", *notes]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def write_roundtrip_report(rows: list[DocRoundtrip], path: Path) -> None:
    lines = [
        "# Round-trip validation — published HTML → blocks → HTML",
        "",
        "Per document: parse the published page into the canonical block tree,"
        " re-render with the ported house-style template, and DOM-compare"
        " (whitespace- and attribute-order-insensitive; JSON-LD compared as"
        " parsed JSON). Gate: ≥99% node-level similarity.",
        "",
        "| Document | Full page | Article content | Nodes | Residual diffs | Gate (full ≥99%) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        ok = "PASS" if r.similarity >= SIMILARITY_GATE else "FAIL"
        lines.append(
            f"| {r.slug} | {r.similarity * 100:.3f}% | {r.content_similarity * 100:.3f}% "
            f"| {r.result.total_nodes} | {len(r.result.diffs)} | {ok} |"
        )
    lines.append("")
    for r in rows:
        if not r.result.diffs:
            continue
        lines += [f"## {r.slug} — residual diffs", ""]
        for i, d in enumerate(r.result.diffs, 1):
            lines += [
                f"### diff {i} ({d.op})",
                "",
                "context before:",
                "```html",
                *[f"  {t}" for t in d.context_before],
                "```",
                "published:",
                "```html",
                *[f"  {t}" for t in (d.expected or ["(nothing)"])],
                "```",
                "re-rendered:",
                "```html",
                *[f"  {t}" for t in (d.actual or ["(nothing)"])],
                "```",
                "",
            ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def import_all(
    session: Session,
    workspace: Path,
    repo_root: Path,
    mf_out: Path | None = None,
    mf_work: Path | None = None,
    reports_dir: Path | None = None,
    subdir: str = "rfs",
) -> tuple[list[DocCoverage], list[DocRoundtrip]]:
    slugs = discover_slugs(repo_root, subdir)
    target = get_or_create_pages_target(session, repo_root)
    get_or_create_local_target(session, workspace)

    coverages: list[DocCoverage] = []
    docs = []
    for slug in slugs:
        doc, cov = import_document(
            session, workspace, repo_root, slug, target, mf_out, mf_work, subdir
        )
        docs.append(doc)
        coverages.append(cov)
    import_homepage_settings(session, repo_root)
    session.flush()

    roundtrips = [roundtrip_document(session, repo_root, doc, subdir) for doc in docs]

    if reports_dir:
        write_coverage_report(coverages, reports_dir / "import-coverage.md")
        write_roundtrip_report(roundtrips, reports_dir / "roundtrip.md")
    return coverages, roundtrips


__all__ = [
    "DocCoverage",
    "DocRoundtrip",
    "coverage_for",
    "discover_slugs",
    "import_all",
    "import_document",
    "roundtrip_document",
]
