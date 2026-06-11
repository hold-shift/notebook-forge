# Notebook Forge

Local-first document pipeline and CMS for the Skitch family memoirs. The
seven published memoirs are ingested from the live family-history site into
a canonical BlockNote block tree (SQLite), edited in a Notion-style editor,
and rendered back to the exact MemoirForge house style — themed HTML now,
NotebookLM-safe Google Doc next sprint.

Sprint 1 status: **`SPRINT_REPORT.md`** (read that first), round-trip
evidence in **`reports/roundtrip.md`**.

## Layout

- `backend/` — Python 3.12 (via `uv`), FastAPI, SQLAlchemy 2.x, SQLite
  (WAL, JSON block trees, FTS5 search)
- `frontend/` — Vite + React + TypeScript + BlockNote (core/react/mantine
  only — no GPL `xl-*` packages)
- `reports/` — import coverage + round-trip validation
- `vendor-readonly/` — read-only reference clones (gitignored); re-create
  with `git clone --depth 1 https://github.com/chris-skitch/family-history
  vendor-readonly/family-history`
- Workspace (DB + content-addressed assets + exports) lives at
  `~/NotebookForge-workspace/` (override: `NOTEBOOK_FORGE_WORKSPACE`)

## Quick start

```sh
# prerequisites: uv, node 20+
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..

make check       # ruff + pytest (42) + tsc + vitest (8)
make dev         # backend on :8400, frontend on :5173
```

To rebuild the workspace from scratch (idempotent assets; needs the
vendor-readonly clone and the local MemoirForge checkout):

```sh
cd backend && uv run python -m notebook_forge.cli import-published \
  --repo ../vendor-readonly/family-history \
  --mf-out /Users/cs/ClaudeCode/MemoirForge/out \
  --mf-work /Users/cs/ClaudeCode/MemoirForge/work \
  --reports ../reports
```

`scripts/smoke.sh` exercises the API happy path end to end.

## Morning checklist (Sprint 1 hand-off)

1. Read `SPRINT_REPORT.md`, then `reports/roundtrip.md`.
2. `make dev` — open http://localhost:5173, check the Library badges
   (everything should be *published · clean* on both targets), open
   **Junior** in the editor.
3. Fix the "THE Army Year" typo (Part 3 — Singapore's title) in the editor;
   watch the github-pages badge go *pending changes*.
4. Publish to the **local-folder** target (Push button) and eyeball
   `~/NotebookForge-workspace/exports/site/` against the live site.
   (A verbatim pre-publish of all seven is already there; the exported
   Singapore page is 100.000% DOM-identical to the live page.)
5. When satisfied: connect Drive OAuth and the Gemini key — Sprint 2
   kickoff. Live GitHub Pages pushes are disabled by construction this
   sprint (the target has no `push_url`); point it at the real repo when
   you're ready.

## Licence

MIT. The memoir content and photographs belong to the Skitch family
archive (CC BY-NC-ND on the published site) and are not part of this
repository.
