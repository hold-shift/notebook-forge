"""Site base URL: setting source-of-truth, ingestion wiring, and the migration
that rewrites stored canonical/homepage URLs."""

from __future__ import annotations

from notebook_forge import services, site_url_migration
from notebook_forge.blocks import make_block, text_run
from notebook_forge.collection import (
    DEFAULT_PAGES_BASE,
    doc_canonical_url,
    pages_base_url,
)
from notebook_forge.models import Setting


def _doc(session, slug="junior", kind="memoir"):
    d = services.create_document(
        session, slug, "Junior",
        blocks=[make_block("paragraph", content=[text_run("Hi.")])],
        meta={
            "slug": slug,
            "canonical_url": f"{DEFAULT_PAGES_BASE}/rfs/{slug}.html",
            "homepage_url": f"{DEFAULT_PAGES_BASE}/index.html",
        },
    )
    d.kind = kind
    session.flush()
    return d


def test_pages_base_url_default_and_override(session):
    assert pages_base_url(session) == DEFAULT_PAGES_BASE
    session.add(Setting(key="publishing", value={"base_url": "https://history.skitch.me/"}))
    session.flush()
    assert pages_base_url(session) == "https://history.skitch.me"  # trailing slash trimmed


def test_url_builders():
    assert doc_canonical_url("https://history.skitch.me", "junior") == (
        "https://history.skitch.me/rfs/junior.html"
    )


def test_migration_scan_and_apply_rewrites_urls(session):
    _doc(session)
    session.add(Setting(key="publishing", value={"base_url": "https://history.skitch.me"}))
    session.flush()

    rows = site_url_migration.scan(session)
    row = next(r for r in rows if r["slug"] == "junior")
    assert row["changed"] is True
    assert row["expected"]["canonical_url"] == "https://history.skitch.me/rfs/junior.html"

    applied = site_url_migration.apply(session)
    assert any(a["slug"] == "junior" for a in applied)
    updated = services.get_document(session, "junior")
    assert updated.meta["canonical_url"] == "https://history.skitch.me/rfs/junior.html"
    assert updated.meta["homepage_url"] == "https://history.skitch.me/index.html"

    # Idempotent: a second scan reports nothing to change.
    assert all(not r["changed"] for r in site_url_migration.scan(session))


def test_migration_handles_homepage(session):
    hp = _doc(session, slug="homepage", kind="homepage")
    session.add(Setting(key="publishing", value={"base_url": "https://history.skitch.me"}))
    session.flush()
    site_url_migration.apply(session)
    assert hp.meta["canonical_url"] == "https://history.skitch.me/index.html"


def test_new_documents_use_configured_base(session):
    from notebook_forge.ingestion import create_blank_document

    session.add(Setting(key="publishing", value={"base_url": "https://history.skitch.me"}))
    session.flush()
    detail = create_blank_document(session, "Fresh Start")
    doc = services.get_document(session, detail["slug"])
    assert doc.meta["canonical_url"].startswith("https://history.skitch.me/rfs/")
