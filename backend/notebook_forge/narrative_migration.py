"""One-time migration: full-italic paragraph blocks → forgeNarrative
(rule B via narrative.convert_full_italic_paragraphs).

Two phases (locked decision D13): a DRY RUN that writes
reports/narrative_migration.md, then an APPLY that snapshots every
affected document first. Guarded by the 'narrative_migration' Setting so
a casual re-run cannot re-convert paragraphs an operator deliberately
converted back in the editor (--force overrides). Homepage excluded (D13).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

MARKER_KEY = "narrative_migration"


def scan(session: Session) -> list[dict[str, Any]]:
    """Return a row per document (incl. zero-conversion docs for full coverage)."""
    from . import services
    from .narrative import convert_full_italic_paragraphs

    rows: list[dict[str, Any]] = []
    for doc in services.list_documents(session):
        if doc.kind == "homepage":
            continue
        _, conversions = convert_full_italic_paragraphs(doc.blocks)
        rows.append({
            "slug": doc.slug,
            "title": doc.title,
            "count": len(conversions),
            "conversions": conversions,
        })
    return rows


def already_applied(session: Session) -> dict[str, Any] | None:
    """Return the marker Setting value, or None if not yet applied."""
    from .models import Setting
    s = session.get(Setting, MARKER_KEY)
    return s.value if s is not None else None


def apply(session: Session) -> list[dict[str, Any]]:
    """Snapshot, convert, and record. Returns applied rows (count > 0 only)."""
    from . import services
    from .models import Setting
    from .narrative import convert_full_italic_paragraphs

    applied: list[dict[str, Any]] = []
    converted_map: dict[str, int] = {}

    for row in scan(session):
        if row["count"] == 0:
            continue
        doc = services.get_document(session, row["slug"])
        if doc is None:
            continue
        new_blocks, conversions = convert_full_italic_paragraphs(doc.blocks)
        services.snapshot_document(session, doc, note="before narrative migration")
        summary = f"narrative migration: {len(conversions)} paragraph(s) converted"
        services.save_blocks(session, doc, new_blocks, summary=summary)
        converted_map[doc.slug] = len(conversions)
        applied.append(row)

    marker_value: dict[str, Any] = {
        "applied_at": dt.datetime.now(dt.UTC).isoformat(),
        "converted": converted_map,
    }
    existing = session.get(Setting, MARKER_KEY)
    if existing is None:
        session.add(Setting(key=MARKER_KEY, value=marker_value))
    else:
        existing.value = marker_value
    return applied


def write_report(reports_dir: Path, rows: list[dict[str, Any]], mode: str) -> None:
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_docs = len(rows)
    affected = sum(1 for r in rows if r["count"] > 0)
    total_conversions = sum(r["count"] for r in rows)

    lines = [
        "# Narrative migration report",
        "",
        f"Mode: **{mode}** · Generated: {ts}",
        f"Documents scanned: {total_docs} · Affected: {affected} "
        f"· Conversions: {total_conversions}",
        "",
    ]

    for row in rows:
        if row["count"] == 0:
            continue
        lines += [f"## {row['slug']} — {row['count']} conversion(s)", ""]
        for c in row["conversions"]:
            flag = "[FLAG <12 words] " if c.get("flagged") else ""
            words = c.get("words", "?")
            preview = c.get("preview", "")
            lines.append(f'- {flag}"{preview}" ({words} words)')
        lines.append("")

    no_conversion_slugs = [r["slug"] for r in rows if r["count"] == 0]
    if no_conversion_slugs:
        lines += [
            "## No conversions",
            "",
            ", ".join(no_conversion_slugs),
            "",
        ]

    lines += [
        "---",
        "",
        "**Rollback:** every applied document has a snapshot 'before narrative migration'.",
        "Restore it from the editor's Snapshots panel or via the API rollback endpoint.",
        "",
    ]

    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "narrative_migration.md").write_text("\n".join(lines) + "\n")
