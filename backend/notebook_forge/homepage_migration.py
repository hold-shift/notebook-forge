"""One-time migration: Settings 'homepage' → homepage Document + The Memoirs group.

Idempotent: if the homepage document already exists, returns None immediately.
Called at API bootstrap — safe to call on every startup.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .blocks import (
    FORGE_DEDICATION,
    FORGE_DOC_GROUP,
    HOMEPAGE_SLUG,
    make_block,
    text_run,
)
from .groups import _start_year, create_group, list_groups
from .homepage import get_homepage
from .models import Document, Setting
from .services import record_change, reindex


def ensure_homepage(session: Session) -> dict[str, Any] | None:
    """Migrate Settings 'homepage' into a homepage Document. Idempotent."""
    if get_homepage(session) is not None:
        return None

    # --- 2. Read settings ---
    from sqlalchemy import select

    setting_row = session.scalar(select(Setting).where(Setting.key == "homepage"))
    hp_s: dict[str, Any] = (setting_row.value if setting_row else {}) or {}
    title = hp_s.get("title") or "The Family Archive"
    welcome: str = hp_s.get("welcome") or ""
    dedication: str = hp_s.get("dedication") or ""
    footer_html: str = hp_s.get("footer_html") or ""

    # --- 3. Seed group ---
    existing_groups = list_groups(session)
    if not existing_groups:
        group = create_group(session, "The Memoirs", "#9c5a3c")
        memoirs = session.scalars(
            select(Document)
            .where(Document.kind == "memoir")
        ).all()
        ordered = sorted(memoirs, key=lambda d: (_start_year(d.slug), d.slug))
        for pos, doc in enumerate(ordered):
            doc.group_id = group.id
            doc.group_position = pos
        session.flush()
    else:
        # Reuse or create "The Memoirs" without touching existing memberships.
        group = next((g for g in existing_groups if g.name == "The Memoirs"), None)
        if group is None:
            group = create_group(session, "The Memoirs", "#9c5a3c")

    # --- 4. Build blocks ---
    blocks: list[dict[str, Any]] = []
    blocks.append(make_block("heading", {"level": 1}, [text_run(title)]))
    for seg in welcome.split("\n\n"):
        seg = seg.strip()
        if seg:
            blocks.append(make_block("paragraph", content=[text_run(seg)]))
    if dedication.strip():
        blocks.append(make_block(FORGE_DEDICATION, {"text": dedication.strip()}))
    blocks.append(make_block("divider"))
    blocks.append(make_block(FORGE_DOC_GROUP, {
        "groupId": str(group.id),
        "sort": "date_range",
        "showBlurbs": True,
        "showWordCounts": True,
        "layout": "list",
    }))

    # --- 5. Create document ---
    doc = Document(
        slug=HOMEPAGE_SLUG,
        title="Homepage",
        kind="homepage",
        blocks=blocks,
        meta={"footer_html": footer_html},
    )
    session.add(doc)
    session.flush()
    record_change(session, doc, "import", "migrated homepage from Settings")
    reindex(session, doc)

    # --- 6. Equivalence check ---
    byte_identical = _check_equivalence(
        session, doc, hp_s, footer_html, title, welcome, dedication
    )

    if byte_identical:
        from sqlalchemy import select as _sel

        from .models import Target
        from .services import mark_published, snapshot_document

        targets = session.scalars(
            _sel(Target).where(Target.kind.in_(["github-pages", "local-folder"]))
        ).all()
        if targets:
            snap = snapshot_document(session, doc)
            for target in targets:
                mark_published(session, doc, target, snap)
            names = ", ".join(t.name for t in targets)
            record_change(
                session,
                doc,
                "publish",
                f"seeded PUBLISHED for {names}: migrated homepage renders"
                " byte-identical to the live index",
            )
    else:
        record_change(
            session,
            doc,
            "note",
            "homepage left unpublished: migrated render differs from legacy index"
            " (push to verify and go live)",
        )

    return {"migrated": True, "byte_identical": byte_identical, "group_id": group.id}


def _check_equivalence(
    session: Session,
    doc: Document,
    hp_s: dict[str, Any],
    footer_html: str,
    title: str,
    welcome: str,
    dedication: str,
) -> bool:
    """Compare new homepage render against the legacy index render."""
    try:
        from .collection import (
            author_name,
            build_entries,
            collection_jsonld,
            reading_time,
        )
        from .renderer import render_index

        base_url = "https://chris-skitch.github.io/family-history"
        import datetime as dt

        now_iso = dt.datetime.now(dt.UTC).isoformat()
        author = author_name(session)
        entries = build_entries(session, None, "", now_iso)
        entries_with_rt = [
            dict(e, reading_time=reading_time(int(e.get("word_count") or 0)))
            for e in entries
        ]

        legacy_index = render_index(
            title=title,
            welcome=welcome,
            dedication=dedication,
            entries=entries_with_rt,
            footer_text=footer_html,
            canonical_url=f"{base_url.rstrip('/')}/index.html",
            og_description=(welcome or "").split("\n", 1)[0][:280],
            jsonld_script=collection_jsonld(base_url, title, welcome, entries_with_rt, author),
        )

        from .homepage import homepage_body

        body, _, derived = homepage_body(session, doc)
        new_title = derived.get("title", "The Family Archive")
        new_welcome = derived.get("welcome", "")
        new_footer = doc.meta.get("footer_html", "")
        new_index = render_index(
            title=new_title,
            welcome=new_welcome,
            dedication="",
            entries=[],
            footer_text=new_footer,
            canonical_url=f"{base_url.rstrip('/')}/index.html",
            og_description=(new_welcome or "").split("\n", 1)[0][:280],
            jsonld_script=collection_jsonld(
                base_url, new_title, new_welcome, entries_with_rt, author
            ),
            body_entries=body,
        )
        return legacy_index == new_index
    except Exception:  # noqa: BLE001
        return False
