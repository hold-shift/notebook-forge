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
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .groups import _start_year  # noqa: F401 (re-exported; used by publish/service indirectly)
from .models import Document, Setting, SyncState, Target
from .renderer import inline_html, render_index

DEFAULT_AUTHOR = "Robert Francis Skitch"

# The published-site base URL. Single source of truth for canonical URLs, the
# homepage URL, the sitemap, and JSON-LD. Operator-editable in Settings
# (Setting key 'publishing'); falls back to the original GitHub Pages project URL.
DEFAULT_PAGES_BASE = "https://chris-skitch.github.io/family-history"
# Memoir pages live under this path segment of the site (kept on the domain move).
PAGES_SUBDIR = "rfs"


def pages_base_url(session: Session) -> str:
    """The configured site base URL (no trailing slash), or the default."""
    row = session.get(Setting, "publishing")
    val = (row.value or {}).get("base_url", "") if row is not None else ""
    return (val.strip() or DEFAULT_PAGES_BASE).rstrip("/")


def site_head_html(session: Session) -> str:
    """Operator-supplied raw HTML injected into the <head> of every published
    page and the homepage (e.g. an analytics <script> tag). Stored alongside
    the base URL under the 'publishing' Setting. Empty by default."""
    row = session.get(Setting, "publishing")
    return ((row.value or {}).get("head_html", "") if row is not None else "") or ""


# Site-branding images (operator-uploaded, stored by Asset SHA in the
# 'publishing' Setting): a site-wide favicon and the homepage social-share
# (OpenGraph) image. Both publish to the site root and are referenced by an
# ABSOLUTE URL so they resolve from every page depth (incl. /rfs/ pages).
SITE_IMAGE_ASSET_KEYS = {"favicon": "favicon_asset_id", "og_image": "og_image_asset_id"}
_SITE_IMAGE_STEM = {"favicon": "favicon", "og_image": "og-image"}

# Fallback favicon: the NotebookForge icon, vendored into the package so a
# published site always has a tab icon even before the operator uploads one.
DEFAULT_FAVICON_PATH = Path(__file__).resolve().parent / "static" / "favicon.png"


def _publishing_value(session: Session) -> dict[str, Any]:
    row = session.get(Setting, "publishing")
    return dict(row.value) if (row is not None and row.value) else {}


def site_image_asset_id(session: Session, kind: str) -> str:
    """The stored Asset SHA for a site-branding image ('favicon' | 'og_image')."""
    return (_publishing_value(session).get(SITE_IMAGE_ASSET_KEYS[kind]) or "") or ""


def _site_image_asset(session: Session, kind: str) -> Any:
    from .models import Asset

    sha = site_image_asset_id(session, kind)
    return session.get(Asset, sha) if sha else None


def site_image_published_name(session: Session, kind: str) -> str:
    """Root-relative published filename (e.g. 'favicon.png'), or '' when unset."""
    asset = _site_image_asset(session, kind)
    return f"{_SITE_IMAGE_STEM[kind]}{asset.ext}" if asset is not None else ""


def favicon_published_name(session: Session) -> str:
    """The favicon's published filename. Falls back to the vendored NotebookForge
    icon ('favicon.png') when the operator hasn't uploaded a custom one."""
    return site_image_published_name(session, "favicon") or "favicon.png"


def favicon_url(session: Session, base_url: str) -> str:
    """Always non-empty — a custom favicon, else the NotebookForge default."""
    return f"{base_url.rstrip('/')}/{favicon_published_name(session)}"


def homepage_og_image_url(session: Session, base_url: str) -> str:
    name = site_image_published_name(session, "og_image")
    return f"{base_url.rstrip('/')}/{name}" if name else ""


def site_image_assets(session: Session, workspace: Any) -> list[tuple[str, Any, str]]:
    """(published_name, source_path, sha256) for each site-branding image the
    publish layer copies to the site root next to index.html. The favicon is
    always present — the custom upload, or the vendored NotebookForge icon."""
    from .assets import asset_path, sha256_file

    out: list[tuple[str, Any, str]] = []
    for kind in SITE_IMAGE_ASSET_KEYS:
        asset = _site_image_asset(session, kind)
        if asset is not None:
            out.append(
                (
                    f"{_SITE_IMAGE_STEM[kind]}{asset.ext}",
                    asset_path(workspace, asset),
                    asset.sha256,
                )
            )
        elif kind == "favicon" and DEFAULT_FAVICON_PATH.exists():
            out.append(
                ("favicon.png", DEFAULT_FAVICON_PATH, sha256_file(DEFAULT_FAVICON_PATH))
            )
    return out


