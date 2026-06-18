"""Report generation orchestration.

Flow (mirrors polish/service.py's shape; injectable runner for tests):
  1. Read provenance from Document.meta (+ computed word count).
  2. Chunk doc.blocks into chapters.
  3. Run every chapter (concurrent) → structured digests; one consolidation
     call for the executive summary + selected anchors.
  4. Assemble the reference-track rows in code (intra-document dedup) — these
     become the canonical ReportTrack rows AND feed render's §6.
  5. Render the §0–§6 body once.
  6. Replace the document's Report + ReportTrack rows (delete + insert) so the
     master rebuild stays idempotent by source.
  7. Record the run in the change log. doc.blocks is never modified.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import services
from ..models import Document, Report, ReportTrack, Setting, utcnow
from .chunker import chunk_document
from .csvbuild import TRACK_FIELDS, TRACK_TYPES
from .render import ReportData, render_report
from .runner import REPORT_MODEL, GeminiReportRunner, run_chunks


def report_settings(session: Session) -> dict[str, Any]:
    """Operator-controlled report settings (default gemini-3.5-flash, no rules)."""
    row = session.get(Setting, "reports")
    value = dict(row.value) if row else {}
    return {
        "model": value.get("model") or REPORT_MODEL,
        "rules": value.get("rules") or "",
    }


def build_provenance(doc: Document) -> dict[str, Any]:
    """Report header fields, taken from the Document record / its meta.

    Source name matches the safe edition's Drive file (meta.slug → doc.slug).
    Word count is computed, not stored.
    """
    from ..collection import count_words

    meta = doc.meta or {}
    return {
        "title": meta.get("title") or doc.title,
        "author": meta.get("author", ""),
        "years": meta.get("year_display", ""),
        "source_name": meta.get("slug") or doc.slug,
        "word_count": count_words(doc.blocks),
    }


# ---------------------------------------------------------------- dedup (intra-doc)

def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def _dedup_keep_first(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Keep the earliest row per normalised key; drop rows with an empty key."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = _norm(str(row.get(key, "")))
        if k and k not in seen:
            seen.add(k)
            out.append(row)
    return out


def _dedup_lines(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        k = _norm(item)
        if k and k not in seen:
            seen.add(k)
            out.append(item.strip())
    return out


def _collect_tracks(
    chapters_data: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Pool per-chapter rows in document order, then dedup intra-document.

    people/geo/glossary keep first occurrence; chronology keeps every row.
    Each stored row is normalised to exactly its track's fields.
    """
    pooled: dict[str, list[dict[str, Any]]] = {tt: [] for tt in TRACK_TYPES}
    for _title, data in chapters_data:
        for track_type in TRACK_TYPES:
            for row in data.get(track_type, []):
                if isinstance(row, dict):
                    pooled[track_type].append(row)

    deduped = {
        "people": _dedup_keep_first(pooled["people"], "name"),
        "geo": _dedup_keep_first(pooled["geo"], "place"),
        "glossary": _dedup_keep_first(pooled["glossary"], "term"),
        "chronology": pooled["chronology"],  # keep all, document order
    }
    # Store only the known fields per track so ReportTrack.data stays tidy.
    return {
        track_type: [
            {f: str(row.get(f, "") or "") for f in TRACK_FIELDS[track_type]}
            for row in rows
        ]
        for track_type, rows in deduped.items()
    }


# ---------------------------------------------------------------- generation

