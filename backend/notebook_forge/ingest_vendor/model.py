"""Core dataclasses: Document (in-memory) and Manifest (durable sidecar)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MANIFEST_VERSION = 1


class TextBlock(BaseModel):
    """A paragraph or heading in document order."""

    kind: Literal["h1", "h2", "h3", "p"] = "p"
    text: str = ""


class ImageRef(BaseModel):
    """An extracted image and where it sat in the source."""

    src_path: str            # repo-relative path on disk (in work/<session>/media/)
    sha256: str
    order: int               # position in the source document
    width: int = 0
    height: int = 0
    nearby_caption: str = ""  # any caption text found adjacent to the image
    mime: str = "image/jpeg"


class DocumentDraft(BaseModel):
    """Output of extract+clean: ordered body with image placeholders."""

    source_file: str
    source_sha256: str
    detected_title: str = ""
    detected_author: str = ""
    detected_standfirst: str = ""           # from docProps/core.xml dc:subject
    blocks: list[TextBlock] = Field(default_factory=list)
    images: list[ImageRef] = Field(default_factory=list)
    # Captions detected with high confidence (e.g. Word "Caption" style on the
    # paragraph immediately following the image). Keyed by image.order. When
    # present, seeded as the figure caption with caption_source="original".
    detected_captions: dict[int, str] = Field(default_factory=dict)
    # Footnotes extracted from page bottoms, in document order. Each:
    #   {"n": global_number, "text": footnote body, "page": source page_idx}
    # Rendered as a Footnotes section at the end of the assembled body,
    # with inline references rewritten to anchor links.
    footnotes: list[dict[str, Any]] = Field(default_factory=list)
    # The body interleaved with image placeholders, keyed by image order index.
    # Each entry is either a TextBlock or {"image_ref": <int order>}.
    body: list[dict[str, Any]] = Field(default_factory=list)
