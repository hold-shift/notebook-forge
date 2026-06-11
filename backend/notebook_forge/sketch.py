"""Sketch generation interface (generation itself is next sprint).

The interface is in place so the forgeImage pipeline can ask for a sketch;
tonight the only implementation is a stub (no GEMINI_API_KEY in the run
environment, and generation was out of scope regardless — imported sketches
are the only sketch source this sprint).

Secrets live in the OS keychain via `keyring`; the settings table records
only WHICH keys exist and their last-verified status, never the value.
"""

from __future__ import annotations

import datetime as dt
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Setting

KEYRING_SERVICE = "notebook-forge"
GEMINI_KEY_NAME = "gemini-api-key"

SKETCH_MODEL = "gemini-3-pro-image"

# The validated hybrid sketch/silhouette prompt — the fidelity-hardened
# variant that produced every published sketch (provenance: MemoirForge
# manifests, e.g. out/1953-1954_in-the-navy.manifest.json; earlier variant
# documented in MemoirForge_PRD.md §7).
SILHOUETTE_PROMPT = """\
Re-render THIS photograph as a hand-drawn greyscale pencil sketch. Treat it as a faithful \
transcription of the existing image into pencil — an edit of the medium only, NOT a new or \
imagined illustration.

FIDELITY (critical): reproduce only what is actually visible in the photograph — the same \
buildings, objects, vehicles, vegetation, ground, and people, in the same positions, poses, and \
sizes. Do not add, invent, duplicate, or imagine any person, figure, animal, or object that is \
not clearly present in the original. The number of people in the sketch must exactly equal the \
number visible in the photograph; if the photograph shows no people, the sketch contains no \
people.

Render the setting and background — buildings, monuments, sky, ground, vehicles, objects — as a \
detailed grey graphite sketch with natural pencil shading, line work, and mid-tones, keeping the \
scene clearly recognisable.

Only where a real person is genuinely present in the photograph, render that person as a solid, \
evenly-filled dark charcoal silhouette (a deep graphite grey, roughly 88% black — distinctly the \
darkest element in the drawing but NOT pure black), with no facial features and no internal \
detail, finished with a thin slightly darker outline so the form stays crisp. Keep each person \
at their original position, size, and pose. Where people overlap, separate them with a thin \
lighter outline. The people are evenly-filled dark-charcoal silhouettes — solid and featureless, \
but tonally part of the pencil drawing, not flat pure black.

Preserve the original framing, composition, and scale exactly. Sketch only what is in the \
photograph; silhouette only the people who are actually there; add nothing."""


@dataclass
class SketchResult:
    image_bytes: bytes
    model: str
    prompt: str


class SketchGenerator(ABC):
    @abstractmethod
    def generate(self, original_bytes: bytes, mime: str, prompt: str | None = None) -> SketchResult:
        """Original photo in → faceless sketch out."""


class StubSketchGenerator(SketchGenerator):
    """Placeholder used when no Gemini key is configured. Refuses loudly
    rather than producing a fake sketch — imported sketches are the only
    sketch source this sprint."""

    def generate(self, original_bytes: bytes, mime: str, prompt: str | None = None) -> SketchResult:
        raise RuntimeError(
            "sketch generation is not configured: no Gemini API key in the "
            "OS keychain (Sprint 2 connects the real generator)"
        )


def get_gemini_key() -> str | None:
    """Keychain first; env var accepted as a fallback (never persisted)."""
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, GEMINI_KEY_NAME)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY") or None


def record_key_status(session: Session, key_name: str, present: bool, verified: bool) -> None:
    """Settings record existence + last-verified status only — no secrets."""
    setting = session.get(Setting, f"secret:{key_name}")
    value = {
        "present": present,
        "verified": verified,
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    if setting is None:
        session.add(Setting(key=f"secret:{key_name}", value=value))
    else:
        setting.value = value


def make_sketch_generator() -> SketchGenerator:
    """Real Gemini generator next sprint; stub whenever the key is absent."""
    return StubSketchGenerator()
