"""Workspace footer / licence: block-document defaults, HTML build, Markdown
build, legacy migration, and escaping across the publish paths."""

from __future__ import annotations

from sqlalchemy.orm import Session

from notebook_forge.footer import (
    DEFAULT_FOOTER,
    footer_blocks,
    footer_html,
    footer_markdown,
    footer_setting,
)
from notebook_forge.models import Setting


def test_default_when_no_row(session: Session) -> None:
    """With no setting, the footer is the default block document and renders the
    notice plus the Creative Commons licence as a link."""
    assert footer_setting(session) == {"blocks": footer_blocks(session)}
    html = footer_html(session)
    assert "© Christopher M.R. Skitch · The Skitch Family Archive" in html
    assert (
        '<a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">'
        "Licensed CC BY-NC-ND 4.0" in html
    )
    assert html.startswith("<p>") and html.endswith("</p>")


def test_default_markdown_links_licence(session: Session) -> None:
    md = footer_markdown(session)
    assert "© Christopher M.R. Skitch" in md
    assert "](https://creativecommons.org/licenses/by-nc-nd/4.0/)" in md


def test_blocks_render_paragraphs_and_links(session: Session) -> None:
    session.add(
        Setting(
            key="footer",
            value={
                "blocks": [
                    {"type": "paragraph", "props": {}, "content": [
                        {"type": "text", "text": "© Me", "styles": {}},
                    ]},
                    {"type": "paragraph", "props": {}, "content": [
                        {"type": "link", "href": "https://example.com",
                         "content": [{"type": "text", "text": "Terms", "styles": {}}]},
                    ]},
                ]
            },
        )
    )
    session.flush()
    html = footer_html(session)
    assert html == '<p>© Me</p><p><a href="https://example.com">Terms</a></p>'
    md = footer_markdown(session)
    assert md == "© Me\n[Terms](https://example.com)"


def test_empty_blocks_render_nothing(session: Session) -> None:
    session.add(Setting(key="footer", value={"blocks": []}))
    session.flush()
    assert footer_html(session) == ""
    assert footer_markdown(session) == ""


def test_legacy_fields_migrate_to_blocks(session: Session) -> None:
    """A pre-upgrade workspace (notice/licence/url trio, no blocks) keeps its
    footer verbatim via on-read migration to a block."""
    session.add(
        Setting(
            key="footer",
            value={"notice": "© Me", "license_label": "All rights reserved", "license_url": ""},
        )
    )
    session.flush()
    html = footer_html(session)
    assert html == "<p>© Me · All rights reserved</p>"  # no anchor when URL blank
    assert "<a" not in html


def test_escapes_html_in_text(session: Session) -> None:
    session.add(
        Setting(
            key="footer",
            value={"blocks": [
                {"type": "paragraph", "props": {}, "content": [
                    {"type": "text", "text": "A & B <x>", "styles": {}},
                ]},
            ]},
        )
    )
    session.flush()
    assert "A &amp; B &lt;x&gt;" in footer_html(session)


def test_default_footer_constant_still_drives_default(session: Session) -> None:
    # The default block document is built from DEFAULT_FOOTER, so its text and
    # licence URL still appear out of the box.
    html = footer_html(session)
    assert DEFAULT_FOOTER["notice"] in html
    assert DEFAULT_FOOTER["license_url"] in html
