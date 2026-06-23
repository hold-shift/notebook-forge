"""Homepage tile + nav: short title, audio-length label, word-count label."""

from __future__ import annotations

from notebook_forge.blocks import make_block, text_run
from notebook_forge.collection import format_audio_length, format_word_count
from notebook_forge.groups import assign_document, create_group
from notebook_forge.homepage import homepage_timeline
from notebook_forge.models import Document, Setting
from notebook_forge.narration_service import get_or_create, save_narration


def _memoir(session, slug, title, blocks=None, **meta):
    doc = Document(slug=slug, title=title, kind="memoir", blocks=blocks or [], meta=meta)
    session.add(doc)
    session.flush()
    return doc


def test_format_audio_length():
    assert format_audio_length(11081) == "3h5m"   # Junior — nearest minute
    assert format_audio_length(2700) == "45m"
    assert format_audio_length(3600) == "1h"
    assert format_audio_length(0) == ""
    assert format_audio_length(None) == ""


def test_format_word_count():
    assert format_word_count(31452) == "31k words"
    assert format_word_count(1499) == "1k words"
    assert format_word_count(300) == "<1k words"
    assert format_word_count(0) == ""


def test_timeline_uses_short_title_and_word_count(session):
    g = create_group(session, "Memoirs", "#9c5a3c")
    blocks = [make_block("paragraph", content=[text_run("word " * 31452)])]
    m = _memoir(
        session, "junior", "Junior", blocks=blocks,
        short_title="Junior", year_display="1934–1945",
        canonical_url="https://history.skitch.me/rfs/junior.html",
    )
    assign_document(session, m, g)

    [grp] = homepage_timeline(session)
    row = grp["rows"][0]
    assert row["title"] == "Junior"            # short title (here same as title)
    assert row["reading_time"].endswith("k words")  # no audio → word-count label
    assert row["has_audio"] is False


def test_timeline_uses_audio_length_when_narrated(session):
    g = create_group(session, "Memoirs", "#9c5a3c")
    m = _memoir(
        session, "junior", "Junior",
        blocks=[make_block("paragraph", content=[text_run("hello world")])],
        canonical_url="https://history.skitch.me/rfs/junior.html",
    )
    assign_document(session, m, g)
    session.add(Setting(key="tts", value={"enabled": True}))
    # Simulate a captured recording length + audio URL (no network in the test).
    rec = get_or_create(session, m)
    rec.audio_base_url = "https://pub.example.r2.dev/junior"
    rec.audio_duration_seconds = 11081.0
    session.flush()

    row = homepage_timeline(session)[0]["rows"][0]
    assert row["has_audio"] is True
    assert row["reading_time"] == "3h5m"       # recording length, not word count


def test_short_title_field_round_trips(session):
    doc = _memoir(session, "junior", "Junior", short_title="Jr.")
    assert doc.meta["short_title"] == "Jr."
    # Saving narration must not disturb meta (separate record).
    save_narration(session, doc, audio_base_url="")
    assert doc.meta["short_title"] == "Jr."
