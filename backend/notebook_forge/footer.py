"""Workspace-level footer / licence notice.

A single global Setting drives the footer that appears at the bottom of
every published HTML document, the homepage index, and every Google Doc
(safe edition). The licence label is rendered as a link to an external
URL (e.g. the Creative Commons deed) when a URL is supplied.

The footer is authoritative workspace-wide: per-document `footer_html`
meta is no longer consulted, so editing the message in Settings updates
all outputs on the next publish.
"""

from __future__ import annotations

from html import escape
from typing import Any

# Out-of-the-box default reproduces the archive's existing footer, now with
# the licence portion linked to the Creative Commons deed.
DEFAULT_FOOTER: dict[str, str] = {
    "notice": "© Christopher M.R. Skitch · The Skitch Family Archive",
    "license_label": (
        "Licensed CC BY-NC-ND 4.0 — read and share with attribution; "
        "no commercial use or adaptations."
    ),
    "license_url": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
}


def footer_setting(session: Any) -> dict[str, str]:
    """Return the workspace footer setting, falling back to DEFAULT_FOOTER
    for the whole row or any individual missing key."""
    from .models import Setting

    row = session.get(Setting, "footer")
    value = (row.value if row is not None else None) or {}
    return {
        "notice": value.get("notice", DEFAULT_FOOTER["notice"]),
        "license_label": value.get("license_label", DEFAULT_FOOTER["license_label"]),
        "license_url": value.get("license_url", DEFAULT_FOOTER["license_url"]),
    }


def footer_html(session: Any) -> str:
    """Build the footer as an inline HTML fragment.

    Notice and licence are joined with ` · `; the licence label becomes an
    anchor to `license_url` when one is set. Returns "" when both parts are
    empty (no footer is emitted by the templates in that case).
    """
    cfg = footer_setting(session)
    notice = cfg["notice"].strip()
    label = cfg["license_label"].strip()
    url = cfg["license_url"].strip()

    parts: list[str] = []
    if notice:
        parts.append(escape(notice))
    if label:
        if url:
            parts.append(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>')
        else:
            parts.append(escape(label))
    return " · ".join(parts)
