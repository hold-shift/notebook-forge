"""Real sketch generation: Gemini image model + face gate + content cache.

Flow (mirrors the validated MemoirForge pipeline):
  1. cache lookup on sha256(image_bytes + prompt + model) — reruns are free;
  2. miss → POST the original photo + the silhouette prompt to Gemini;
  3. face-safety gate: a local OpenCV detector checks the result — a
     surviving face means the filter-defeating silhouette failed, so retry
     (up to max_retries), then refuse ("block") or surface ("warn").

The generator returns bytes; persisting to the asset store and wiring the
forgeImage block is the service layer's job (sketch_service).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .sketch import SILHOUETTE_PROMPT, SKETCH_MODEL, SketchGenerator, SketchResult, get_gemini_key

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_RETRIES = 2


class NoImageReturned(RuntimeError):
    """Gemini replied without an image part. Often transient (the image model
    sporadically returns text only), so it's retried; a persistent safety
    refusal carries its reason in the message for the operator."""


def cache_key(image_bytes: bytes, prompt: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(prompt.encode("utf-8"))
    h.update(model.encode("utf-8"))
    return h.hexdigest()


def detect_faces(image_bytes: bytes) -> int:
    """Local face count via OpenCV haarcascade — offline, no API cost.
    Returns 0 on undecodable input (the gate then passes; a garbage image
    fails elsewhere)."""
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6)
    return len(faces)


@dataclass
class GateReport:
    status: str  # pass | flagged
    faces: int
    attempts: int


class GeminiSketchGenerator(SketchGenerator):
    """generateContent with the original image inline; the response carries
    the generated image as inline_data in the candidate parts."""

    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        model: str = SKETCH_MODEL,
        face_gate: str = "block",  # block | warn
        transport=None,  # noqa: ANN001 — httpx transport override for tests
    ) -> None:
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.model = model
        self.face_gate = face_gate
        self.transport = transport
        self.last_gate: GateReport | None = None

    def _call_gemini(self, original_bytes: bytes, mime: str, prompt: str) -> bytes:
        import httpx

        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(original_bytes).decode("ascii"),
                            }
                        },
                    ]
                }
            ]
        }
        with httpx.Client(transport=self.transport, timeout=180) as client:
            resp = client.post(
                GEMINI_ENDPOINT.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
        resp.raise_for_status()
        data = resp.json()
        reasons: list[str] = []
        texts: list[str] = []
        for candidate in data.get("candidates", []):
            fr = candidate.get("finishReason")
            if fr and fr != "STOP":
                reasons.append(str(fr))
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
                if part.get("text"):
                    texts.append(part["text"].strip())
        # No image part. Pull whatever the API told us about why, so a real
        # refusal is distinguishable from a transient empty response.
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        bits: list[str] = []
        if block_reason:
            bits.append(f"blockReason={block_reason}")
        if reasons:
            bits.append(f"finishReason={','.join(reasons)}")
        if texts:
            bits.append(f'model said: "{" ".join(texts)[:200]}"')
        raise NoImageReturned("; ".join(bits) or "empty response")

    def generate(
        self,
        original_bytes: bytes,
        mime: str,
        prompt: str | None = None,
        force: bool = False,
    ) -> SketchResult:
        """`force=True` skips the cache READ (a regenerate must produce a
        fresh variation — image models are non-deterministic); the new
        result still overwrites the cache slot."""
        prompt = prompt or SILHOUETTE_PROMPT
        key = cache_key(original_bytes, prompt, self.model)
        cached = self.cache_dir / f"{key}.png"
        if cached.exists() and not force:
            self.last_gate = GateReport(status="pass", faces=0, attempts=0)
            return SketchResult(cached.read_bytes(), self.model, prompt)

        attempts = 0
        sketch = b""
        faces = 0
        last_no_image: NoImageReturned | None = None
        while attempts <= MAX_RETRIES:
            attempts += 1
            try:
                sketch = self._call_gemini(original_bytes, mime, prompt)
            except NoImageReturned as exc:
                # Image models sporadically return text-only; retry within the
                # same budget before giving up.
                last_no_image = exc
                sketch = b""
                continue
            faces = detect_faces(sketch)
            if faces == 0:
                break
        if not sketch:
            raise RuntimeError(
                f"Gemini returned no image after {attempts} attempts ({last_no_image})"
            )
        if faces > 0:
            self.last_gate = GateReport(status="flagged", faces=faces, attempts=attempts)
            if self.face_gate == "block":
                raise RuntimeError(
                    f"face gate: {faces} face(s) still detected after {attempts} attempts"
                )
        else:
            self.last_gate = GateReport(status="pass", faces=0, attempts=attempts)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(sketch)
        return SketchResult(sketch, self.model, prompt)


def make_generator(
    cache_dir: Path, model: str = SKETCH_MODEL, face_gate: str = "block"
) -> SketchGenerator:
    """Real generator when a key is configured; the loud stub otherwise."""
    api_key = get_gemini_key()
    if not api_key:
        from .sketch import StubSketchGenerator

        return StubSketchGenerator()
    return GeminiSketchGenerator(api_key, cache_dir, model=model, face_gate=face_gate)
