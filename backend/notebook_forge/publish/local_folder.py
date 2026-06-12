"""LocalFolderTarget — write the bundle to a folder on disk (complete)."""

from __future__ import annotations

from pathlib import Path

from .base import PublishBundle, PublishResult, PublishTarget, copy_if_changed


class LocalFolderTarget(PublishTarget):
    kind = "local-folder"

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def publish_root_files(self, root_files: dict[str, str]) -> None:
        """Write only the site-root artefacts (Rebuild index action)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        for name, content in root_files.items():
            (self.folder / name).write_text(content)

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
        for name, content in bundle.root_files.items():
            (self.folder / name).write_text(content)
        return PublishResult(
            ok=True,
            detail={"folder": str(self.folder), "html": f"{bundle.slug}.html"},
            assets_written=written,
            assets_skipped=skipped,
        )

    def remove(self, slug: str) -> None:
        import shutil

        html = self.folder / f"{slug}.html"
        if html.exists():
            html.unlink()
        assets_dir = self.folder / f"{slug}_assets"
        if assets_dir.exists():
            shutil.rmtree(assets_dir)
