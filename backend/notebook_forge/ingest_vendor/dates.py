"""Year / year-range detection.

Spec §6 S4 / PRD §5 step 4:
  - 4-digit year scan over body text, sane range (1850 → current_year)
  - Also scan filename for a year
  - Propose single year, or earliest-latest range

Naïve min/max widens to nonsense on memoirs that reference a historical
date and a publication date (e.g. 1860 origin story + 2010 writing date
yields 1860-2010 when the memoir is *about* 1934-1945). We instead find
the densest cluster of mentions — the period the memoir actually covers
— and quote that range. Filename years are weighted higher since they're
the operator's strongest a-priori signal.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from .model import DocumentDraft

# Match 4-digit years not glued to other digits. `\b` is too strict around
# underscores (which are word chars), so use look-arounds for digit boundaries.
_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2}|21\d{2})(?!\d)")
_MIN_YEAR = 1850
_MAX_YEAR = datetime.now().year + 1   # tolerate "this year"
_CLUSTER_SPAN = 15                    # densest N-year window wins
_FILENAME_WEIGHT = 5                  # filename year mentions weighted higher


def detect_year_range(draft: DocumentDraft) -> tuple[str, str]:
    """Return (detected, display) for the draft.

    detected: ASCII-safe filename form ("1953" or "1934-1945")
    display:  human form with en-dash ("1953" or "1934–1945")
    Empty strings if nothing found.
    """
    counts: Counter[int] = Counter()
    for b in draft.blocks:
        for m in _YEAR_RE.finditer(b.text):
            y = int(m.group(0))
            if _MIN_YEAR <= y <= _MAX_YEAR:
                counts[y] += 1
    for y in _years_from_filename(draft.source_file):
        if _MIN_YEAR <= y <= _MAX_YEAR:
            counts[y] += _FILENAME_WEIGHT

    if not counts:
        return "", ""

    if len(counts) == 1:
        y = next(iter(counts))
        return str(y), str(y)

    lo, hi = _densest_cluster(counts)
    if lo == hi:
        return str(lo), str(lo)
    return f"{lo}-{hi}", f"{lo}–{hi}"   # en-dash for display


def _densest_cluster(counts: Counter[int]) -> tuple[int, int]:
    """Pick the cluster that maximises total weight in a CLUSTER_SPAN window,
    then trim to the years that actually carry weight within it."""
    sorted_years = sorted(counts)
    best_weight = -1
    best_lo, best_hi = sorted_years[0], sorted_years[-1]
    for start in sorted_years:
        end = start + _CLUSTER_SPAN
        in_window = [y for y in sorted_years if start <= y <= end]
        weight = sum(counts[y] for y in in_window)
        if weight > best_weight:
            best_weight = weight
            best_lo, best_hi = in_window[0], in_window[-1]
    return best_lo, best_hi


def _years_from_filename(name: str) -> set[int]:
    return {int(m.group(0)) for m in _YEAR_RE.finditer(name)}