def set_site_image(session: Session, kind: str, asset_sha: str | None) -> None:
    """Point a site-branding image at an uploaded asset (or clear it with None),
    preserving all other publishing config."""
    if kind not in SITE_IMAGE_ASSET_KEYS:
        raise ValueError(f"unknown site image kind '{kind}'")
    row = session.get(Setting, "publishing")
    value = dict(row.value) if (row is not None and row.value) else {}
    value[SITE_IMAGE_ASSET_KEYS[kind]] = asset_sha or None
    if row is None:
        session.add(Setting(key="publishing", value=value))
    else:
        row.value = value
    session.flush()


def doc_canonical_url(base: str, slug: str) -> str:
    return f"{base.rstrip('/')}/{PAGES_SUBDIR}/{slug}.html"


def doc_homepage_url(base: str) -> str:
    """The homepage's canonical URL: the SITE ROOT, not '/index.html'.

    Both are served 200 by the host, so pointing the canonical (and the
    sitemap, and every internal 'Archive' link) at '/index.html' made Google
    crawl and consolidate two URLs for the single most important page. The
    root is the natural canonical — '/index.html' remains reachable, it just
    isn't what we advertise."""
    return f"{base.rstrip('/')}/"


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


def format_audio_length(seconds: float | None) -> str:
    """Recording length for the homepage tile, e.g. '3h5m' / '45m' (nearest min)."""
    if not seconds or seconds <= 0:
        return ""
    minutes = round(seconds / 60)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h{m}m"
    return f"{h}h" if h else f"{m}m"


def format_word_count(words: int) -> str:
    """Word count to the nearest 1000, e.g. '31k words'."""
    if words <= 0:
        return ""
    k = round(words / 1000)
    return "<1k words" if k == 0 else f"{k}k words"


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
                "short_title": doc.meta.get("short_title", ""),
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


def live_html_target(session: Session) -> Target | None:
    """The live-HTML publishing target (github-pages) — the one whose PUBLISHED
    sync-state defines "published" for the crawler-facing discovery artefacts
    (SEO/AEO plan §3). None when no such target is configured."""
    return session.scalar(select(Target).where(Target.kind == "github-pages"))


def published_slugs(
    session: Session,
    live_target: Target | None,
    publishing_slug: str = "",
    publishing_target: Target | None = None,
) -> set[str]:
    """Slugs currently live on the live-HTML target — the gate for the
    sitemap, llms.txt and the collection JSON-LD (plan §3, §8). The document
    being published in THIS pass is included when the pass targets the live
    site, because its sync-state is not flipped to PUBLISHED until after the
    root files are built."""
    from . import services

    slugs: set[str] = set()
    if live_target is not None:
        for doc in session.scalars(select(Document).where(Document.kind == "memoir")):
            if services.is_published(session, doc, live_target):
                slugs.add(doc.slug)
    if (
        publishing_slug
        and live_target is not None
        and publishing_target is not None
        and publishing_target.id == live_target.id
    ):
        slugs.add(publishing_slug)
    return slugs


def nav_for(session: Session, doc: Document) -> tuple[dict | None, dict | None]:
    """Derived prev/next from the library's reading order — groups in their own
    order, members in the operator's manual order, ungrouped last. Deriving it
    at publish time is what propagates a title fix, or a drag in the library,
    into the neighbours' docnav footers."""
    from .groups import reading_order

    docs = reading_order(session)
    idx = next((i for i, d in enumerate(docs) if d.slug == doc.slug), None)
    if idx is None:
        return None, None

    def ref(d: Document) -> dict[str, Any]:
        # Prev/next nav uses the short title when set (the long titles overflow).
        meta = d.meta or {}
        return {
            "url": meta.get("canonical_url", ""),
            "title": meta.get("short_title") or meta.get("title") or d.title,
        }

    prev_d = ref(docs[idx - 1]) if idx > 0 else None
    next_d = ref(docs[idx + 1]) if idx < len(docs) - 1 else None
    return prev_d, next_d


