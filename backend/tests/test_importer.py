"""M4 importer mechanics, tested against the committed real page fixture
with a synthetic assets directory (asset bytes don't matter to the logic;
the real corpus run happens via the CLI and is recorded in reports/)."""

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import FORGE_IMAGE, FORGE_NARRATIVE
from notebook_forge.domcompare import compare
from notebook_forge.importer import (
    coverage_for,
    discover_slugs,
    get_or_create_pages_target,
    import_document,
    roundtrip_document,
)
from notebook_forge.models import Change, SyncState
from notebook_forge.renderer import render_document

FIXTURES = Path(__file__).parent / "fixtures"
SLUG = "1953-1954_in-the-navy"


def make_repo(tmp_path: Path, with_sketches: bool = True, drop_sketch_n: int | None = None) -> Path:
    repo = tmp_path / "repo"
    rfs = repo / "rfs"
    assets = rfs / f"{SLUG}_assets"
    assets.mkdir(parents=True)
    shutil.copy(FIXTURES / "full_page_in_the_navy.html", rfs / f"{SLUG}.html")
    for n in range(1, 16):
        (assets / f"figure-{n}-original.jpeg").write_bytes(b"original-bytes-%d" % n)
        if with_sketches and n != drop_sketch_n:
            (assets / f"figure-{n}-silhouette.png").write_bytes(b"sketch-bytes-%d" % n)
    return repo


def test_discover_and_coverage(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, drop_sketch_n=7)
    assert discover_slugs(repo) == [SLUG]
    cov = coverage_for(repo, SLUG, None, None)
    assert cov.figure_blocks == 15
    assert cov.unique_images == 15
    assert cov.originals_found == 15
    assert cov.sketches_found == 14
    assert cov.sketch_gaps == [7]


def test_import_document_end_to_end(tmp_path: Path, workspace: Path, session: Session) -> None:
    repo = make_repo(tmp_path)
    target = get_or_create_pages_target(session, repo)
    doc, cov = import_document(session, workspace, repo, SLUG, target)
    session.commit()

    # blocks got content-addressed assets, originals paired with sketches
    images = [b for b in doc.blocks if b["type"] == FORGE_IMAGE]
    assert len(images) == 15
    assert all(b["props"]["assetId"] for b in images)
    assert all(b["props"]["sketchAssetId"] for b in images)
    assert len({b["props"]["assetId"] for b in images}) == 15

    # day one shows nothing pending: PUBLISHED + CLEAN
    state = session.scalar(select(SyncState).where(SyncState.document_id == doc.id))
    assert state.status == "PUBLISHED"
    assert state.snapshot_id is not None
    assert state.published_at is not None  # taken from the page's JSON-LD
    assert not services.is_dirty(session, doc, target)

    # the import is in the change log
    kinds = [c.kind for c in session.scalars(select(Change))]
    assert "import" in kinds

    # round trip vs the published file passes the gate
    rt = roundtrip_document(session, repo, doc)
    assert rt.similarity > 0.99

    # metadata captured for rendering
    assert doc.meta["title"] == "In The Navy"
    assert doc.meta["date_prefix"] == "1953-1954"
    assert doc.meta["jsonld"]["author"]["name"] == "Robert Francis Skitch"


def test_asset_rows_deduplicate_across_imports(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    repo = make_repo(tmp_path)
    # a second document whose assets are byte-identical to the first's
    rfs = repo / "rfs"
    second = "1953-1954_in-the-navy-copy"
    shutil.copy(rfs / f"{SLUG}.html", rfs / f"{second}.html")
    shutil.copytree(rfs / f"{SLUG}_assets", rfs / f"{second}_assets")

    from notebook_forge.models import Asset

    target = get_or_create_pages_target(session, repo)
    import_document(session, workspace, repo, SLUG, target)
    session.commit()
    assert len(list(session.scalars(select(Asset)))) == 30  # 15 originals + 15 sketches

    import_document(session, workspace, repo, second, target)
    session.commit()
    # identical bytes → same content addresses → no new asset rows
    assert len(list(session.scalars(select(Asset)))) == 30


# ── M4: narrative post-pass in house-style import ──

NARRATIVE_SLUG = "1960_narrative-test"


def make_narrative_repo(tmp_path: Path) -> Path:
    """Repo with a minimal full-page fixture containing italic paragraphs."""
    repo = tmp_path / "repo"
    rfs = repo / "rfs"
    rfs.mkdir(parents=True)
    shutil.copy(FIXTURES / "full_page_narrative.html", rfs / f"{NARRATIVE_SLUG}.html")
    return repo


def test_import_narrative_converts_paragraphs(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """House-style import: full-italic paragraphs → forgeNarrative; coverage notes present."""
    repo = make_narrative_repo(tmp_path)
    target = get_or_create_pages_target(session, repo)
    doc, cov = import_document(session, workspace, repo, NARRATIVE_SLUG, target)
    session.commit()

    narrative_blocks = [b for b in doc.blocks if b["type"] == FORGE_NARRATIVE]
    assert len(narrative_blocks) == 2  # one ≥12-word + one <12-word italic paragraph

    # coverage notes contain the flag line for the short one
    notes_text = " ".join(cov.notes)
    assert "forgeNarrative" in notes_text  # conversion count note
    assert "narrative <12 words" in notes_text  # flag note for short passage


def test_narrative_roundtrip_idempotent(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """Self-idempotence gate (D15): parse+convert → render → parse must round-trip perfectly."""
    from notebook_forge.parser import parse_page

    src = (FIXTURES / "full_page_narrative.html").read_text()
    from notebook_forge.narrative import convert_full_italic_paragraphs

    page = parse_page(src)
    page.blocks, _ = convert_full_italic_paragraphs(page.blocks)

    # r1 = render from converted blocks
    r1 = render_document({"title": "T", "show_toc": False}, page.blocks, lambda b, n: "")

    # parse r1 → should produce same narrative blocks (panel splits back to consecutive blocks)
    page2 = parse_page(r1)
    narrative1 = [b for b in page.blocks if b["type"] == FORGE_NARRATIVE]
    narrative2 = [b for b in page2.blocks if b["type"] == FORGE_NARRATIVE]
    assert len(narrative2) == len(narrative1)
    # content matches (ignoring ids)
    from notebook_forge.blocks import content_hash
    assert content_hash(narrative2) == content_hash(narrative1)

    # r2 = render from re-parsed blocks → DOM-equal to r1 at 100%
    r2 = render_document({"title": "T", "show_toc": False}, page2.blocks, lambda b, n: "")
    result = compare(r1, r2)
    assert result.equal, [d.expected for d in result.diffs]
