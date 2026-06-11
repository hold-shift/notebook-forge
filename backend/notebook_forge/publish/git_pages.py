"""GitPagesTarget — commit + push the bundle to a git remote.

This sprint it is exercised against a LOCAL bare-repo fixture only (hard
guardrail: no live publishing). The adapter itself is remote-agnostic: the
push URL comes from target config, and tests point it at a file:// bare
repo. Shells out to system git; never interactive (GIT_TERMINAL_PROMPT=0).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import PublishBundle, PublishResult, PublishTarget, copy_if_changed


class GitPagesTarget(PublishTarget):
    kind = "github-pages"

    def __init__(
        self,
        push_url: str,
        clones_dir: Path,
        branch: str = "main",
        subdir: str = "",
        author_name: str = "Notebook Forge",
        author_email: str = "forge@localhost",
    ) -> None:
        self.push_url = push_url
        self.clones_dir = Path(clones_dir)
        self.branch = branch
        self.subdir = subdir
        self.author_name = author_name
        self.author_email = author_email

    def _redact(self, text: str) -> str:
        """Strip the authenticated push URL (which may embed a PAT) from
        anything that could surface in logs or exceptions."""
        return text.replace(self.push_url, "<push-url>") if self.push_url else text

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"},
            check=False,
        )
        if result.returncode != 0:
            cmd = self._redact(" ".join(["git", *args]))
            raise RuntimeError(
                f"git failed ({result.returncode}): {cmd}\n{self._redact(result.stderr.strip())}"
            )
        return result.stdout.strip()

    def _working_clone(self) -> Path:
        clone = self.clones_dir / "pages-clone"
        if not (clone / ".git").exists():
            self.clones_dir.mkdir(parents=True, exist_ok=True)
            # shallow: the live repo carries hundreds of photos; pushing
            # from a shallow clone is fine (proven by the MemoirForge flow)
            self._git("clone", "--depth", "50", self.push_url, str(clone))
        else:
            # explicit-branch fetch + checkout -B: works for shallow clones
            # and for clones made from an initially-empty fixture (which
            # may lack a fetch refspec)
            heads = self._git("ls-remote", "--heads", "origin", self.branch, cwd=clone)
            if heads:
                self._git("fetch", "origin", self.branch, cwd=clone)
                self._git("checkout", "-B", self.branch, "FETCH_HEAD", cwd=clone)
        return clone

    def publish_root_files(self, root_files: dict[str, str]) -> str | None:
        """Commit + push only the site-root artefacts (Rebuild index
        action — e.g. after editing the homepage welcome). Returns the
        commit sha, or None when nothing changed."""
        clone = self._working_clone()
        for name, content in root_files.items():
            (clone / name).write_text(content)
        for name in root_files:
            self._git("add", "--", name, cwd=clone)
        if not self._git("status", "--porcelain", cwd=clone):
            return None
        self._git(
            "-c", f"user.name={self.author_name}", "-c", f"user.email={self.author_email}",
            "commit", "-m", "Update collection index", cwd=clone,
        )
        sha = self._git("rev-parse", "HEAD", cwd=clone)
        current = self._git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone)
        self._git("push", "origin", f"{current}:{self.branch}", cwd=clone)
        return sha

    def publish(self, bundle: PublishBundle) -> PublishResult:
        clone = self._working_clone()
        dest = clone / self.subdir if self.subdir else clone
        dest.mkdir(parents=True, exist_ok=True)

        html_rel = (Path(self.subdir) if self.subdir else Path()) / f"{bundle.slug}.html"
        (clone / html_rel).write_text(bundle.html)
        written = skipped = 0
        for asset in bundle.assets:
            target = dest / bundle.assets_dirname / asset.name
            if copy_if_changed(asset.path, target, asset.sha256):
                written += 1
            else:
                skipped += 1

        for name, content in bundle.root_files.items():
            (clone / name).write_text(content)

        # stage explicit paths only — never `git add -A`
        self._git("add", "--", str(html_rel), cwd=clone)
        assets_rel = str(
            (Path(self.subdir) if self.subdir else Path()) / bundle.assets_dirname
        )
        if bundle.assets:
            self._git("add", "--", assets_rel, cwd=clone)
        for name in bundle.root_files:
            self._git("add", "--", name, cwd=clone)

        status = self._git("status", "--porcelain", cwd=clone)
        commit_sha = None
        if status:
            self._git(
                "-c",
                f"user.name={self.author_name}",
                "-c",
                f"user.email={self.author_email}",
                "commit",
                "-m",
                f"Publish {bundle.slug}",
                cwd=clone,
            )
            commit_sha = self._git("rev-parse", "HEAD", cwd=clone)
            current = self._git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone)
            self._git("push", "origin", f"{current}:{self.branch}", cwd=clone)
        return PublishResult(
            ok=True,
            detail={"commit": commit_sha, "branch": self.branch, "pushed": bool(status)},
            assets_written=written,
            assets_skipped=skipped,
        )
