"""Sketch generation: Gemini call shape, cache, face gate, block wiring."""

import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session
from test_importer import SLUG, make_repo

from notebook_forge.blocks import FORGE_IMAGE
from notebook_forge.importer import get_or_create_pages_target, import_document
from notebook_forge.sketch import SILHOUETTE_PROMPT
from notebook_forge.sketch_gen import GeminiSketchGenerator, cache_key, detect_faces
from notebook_forge.sketch_service import generate_sketch_for_block


def png_bytes(color=(200, 200, 200), size=(64, 64)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def gemini_transport(sketch: bytes, calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        assert request.headers["x-goog-api-key"] == "test-key"
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png",
                                "data": base64.b64encode(sketch).decode()}}
            ]}}]
        })

    return httpx.MockTransport(handler)


def test_generate_calls_gemini_with_prompt_and_image(tmp_path: Path) -> None:
    sketch = png_bytes()
    calls: list = []
    gen = GeminiSketchGenerator(
        "test-key", tmp_path / "cache", transport=gemini_transport(sketch, calls)
    )
    original = png_bytes((10, 10, 10))
    result = gen.generate(original, "image/jpeg")

    assert result.image_bytes == sketch
    assert result.prompt == SILHOUETTE_PROMPT
    [body] = calls
    parts = body["contents"][0]["parts"]
    assert parts[0]["text"] == SILHOUETTE_PROMPT
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert base64.b64decode(parts[1]["inline_data"]["data"]) == original
    assert gen.last_gate.status == "pass"


def test_cache_prevents_rebilling(tmp_path: Path) -> None:
    sketch = png_bytes()
    calls: list = []
    gen = GeminiSketchGenerator(
        "test-key", tmp_path / "cache", transport=gemini_transport(sketch, calls)
    )
    original = png_bytes((20, 20, 20))
    gen.generate(original, "image/png")
    gen.generate(original, "image/png")
    assert len(calls) == 1  # second call served from cache

    # different prompt → different cache slot → new API call
    gen.generate(original, "image/png", prompt="other prompt")
    assert len(calls) == 2
    assert cache_key(original, "a", "m") != cache_key(original, "b", "m")


def test_face_gate_blocks_after_retries(tmp_path: Path, monkeypatch) -> None:
    # the gate's retry/block/warn wiring is ours to test; the detector's
    # true-positive rate is OpenCV's. Patch the detector to always "see"
    # one face so every attempt fails the gate.
    monkeypatch.setattr("notebook_forge.sketch_gen.detect_faces", lambda b: 1)
    face = png_bytes((30, 30, 30))
    calls: list = []
    gen = GeminiSketchGenerator(
        "test-key", tmp_path / "cache", face_gate="block",
        transport=gemini_transport(face, calls),
    )
    with pytest.raises(RuntimeError, match="face gate"):
        gen.generate(png_bytes(), "image/png")
    assert len(calls) == 3  # initial + MAX_RETRIES
    assert gen.last_gate.status == "flagged"
    # a blocked sketch is never cached
    assert not list((tmp_path / "cache").glob("*.png"))

    # warn mode lets it through but reports the flag
    gen_warn = GeminiSketchGenerator(
        "test-key", tmp_path / "cache2", face_gate="warn",
        transport=gemini_transport(face, []),
    )
    result = gen_warn.generate(png_bytes((1, 2, 3)), "image/png")
    assert result.image_bytes == face
    assert gen_warn.last_gate.status == "flagged"


def test_detect_faces_clean_image() -> None:
    assert detect_faces(png_bytes()) == 0
    assert detect_faces(b"not an image") == 0


def test_generate_sketch_for_block_wires_asset_and_pending(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    repo = make_repo(tmp_path, with_sketches=False)
    target = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, target)
    session.commit()

    block = next(b for b in doc.blocks if b["type"] == FORGE_IMAGE)
    assert block["props"]["sketchAssetId"] == ""

    sketch = png_bytes((5, 5, 5))
    gen = GeminiSketchGenerator(
        "test-key", workspace / "sketch-cache", transport=gemini_transport(sketch, [])
    )
    detail = generate_sketch_for_block(session, workspace, doc, block["id"], generator=gen)
    session.commit()

    updated = next(b for b in doc.blocks if b["id"] == block["id"])
    assert updated["props"]["sketchAssetId"] == detail["sketchAssetId"]
    assert updated["props"]["approval"] == "pending"  # fresh sketch needs review
    assert detail["face_gate"] == "pass"
    # the sketch landed in the content-addressed store
    from notebook_forge.assets import asset_path
    from notebook_forge.models import Asset

    asset = session.get(Asset, detail["sketchAssetId"])
    assert asset.kind == "sketches"
    assert asset_path(workspace, asset).read_bytes() == sketch


def test_sketch_settings_defaults_and_override(session: Session) -> None:
    from notebook_forge.models import Setting
    from notebook_forge.sketch import SILHOUETTE_PROMPT, SKETCH_MODEL
    from notebook_forge.sketch_service import sketch_settings

    cfg = sketch_settings(session)
    assert cfg == {
        "model": SKETCH_MODEL,
        "default_prompt": SILHOUETTE_PROMPT,
        "face_gate": "block",
    }
    session.add(Setting(key="sketch", value={"model": "gemini-2.5-flash-image",
                                             "face_gate": "warn"}))
    session.flush()
    cfg = sketch_settings(session)
    assert cfg["model"] == "gemini-2.5-flash-image"
    assert cfg["face_gate"] == "warn"
    assert cfg["default_prompt"] == SILHOUETTE_PROMPT  # unset fields keep defaults
