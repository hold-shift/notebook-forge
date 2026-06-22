"""Tests for the TTS narration backend (ElevenLabs dialect): extraction,
payloads, hashing, lexicon, staleness, manifest, and the per-document
service/export."""

from __future__ import annotations

import io
import json
import zipfile

from notebook_forge import narration, narration_service, services
from notebook_forge.blocks import make_block, text_run


def _doc_blocks() -> list[dict]:
    return [
        make_block("forgeDedication", props={"text": "For my family"}),
        make_block("heading", props={"level": 2}, content=[text_run("Chapter One")]),
        make_block("paragraph", content=[text_run("The first paragraph.")]),
        make_block("forgeFootnote", props={"marker": "1", "text": "A side note."}),
        make_block("forgeNarrative", content=[text_run("A reflective aside.")]),
        make_block("forgeImage", props={"caption": "A photo", "altText": "alt"}),
        make_block("forgeDocGroup", props={"groupId": 3}),
        make_block("paragraph", content=[text_run("")]),  # empty → skipped
    ]


def test_extraction_order_types_and_highlightable():
    blocks = narration.extract_blocks(_doc_blocks())
    types = [(b["index"], b["type"], b["highlightable"]) for b in blocks]
    assert types == [
        (0, "paragraph", True),   # dedication, spoken up front
        (1, "heading", True),
        (2, "paragraph", True),
        (3, "footnote", False),   # footnote: own block, not highlighted
        (4, "paragraph", True),   # forgeNarrative → paragraph
    ]
    assert all("photo" not in b["text"].lower() for b in blocks)


def test_payloads_are_clean_text_plus_light_break():
    """ElevenLabs dialect: clean text + a light trailing <break>, no <speak>/<prosody>."""
    blocks = narration.extract_blocks(_doc_blocks())
    heading = next(b for b in blocks if b["type"] == "heading")
    para = next(b for b in blocks if b["type"] == "paragraph" and b["index"] == 2)
    assert heading["ssml"] == 'Chapter One<break time="0.4s"/>'
    assert para["ssml"] == 'The first paragraph.<break time="0.3s"/>'
    for b in blocks:
        assert "<speak>" not in b["ssml"]
        assert "<prosody" not in b["ssml"]


def test_footnote_leads_with_spoken_cue():
    blocks = narration.extract_blocks(_doc_blocks())
    fn = next(b for b in blocks if b["type"] == "footnote")
    assert fn["ssml"] == 'Footnote. A side note.<break time="0.3s"/>'
    assert fn["highlightable"] is False


def test_plain_mode_drops_breaks():
    assert narration.build_ssml("heading", "Hi", payload_mode="plain") == "Hi"
    assert (
        narration.build_ssml("footnote", "note", payload_mode="plain") == "Footnote. note"
    )


def test_hash_is_sensitive_to_voice_and_model():
    base = narration.extract_blocks(_doc_blocks())
    other_voice = narration.extract_blocks(_doc_blocks(), voice="OTHERVOICE")
    other_model = narration.extract_blocks(_doc_blocks(), model="eleven_multilingual_v2")
    h = [b["hash"] for b in base]
    assert h != [b["hash"] for b in other_voice]
    assert h != [b["hash"] for b in other_model]
    assert h == [b["hash"] for b in narration.extract_blocks(_doc_blocks())]


def test_defaults_are_the_locked_elevenlabs_voice_and_model():
    assert narration.DEFAULT_VOICE == "fjnwTZkKtQOJaYzGLa6n"
    assert narration.DEFAULT_MODEL == "eleven_v3"


def test_text_is_not_xml_escaped():
    """EL takes natural text — ampersands/brackets pass through unescaped
    (unlike the old Polly SSML path)."""
    blocks = [make_block("paragraph", content=[text_run("R & R <at base>")])]
    out = narration.extract_blocks(blocks)
    assert out[0]["ssml"] == 'R & R <at base><break time="0.3s"/>'


def test_lexicon_plain_substitution_longest_first():
    text = "the Nui Dat base"
    lex = [
        {"phrase": "Nui", "replacement": "X"},
        {"phrase": "Nui Dat", "replacement": "Noo-ee Dat"},
    ]
    assert narration.apply_lexicon(text, lex) == "the Noo-ee Dat base"


def test_lexicon_applied_in_payload():
    blocks = [make_block("paragraph", content=[text_run("We marched to Nui Dat")])]
    lex = [{"phrase": "Nui Dat", "replacement": "Noo-ee Dat"}]
    out = narration.extract_blocks(blocks, lexicon=lex)
    assert out[0]["ssml"] == 'We marched to Noo-ee Dat<break time="0.3s"/>'


