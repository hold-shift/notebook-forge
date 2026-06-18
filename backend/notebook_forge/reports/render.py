"""Render the locked §0–§6 report body from structured data.

Mirrors `build_report` in the standalone `notebook_forge_reports.py`: the same
section order, headings, the fixed provenance note, and the "(none …)"
fallbacks. This is the single source of truth for the Drive Doc body and any
preview — `service.py` calls it once at generation and stores the result as
`Report.body_md`.

§6 is a compact counts summary that points at the master reference tables; the
full per-document rows are persisted as ReportTrack and pooled into the
master CSVs (see master.py), so they are never inlined here. Inlining the CSVs
both duplicated the master and was the single biggest page inflator once the
Markdown was converted to a Google Doc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# (track_type, summary label) in the locked order.
_TRACK_LABELS = [
    ("people", "People"),
    ("geo", "Places"),
    ("glossary", "Glossary terms"),
    ("chronology", "Chronology entries"),
]

_NOTE = (
    "This is a derived analytical summary generated from the source memoir. "
    "It is a navigational index, not a primary record. Where this summary and "
    "the original memoir differ, **the original memoir is authoritative.** "
    "Interpretive statements are tagged [INFERENCE]."
)


@dataclass
class ReportData:
    """Everything render_report needs, assembled by service.py."""

    title: str
    author: str
    years: str
    source_name: str
    word_count: int
    exec_summary: str
    digest_md: str
    stated: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    inconsistencies: list[str] = field(default_factory=list)
    anchors: list[dict[str, Any]] = field(default_factory=list)
    # track_type -> ordered list of stored row dicts (section/name/role, …).
    tracks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _bullets(items: list[str], empty: str) -> str:
    return "\n".join(f"- {it}" for it in items) if items else empty


def render_report(data: ReportData) -> str:
    """Assemble the full report Markdown body."""
    parts: list[str] = []
    parts.append(f"# Analytical Report — *{data.title}*\n")

    parts.append("### 0. Provenance header\n")
    parts.append(
        f"- **Document:** *{data.title}* ({data.author})\n"
        f"- **Period covered:** {data.years}\n"
        f"- **Source word count:** {data.word_count:,}\n"
        f"- **Source name (NotebookLM):** {data.source_name}\n"
        f"- **Note:** {_NOTE}"
    )

    parts.append("\n### 1. Executive summary\n")
    parts.append(data.exec_summary.strip() or "- (none generated)")

    parts.append("\n### 2. Section-by-section digest\n")
    parts.append(data.digest_md.strip() or "- (none)")

    parts.append("\n### 3. Interpersonal & familial dynamics\n")
    parts.append("**Stated:**\n" + _bullets(data.stated, "- (none recorded)"))
    parts.append("\n**[INFERENCE]:**\n" + _bullets(data.inferences, "- (none)"))

    parts.append("\n### 4. Source inconsistencies & open questions\n")
    parts.append(_bullets(data.inconsistencies, "- (none identified)"))

    parts.append("\n### 5. Notable verbatim anchors\n")
    anchor_lines = [
        f'- *{a.get("section", "")}* — {a.get("attribution", "")}: "{a.get("quote", "")}"'
        for a in data.anchors
    ]
    parts.append("\n".join(anchor_lines) if anchor_lines else "- (none selected)")

    parts.append("\n### 6. Reference tracks\n")
    parts.append(render_tracks_section(data.tracks))

    return "\n".join(parts) + "\n"


def render_tracks_section(tracks: dict[str, list[dict[str, Any]]]) -> str:
    """The §6 body: a compact per-track counts summary, not inline CSV.

    The full rows live in ReportTrack and are pooled into the master CSVs;
    inlining them here duplicated the master and inflated the Google Doc.
    """
    lines = [
        "This report's structured reference data is maintained in the master "
        "reference tables, not inline. For this document:",
        "",
    ]
    lines += [
        f"- {label}: {len(tracks.get(track_type, []))}"
        for track_type, label in _TRACK_LABELS
    ]
    lines += [
        "",
        "Full rows — each carrying its `source` column — are pooled into the "
        "master reference tables (master_people, master_geography, "
        "master_glossary, master_chronology) maintained as Google Sheets in Drive.",
    ]
    return "\n".join(lines)
