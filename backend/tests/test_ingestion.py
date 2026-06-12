"""New-document ingest against the REAL sample sources (read-only,
/Users/cs/ClaudeCode/MemoirForge/samples). Skipped if the samples are
absent (e.g. CI on another machine)."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import FORGE_IMAGE
from notebook_forge.ingestion import _md_inline_runs, ingest_document
from notebook_forge.models import Asset

SAMPLES = Path("/Users/cs/ClaudeCode/MemoirForge/samples")

needs_samples = pytest.mark.skipif(not SAMPLES.exists(), reason="MemoirForge samples not present")


def test_md_inline_runs() -> None:
    runs = _md_inline_runs("plain **bold** and *italic* end[^2] tail")
    texts = [(r["text"], r["styles"]) for r in runs]
    assert ("bold", {"bold": True}) in texts
    assert ("italic", {"italic": True}) in texts
    assert ("2", {"fnRef": True}) in texts
    assert "".join(r["text"] for r in runs) == "plain bold and italic end2 tail"


@needs_samples
def test_ingest_docx(workspace: Path, session: Session) -> None:
    detail = ingest_document(session, workspace, SAMPLES / "Test_Word_Document.docx")
    session.commit()
    assert detail["detected_date"]
    doc = services.get_document(session, detail["slug"])
    assert doc is not None
    assert doc.meta["date_confirmed"] is False

    figures = [b for b in doc.blocks if b["type"] == FORGE_IMAGE]
    assert len(figures) == detail["figures"] > 0
    for fig in figures:
        assert fig["props"]["assetId"], "original ingested into the asset store"
        assert fig["props"]["sketchAssetId"] == ""  # sketches come from Generate
        assert fig["props"]["approval"] == "pending"
    # the known caption from the test doc survived
    assert any("Baby Junior" in f["props"]["caption"] for f in figures)
    # source file archived
    src = session.get(Asset, doc.meta["source_asset_id"])
    assert src.kind == "sources"
    assert src.filename == "Test_Word_Document.docx"
    # H1 (title) is meta, not body
    assert not any(
        b["type"] == "heading" and b["props"].get("level") == 1 for b in doc.blocks
    )


@needs_samples
def test_ingest_pdf_with_geometric_captions(workspace: Path, session: Session) -> None:
    detail = ingest_document(session, workspace, SAMPLES / "Test_PDF_Doc.pdf")
    session.commit()
    doc = services.get_document(session, detail["slug"])
    figures = [b for b in doc.blocks if b["type"] == FORGE_IMAGE]
    assert len(figures) >= 20  # the Berlin doc is image-heavy
    captioned = [f for f in figures if f["props"]["caption"]]
    assert len(captioned) >= 10  # geometry-matched captions came through
    assert any("Tacheles" in f["props"]["caption"] for f in figures)


@needs_samples
def test_ingest_slug_collision_appends_suffix(workspace: Path, session: Session) -> None:
    d1 = ingest_document(session, workspace, SAMPLES / "Test_Word_Document.docx")
    session.commit()
    d2 = ingest_document(session, workspace, SAMPLES / "Test_Word_Document.docx")
    session.commit()
    assert d2["slug"] == f"{d1['slug']}-2"


def test_unsupported_type_refuses(workspace: Path, session: Session, tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(ValueError, match="unsupported source type"):
        ingest_document(session, workspace, bad)


@needs_samples
def test_reingest_carries_figure_work_over(workspace: Path, session: Session) -> None:
    from notebook_forge.ingestion import reingest_document
    from notebook_forge.models import Snapshot

    detail = ingest_document(session, workspace, SAMPLES / "Test_Word_Document.docx")
    session.commit()
    doc = services.get_document(session, detail["slug"])

    # simulate operator figure work: sketch attached, approved, caption edit
    blocks = [dict(b) for b in doc.blocks]
    fig = next(b for b in blocks if b["type"] == FORGE_IMAGE)
    fig["props"] = {
        **fig["props"],
        "sketchAssetId": "f" * 64,
        "approval": "approved",
        "caption": "An edited caption.",
    }
    services.save_blocks(session, doc, blocks, summary="figure work")
    asset_id = fig["props"]["assetId"]
    session.commit()

    result = reingest_document(session, workspace, doc)
    session.commit()

    assert result["figures_matched"] >= 1
    refreshed = next(
        b for b in doc.blocks
        if b["type"] == FORGE_IMAGE and b["props"]["assetId"] == asset_id
    )
    assert refreshed["props"]["sketchAssetId"] == "f" * 64
    assert refreshed["props"]["approval"] == "approved"
    assert refreshed["props"]["caption"] == "An edited caption."
    # a safety snapshot exists
    notes = [s.note for s in session.query(Snapshot).filter_by(document_id=doc.id)]
    assert "before re-ingest from source" in notes
    # meta untouched (title/date confirmation state preserved)
    assert doc.meta["source_file"] == "Test_Word_Document.docx"


def test_reingest_without_source_refuses(workspace: Path, session: Session) -> None:
    from notebook_forge.ingestion import reingest_document

    doc = services.create_document(session, "no-source", "No Source", [])
    session.commit()
    with pytest.raises(LookupError, match="no archived source"):
        reingest_document(session, workspace, doc)
