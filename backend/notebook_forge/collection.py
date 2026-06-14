"""Collection index publishing (Collection Index spec §5, §10).

The homepage, catalogue, sitemap, robots and llms.txt are a DERIVED view of
the corpus — generated from the documents table + the human-authored
homepage settings (imported from the live index page), never hand-edited.
Regenerated on every publish so a title fix propagates to the index card,
the JSON-LD graph, and the prev/next footers of neighbouring documents.

Rendering rules (word counts, reading time, JSON-LD shapes, file formats)
are ported from MemoirForge's collection_index package — the generator of
the live site's root artefacts.
"""

from __future__ import annotations

import datetime as dt
import html as _htmllib
import json
import re
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .groups import _start_year  # noqa: F401 (re-exported; used by publish/service indirectly)
from .models import Document, Setting, SyncState, Target
from .renderer import inline_html, render_index

DEFAULT_AUTHOR = "Robert Francis Skitch"

_PROSE_KINDS = {"paragraph", "heading", "quote", "bulletListItem", "numberedListItem"}
_TAG_RE = re.compile(r"<[^>]+>")


def count_words(blocks: list[dict[str, Any]]) -> int:
    """Body prose + headings only — figures (captions) and footnotes are
    excluded. Counting runs over the rendered inline HTML with tags
    replaced by spaces, byte-matching the live site's rule (so a footnote
    marker counts as its own token, exactly as upstream counted it)."""
    total = 0
    for block in blocks:
        if block.get("type") in _PROSE_KINDS:
            rendered = inline_html(block.get("content"))
            text = _htmllib.unescape(_TAG_RE.sub(" ", rendered))
            total += len(text.split())
            for child in block.get("children") or []:
                total += count_words([child])
    return total


def reading_time(words: int, wpm: int = 200) -> str:
    """'~25 min read' under an hour; '~2½ hr read' above (ported verbatim)."""
    if not words or words <= 0:
        return ""
    minutes = words / wpm
    if minutes < 60:
        m = max(5, round(minutes / 5) * 5)
        return f"~{m} min read"
    halves = round((minutes / 60) * 2) / 2
    whole = int(halves)
    half = "½" if (halves - whole) >= 0.5 else ""
    return f"~{whole}{half} hr read"


def _setting(session: Session, key: str) -> dict[str, Any]:
    row = session.get(Setting, key)
    return dict(row.value) if row else {}


def _iso_utc(value: dt.datetime) -> str:
    """SQLite hands back naive datetimes; ours are always UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat()



def build_entries(
    session: Session,
    target: Target | None = None,
    publishing_slug: str = "",
    now_iso: str = "",
) -> list[dict[str, Any]]:
    """Catalogue entries in chronological order (the year prefix was
    front-loaded into slugs for exactly this). Human-curated fields
    (description, needs_description, source) carry over from the imported
    catalogue; everything else is derived from current document state."""
    imported = {
        e.get("stem"): e for e in _setting(session, "catalogue").get("entries", [])
    }
    docs = list(session.scalars(select(Document).where(Document.kind == "memoir")))
    docs.sort(key=lambda d: (_start_year(d.slug), d.slug))

    entries: list[dict[str, Any]] = []
    for doc in docs:
        old = imported.get(doc.slug, {})
        published = ""
        if doc.slug == publishing_slug and now_iso:
            published = now_iso
        elif target is not None:
            state = session.scalar(
                select(SyncState).where(
                    SyncState.document_id == doc.id, SyncState.target_id == target.id
                )
            )
            # Import seeded published_at from the page's own JSON-LD, which
            # can predate the catalogue's publish record. Only trust
            # sync_state when it differs from that seed — i.e. when WE
            # republished — otherwise keep the imported catalogue value.
            if state and state.published_at:
                state_iso = _iso_utc(state.published_at)
                if state_iso != doc.meta.get("date_published", ""):
                    published = state_iso
        if not published:
            published = old.get("published", "") or doc.meta.get("date_published", "")

        description = old.get("description", "")
        entries.append(
            {
                "stem": doc.slug,
                "title": doc.meta.get("title", doc.title),
                "years": doc.meta.get("year_display", ""),
                "description": description,
                "url": doc.meta.get("canonical_url", ""),
                "subtitle": doc.meta.get("standfirst", ""),
                "source": old.get("source", "generated"),
                "needs_description": old.get("needs_description", not description),
                "word_count": count_words(doc.blocks),
                "published": published,
            }
        )
    return entries


def nav_for(session: Session, doc: Document) -> tuple[dict | None, dict | None]:
    """Derived prev/next from chronological order — this is what propagates
    a title fix into the neighbours' docnav footers."""
    entries = build_entries(session)
    idx = next((i for i, e in enumerate(entries) if e["stem"] == doc.slug), None)
    if idx is None:
        return None, None

    def ref(e: dict[str, Any]) -> dict[str, Any]:
        return {"url": e["url"], "title": e["title"]}

    prev_e = ref(entries[idx - 1]) if idx > 0 else None
    next_e = ref(entries[idx + 1]) if idx < len(entries) - 1 else None
    return prev_e, next_e


# ------------------------------------------------------------------ JSON-LD


def _person(name: str, base_url: str) -> dict[str, Any]:
    return {
        "@type": "Person",
        "@id": f"{base_url.rstrip('/')}/index.html#author",
        "name": name or "Author",
    }


