"""Rewrite stored per-document URLs to the configured site base URL.

Each document freezes `canonical_url` + `homepage_url` in its meta at import time
(they drive the page's canonical/og tags, the homepage tile links and prev/next
nav). Those are NOT derived at publish time, so changing the site base URL — e.g.
moving from a github.io project URL to a custom domain — needs a one-time rewrite.

Idempotent by design: it re-derives each document's expected URLs from the current
base (Setting 'publishing', via collection.pages_base_url) and only touches docs
whose stored values differ. Safe to re-run after any later domain change — no
marker guard. Every changed document is snapshotted first; the meta change marks
it dirty, so the operator re-publishes afterwards.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from . import services
from .collection import doc_canonical_url, doc_homepage_url, pages_base_url


def _expected(doc: Any, base: str) -> dict[str, str]:
    if doc.kind == "homepage":
        return {"canonical_url": doc_homepage_url(base), "homepage_url": doc_homepage_url(base)}
    slug = doc.meta.get("slug", doc.slug)
    return {"canonical_url": doc_canonical_url(base, slug), "homepage_url": doc_homepage_url(base)}


def scan(session: Session) -> list[dict[str, Any]]:
    """One row per document; `changed` is True when its stored URLs differ from
    what the current base URL would produce."""
    base = pages_base_url(session)
    rows: list[dict[str, Any]] = []
    for doc in services.list_documents(session):
        exp = _expected(doc, base)
        cur = {k: doc.meta.get(k, "") for k in exp}
        rows.append({
            "slug": doc.slug,
            "kind": doc.kind,
            "changed": cur != exp,
            "current": cur,
            "expected": exp,
        })
    return rows


def apply(session: Session) -> list[dict[str, Any]]:
    """Snapshot + rewrite the URLs of every document that differs. Returns the
    applied rows (changed only)."""
    base = pages_base_url(session)
    applied: list[dict[str, Any]] = []
    for doc in services.list_documents(session):
        exp = _expected(doc, base)
        if all(doc.meta.get(k) == v for k, v in exp.items()):
            continue
        services.snapshot_document(session, doc, note="before site-url migration")
        meta = dict(doc.meta)
        meta.update(exp)
        services.save_blocks(
            session, doc, doc.blocks, meta=meta, summary=f"site URL set to {base}"
        )
        applied.append({"slug": doc.slug, "kind": doc.kind, "expected": exp})
    return applied


def write_report(reports_dir: Path, rows: list[dict[str, Any]], mode: str, base: str) -> None:
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = [r for r in rows if r["changed"]]
    lines = [
        "# Site URL migration report",
        "",
        f"Mode: **{mode}** · Generated: {ts}",
        f"Base URL: {base}",
        f"Documents scanned: {len(rows)} · To change: {len(changed)}",
        "",
    ]
    for r in changed:
        cur, exp = r["current"], r["expected"]
        lines += [
            f"## {r['slug']} ({r['kind']})",
            f"- canonical_url: `{cur['canonical_url']}` → `{exp['canonical_url']}`",
            f"- homepage_url:  `{cur['homepage_url']}` → `{exp['homepage_url']}`",
            "",
        ]
    if not changed:
        lines += ["All documents already match the configured base URL.", ""]
    lines += [
        "---",
        "",
        "**After applying:** every changed document is dirty for its targets — "
        "re-publish them (and the homepage) to push the new URLs.",
        "Each applied document has a snapshot 'before site-url migration'.",
        "",
    ]
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "site_url_migration.md").write_text("\n".join(lines) + "\n")