def test_title_preamble_announced_from_meta():
    """The masthead (title/subtitle/dates/author) is announced first, built from
    meta — it lives outside the block tree so would otherwise never be spoken."""
    meta = {
        "title": "Junior",
        "standfirst": "The boy I once knew but now remember",
        "year_display": "1934–1945",  # en-dash
        "author": "R.F Skitch",
    }
    blocks = narration.extract_blocks(_doc_blocks(), meta=meta)
    head = blocks[0]
    assert head["index"] == 0
    assert head["type"] == "heading"
    assert head["highlightable"] is True
    # Segments present, en-dash year range spoken as a span, author lead-in.
    assert "Junior." in head["ssml"]
    assert "The boy I once knew but now remember." in head["ssml"]
    assert "1934 to 1945." in head["ssml"]
    assert "By R.F Skitch." in head["ssml"]
    assert '<break time="0.5s"/>' in head["ssml"]   # pauses between segments
    assert head["ssml"].endswith('<break time="0.7s"/>')
    # Preamble is additive: the 5 body blocks still follow.
    assert len(blocks) == 6
    assert [b["type"] for b in blocks[1:]] == ["paragraph", "heading", "paragraph", "footnote", "paragraph"]


def test_no_title_preamble_without_meta_or_title():
    assert narration.extract_blocks(_doc_blocks()) [0]["type"] == "paragraph"  # dedication
    assert narration.extract_blocks(_doc_blocks(), meta={"title": ""})[0]["type"] == "paragraph"


def test_spoken_years_variants():
    assert narration.spoken_years("1934–1945") == "1934 to 1945"
    assert narration.spoken_years("1934-1945") == "1934 to 1945"
    assert narration.spoken_years("2004") == "2004"  # single year unchanged


def test_inline_footnote_marker_not_spoken():
    """The superscript footnote marker run (styles.fnRef) in the prose is NOT
    read aloud — only the separate footnote block speaks the note."""
    para = make_block(
        "paragraph",
        content=[
            text_run("It was a poor image of the base"),
            text_run("1", {"fnRef": True}),
            text_run("."),
        ],
    )
    out = narration.extract_blocks([para])
    assert out[0]["type"] == "paragraph"
    assert out[0]["text"] == "It was a poor image of the base."
    assert out[0]["ssml"] == 'It was a poor image of the base.<break time="0.3s"/>'
    assert "1" not in out[0]["text"]


def test_sync_status():
    assert narration.sync_status("", [], []) == "no_audio"
    assert narration.sync_status("https://s3/x", ["a", "b"], ["b", "a"]) == "in_sync"
    assert narration.sync_status("https://s3/x", ["a"], ["a", "b"]) == "stale"


def test_build_manifest_shape():
    blocks = narration.extract_blocks(_doc_blocks())
    m = narration.build_manifest(
        slug="junior", title="Junior", voice="fjnwTZkKtQOJaYzGLa6n",
        model="eleven_v3", blocks=blocks,
    )
    assert m["document_slug"] == "junior"
    assert m["voice"] == "fjnwTZkKtQOJaYzGLa6n"
    assert m["model"] == "eleven_v3"
    assert {k for k in m["blocks"][0]} == {"index", "type", "hash", "ssml", "highlightable"}


def test_tts_enabled_default_false(session):
    assert narration.tts_enabled(session) is False


def test_export_stores_hashes_and_zips_manifest(session):
    doc = services.create_document(session, "junior", "Junior", blocks=_doc_blocks())
    view = narration_service.narration_view(session, doc)
    assert view["status"] == "no_audio"
    assert view["voice"] == "fjnwTZkKtQOJaYzGLa6n"
    assert view["model"] == "eleven_v3"

    data, filename = narration_service.export_manifest(session, doc)
    assert filename == "junior.manifest.zip"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["document_slug"] == "junior"
    assert manifest["model"] == "eleven_v3"
    assert len(manifest["blocks"]) == 5

    rec = narration_service.get_or_create(session, doc)
    assert rec.exported_hashes == [b["hash"] for b in manifest["blocks"]]
    assert rec.last_exported_at is not None


def test_save_and_staleness_flow(session):
    doc = services.create_document(session, "junior", "Junior", blocks=_doc_blocks())
    narration_service.export_manifest(session, doc)
    narration_service.save_narration(session, doc, audio_base_url="https://b.s3/junior/")
    view = narration_service.narration_view(session, doc)
    assert view["status"] == "in_sync"
    assert narration_service.audio_state(session, doc) == {
        "has_audio": True,
        "audio_stale": False,
    }

    new_blocks = doc.blocks + [make_block("paragraph", content=[text_run("New tail.")])]
    services.save_blocks(session, doc, new_blocks)
    assert narration_service.narration_view(session, doc)["status"] == "stale"
    assert narration_service.audio_state(session, doc)["audio_stale"] is True


def test_save_narration_filters_empty_lexicon_rows(session):
    doc = services.create_document(session, "junior", "Junior", blocks=_doc_blocks())
    view = narration_service.save_narration(
        session,
        doc,
        lexicon=[
            {"phrase": "  ", "replacement": "x"},  # dropped
            {"phrase": "Nui Dat", "replacement": "Noo-ee Dat"},
        ],
    )
    assert view["lexicon"] == [{"phrase": "Nui Dat", "replacement": "Noo-ee Dat"}]
