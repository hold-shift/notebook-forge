"""Workspace location and app configuration.

The workspace lives OUTSIDE the repo (default ~/NotebookForge-workspace/) and
holds the SQLite DB, the content-addressed asset store, and export output.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_WORKSPACE = "NOTEBOOK_FORGE_WORKSPACE"
DEFAULT_WORKSPACE = Path.home() / "NotebookForge-workspace"

ASSET_KINDS = ("originals", "sketches", "sources")


def workspace_path() -> Path:
    raw = os.environ.get(ENV_WORKSPACE)
    return Path(raw).expanduser() if raw else DEFAULT_WORKSPACE


def db_path(workspace: Path | None = None) -> Path:
    return (workspace or workspace_path()) / "forge.db"


def bootstrap_workspace(workspace: Path | None = None) -> Path:
    """Create the workspace directory tree on first run. Idempotent."""
    ws = workspace or workspace_path()
    for sub in [*(f"assets/{k}" for k in ASSET_KINDS), "exports"]:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    return ws