def collection_jsonld(
    base_url: str, title: str, welcome: str, entries: list[dict], author_name: str
) -> str:
    homepage_url = f"{base_url.rstrip('/')}/index.html"
    obj = {
        "@context": "https://schema.org",
        "@type": "CreativeWorkSeries",
        "@id": f"{homepage_url}#collection",
        "name": title or "The Family Archive",
        "url": homepage_url,
        "description": (welcome or "").strip(),
        "creator": _person(author_name, base_url),
        "hasPart": [
            {
                "@type": "Article",
                "@id": e.get("url") or "",
                "name": e.get("title") or "",
                "url": e.get("url") or "",
                "datePublished": e.get("published") or "",
                "temporalCoverage": (e.get("years") or "").replace("–", "/").replace("—", "/"),
            }
            for e in entries
        ],
    }
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


# ------------------------------------------------------------- root files


def render_sitemap(base_url: str, entries: list[dict], homepage_lastmod: str) -> str:
    base = base_url.rstrip("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>{xml_escape(base + '/index.html')}</loc>",
    ]
    if homepage_lastmod:
        lines.append(f"    <lastmod>{xml_escape(homepage_lastmod)}</lastmod>")
    lines += ["    <changefreq>monthly</changefreq>", "    <priority>1.0</priority>", "  </url>"]
    for e in entries:
        url = (e.get("url") or "").strip()
        if not url:
            continue
        lines.append("  <url>")
        lines.append(f"    <loc>{xml_escape(url)}</loc>")
        lastmod = (e.get("published") or "").strip()
        if lastmod:
            lines.append(f"    <lastmod>{xml_escape(lastmod)}</lastmod>")
        lines.append("    <changefreq>yearly</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_robots(base_url: str) -> str:
    sitemap_url = f"{base_url.rstrip('/')}/sitemap.xml"
    return "\n".join(
        [
            "# MemoirForge family archive — public by decision.",
            "# All crawlers welcome, including AI answer-bots.",
            "",
            "User-agent: *",
            "Allow: /",
            "",
            "User-agent: GPTBot",
            "Allow: /",
            "",
            "User-agent: ClaudeBot",
            "Allow: /",
            "",
            "User-agent: PerplexityBot",
            "Allow: /",
            "",
            "User-agent: Google-Extended",
            "Allow: /",
            "",
            f"Sitemap: {sitemap_url}",
            "",
        ]
    )


def render_llms(title: str, welcome: str, entries: list[dict]) -> str:
    lines = [f"# {title or 'The Family Archive'}", ""]
    if welcome:
        lines += [welcome.strip(), ""]
    lines += ["## Documents", ""]
    for e in entries:
        url = (e.get("url") or "").strip()
        if not url:
            continue
        name = (e.get("title") or "").strip() or e.get("stem", "")
        years = (e.get("years") or "").strip()
        desc = (e.get("description") or "").strip()
        line = f"- [{name}]({url})"
        if years:
            line += f" — {years}"
        lines.append(line)
        if desc:
            lines.append(f"  {desc}")
    lines.append("")
    return "\n".join(lines)


def author_name(session: Session) -> str:
    doc = session.scalar(select(Document).limit(1))
    if doc:
        name = (doc.meta.get("jsonld") or {}).get("author", {}).get("name")
        if name:
            return name
    return DEFAULT_AUTHOR


def root_files(
    session: Session,
    target: Target | None = None,
    publishing_slug: str = "",
    base_url: str = "https://chris-skitch.github.io/family-history",
) -> tuple[dict[str, str], list[str]]:
    """All five root artefacts, regenerated together (spec §8: rebuild on
    every publish so they can never drift from what is actually published).
    Returns (files, warnings)."""
    from .homepage import get_homepage, homepage_body

    now_iso = dt.datetime.now(dt.UTC).isoformat()
    author = author_name(session)
    entries = build_entries(session, target, publishing_slug, now_iso)
    catalogue = json.dumps(
        {"entries": entries, "rebuilt": now_iso}, ensure_ascii=False, indent=2
    ) + "\n"
    entries_with_rt = [
        dict(e, reading_time=reading_time(int(e.get("word_count") or 0))) for e in entries
    ]

    from .footer import footer_html as _footer_html

    hp = get_homepage(session)
    warnings: list[str] = []
    if hp is not None:
        body, warnings, derived = homepage_body(session, hp)
        title = derived.get("title", "The Family Archive")
        welcome = derived.get("welcome", "")
        footer = _footer_html(session)
        index_html = render_index(
            title=title,
            welcome=welcome,
            dedication="",
            entries=[],
            footer_text=footer,
            canonical_url=f"{base_url.rstrip('/')}/index.html",
            og_description=(welcome or "").split("\n", 1)[0][:280],
            jsonld_script=collection_jsonld(base_url, title, welcome, entries_with_rt, author),
            body_entries=body,
        )
    else:
        homepage_s = _setting(session, "homepage")
        title = homepage_s.get("title", "The Family Archive")
        welcome = homepage_s.get("welcome", "")
        dedication = homepage_s.get("dedication", "")
        footer = _footer_html(session)
        index_html = render_index(
            title=title,
            welcome=welcome,
            dedication=dedication,
            entries=entries_with_rt,
            footer_text=footer,
            canonical_url=f"{base_url.rstrip('/')}/index.html",
            og_description=(welcome or "").split("\n", 1)[0][:280],
            jsonld_script=collection_jsonld(base_url, title, welcome, entries_with_rt, author),
        )

    return {
        "index.html": index_html,
        "catalogue.json": catalogue,
        "sitemap.xml": render_sitemap(base_url, entries_with_rt, now_iso),
        "robots.txt": render_robots(base_url),
        "llms.txt": render_llms(title, welcome, entries_with_rt),
    }, warnings
