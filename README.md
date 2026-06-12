# Notebook Forge

Local-first CMS for the Skitch family memoirs. The published memoirs live as
canonical BlockNote block trees in SQLite, get edited in a Notion-style
editor, and publish to three synchronised targets:

- **GitHub Pages** — the live family site (exact MemoirForge house style,
  collection index / sitemap / robots / llms.txt regenerated on every publish)
- **Google Drive** — the NotebookLM-safe edition per document (faceless
  sketches inlined, captions linking back to the originals on the live site)
- **Local folder** — a rehearsal copy and portable static mirror of the site

History: `SPRINT_REPORT.md` (Sprint 1, the import + round-trip build) and
`reports/roundtrip.md` (per-document validation evidence).

## Layout

- `backend/` — Python 3.12 (via `uv`), FastAPI, SQLAlchemy 2.x, SQLite (WAL,
  JSON block trees, FTS5 search). `notebook_forge/ingest_vendor/` is the
  MemoirForge extraction pipeline, vendored byte-faithful.
- `frontend/` — Vite + React + TypeScript + BlockNote (core/react/mantine
  only — no GPL `xl-*` packages)
- `secret/` — OAuth client secrets (gitignored, never committed)
- Workspace (DB, content-addressed assets, sketch cache, exports) lives at
  `~/NotebookForge-workspace/` (override: `NOTEBOOK_FORGE_WORKSPACE`)

## Quick start

```sh
cd backend && uv sync && cd ../frontend && npm install && cd ..
make check     # ruff + pytest + tsc + vitest
make dev       # backend :8400, frontend :5173
```

## What the app does

- **Library** — the corpus with live sync badges per target, full-text
  search, **+ Add document** (PDF/DOCX ingest: headings, captions paired by
  geometry, footnotes, date detection), ⚙ Settings.
- **Editor** — BlockNote with the two custom blocks (`forgeImage` shows the
  original beside its NotebookLM-safe sketch; `forgeFootnote` is the
  co-located aside). Body edits autosave; Title/Years/Standfirst save via
  the meta bar (doubles as the date-confirmation gate for new ingests).
  Generate/Regenerate sketches per figure (Gemini + face gate; fresh
  sketches come back *pending* until approved). Targets panel: per-target
  state, Push, ↗ open published output. Snapshots panel: publish history
  with one-click restore.
- **Settings** — sketch model/prompt, polish model, connection status for
  the three secrets.

## Groups & Homepage

Documents can be collected into named **Groups** (Library → any document →
assign group). Each group has a colour and a manual sort order that can be
overridden per block.

The **Homepage** (`/api/documents/homepage`, `kind: "homepage"`) is a
first-class BlockNote document that lives in the Library alongside the
memoirs. It autogenerates on first boot from the Settings seed data and
gets a **forgeDocGroup** block for each group. Open it in the Editor to
reorder sections, add prose, or set the dedication. Pushing it regenerates
the collection-index pages on every configured target.

The **forgeDocGroup** block embeds a live, sortable member list right in
the editor canvas. Choose a group from the dropdown, pick a sort mode
(Manual / Date range / A–Z / Last updated), and toggle word-count + blurb
display. The block shows a live preview of the first five members; the
member list updates whenever a document's metadata changes.

## Secrets (macOS keychain, service `notebook-forge`)

| name | purpose | how to set |
|---|---|---|
| `github-pat` | live Pages pushes (fine-grained, Contents R/W on family-history) | `uv run keyring set notebook-forge github-pat` |
| `gemini-api-key` | sketch generation | `uv run keyring set notebook-forge gemini-api-key` |
| `drive-oauth-token` | Drive uploads (account **cskitch@gmail.com**) | `uv run python -m notebook_forge.cli drive-auth --secrets secret/<client>.json` |

Nothing secret is ever written to the DB, config, logs, or git.

## Operational notes

- Re-import the corpus from scratch:
  `uv run python -m notebook_forge.cli import-published --repo ../vendor-readonly/family-history --mf-out /Users/cs/ClaudeCode/MemoirForge/out --mf-work /Users/cs/ClaudeCode/MemoirForge/work --reports ../reports`
- `scripts/smoke.sh` exercises the API happy path end to end.
- Drive uses the narrow `drive.file` scope: the app can only see files it
  created. Its folder ("NotebookForge — NotebookLM editions") can be moved
  anywhere in Drive without losing access.
- The first NotebookLM ingestion of a generated Doc was verified
  11 June 2026 — sketches survive, caption links resolve.

## Licence

MIT. Memoir content and photographs belong to the family archive
(CC BY-NC-ND on the published site) and are not part of this repository.
