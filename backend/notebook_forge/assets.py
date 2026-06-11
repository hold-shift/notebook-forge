"""Content-addressed asset store.

Files live at {workspace}/assets/{kind}/{sha256}{ext}; the DB row (Asset)
holds metadata only. Ingest is idempotent: same bytes → same address.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Asset


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_path(workspace: Path, asset: Asset) -> Path:
    return workspace / "assets" / asset.kind / f"{asset.sha256}{asset.ext}"


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return None, None


def ingest_file(session: Session, workspace: Path, src: Path, kind: str) -> Asset:
    """Copy a file into the store (if new) and upsert its Asset row."""
    digest = sha256_file(src)
    ext = src.suffix.lower()
    existing = session.get(Asset, digest)
    if existing is not None:
        return existing

    width, height = _image_size(src)
    asset = Asset(
        sha256=digest,
        kind=kind,
        filename=src.name,
        ext=ext,
        mime=mimetypes.guess_type(src.name)[0] or "application/octet-stream",
        size_bytes=src.stat().st_size,
        width=width,
        height=height,
    )
    dst = asset_path(workspace, asset)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    session.add(asset)
    return asset
