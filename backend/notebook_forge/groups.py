"""Group CRUD + membership. A document belongs to at most one group
(group_id nullable); group_position orders documents within a group and
within the Ungrouped (NULL) bucket. Positions may gap after deletes;
every positions write renormalises to 0..n-1."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services
from .models import Document, Group

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _start_year(slug: str) -> int:
    try:
        return int(slug.split("-", 1)[0])
    except ValueError:
        return 9999


def list_groups(session: Session) -> list[Group]:
    return list(session.scalars(select(Group).order_by(Group.sort_order, Group.id)))


def create_group(session: Session, name: str, color: str) -> Group:
    name = name.strip()
    if not name:
        raise ValueError("group name must not be empty")
    if not COLOR_RE.match(color):
        raise ValueError(f"invalid color '{color}': must be #rrggbb")
    max_order = session.scalar(
        select(Group.sort_order).order_by(Group.sort_order.desc()).limit(1)
    )
    next_order = (max_order if max_order is not None else -1) + 1
    group = Group(name=name, color=color, sort_order=next_order)
    session.add(group)
    session.flush()
    return group


def update_group(
    session: Session, group: Group, *, name: str | None = None, color: str | None = None
) -> Group:
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("group name must not be empty")
        group.name = name
    if color is not None:
        if not COLOR_RE.match(color):
            raise ValueError(f"invalid color '{color}': must be #rrggbb")
        group.color = color
    session.flush()
    return group


def reorder_groups(session: Session, ids: list[int]) -> None:
    existing = {g.id for g in list_groups(session)}
    if set(ids) != existing:
        raise ValueError("ids must be exactly the set of existing group ids")
    for i, gid in enumerate(ids):
        group = session.get(Group, gid)
        if group is not None:
            group.sort_order = i
    session.flush()


def delete_group(session: Session, group: Group) -> int:
    members = list(session.scalars(
        select(Document)
        .where(Document.group_id == group.id)
        .order_by(Document.group_position, Document.id)
    ))
    ungrouped_max = session.scalar(
        select(Document.group_position)
        .where(Document.group_id.is_(None))
        .order_by(Document.group_position.desc())
        .limit(1)
    )
    base = (ungrouped_max if ungrouped_max is not None else -1) + 1
    for i, doc in enumerate(members):
        doc.group_id = None
        doc.group_position = base + i
    session.delete(group)
    session.flush()
    return len(members)


def assign_document(session: Session, doc: Document, group: Group | None) -> Document:
    new_gid = group.id if group is not None else None
    if doc.group_id == new_gid:
        return doc
    if group is not None:
        max_pos = session.scalar(
            select(Document.group_position)
            .where(Document.group_id == group.id)
            .order_by(Document.group_position.desc())
            .limit(1)
        )
        doc.group_position = (max_pos if max_pos is not None else -1) + 1
        doc.group_id = group.id
        services.record_change(session, doc, "edit", f"moved to group '{group.name}'")
    else:
        max_pos = session.scalar(
            select(Document.group_position)
            .where(Document.group_id.is_(None))
            .order_by(Document.group_position.desc())
            .limit(1)
        )
        doc.group_position = (max_pos if max_pos is not None else -1) + 1
        doc.group_id = None
        services.record_change(session, doc, "edit", "removed from group")
    session.flush()
    return doc


def set_positions(session: Session, group_id: int | None, slugs: list[str]) -> None:
    if group_id is None:
        members = list(session.scalars(
            select(Document).where(Document.group_id.is_(None))
        ))
    else:
        members = list(session.scalars(
            select(Document).where(Document.group_id == group_id)
        ))
    member_slugs = {d.slug for d in members}
    if set(slugs) != member_slugs or len(slugs) != len(member_slugs):
        raise ValueError("slugs must be exactly the membership of the bucket")
    slug_to_doc = {d.slug: d for d in members}
    for i, slug in enumerate(slugs):
        slug_to_doc[slug].group_position = i
    session.flush()


def resolve_members(session: Session, group_id: int, sort: str) -> list[Document]:
    docs = list(session.scalars(
        select(Document)
        .where(Document.group_id == group_id, Document.kind == "memoir")
    ))
    if sort == "manual":
        docs.sort(key=lambda d: (d.group_position, d.id))
    elif sort == "date_range":
        docs.sort(key=lambda d: (_start_year(d.slug), d.slug))
    elif sort == "title_az":
        docs.sort(key=lambda d: d.title.casefold())
    elif sort == "last_updated":
        docs.sort(key=lambda d: d.updated_at or d.created_at, reverse=True)
    else:
        raise ValueError(f"unknown sort '{sort}'")
    return docs


def catalogue_descriptions(session: Session) -> dict[str, str]:
    from .models import Setting

    setting = session.get(Setting, "catalogue")
    if setting is None:
        return {}
    return {
        e.get("stem", ""): e.get("description", "")
        for e in (setting.value or {}).get("entries", [])
        if e.get("stem")
    }


def group_member_dict(
    session: Session, group: Group, descriptions: dict[str, str]
) -> dict[str, Any]:
    from .collection import count_words

    members = list(session.scalars(
        select(Document)
        .where(Document.group_id == group.id)
        .order_by(Document.group_position, Document.id)
    ))
    return {
        "id": group.id,
        "name": group.name,
        "color": group.color,
        "sort_order": group.sort_order,
        "members": [
            {
                "slug": d.slug,
                "title": d.meta.get("title") or d.title,
                "year_display": d.meta.get("year_display", ""),
                "standfirst": d.meta.get("standfirst", ""),
                "description": descriptions.get(d.slug, ""),
                "word_count": count_words(d.blocks),
                "group_position": d.group_position,
            }
            for d in members
        ],
    }
