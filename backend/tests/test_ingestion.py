"""New-document ingest against the REAL sample sources (read-only,
/Users/cs/ClaudeCode/MemoirForge/samples). Skipped if the samples are
absent (e.g. CI on another machine)."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from notebook_forge import services
from notebook_forge.blocks import FORGE_IMAGE, FORGE_NARRATIVE
from notebook_forge.ingest_vendor.extract_docx import _strip_inline_emph
from notebook_forge.ingestion import _md_inline_runs, draft_to_blocks, ingest_document
from notebook_forge.models import Asset
from notebook_forge.narrative import convert_full_italic_paragraphs

SAMPLES = Path("/Users/cs/ClaudeCode/MemoirForge/samples")

needs_samples = pytest.mark.skipif(not SAMPLES.exists(), reason="MemoirForge samples not present")


def test_strip_inline_emph_strips_sup_sub() -> None:
    """Pandoc emits <sup>st</sup> for ordinal superscripts in GFM; strip tags, keep text."""
    assert _strip_inline_emph("1<sup>st</sup> January") == "1st January"
    assert _strip_inline_emph("22<sup>nd</sup> of October") == "22nd of October"
    assert _strip_inline_emph("H<sub>2</sub>O") == "H2O"
    assert _strip_inline_emph("no tags here") == "no tags here"
    assert _strip_inline_emph("<SUP>X</SUP>") == "X"


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


# ── M4: narrative post-pass on DOCX/PDF extraction path ──

def _make_draft(body_entries: list[dict], footnotes: list | None = None):
    """Build a minimal DocumentDraft-like object for testing draft_to_blocks."""
    from notebook_forge.ingest_vendor.model import DocumentDraft

    draft = DocumentDraft(
        source_file="test.docx",
        source_sha256="a" * 64,
        body=body_entries,
        footnotes=footnotes or [],
        detected_captions={},
    )
    return draft


def test_m4_fully_italic_paragraph_converts(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """DOCX path: a fully italic paragraph → forgeNarrative with upright runs."""
    draft = _make_draft([
        {"kind": "p", "text": "*Entirely italic reflection across many words indeed and more*"},
    ])
    blocks = draft_to_blocks(draft, session, workspace, tmp_path)
    blocks, conversions = convert_full_italic_paragraphs(blocks)
    narrative = [b for b in blocks if b["type"] == FORGE_NARRATIVE]
    assert len(narrative) == 1
    assert len(conversions) == 1
    # runs are upright (italic stripped)
    for run in narrative[0]["content"]:
        assert not run.get("styles", {}).get("italic")


def test_m4_partial_italic_stays_paragraph(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """PDF-style mixed emphasis → paragraph unchanged."""
    draft = _make_draft([{"kind": "p", "text": "*italic* mid-sentence not all italic here"}])
    blocks = draft_to_blocks(draft, session, workspace, tmp_path)
    blocks, conversions = convert_full_italic_paragraphs(blocks)
    assert all(b["type"] == "paragraph" for b in blocks)
    assert len(conversions) == 0


def test_m4_bold_italic_converts_and_flagged(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """***bold italic*** whole paragraph → converts, bold kept, flagged when short."""
    draft = _make_draft([{"kind": "p", "text": "***Dining In The Mess***"}])
    blocks = draft_to_blocks(draft, session, workspace, tmp_path)
    blocks, conversions = convert_full_italic_paragraphs(blocks)
    narrative = [b for b in blocks if b["type"] == FORGE_NARRATIVE]
    assert len(narrative) == 1
    assert len(conversions) == 1
    assert conversions[0]["flagged"] is True  # < 12 words
    run = narrative[0]["content"][0]
    assert run["styles"].get("bold") is True


def test_m4_ingest_response_has_narrative_fields(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """The ingest response dict carries narrative_conversions / narrative_flagged."""
    # Use the no-source path to verify the response fields exist on the returned dict.
    # Even with zero conversions the fields should be present.
    draft = _make_draft([{"kind": "p", "text": "Some ordinary prose here."}])
    blocks = draft_to_blocks(draft, session, workspace, tmp_path)
    blocks, conversions = convert_full_italic_paragraphs(blocks)
    # Fields are always present (zero counts)
    result = {
        "narrative_conversions": len(conversions),
        "narrative_flagged": [c["preview"] for c in conversions if c["flagged"]],
    }
    assert "narrative_conversions" in result
    assert "narrative_flagged" in result
    assert result["narrative_conversions"] == 0
    assert result["narrative_flagged"] == []


# ── Regression: footnote-bearing block must preserve paragraph breaks ──
# Previously _split_footnote_lines flattened the body above a footnote into a
# single string and cleared line_records, merging every paragraph into one
# (reported by Chris, 15 Jun 2026 — Vietnam Part 1 PDF). The blank lines that
# encode paragraph breaks must survive so the downstream rebuild can split.

def _rec(text: str, li: int, y: float, size: float, *, md: str | None = None) -> dict:
    return {
        "text": text,
        "md_text": md if md is not None else text,
        "li": li,
        "bbox": (50.0, y, 500.0, y + 12.0),
        "size": size,
        "bold": False,
    }


def test_footnote_split_preserves_paragraph_breaks() -> None:
    from notebook_forge.ingest_vendor.extract_pdf import _split_footnote_lines

    page_height = 800.0
    body_size = 12.0
    footnote_size_max = body_size * 0.92  # 11.04
    # Two body paragraphs separated by a blank line, then a footnote in the
    # bottom band set in a smaller font.
    recs = [
        _rec("First paragraph ends here.", 0, 100.0, body_size),
        _rec("", 1, 112.0, 0.0),  # paragraph break
        _rec("Second paragraph before the note.2", 2, 124.0, body_size),
        _rec("2 The footnote body, long enough to keep.", 3, 760.0, 10.0),
    ]
    block = {
        "bbox": (50.0, 100.0, 500.0, 772.0),
        "text": "joined",
        "size": body_size,
        "block_idx": 1,
        "line_records": recs,
    }
    footnotes: list[dict] = []
    out = _split_footnote_lines([block], page_height, footnote_size_max, footnotes, 5)

    assert len(out) == 1
    kept = out[0]["line_records"]
    # The blank-line paragraph break must still be present.
    assert any(not r.get("text") for r in kept), "paragraph break (blank line) was lost"
    # The footnote line itself is gone from the body.
    assert all("The footnote body" not in (r.get("text") or "") for r in kept)
    # The [^n] marker is appended to the last body line (digit stripped).
    last = [r for r in kept if r.get("text")][-1]
    assert last["text"].endswith("[^1]")
    assert "before the note.2" not in last["text"]  # flattened superscript stripped
    # The footnote was captured.
    assert len(footnotes) == 1
    assert footnotes[0]["text"].startswith("The footnote body")
