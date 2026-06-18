"""Homepage-as-document: block-tree rendering of the collection index +
the resolved-group fingerprint that drives homepage dirty state.

The homepage's render depends on data OUTSIDE its own blocks (group
membership/order and member metadata), so its content hash must fold in a
fingerprint of everything a forgeDocGroup block renders. is_dirty then
detects library-side changes with zero event wiring."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .blocks import FORGE_DEDICATION, FORGE_DOC_GROUP, FORGE_NARRATIVE
from .collection import count_words, reading_time
from .groups import resolve_members
from .models import Asset, Document, Group, Setting

# Banner images are published as static files next to index.html (the dev-only
# /api/assets URL doesn't exist on a published site). Mirrors the per-document
# "{slug}_assets" convention.
HOMEPAGE_ASSETS_DIR = "homepage_assets"


def _banner_published_name(index: int, ext: str) -> str:
    return f"{HOMEPAGE_ASSETS_DIR}/banner-{index}{ext}"


def get_homepage(session: Session) -> Document | None:
    from sqlalchemy import select
    return session.scalar(select(Document).where(Document.kind == "homepage"))


# ---------------------------------------------------------------------------
# Content settings (the redesigned homepage's editable fields)
#
# These live alongside the legacy title/welcome/dedication/footer_html keys in
# the single "homepage" Setting row (a JSON blob — no schema migration needed).
# The timeline is NOT stored here: it is derived live from the Group model.
# ---------------------------------------------------------------------------

HOMEPAGE_CONTENT_DEFAULTS: dict[str, Any] = {
    "subject_name": "Robert Francis Skitch",
    "subject_birth": "1934",
    "subject_place": "Collie, Western Australia",
    "tagline": (
        "From a boyhood in the Collie coalfields to Lieutenant Colonel "
        "commanding the Army Survey Regiment — eleven memoirs spanning eight "
        "decades of Australian life."
    ),
    "dedication": "To Mum & Dad, for the love, for the stories.",
    "notebooklm_cta_title": "Explore with NotebookLM",
    "notebooklm_cta_subtitle": (
        "Ask questions across the entire collection · every answer drawn from "
        "Bob's own words"
    ),
    "notebooklm_url": (
        "https://notebooklm.google.com/notebook/"
        "3a3bfc7e-fd73-49c6-a7e1-c4863af87c59"
    ),
    "about_archive": (
        "My father wrote these memoirs between 1999 and 2018, setting down "
        "nearly half a million words from memory — a remarkable act of personal "
        "record-keeping that I feel privileged to have inherited.\n\n"
        "I have digitised, edited, and published the collection here so that his "
        "stories are accessible to family, friends, and anyone with an interest "
        "in Australian life across the twentieth century.\n\n"
        "The documents are presented as he wrote them, with only light "
        "corrections for formatting. The voice is entirely his."
    ),
    "signoff": "— Christopher Skitch",
    "about_notebooklm": (
        "I have uploaded the complete collection to Google NotebookLM — an AI "
        "research tool that works exclusively from the source documents, so "
        "every answer it gives is grounded in Dad's own words.\n\n"
        "As well as answering questions about his life, NotebookLM can generate:"
    ),
    "notebooklm_features": [
        "Analytical reports on themes across the memoirs",
        "A glossary of people, places, and military terms",
        "Guided slideshows through key chapters",
        "Audio podcasts narrating the collection",
    ],
    "banner_slots": [
        {
            "era": "Army Years",
            "image_asset_id": None,
            "caption": "Officer portrait",
            "notebooklm_adapted": True,
        },
        {
            "era": "The Years Between",
            "image_asset_id": None,
            "caption": "Caravan under tree",
            "notebooklm_adapted": False,
        },
        {
            "era": "Army Years",
            "image_asset_id": None,
            "caption": "Surveyor at theodolite",
            "notebooklm_adapted": False,
        },
    ],
}


def seed_homepage_content(session: Session) -> bool:
    """Ensure the "homepage" Setting carries every redesign content field.

    Idempotent: only fills in keys that are absent, so operator edits and the
    legacy title/welcome/dedication/footer_html keys are never overwritten.
    Returns True if anything was added.
    """
    row = session.get(Setting, "homepage")
    value: dict[str, Any] = dict(row.value) if (row and row.value) else {}
    changed = False
    for key, default in HOMEPAGE_CONTENT_DEFAULTS.items():
        if key not in value:
            value[key] = copy.deepcopy(default)
            changed = True
    if changed:
        if row is None:
            session.add(Setting(key="homepage", value=value))
        else:
            row.value = value
    return changed


def _resolve_banner_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a template-ready image_url to each slot (empty → placeholder)."""
    resolved = []
    for slot in slots:
        s = dict(slot)
        asset_id = s.get("image_asset_id")
        s["image_url"] = f"/api/assets/{asset_id}" if asset_id else ""
        resolved.append(s)
    return resolved


