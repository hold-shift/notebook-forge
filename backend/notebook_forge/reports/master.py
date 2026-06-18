"""Corpus-wide master reference tracks.

Pools every document's ReportTrack rows by track type into four CSVs for
NotebookLM Data Tables. Pooling is NOT reconciliation: the same person can
legitimately appear under several sources, and the `source` column keeps every
row traceable. No cross-document merging happens here — that is a separate,
later, human-in-the-loop pass.

Idempotency is structural: ReportTrack rows ARE the source of truth, and
per-document regeneration already replaces a source's rows (service._persist).
So building the master is a pure read of the current rows — regenerating one
document and rebuilding the master reflects exactly that document's new rows,
with every other source untouched.

Rows are ordered by (source_name, seq) so each source's rows stay grouped and
in document order.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ReportTrack
from .csvbuild import TRACK_HEADERS, TRACK_TYPES, row_from_data, write_csv

# Drive filenames per track type (note: geo → "geography").
MASTER_FILENAMES: dict[str, str] = {
    "people": "master_people.csv",
    "geo": "master_geography.csv",
    "glossary": "master_glossary.csv",
    "chronology": "master_chronology.csv",
}


def build_master_csvs(session: Session) -> dict[str, str]:
    """Return {track_type: csv_text} for all four tracks, pooled across docs."""
    out: dict[str, str] = {}
    for track_type in TRACK_TYPES:
        rows = session.scalars(
            select(ReportTrack)
            .where(ReportTrack.track_type == track_type)
            .order_by(ReportTrack.source_name, ReportTrack.seq)
        ).all()
        csv_rows = [row_from_data(track_type, r.source_name, r.data) for r in rows]
        out[track_type] = write_csv(TRACK_HEADERS[track_type], csv_rows)
    return out


def master_stats(session: Session) -> dict[str, Any]:
    """Counts for the master status line: documents, total rows, per-track."""
    by_track = dict(
        session.execute(
            select(ReportTrack.track_type, func.count())
            .group_by(ReportTrack.track_type)
        ).all()
    )
    documents = session.scalar(
        select(func.count(func.distinct(ReportTrack.source_name)))
    ) or 0
    return {
        "documents": documents,
        "rows": sum(by_track.values()),
        "by_track": {tt: by_track.get(tt, 0) for tt in TRACK_TYPES},
    }