# ------------------------------------------------------------------ JSON-LD


def _person(name: str, base_url: str) -> dict[str, Any]:
    return {
        "@type": "Person",
        "@id": f"{doc_homepage_url(base_url)}#author",
        "name": name or "Author",
    }


def default_org_name(author_name: str) -> str:
    """The archive's publisher name, derived from the author's surname —
    'The Skitch Family Archive'. Single source of truth: both the homepage
    JSON-LD and the per-document graph must agree on this string."""
    surname = author_name.split()[-1] if author_name.split() else ""
    return f"The {surname} Family Archive" if surname else "The Family Archive"


def _publisher_org(base_url: str, author_name: str) -> dict[str, Any]:
    """Shared publisher Organization, @id-matched to the per-document pages'
    graph (structured_data._publisher) so answer engines de-duplicate it."""
    return {
        "@type": "Organization",
        "@id": f"{doc_homepage_url(base_url)}#publisher",
        "name": default_org_name(author_name),
        "url": doc_homepage_url(base_url),
    }


def collection_jsonld(
    base_url: str, title: str, welcome: str, entries: list[dict], author_name: str
) -> str:
    homepage_url = doc_homepage_url(base_url)
    obj = {
        "@context": "https://schema.org",
        "@type": "CreativeWorkSeries",
        "@id": f"{homepage_url}#collection",
        "name": title or "The Family Archive",
        "url": homepage_url,
        "description": (welcome or "").strip(),
        "creator": _person(author_name, base_url),
        "publisher": _publisher_org(base_url, author_name),
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
        f"    <loc>{xml_escape(doc_homepage_url(base))}</loc>",
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
    now_iso = dt.datetime.now(dt.UTC).isoformat()
    author = author_name(session)
    entries = build_entries(session, target, publishing_slug, now_iso)
    # catalogue.json is NotebookForge's own re-import seed (carries curated
    # descriptions for drafts too), so it stays complete. The crawler-facing
    # artefacts below are gated to published-only (plan §3, §8).
    catalogue = json.dumps(
        {"entries": entries, "rebuilt": now_iso}, ensure_ascii=False, indent=2
    ) + "\n"
    entries_with_rt = [
        dict(e, reading_time=reading_time(int(e.get("word_count") or 0))) for e in entries
    ]
    live_target = live_html_target(session) or target
    gate = published_slugs(
        session, live_target, publishing_slug, publishing_target=target
    )
    live_entries = [e for e in entries_with_rt if e.get("stem") in gate]

    from .footer import footer_html as _footer_html
    from .homepage import homepage_content, homepage_timeline

    # The published homepage renders entirely from the content settings and the
    # group-derived timeline (the homepage document's blocks are no longer a
    # render input — see docs/Homepage_Redesign_Spec.md).
    content = homepage_content(session)
    timeline = homepage_timeline(session)
    footer = _footer_html(session)
    canonical = doc_homepage_url(base_url)
    # Subject name is the page title; tagline is the site description (meta/OG,
    # JSON-LD, llms.txt). Dedication is content-managed in the homepage editor.
    title = content.get("subject_name") or "The Family Archive"
    description = (content.get("tagline") or "").strip()
    # The <title> tag carries the archive name alongside the subject, so the
    # single most-searched string ("the Skitch family archive") is present. The
    # bare `title` stays the subject name everywhere else (OG/JSON-LD/llms).
    org = default_org_name(author)
    page_title = f"{title} — {org}" if org and org not in title else title
    warnings: list[str] = []
    index_html = render_index(
        title=title,
        page_title=page_title,
        welcome="",
        dedication=content.get("dedication", ""),
        entries=[],
        footer_text=footer,
        head_html=site_head_html(session),
        canonical_url=canonical,
        og_description=description[:280],
        jsonld_script=collection_jsonld(base_url, title, description, live_entries, author),
        content=content,
        timeline=timeline,
        favicon_url=favicon_url(session, base_url),
        og_image=homepage_og_image_url(session, base_url),
    )

    return {
        "index.html": index_html,
        "catalogue.json": catalogue,
        "sitemap.xml": render_sitemap(base_url, live_entries, now_iso),
        "robots.txt": render_robots(base_url),
        "llms.txt": render_llms(title, description, live_entries),
    }, warnings