def homepage_content(session: Session) -> dict[str, Any]:
    """The redesign's editable content, merged over defaults and made
    template-ready (multiline blocks split into paragraph lists, banner image
    URLs resolved)."""
    row = session.get(Setting, "homepage")
    stored: dict[str, Any] = dict(row.value) if (row and row.value) else {}
    content: dict[str, Any] = {
        key: stored.get(key, copy.deepcopy(default))
        for key, default in HOMEPAGE_CONTENT_DEFAULTS.items()
    }
    content["about_archive_paras"] = [
        p.strip() for p in str(content["about_archive"]).split("\n\n") if p.strip()
    ]
    content["about_notebooklm_paras"] = [
        p.strip() for p in str(content["about_notebooklm"]).split("\n\n") if p.strip()
    ]
    # Render uses the published static path (copied next to index.html), not the
    # dev /api/assets URL — so images work on GitHub Pages too.
    slots = []
    for i, slot in enumerate(content.get("banner_slots") or []):
        s = dict(slot)
        aid = s.get("image_asset_id")
        asset = session.get(Asset, aid) if aid else None
        s["image_url"] = _banner_published_name(i, asset.ext) if asset else ""
        slots.append(s)
    content["banner_slots"] = slots
    return content


def homepage_banner_assets(
    session: Session, workspace: Path
) -> list[tuple[str, Path, str]]:
    """(published_relative_name, source_file, sha256) for each banner slot that
    has an uploaded image, so the publish layer can copy them next to
    index.html. Names match the src emitted by homepage_content()."""
    from .assets import asset_path

    row = session.get(Setting, "homepage")
    stored = dict(row.value) if (row and row.value) else {}
    slots = stored.get("banner_slots") or HOMEPAGE_CONTENT_DEFAULTS["banner_slots"]
    out: list[tuple[str, Path, str]] = []
    for i, slot in enumerate(slots):
        aid = slot.get("image_asset_id")
        if not aid:
            continue
        asset = session.get(Asset, aid)
        if asset is None:
            continue
        out.append((
            _banner_published_name(i, asset.ext),
            asset_path(workspace, asset),
            asset.sha256,
        ))
    return out


def homepage_settings_view(session: Session) -> dict[str, Any]:
    """The editable homepage content for the Settings panel: raw field values
    (multiline text left intact) merged over defaults, with each banner slot's
    image_url resolved for thumbnail display."""
    row = session.get(Setting, "homepage")
    stored: dict[str, Any] = dict(row.value) if (row and row.value) else {}
    view: dict[str, Any] = {
        key: stored.get(key, copy.deepcopy(default))
        for key, default in HOMEPAGE_CONTENT_DEFAULTS.items()
    }
    view["banner_slots"] = _resolve_banner_slots(view.get("banner_slots") or [])
    return view


def set_banner_image(session: Session, slot_index: int, asset_sha: str) -> str:
    """Point a banner slot at an uploaded asset, preserving the other slots and
    all non-banner content. Returns the slot's new image_url."""
    row = session.get(Setting, "homepage")
    value: dict[str, Any] = dict(row.value) if (row and row.value) else {}
    slots = copy.deepcopy(
        value.get("banner_slots") or HOMEPAGE_CONTENT_DEFAULTS["banner_slots"]
    )
    if not 0 <= slot_index < len(slots):
        raise IndexError(f"slot_index {slot_index} out of range")
    slots[slot_index]["image_asset_id"] = asset_sha
    value["banner_slots"] = slots
    if row is None:
        session.add(Setting(key="homepage", value=value))
    else:
        row.value = value
    return f"/api/assets/{asset_sha}"


def homepage_fingerprint(session: Session) -> dict[str, Any]:
    """Everything the published homepage renders from that lives OUTSIDE the
    homepage document's own blocks: the content settings and the group-derived
    timeline. Folded into the homepage's effective content hash so editing a
    content field (or changing a library group) marks the homepage dirty —
    the block editor is no longer the source of that signal."""
    return {
        "content": homepage_settings_view(session),
        "timeline": homepage_timeline(session),
    }


def homepage_timeline(session: Session) -> list[dict[str, Any]]:
    """The memoir timeline, derived live from the library Group model in its
    existing order. Each group → {name, rows:[{period,title,reading_time,url}]}.
    Empty groups are omitted; ungrouped documents never appear (§1d/§3)."""
    from .groups import list_groups

    timeline: list[dict[str, Any]] = []
    for group in list_groups(session):
        rows = []
        for m in resolve_members(session, group.id, "date_range"):
            wc = count_words(m.blocks)
            rows.append({
                "period": m.meta.get("year_display", ""),
                "title": m.meta.get("title") or m.title,
                # Mockup shows "~2 hr" (no "read" suffix) in the timeline meta.
                "reading_time": reading_time(wc).replace(" read", "") if wc else "",
                "url": m.meta.get("canonical_url", ""),
            })
        if rows:
            timeline.append({"name": group.name, "rows": rows})
    return timeline


def _walk(blocks: list[dict[str, Any]]):
    for block in blocks:
        yield block
        children = block.get("children") or []
        if children:
            yield from _walk(children)


