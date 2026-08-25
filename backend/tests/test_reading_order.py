"""One reading order for the archive: the library's own.

Groups in their library order, each group's members in the operator's manual
(drag) order, ungrouped last — driving both the homepage timeline and the
prev/next footer, so the two can never disagree again.
"""

from __future__ import annotations

from notebook_forge.collection import nav_for
from notebook_forge.groups import (
    _start_year,
    assign_document,
    create_group,
    reading_order,
    set_positions,
)
from notebook_forge.homepage import homepage_timeline
from notebook_forge.models import Document


def _memoir(session, slug, title, **meta):
    doc = Document(slug=slug, title=title, kind="memoir", blocks=[], meta=meta)
    session.add(doc)
    session.flush()
    return doc


# ── the year prefix ──────────────────────────────────────────────────────────

def test_start_year_reads_either_separator() -> None:
    """Both slug shapes are real in the corpus. Reading only up to the first
    hyphen filed every ``1966_x`` slug under 9999, which sorted the middle of
    the Vietnam series after the 1980s."""
    assert _start_year("1965-1966_war-in-vietnam-part-1") == 1965
    assert _start_year("1966_war-in-vietnam-part-2") == 1966
    assert _start_year("1981-1990_the-public-servant") == 1981
    assert _start_year("annex-a-to-m") == 9999  # no year prefix → files last


# ── the reading order ────────────────────────────────────────────────────────

def test_reading_order_is_groups_then_ungrouped(session) -> None:
    early = create_group(session, "Early life", "#9c5a3c")
    vietnam = create_group(session, "Vietnam", "#5a7d5a")

    junior = _memoir(session, "1934-1945_junior", "Junior")
    genesis = _memoir(session, "1965-1966_genesis", "The Genesis")
    part2 = _memoir(session, "1966_part-2", "A Developing Role")
    annexes = _memoir(session, "annex-a-to-m", "Annexes A to M")
    berlin = _memoir(session, "2004_berlin", "Three Days in Berlin")

    assign_document(session, junior, early)
    for doc in (genesis, part2, annexes):
        assign_document(session, doc, vietnam)
    session.flush()

    assert [d.slug for d in reading_order(session)] == [
        "1934-1945_junior",       # group 1
        "1965-1966_genesis",      # group 2, in the order they were added
        "1966_part-2",
        "annex-a-to-m",
        "2004_berlin",            # ungrouped, last
    ]
    assert berlin.group_id is None


def test_reading_order_follows_the_manual_drag_order(session) -> None:
    vietnam = create_group(session, "Vietnam", "#5a7d5a")
    genesis = _memoir(session, "1965-1966_genesis", "The Genesis")
    annex_n = _memoir(session, "1966-1967_annex-n", "Annex N")
    part2 = _memoir(session, "1966_part-2", "A Developing Role")
    for doc in (genesis, annex_n, part2):
        assign_document(session, doc, vietnam)
    session.flush()

    # The operator drags Annex N to the end — the published order follows,
    # even though its slug year would sort it second.
    set_positions(session, vietnam.id, ["1965-1966_genesis", "1966_part-2", "1966-1967_annex-n"])

    assert [d.slug for d in reading_order(session)] == [
        "1965-1966_genesis",
        "1966_part-2",
        "1966-1967_annex-n",
    ]


# ── what it drives ───────────────────────────────────────────────────────────

def test_homepage_rows_follow_the_manual_order(session) -> None:
    vietnam = create_group(session, "Vietnam", "#5a7d5a")
    genesis = _memoir(session, "1965-1966_genesis", "The Genesis", short_title="The Genesis")
    annex_n = _memoir(session, "1966-1967_annex-n", "Annex N", short_title="Annex N")
    part2 = _memoir(session, "1966_part-2", "Part 2", short_title="A Developing Role")
    for doc in (genesis, annex_n, part2):
        assign_document(session, doc, vietnam)
    session.flush()
    set_positions(session, vietnam.id, ["1965-1966_genesis", "1966_part-2", "1966-1967_annex-n"])

    [group] = homepage_timeline(session)
    assert [row["title"] for row in group["rows"]] == [
        "The Genesis",
        "A Developing Role",
        "Annex N",
    ]


def test_nav_crosses_a_group_boundary_in_reading_order(session) -> None:
    """Prev/next walks the whole archive as one sequence, so the last document
    of a section leads into the first of the next — and never sideways into a
    section the reader isn't in."""
    early = create_group(session, "Early life", "#9c5a3c")
    vietnam = create_group(session, "Vietnam", "#5a7d5a")
    navy = _memoir(session, "1953-1954_in-the-navy", "In The Navy", short_title="In The Navy")
    genesis = _memoir(session, "1965-1966_genesis", "The Genesis", short_title="The Genesis")
    part2 = _memoir(session, "1966_part-2", "Part 2", short_title="A Developing Role")
    assign_document(session, navy, early)
    assign_document(session, genesis, vietnam)
    assign_document(session, part2, vietnam)
    session.flush()

    prev, nxt = nav_for(session, genesis)
    assert prev and prev["title"] == "In The Navy"       # last of the previous group
    assert nxt and nxt["title"] == "A Developing Role"

    prev, nxt = nav_for(session, navy)
    assert prev is None                                   # first document overall
    assert nxt and nxt["title"] == "The Genesis"


def test_nav_uses_the_short_title_and_canonical_url(session) -> None:
    group = create_group(session, "Vietnam", "#5a7d5a")
    first = _memoir(session, "1965-1966_genesis", "The Genesis")
    second = _memoir(
        session, "1966_part-2",
        "War In Vietnam – A Surveyor's Story - Part 2 - A Developing Role",
        short_title="A Developing Role",
        canonical_url="https://history.skitch.me/rfs/1966_part-2.html",
    )
    assign_document(session, first, group)
    assign_document(session, second, group)
    session.flush()

    _, nxt = nav_for(session, first)
    assert nxt == {
        "url": "https://history.skitch.me/rfs/1966_part-2.html",
        "title": "A Developing Role",
    }
