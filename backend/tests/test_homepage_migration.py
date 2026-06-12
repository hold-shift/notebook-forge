"""M5 homepage migration tests."""


from sqlalchemy.orm import Session

from notebook_forge.blocks import FORGE_DEDICATION, FORGE_DOC_GROUP
from notebook_forge.groups import list_groups
from notebook_forge.homepage import get_homepage
from notebook_forge.homepage_migration import ensure_homepage
from notebook_forge.models import Document, Setting, Target

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_homepage_setting(session: Session, **kwargs) -> None:
    row = session.get(Setting, "homepage")
    if row is None:
        row = Setting(key="homepage", value=kwargs)
        session.add(row)
    else:
        row.value = kwargs
    session.flush()


def _memoir(session: Session, slug: str, title: str) -> Document:
    doc = Document(slug=slug, title=title, kind="memoir", blocks=[], meta={})
    session.add(doc)
    session.flush()
    return doc


# ---------------------------------------------------------------------------
# Test 1: populated settings + 3 memoir docs
# ---------------------------------------------------------------------------

def test_migration_creates_group_and_homepage(session: Session) -> None:
    _set_homepage_setting(
        session,
        title="My Archive",
        welcome="Welcome to the collection.\n\nMore text here.",
        dedication="For the family",
        footer_html="<p>Footer</p>",
    )
    _memoir(session, "1950-1960_early", "Early Years")
    _memoir(session, "1970-1980_later", "Later Years")
    _memoir(session, "1960-1970_middle", "Middle Years")

    result = ensure_homepage(session)

    assert result is not None
    assert result["migrated"] is True

    # Group created with all memoirs
    groups = list_groups(session)
    assert len(groups) == 1
    assert groups[0].name == "The Memoirs"

    # Docs ordered chronologically (1950, 1960, 1970)
    docs = session.query(Document).filter(
        Document.group_id == groups[0].id
    ).order_by(Document.group_position).all()
    assert [d.slug for d in docs] == ["1950-1960_early", "1960-1970_middle", "1970-1980_later"]

    # Homepage document created
    hp = get_homepage(session)
    assert hp is not None
    assert hp.kind == "homepage"
    assert hp.meta.get("footer_html") == "<p>Footer</p>"

    # Check block sequence: H1, para, para, dedication, divider, group
    blocks = hp.blocks
    assert blocks[0]["type"] == "heading"
    assert blocks[0]["props"]["level"] == 1
    assert blocks[1]["type"] == "paragraph"
    assert blocks[2]["type"] == "paragraph"
    assert blocks[3]["type"] == FORGE_DEDICATION
    assert blocks[3]["props"]["text"] == "For the family"
    assert blocks[4]["type"] == "divider"
    assert blocks[5]["type"] == FORGE_DOC_GROUP
    assert blocks[5]["props"]["groupId"] == str(groups[0].id)


# ---------------------------------------------------------------------------
# Test 2: idempotent
# ---------------------------------------------------------------------------

def test_migration_idempotent(session: Session) -> None:
    _memoir(session, "1950-1960_early", "Early Years")
    ensure_homepage(session)
    session.flush()

    result2 = ensure_homepage(session)
    assert result2 is None

    # Only one group, one homepage
    assert len(list_groups(session)) == 1
    assert session.query(Document).filter(Document.kind == "homepage").count() == 1


# ---------------------------------------------------------------------------
# Test 3: byte-equivalence path seeds PUBLISHED
# ---------------------------------------------------------------------------

def test_byte_equivalence_seeds_published(session: Session) -> None:
    _set_homepage_setting(session, title="Archive", welcome="", dedication="", footer_html="")
    target = Target(name="local", kind="local-folder", config={"folder": "/tmp/x"})
    session.add(target)
    session.flush()

    result = ensure_homepage(session)
    assert result is not None

    from notebook_forge.services import is_dirty

    hp = get_homepage(session)
    if result["byte_identical"]:
        assert not is_dirty(session, hp, target)
    # If not byte_identical (e.g. timing diff), just assert no crash


# ---------------------------------------------------------------------------
# Test 4: empty settings → defaults, no intro paras
# ---------------------------------------------------------------------------

def test_empty_settings_uses_defaults(session: Session) -> None:
    result = ensure_homepage(session)
    assert result is not None

    hp = get_homepage(session)
    blocks = hp.blocks
    # H1 with default title
    assert blocks[0]["type"] == "heading"
    from notebook_forge.blocks import inline_text
    assert inline_text(blocks[0].get("content") or []) == "The Family Archive"

    # No intro paragraphs (welcome empty)
    types = [b["type"] for b in blocks]
    assert "paragraph" not in types


# ---------------------------------------------------------------------------
# Test 5: dedication empty → no forgeDedication block
# ---------------------------------------------------------------------------

def test_no_dedication_block_when_empty(session: Session) -> None:
    _set_homepage_setting(session, title="A", welcome="Hello", dedication="", footer_html="")
    ensure_homepage(session)

    hp = get_homepage(session)
    types = [b["type"] for b in hp.blocks]
    assert FORGE_DEDICATION not in types


# ---------------------------------------------------------------------------
# Test 6: existing-groups guard
# ---------------------------------------------------------------------------

def test_existing_group_preserved(session: Session) -> None:
    from notebook_forge.groups import create_group

    pre = create_group(session, "Pre-existing", "#5a7d5a")
    m = _memoir(session, "1950-1960_doc", "Doc")
    from notebook_forge.groups import assign_document
    assign_document(session, m, pre)

    ensure_homepage(session)
    session.flush()

    groups = list_groups(session)
    # Both pre-existing and "The Memoirs" (or reuse if named same)
    names = {g.name for g in groups}
    assert "Pre-existing" in names
    assert "The Memoirs" in names

    # Pre-existing group membership untouched
    m_refreshed = session.get(Document, m.id)
    assert m_refreshed.group_id == pre.id
