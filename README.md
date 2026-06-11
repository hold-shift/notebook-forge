# Notebook Forge

Local-first document pipeline and CMS for the Skitch family memoirs: ingests
published memoir HTML into a canonical BlockNote block tree (SQLite), edits it
in a Notion-style editor, and renders synchronised outputs — themed HTML now,
NotebookLM-safe Google Doc next sprint.

Status: Sprint 1 (see `SPRINT_REPORT.md`).

## Layout

- `backend/` — Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite (WAL, JSON block
  trees, FTS5 search)
- `frontend/` — Vite + React + TypeScript + BlockNote editor
- `vendor-readonly/` — read-only external reference material (gitignored)

## Quick start

```sh
make check   # ruff + pytest + tsc + vitest
make dev     # backend (uvicorn :8400) + frontend (vite :5173)
```

More in `SPRINT_REPORT.md` once Sprint 1 lands.
