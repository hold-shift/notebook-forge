"""LocalFolderTarget — write the bundle to a folder on disk (complete)."""

from __future__ import annotations

from pathlib import Path

from .base import PublishBundle, PublishResult, PublishTarget, copy_if_changed


class LocalFolderTarget(PublishTarget):
    kind = "local-folder"

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def publish(self, bundle: PublishBundle) -> PublishResult:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{bundle.slug}.html").write_text(bundle.html)
        written = skipped = 0
        assets_dir = self.folder / bundle.assets_dirname
        for asset in bundle.assets:
            if copy_if_changed(asset.path, assets_dir / asset.name, asset.sha256):
                written += 1
            else:
                skipped += 1
        return PublishResult(
            ok=True,
            detail={"folder": str(self.folder), "html": f"{bundle.slug}.html"},
            assets_written=written,
            assets_skipped=skipped,
        )
