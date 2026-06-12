"""PublishTarget interface (M6).

A publish renders the document to a self-contained bundle (HTML + named
asset files), hands it to an adapter, then — only on success — snapshots
and updates sync_state atomically in the caller's transaction.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BundleAsset:
    name: str  # e.g. "figure-3-original.jpeg" within the assets dir
    path: Path  # file in the content-addressed store
    sha256: str


@dataclass
class PublishBundle:
    slug: str
    html: str
    assets: list[BundleAsset] = field(default_factory=list)
    # Site-root artefacts regenerated with every publish (index.html,
    # catalogue.json, sitemap.xml, robots.txt, llms.txt). Written at the
    # TARGET ROOT, not inside the documents subdir.
    root_files: dict[str, str] = field(default_factory=dict)
    # NotebookLM-safe edition (sketches inlined, captions linking to the
    # live anchors). Only populated for targets that consume it (Drive).
    safe_md: str = ""

    @property
    def assets_dirname(self) -> str:
        return f"{self.slug}_assets"


@dataclass
class PublishResult:
    ok: bool
    detail: dict = field(default_factory=dict)
    assets_written: int = 0
    assets_skipped: int = 0


class PublishTarget(ABC):
    """One publish destination. Adapters are pure I/O: no DB access."""

    kind: str

    @abstractmethod
    def publish(self, bundle: PublishBundle) -> PublishResult: ...

    def remove(self, slug: str) -> None:  # noqa: B027
        """Delete a published document from this target. Override in adapters
        that support removal; the default is a no-op (e.g. Drive may lack it)."""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_if_changed(src: Path, dst: Path, src_sha: str) -> bool:
    """Copy src→dst unless dst already has identical content (assets are
    content-addressed, so a SHA-256 match is exact). Returns True if a
    copy happened."""
    if dst.exists() and file_sha256(dst) == src_sha:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(src, dst)
    return True
