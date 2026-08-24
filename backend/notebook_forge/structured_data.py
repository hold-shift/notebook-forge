"""Rich structured data (JSON-LD) + head metadata for published pages.

SEO/AEO plan §4–§6. The per-document page carries a JSON-LD ``@graph`` that
de-duplicates the shared entities (author Person, publisher Organization,
the collection CreativeWorkSeries) by ``@id`` and hangs the page's ``Article``
— with dates, word count, reading time, ``about``/``mentions`` entities drawn
from the report tracks, an ``AudioObject`` when the doc is narrated, a
``SpeakableSpecification`` and a ``BreadcrumbList`` — off them.

Everything here is a PURE function of an already-assembled context dict
(``DocSeoContext``): the session-side gathering (report tracks, audio record,
group, base URL, homepage title) lives in ``publish.service.build_bundle`` so
this module stays trivially unit-testable and free of DB access.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .models import Document

# The one canonical robots directive for every published page (plan §5): index
# everything, and let crawlers use large image/text/video previews.
ROBOTS = "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
LOCALE = "en_AU"  # OpenGraph locale form
LANG = "en-AU"  # BCP-47 / html lang + inLanguage form

# Cap how many entities we emit so a heavily-annotated memoir doesn't bloat the
# page head with hundreds of names.
_MAX_ABOUT = 12
_MAX_MENTIONS = 30
_MAX_TAGS = 8


@dataclass
class DocSeoContext:
    """Everything needed to build a document page's structured data + head.

    Assembled by the publish layer; consumed by the pure builders below."""

    base_url: str
    canonical_url: str
    title: str
    description: str = ""
    author_name: str = ""  # the byline as printed on the page ("R.F Skitch")
    # The subject's canonical name. The Person entity is shared by @id with the
    # homepage graph, so its `name` must be the same string in both — the
    # per-document byline may be an abbreviated form and is NOT used here.
    person_name: str = ""
    author_birth: str = ""  # e.g. "1934" → Person.birthDate
    author_death: str = ""  # e.g. "2026-07-08" → Person.deathDate
    publisher_name: str = ""
    publisher_url: str = ""
    logo_url: str = ""
    site_title: str = ""  # collection / og:site_name
    series_id: str = ""  # @id of the CreativeWorkSeries (homepage#collection)
    series_name: str = ""
    homepage_url: str = ""
    date_published: str = ""  # ISO-8601
    date_modified: str = ""  # ISO-8601
    section: str = ""  # articleSection / group name
    word_count: int = 0
    time_required: str = ""  # ISO-8601 duration, e.g. "PT25M"
    image_url: str = ""  # absolute og:image
    places: list[str] = field(default_factory=list)  # geo track → about (Place)
    people: list[str] = field(default_factory=list)  # people track → mentions (Person)
    audio_url: str = ""  # absolute mp3 URL (empty → no AudioObject)
    audio_duration: str = ""  # ISO-8601 duration, e.g. "PT3H5M"
    twitter_site: str = ""  # @handle (optional)
    twitter_creator: str = ""  # @handle (optional)
    year_display: str = ""  # e.g. "1934–1945", for the <title>


def page_title(title: str, year_display: str, site_title: str) -> str:
    """The <title> tag for a memoir page.

    The legacy form was "1934–1945 · Junior" — a date range and a word that
    means nothing out of context, which wastes the strongest relevance signal
    the page has. Lead with the document title, keep the era as a qualifier,
    and append the subject's name (what people actually search):
    "Junior (1934–1945) · Robert Francis Skitch"."""
    head = f"{title} ({year_display})" if (title and year_display) else (title or year_display)
    if site_title and site_title.casefold() not in head.casefold():
        return f"{head} · {site_title}" if head else site_title
    return head


# ------------------------------------------------------------- assembly


def _first_figure_image_url(session: Session, doc: Document, base_url: str) -> str:
    """Absolute URL of the document's first figure (og:image fallback, plan §5).

    Mirrors the published asset naming (``{slug}_assets/figure-1-original{ext}``)
    and the ``rfs/`` page subdir, so the URL resolves on the live site."""
    from .blocks import FORGE_IMAGE
    from .collection import PAGES_SUBDIR
    from .models import Asset

    for block in doc.blocks:
        if block.get("type") != FORGE_IMAGE:
            continue
        asset_id = block.get("props", {}).get("assetId", "")
        if not asset_id:
            continue
        asset = session.get(Asset, asset_id)
        ext = asset.ext if asset is not None else ".jpeg"
        slug = doc.meta.get("slug", doc.slug)
        return f"{base_url.rstrip('/')}/{PAGES_SUBDIR}/{slug}_assets/figure-1-original{ext}"
    return ""


def build_context(
    session: Session, doc: Document, base_url: str | None = None
) -> DocSeoContext:
    """Assemble a document's SEO context from current DB state (plan §4–§6).

    The one DB-aware entry point; the builders above stay pure. Called by the
    publish layer, which stores the result in ``meta['seo']`` for the renderer."""
    from sqlalchemy import select

    from .collection import (
        author_name,
        count_words,
        doc_canonical_url,
        doc_homepage_url,
        pages_base_url,
    )
    from .homepage import homepage_content
    from .models import Group, ReportTrack, Setting
    from .narration import tts_enabled
    from .narration_service import audio_duration, has_audio

    base = (base_url or pages_base_url(session)).rstrip("/")
    meta = doc.meta or {}
    slug = meta.get("slug", doc.slug)
    canonical = meta.get("canonical_url") or doc_canonical_url(base, slug)
    homepage_url = meta.get("homepage_url") or doc_homepage_url(base)

    content = homepage_content(session)
    site_title = content.get("subject_name") or "The Family Archive"
    author = meta.get("author") or author_name(session)

    publishing = session.get(Setting, "publishing")
    pub_cfg = (publishing.value or {}) if publishing is not None else {}
    org_name = (pub_cfg.get("org_name") or "").strip()
    if not org_name:
        surname = (author.split()[-1] if author.split() else "").strip()
        org_name = f"The {surname} Family Archive" if surname else site_title

    # articleSection = the document's library group name, if any.
    section = ""
    if doc.group_id is not None:
        group = session.get(Group, doc.group_id)
        section = group.name if group is not None else ""

    words = count_words(doc.blocks)

    # about (Place) / mentions (Person) from the report tracks, in stored order.
    tracks = session.scalars(
        select(ReportTrack)
        .where(ReportTrack.document_id == doc.id)
        .order_by(ReportTrack.seq, ReportTrack.id)
    ).all()
    places = [t.data.get("place", "") for t in tracks if t.track_type == "geo"]
    people = [t.data.get("name", "") for t in tracks if t.track_type == "people"]

    # AudioObject inputs — only when narration is on and the doc has audio.
    audio_url = ""
    audio_iso = ""
    if tts_enabled(session) and has_audio(session, doc):
        rec_base = _narration_base(session, doc)
        if rec_base:
            audio_url = f"{rec_base}/document.mp3"
            audio_iso = iso_duration_from_seconds(audio_duration(session, doc))

    image_url = (meta.get("og_image") or "").strip() or _first_figure_image_url(
        session, doc, base
    )

    return DocSeoContext(
        base_url=base,
        canonical_url=canonical,
        title=meta.get("title") or doc.title,
        description=(meta.get("meta_description") or meta.get("standfirst") or "").strip(),
        author_name=author,
        person_name=str(content.get("subject_name") or "").strip() or author,
        author_birth=str(content.get("subject_birth") or "").strip(),
        author_death=str(content.get("subject_death") or "").strip(),
        publisher_name=org_name,
        publisher_url=homepage_url,
        logo_url=(pub_cfg.get("logo_url") or "").strip(),
        site_title=site_title,
        series_id=f"{homepage_url}#collection",
        series_name=site_title,
        homepage_url=homepage_url,
        date_published=meta.get("date_published", ""),
        date_modified=_iso(doc.updated_at),
        section=section,
        word_count=words,
        time_required=iso_duration_from_words(words),
        image_url=image_url,
        places=places,
        people=people,
        audio_url=audio_url,
        audio_duration=audio_iso,
        twitter_site=(pub_cfg.get("twitter_site") or "").strip(),
        twitter_creator=(pub_cfg.get("twitter_creator") or "").strip(),
        year_display=meta.get("year_display", ""),
    )


def _narration_base(session: Session, doc: Document) -> str:
    from .models import DocumentNarration

    rec = (
        session.query(DocumentNarration)
        .filter(DocumentNarration.document_id == doc.id)
        .one_or_none()
    )
    return (rec.audio_base_url or "").strip().rstrip("/") if rec is not None else ""


def _iso(value: Any) -> str:
    import datetime as _dt

    if value is None:
        return ""
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_dt.UTC)
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------- duration


def iso_duration_from_minutes(minutes: float) -> str:
    """Whole-minute ISO-8601 duration: 25 → 'PT25M', 185 → 'PT3H5M'."""
    total = max(0, round(minutes))
    if total == 0:
        return ""
    h, m = divmod(total, 60)
    out = "PT"
    if h:
        out += f"{h}H"
    if m or not h:
        out += f"{m}M"
    return out


def iso_duration_from_words(words: int, wpm: int = 200) -> str:
    if not words or words <= 0:
        return ""
    return iso_duration_from_minutes(words / wpm)


def iso_duration_from_seconds(seconds: float | None) -> str:
    """'PT3H5M4S' — seconds included only when non-zero."""
    if not seconds or seconds <= 0:
        return ""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    out = "PT"
    if h:
        out += f"{h}H"
    if m:
        out += f"{m}M"
    if s or (not h and not m):
        out += f"{s}S"
    return out


# ---------------------------------------------------------------- entities


_ISO_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def iso_date_or_year(value: str) -> str:
    """A schema.org-safe date: a full ISO date or a bare year, else the year
    found inside the value, else "". Guards against a human-readable lifespan
    ("1934 - 2026") reaching birthDate, which is not a valid date literal."""
    v = str(value or "").strip()
    if _ISO_DATE_RE.match(v):
        return v
    m = re.search(r"\d{4}", v)
    return m.group(0) if m else ""


def _person(ctx: DocSeoContext) -> dict[str, Any]:
    # @id anchors on the homepage's canonical URL (the site root) — must stay
    # byte-identical to collection._person so the entities de-duplicate.
    person: dict[str, Any] = {
        "@type": "Person",
        "@id": f"{ctx.base_url.rstrip('/')}/#author",
        "name": ctx.person_name or ctx.author_name or "Author",
    }
    if iso_date_or_year(ctx.author_birth):
        person["birthDate"] = iso_date_or_year(ctx.author_birth)
    if iso_date_or_year(ctx.author_death):
        person["deathDate"] = iso_date_or_year(ctx.author_death)
    if ctx.homepage_url:
        person["url"] = ctx.homepage_url
    return person


def _publisher(ctx: DocSeoContext) -> dict[str, Any]:
    org: dict[str, Any] = {
        "@type": "Organization",
        "@id": f"{ctx.base_url.rstrip('/')}/#publisher",
        "name": ctx.publisher_name or ctx.site_title or "The Family Archive",
    }
    if ctx.publisher_url or ctx.homepage_url:
        org["url"] = ctx.publisher_url or ctx.homepage_url
    if ctx.logo_url:
        org["logo"] = {"@type": "ImageObject", "url": ctx.logo_url}
    return org


def _series_ref(ctx: DocSeoContext) -> dict[str, Any] | None:
    if not ctx.series_id:
        return None
    ref: dict[str, Any] = {
        "@type": "CreativeWorkSeries",
        "@id": ctx.series_id,
    }
    if ctx.series_name:
        ref["name"] = ctx.series_name
    if ctx.homepage_url:
        ref["url"] = ctx.homepage_url
    return ref


def _dedup(names: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        name = (raw or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _audio_object(ctx: DocSeoContext) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "@type": "AudioObject",
        "@id": f"{ctx.canonical_url}#audio",
        "contentUrl": ctx.audio_url,
        "encodingFormat": "audio/mpeg",
        # The published page carries the full text synced to the audio, so it
        # is itself the transcript surface.
        "transcript": ctx.canonical_url,
    }
    if ctx.audio_duration:
        obj["duration"] = ctx.audio_duration
    return obj


def _breadcrumb(ctx: DocSeoContext) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    pos = 1
    if ctx.homepage_url:
        items.append({
            "@type": "ListItem",
            "position": pos,
            "name": ctx.site_title or ctx.series_name or "The Archive",
            "item": ctx.homepage_url,
        })
        pos += 1
    if ctx.section:
        # No dedicated group page exists; the section resolves to the homepage.
        items.append({
            "@type": "ListItem",
            "position": pos,
            "name": ctx.section,
            "item": ctx.homepage_url or ctx.canonical_url,
        })
        pos += 1
    items.append({
        "@type": "ListItem",
        "position": pos,
        "name": ctx.title,
        "item": ctx.canonical_url,
    })
    return {
        "@type": "BreadcrumbList",
        "@id": f"{ctx.canonical_url}#breadcrumb",
        "itemListElement": items,
    }


def article_graph(ctx: DocSeoContext) -> dict[str, Any]:
    """The full ``@graph`` object for a document page (plan §5–§6)."""
    author = _person(ctx)
    publisher = _publisher(ctx)

    article: dict[str, Any] = {
        "@type": "Article",
        "@id": f"{ctx.canonical_url}#article",
        "headline": ctx.title,
        "name": ctx.title,
        "url": ctx.canonical_url,
        "inLanguage": LANG,
        "author": {"@id": author["@id"]},
        "publisher": {"@id": publisher["@id"]},
    }
    if ctx.description:
        article["description"] = ctx.description
    series = _series_ref(ctx)
    if series is not None:
        article["isPartOf"] = {"@id": series["@id"]}
    if ctx.date_published:
        article["datePublished"] = ctx.date_published
    if ctx.date_modified:
        article["dateModified"] = ctx.date_modified
    if ctx.section:
        article["articleSection"] = ctx.section
    if ctx.word_count > 0:
        article["wordCount"] = ctx.word_count
    if ctx.time_required:
        article["timeRequired"] = ctx.time_required
    if ctx.image_url:
        article["image"] = ctx.image_url

    about = [{"@type": "Place", "name": p} for p in _dedup(ctx.places, _MAX_ABOUT)]
    mentions = [{"@type": "Person", "name": p} for p in _dedup(ctx.people, _MAX_MENTIONS)]
    if about:
        article["about"] = about
    if mentions:
        article["mentions"] = mentions

    # Speakable: the masthead heading + standfirst read well aloud and are the
    # natural voice-assistant answer surface.
    article["speakable"] = {
        "@type": "SpeakableSpecification",
        "cssSelector": ["h1.title", ".standfirst"],
    }

    if ctx.audio_url:
        article["audio"] = _audio_object(ctx)
        # We earn the accessibility claims: the player syncs words to audio.
        article["accessMode"] = ["textual", "visual", "auditory"]
        article["accessModeSufficient"] = [["auditory"], ["textual"]]
        article["accessibilityFeature"] = ["synchronizedAudioText", "readingOrder"]
        article["potentialAction"] = {
            "@type": "ListenAction",
            "target": f"{ctx.canonical_url}#ttsPlayer",
        }

    graph: list[dict[str, Any]] = [author, publisher]
    if series is not None:
        graph.append(series)
    graph.append(article)
    graph.append(_breadcrumb(ctx))
    return {"@context": "https://schema.org", "@graph": graph}


def article_jsonld_script(ctx: DocSeoContext) -> str:
    """The ``<script type="application/ld+json">`` for the document page."""
    body = json.dumps(
        article_graph(ctx), ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


# ---------------------------------------------------------------- head tags


def head_meta(ctx: DocSeoContext) -> dict[str, Any]:
    """The extra ``<head>`` fields the page template emits (plan §5–§6).

    Returned as a flat dict so the template can pull each with a default; empty
    values are simply omitted by the template's ``{% if %}`` guards."""
    tags = _dedup(ctx.places + ctx.people, _MAX_TAGS)
    return {
        "page_title": page_title(ctx.title, ctx.year_display, ctx.site_title),
        "lang": LANG,
        "locale": LOCALE,
        "robots": ROBOTS,
        "site_name": ctx.site_title,
        "author": ctx.author_name,
        "article_published_time": ctx.date_published,
        "article_modified_time": ctx.date_modified,
        "article_section": ctx.section,
        "article_tags": tags,
        "twitter_site": ctx.twitter_site,
        "twitter_creator": ctx.twitter_creator,
        "image": ctx.image_url,
        "audio_url": ctx.audio_url,
    }
