"""CSV assembly for the reference tracks — code-side, never hand-formatted.

Ported from `notebook_forge_reports.py` (`csv_block` / `_validate_csv`): rows
are written with `csv.writer` (QUOTE_MINIMAL) so embedded commas, quotes and
newlines always escape correctly. Two consumers share this:

- `render.py` wraps each track in a ```csv fenced block for the report §6.
- `master.py` emits raw `.csv` files for upload to Drive as NotebookLM Data
  Tables.

Hand-formatting these strings broke on commas/quotes during prototyping; the
writer plus the width self-check (`validate_widths`) prevent that regression.
"""
from __future__ import annotations

import csv
import io

# Track CSV headers — must match the schemas locked in the build plan §4.4 and
# the validated reference reports.
TRACK_HEADERS: dict[str, list[str]] = {
    "people": ["source", "section", "name", "role_or_relationship"],
    "geo": ["source", "section", "place", "what_occurred_there", "arrival_or_movement"],
    "glossary": ["source", "section", "term", "meaning"],
    "chronology": ["source", "section", "date_or_marker", "event"],
}

# The stored ReportTrack.data keys that fill each track's columns after the
# leading `source` column. These are the model's own row keys (see the chapter
# JSON contract), distinct from the CSV header labels above.
TRACK_FIELDS: dict[str, list[str]] = {
    "people": ["section", "name", "role"],
    "geo": ["section", "place", "what", "arrival"],
    "glossary": ["section", "term", "meaning"],
    "chronology": ["section", "marker", "event"],
}

TRACK_TYPES = tuple(TRACK_HEADERS)


def row_from_data(track_type: str, source: str, data: dict) -> list[str]:
    """Map a stored track-row dict to its CSV row: [source, *fields]."""
    return [source, *(str(data.get(f, "") or "") for f in TRACK_FIELDS[track_type])]


def write_csv(header: list[str], rows: list[list[str]]) -> str:
    """Render header + rows to a CSV string (QUOTE_MINIMAL, \\n line endings)."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().rstrip("\n") + "\n"


def csv_block(header: list[str], rows: list[list[str]]) -> str:
    """A fenced ```csv block (header + rows) for embedding in the report body."""
    body = write_csv(header, rows).rstrip("\n")
    return f"```csv\n{body}\n```"


def validate_widths(csv_text: str) -> int:
    """Parse a CSV string and assert every row has the same column count.

    Returns the (single) column width. Raises ValueError on a width mismatch —
    the prototyping regression this whole module exists to prevent.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    widths = {len(r) for r in rows}
    if len(widths) > 1:
        raise ValueError(f"CSV column-width mismatch: {sorted(widths)}")
    return next(iter(widths)) if widths else 0