def generate_report(
    session: Session,
    workspace: Path,  # noqa: ARG001 — kept for signature parity with polish/publish
    doc: Document,
    *,
    runner: GeminiReportRunner | None = None,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate (or regenerate) the analytical report for one document.

    runner can be injected in tests; when None it is built from the keychain
    key (RuntimeError → 409 if no key). Returns a summary of the run.
    """
    cfg = report_settings(session)
    prov = build_provenance(doc)
    source_name = prov["source_name"]

    chunks = chunk_document(doc.blocks)
    if progress is not None:
        progress["total"] = len(chunks)

    if runner is None:
        from .runner import make_runner
        runner = make_runner(cfg["model"])

    def _on_chunk_done(failed: bool) -> None:
        if progress is not None:
            progress["done"] += 1
            if failed:
                progress["failed"] += 1

    chapters_data, failed_chapters = run_chunks(
        chunks, runner, source_name, extra_rules=cfg["rules"], on_chunk_done=_on_chunk_done,
    )

    tracks = _collect_tracks(chapters_data)
    # Raw pooled §3/§4 material: source for the consolidation synthesis and the
    # fallback if the model omits a curated field.
    raw_stated = _dedup_lines(
        [s for _, d in chapters_data for s in d.get("interpersonal_stated", [])]
    )
    raw_inference = _dedup_lines(
        [s for _, d in chapters_data for s in d.get("interpersonal_inference", [])]
    )
    raw_inconsistencies = _dedup_lines(
        [s for _, d in chapters_data for s in d.get("inconsistencies", [])]
    )
    digest_md = "\n\n".join(
        d["digest_md"].strip() for _, d in chapters_data if d.get("digest_md")
    )

    consolidated = runner.consolidate(
        source_name, prov["years"], chapters_data,
        stated=raw_stated, inference=raw_inference, inconsistencies=raw_inconsistencies,
        extra_rules=cfg["rules"],
    )

    # Render §3/§4 from the curated output; defensively fall back to the raw
    # pooled lists (covers stub runners that bypass parse_consolidate_json).
    body_md = render_report(
        ReportData(
            title=prov["title"],
            author=prov["author"],
            years=prov["years"],
            source_name=source_name,
            word_count=prov["word_count"],
            exec_summary=consolidated.get("executive_summary", ""),
            digest_md=digest_md,
            stated=consolidated.get("interpersonal_stated") or raw_stated,
            inferences=consolidated.get("interpersonal_inference") or raw_inference,
            inconsistencies=consolidated.get("inconsistencies") or raw_inconsistencies,
            anchors=consolidated.get("anchors", []),
            tracks=tracks,
        )
    )

    model_name = runner.model if hasattr(runner, "model") else cfg["model"]
    status = "failed" if chunks and not chapters_data else "generated"
    _persist(
        session, doc, source_name, model_name, status,
        consolidated.get("executive_summary", ""), body_md, tracks,
    )

    n_tracks = {tt: len(rows) for tt, rows in tracks.items()}
    services.record_change(
        session, doc, "edit",
        f"report run: {len(chapters_data)}/{len(chunks)} chapters"
        + (f", {len(failed_chapters)} failed" if failed_chapters else ""),
        detail={
            "model": model_name,
            "chapters": len(chunks),
            "chapters_done": len(chapters_data),
            "failed_chapters": len(failed_chapters),
            "tracks": n_tracks,
            "status": status,
            "consolidation_error": consolidated.get("consolidation_error"),
        },
    )

    return {
        "status": status,
        "model": model_name,
        "chapters": len(chunks),
        "chapters_done": len(chapters_data),
        "failed_chapters": failed_chapters,
        "tracks": n_tracks,
        "anchors": len(consolidated.get("anchors", [])),
        "consolidation_error": consolidated.get("consolidation_error"),
    }


def _persist(
    session: Session,
    doc: Document,
    source_name: str,
    model: str,
    status: str,
    exec_summary: str,
    body_md: str,
    tracks: dict[str, list[dict[str, Any]]],
) -> Report:
    """Replace the document's Report + ReportTrack rows (delete + insert)."""
    session.execute(delete(ReportTrack).where(ReportTrack.document_id == doc.id))
    content_hash = services.effective_content_hash(session, doc)
    report = get_report(session, doc)
    if report is None:
        report = Report(document_id=doc.id)
        session.add(report)
    report.source_name = source_name
    report.model = model
    report.status = status
    report.exec_summary = exec_summary
    report.body_md = body_md
    report.content_hash = content_hash
    # Stamp generation time explicitly (the column is no longer onupdate), so a
    # later push doesn't bump it. pushed_at / drive_file_id are left intact —
    # the prior Drive Doc still exists and stays linked — and the freshly bumped
    # generated_at now exceeds pushed_at, which is what flags "needs push".
    report.generated_at = utcnow()
    session.flush()

    for track_type, rows in tracks.items():
        for seq, data in enumerate(rows):
            session.add(
                ReportTrack(
                    document_id=doc.id,
                    source_name=source_name,
                    track_type=track_type,
                    seq=seq,
                    data=data,
                )
            )
    return report


def get_report(session: Session, doc: Document) -> Report | None:
    from sqlalchemy import select
    return session.scalar(select(Report).where(Report.document_id == doc.id))


def report_is_stale(session: Session, doc: Document, report: Report) -> bool:
    """A report is stale once the document content diverges from generation."""
    return services.effective_content_hash(session, doc) != report.content_hash


def report_needs_push(report: Report | None) -> bool:
    """True when the current generation has not yet been pushed to Drive —
    never pushed, or regenerated since the last push."""
    if report is None:
        return False
    if report.pushed_at is None:
        return True
    return report.generated_at > report.pushed_at
