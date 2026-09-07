"""Workspace location and app configuration.

The workspace lives OUTSIDE the repo (default ~/Claude/NotebookForge-workspace/) and
holds the SQLite DB, the content-addressed asset store, and export output.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_WORKSPACE = "NOTEBOOK_FORGE_WORKSPACE"
DEFAULT_WORKSPACE = Path.home() / "Claude" / "NotebookForge-workspace"

# MemoirForge is the predecessor project this tool can re-import from (an
# operator migration path, and the source of the read-only ingest samples used
# by some tests). It is optional: when the directory is absent those tests skip
# and the re-import CLI is simply unused.
ENV_MEMOIRFORGE_ROOT = "MEMOIRFORGE_ROOT"
DEFAULT_MEMOIRFORGE_ROOT = Path.home() / "ClaudeCode" / "MemoirForge"

ASSET_KINDS = ("originals", "sketches", "sources", "attachments")


def workspace_path() -> Path:
    raw = os.environ.get(ENV_WORKSPACE)
    return Path(raw).expanduser() if raw else DEFAULT_WORKSPACE


def memoirforge_root() -> Path:
    """Optional MemoirForge checkout used by the re-import tool and sample tests."""
    raw = os.environ.get(ENV_MEMOIRFORGE_ROOT)
    return Path(raw).expanduser() if raw else DEFAULT_MEMOIRFORGE_ROOT


def db_path(workspace: Path | None = None) -> Path:
    return (workspace or workspace_path()) / "forge.db"


def bootstrap_workspace(workspace: Path | None = None) -> Path:
    """Create the workspace directory tree on first run. Idempotent."""
    ws = workspace or workspace_path()
    for sub in [*(f"assets/{k}" for k in ASSET_KINDS), "exports"]:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    return ws
