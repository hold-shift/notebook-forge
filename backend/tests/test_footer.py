"""Workspace footer / licence: defaults, HTML build, link, and the three
publish paths (HTML doc, homepage index, Google Doc markdown)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from notebook_forge.footer import DEFAULT_FOOTER, footer_html, footer_setting
from notebook_forge.models import Setting
from notebook_forge.safe_edition import html_fragment_to_md


def test_default_when_no_row(session: Session) -> None:
    assert footer_setting(session) == DEFAULT_FOOTER


def test_html_links_licence_to_url(session: Session) -> None:
    html = footer_html(session)
    assert "© Christopher M.R. Skitch · The Skitch Family Archive" in html
    assert (
        '<a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">'
        "Licensed CC BY-NC-ND 4.0" in html
    )
    # The same fragment converts to a Markdown link for the Google Doc path.
    md = html_fragment_to_md(html)
    assert "](https://creativecommons.org/licenses/by-nc-nd/4.0/)" in md


def test_custom_value_and_blank_url(session: Session) -> None:
    session.add(
        Setting(
            key="footer",
            value={"notice": "© Me", "license_label": "All rights reserved", "license_url": ""},
        )
    )
    session.flush()
    html = footer_html(session)
    assert html == "© Me · All rights reserved"  # no anchor when URL blank
    assert "<a" not in html


def test_escapes_html_in_fields(session: Session) -> None:
    session.add(
        Setting(
            key="footer",
            value={"notice": "A & B <x>", "license_label": "L", "license_url": ""},
        )
    )
    session.flush()
    html = footer_html(session)
    assert "A &amp; B &lt;x&gt;" in html


def test_missing_keys_fall_back_to_defaults(session: Session) -> None:
    session.add(Setting(key="footer", value={"notice": "Just a notice"}))
    session.flush()
    cfg = footer_setting(session)
    assert cfg["notice"] == "Just a notice"
    assert cfg["license_label"] == DEFAULT_FOOTER["license_label"]
    assert cfg["license_url"] == DEFAULT_FOOTER["license_url"]