def doc_group_blocks(blocks: list[dict[str, Any]]) -> list[dict]:
    return [b for b in _walk(blocks) if b.get("type") == FORGE_DOC_GROUP]


def member_entry(
    session: Session,
    doc: Document,
    descriptions: dict[str, str],
    *,
    with_blurbs: bool,
    with_counts: bool,
) -> dict[str, Any]:
    wc = count_words(doc.blocks)
    entry: dict[str, Any] = {
        "slug": doc.slug,
        "title": doc.meta.get("title") or doc.title,
        "years": doc.meta.get("year_display", ""),
        "standfirst": doc.meta.get("standfirst", ""),
        "url": doc.meta.get("canonical_url", ""),
    }
    if with_blurbs:
        entry["description"] = descriptions.get(doc.slug, "")
    if with_counts:
        entry["word_count"] = wc
    return entry


def group_listing_fingerprint(session: Session, blocks: list[dict[str, Any]]) -> list[dict]:
    from .groups import catalogue_descriptions
    descriptions = catalogue_descriptions(session)
    result = []
    for block in doc_group_blocks(blocks):
        props = block.get("props", {})
        gid_raw = props.get("groupId") or "0"
        try:
            gid = int(gid_raw)
        except (ValueError, TypeError):
            gid = 0
        if gid == 0:
            result.append({"groupId": gid, "missing": True})
            continue
        group = session.get(Group, gid)
        if group is None:
            result.append({"groupId": gid, "missing": True})
            continue
        sort = props.get("sort", "date_range")
        with_blurbs = bool(props.get("showBlurbs", True))
        with_counts = bool(props.get("showWordCounts", True))
        members = resolve_members(session, gid, sort)
        result.append({
            "groupId": gid,
            "name": group.name,
            "members": [
                member_entry(session, m, descriptions,
                             with_blurbs=with_blurbs, with_counts=with_counts)
                for m in members
            ],
        })
    return result


def _inline_text_of(block: dict[str, Any]) -> str:
    from .blocks import inline_text
    return inline_text(block.get("content") or [])


def homepage_body(
    session: Session, doc: Document
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    from .groups import catalogue_descriptions
    from .renderer import inline_html

    descriptions = catalogue_descriptions(session)
    body_entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    derived: dict[str, Any] = {}

    first_h1_seen = False
    first_group_seen = False
    intro_paras_before_group: list[str] = []

    for block in doc.blocks:
        btype = block.get("type")
        props = block.get("props", {})

        if btype == "heading":
            level = int(props.get("level", 1))
            text = _inline_text_of(block)
            if level == 1 and not first_h1_seen:
                first_h1_seen = True
                derived["title"] = text
            else:
                body_entries.append({"kind": "seclabel", "text": text})

        elif btype == "paragraph":
            rendered = inline_html(block.get("content") or [])
            if not rendered.strip():
                continue
            is_first = not body_entries and not first_group_seen
            entry: dict[str, Any] = {"kind": "intro", "html": rendered}
            if is_first:
                entry["lead"] = True
            body_entries.append(entry)
            if not first_group_seen:
                intro_paras_before_group.append(_inline_text_of(block))

        elif btype == FORGE_NARRATIVE:
            rendered = inline_html(block.get("content") or [])
            if rendered.strip():
                body_entries.append({"kind": "narrative", "paragraphs": [rendered]})

        elif btype == FORGE_DEDICATION:
            text = props.get("text", "")
            if text:
                body_entries.append({"kind": "dedication", "text": text})

        elif btype == "divider":
            body_entries.append({"kind": "hr"})

        elif btype == FORGE_DOC_GROUP:
            first_group_seen = True
            gid_raw = props.get("groupId") or "0"
            try:
                gid = int(gid_raw)
            except (ValueError, TypeError):
                gid = 0
            if gid == 0:
                warnings.append("homepage: skipped group block (no group selected)")
                continue
            group = session.get(Group, gid)
            if group is None:
                warnings.append(
                    f"homepage: skipped group block (group #{gid} no longer exists)"
                )
                continue
            sort = props.get("sort", "date_range")
            with_blurbs = bool(props.get("showBlurbs", True))
            with_counts = bool(props.get("showWordCounts", True))
            layout = props.get("layout", "list")
            members = resolve_members(session, gid, sort)
            if not members:
                warnings.append(f"homepage: skipped empty group '{group.name}'")
                continue
            entries = []
            for m in members:
                e = member_entry(session, m, descriptions,
                                 with_blurbs=with_blurbs, with_counts=with_counts)
                if with_counts and "word_count" in e:
                    e["reading_time"] = reading_time(e["word_count"])
                entries.append(e)
            body_entries.append({
                "kind": "group",
                "label": group.name,
                "layout": layout,
                "entries": entries,
            })

        else:
            if btype and btype not in ("heading",):
                warnings.append(f"homepage: skipped unsupported block type '{btype}'")

    from .renderer import _merge_narrative
    body_entries = _merge_narrative(body_entries)
    derived.setdefault("title", "The Family Archive")
    derived["welcome"] = "\n\n".join(intro_paras_before_group)
    return body_entries, warnings, derived
