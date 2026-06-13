"""Homepage-as-document: block-tree rendering of the collection index +
the resolved-group fingerprint that drives homepage dirty state.

The homepage's render depends on data OUTSIDE its own blocks (group
membership/order and member metadata), so its content hash must fold in a
fingerprint of everything a forgeDocGroup block renders. is_dirty then
detects library-side changes with zero event wiring."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .blocks import FORGE_DEDICATION, FORGE_DOC_GROUP, FORGE_NARRATIVE
from .collection import count_words, reading_time
from .groups import resolve_members
from .models import Document, Group


def get_homepage(session: Session) -> Document | None:
    from sqlalchemy import select
    return session.scalar(select(Document).where(Document.kind == "homepage"))


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
