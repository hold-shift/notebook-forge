# Notebook Forge — Sprint 1 build plan (autonomous overnight run)

**Executor:** Claude (Fable 5) in Claude Code, unattended.
**Owner:** Chris — asleep. No checkpoints tonight: every gate is self-verified.
**Date:** 10 June 2026
**Repo:** git@github-memoirforge:chris-skitch/notebook-forge.git (private)

## 1. Mission

Build the working core of Notebook Forge: a local-first document pipeline and
CMS that ingests memoir documents into a canonical BlockNote block tree
(SQLite), edits them in a Notion-style editor, and renders synchronised
outputs — themed HTML now, NotebookLM-safe Google Doc next sprint. The sprint
ends with the seven published Skitch memoirs imported from MemoirForge,
round-trip validated against the live site's HTML, editable in the browser,
and publishable to a local folder and a git-based Pages target (fixture only —
no live publishing tonight).

## 2. Hard guardrails — read first, never violate

1. All work happens inside this directory (`/Users/cs/ClaudeCode/NotebookForge/`).
   Never modify files outside it. External material is cloned or copied into
   `vendor-readonly/` and treated as read-only reference.
2. Git pushes go ONLY to the repo above. NEVER push to `family-history` or
   `MemoirForge`. Never run `git add -A`; stage explicit paths.
3. `/Users/cs/ClaudeCode/MemoirForge/` and any `family-history` clone are
   READ-ONLY sources. Copy what you need; never edit them in place.
4. Never commit secrets. `.gitignore` includes `.env` from the first commit.
   If `GEMINI_API_KEY` is present in the environment you may use it; if not,
   stub image generation behind its interface and note it in the report.
5. No live publishing tonight. The GitHub Pages adapter is exercised against a
   LOCAL bare-repo fixture only. The Drive adapter is mocked.
6. Commit at every milestone gate (conventional commits). If a gate still
   fails after 3 distinct fix attempts, record the failure and your analysis
   in `SPRINT_REPORT.md`, mark the milestone partial, and move on. A complete,
   honest report beats a perfect milestone.
7. No interactive prompts anywhere in scripts or tooling; no human is around.
8. Do not relitigate locked decisions (section 3). For ambiguities not covered
   here, choose the simplest option consistent with the MemoirForge PRD spirit
   and log the call in the report.

## 3. Locked architecture decisions

- Monorepo: `backend/` — Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite (WAL
  mode, JSON column for block trees, FTS5 for library search). `frontend/` —
  Vite + React + TypeScript + `@blocknote/core` + `@blocknote/react` +
  `@blocknote/mantine`. NEVER use any `@blocknote/xl-*` package (GPL).
- Canonical document format: BlockNote block JSON plus two custom blocks:
  - `forgeImage` props: { assetId, sketchAssetId?, caption, altText,
    approval: "pending"|"approved", peopleCount?, displayWidth }
  - `forgeFootnote` props: { marker, text } — renders as an inline `<aside>`
    immediately after the referencing paragraph (house style).
- Workspace layout (created on first run, lives outside the repo, default
  `~/NotebookForge-workspace/`, path configurable): `forge.db`,
  `assets/originals/`, `assets/sketches/`, `assets/sources/`, `exports/`.
  Assets are content-addressed by SHA-256; the DB stores metadata only.
- Schema: `documents`, `assets`, `snapshots`, `targets`, `sync_state`,
  `changes`, `settings` per the agreed ERD. A document is dirty for a target
  when its current blocks differ from the snapshot in that target's sync row.
- Renderer reproduces the MemoirForge house style exactly: semantic HTML,
  pt-based font sizes, full-width inline-styled images with relative paths,
  no CSS floats, inline `<aside>` footnotes, per-document HTML ToC.
- Secrets live in the OS keychain via `keyring`; settings table records only
  which keys exist and last-verified status.
- Licence MIT; repo stays private for now.

## 4. Source material map

- MemoirForge (read-only): `/Users/cs/ClaudeCode/MemoirForge/` — specs in
  `docs/` (PRD, M1 build spec, collection index spec, house-style reference
  page, silhouette prompt). Read these BEFORE writing the parser or renderer.
- family-history: look for a local clone under `~/ClaudeCode/` and `~/` first;
  if none found, clone read-only:
  `git clone --depth 1 https://github.com/chris-skitch/family-history
  vendor-readonly/family-history`. Its published HTML is the ground truth for
  round-trip validation.
- Sketch assets: search the MemoirForge workspace first, then the
  family-history clone. Produce a coverage table (expected vs found, per
  document) in the import report BEFORE migrating anything.

## 5. Milestones and gates

Work strictly in order. Each gate = `make check` green plus listed criteria.

### M0 — Scaffold and repo
Init git with the remote above (Chris has pre-created the empty private repo).
Scaffold backend and frontend, shared `Makefile` (`make check` = ruff + pytest
+ tsc + vitest; `make dev` runs both servers), `.gitignore`, MIT licence, stub
README. Gate: `make check` green on the skeleton; initial push succeeds.

### M1 — Data layer and workspace
SQLAlchemy models for all seven tables; workspace bootstrap; document CRUD;
snapshot creation; dirty-state computation; change-log writes; FTS indexing of
extracted plain text. Gate: unit tests cover create / edit / snapshot / dirty
/ rollback paths.

### M2 — House-style HTML → blocks parser
BeautifulSoup-based. Handle headings, paragraphs, inline marks, links, figures
with captions (→ forgeImage), inline asides (→ forgeFootnote), blockquotes,
tables, lists and horizontal rules. Strip the ToC — it is derived, not
content. Gate: unit tests pass against fixture fragments cut from the real
published memoirs (not synthetic samples).

### M3 — Blocks → HTML renderer
The inverse of M2, plus the index-page renderer from document metadata.
Gate: render(parse(x)) is idempotent on all fixtures (normalised DOM equality).

### M4 — Importer and round-trip validation (the centrepiece)
Import all seven memoirs: parse published HTML → blocks; ingest originals,
source files and sketches into the asset store; pair sketches to originals by
filename/position; seed sync_state as PUBLISHED + CLEAN against a
`github-pages` target record (day one must show nothing pending); write
change-log entries marking the import. Then re-render every document and diff
against the published HTML with a whitespace- and attribute-order-insensitive
DOM compare. Gate: ≥99% node-level similarity per document;
`reports/roundtrip.md` lists every residual diff with context; asset coverage
table complete. If sketches are missing locally and in the repo, log the gap —
do NOT attempt Drive extraction tonight.

### M5 — API and frontend core
FastAPI routes: documents (list / get / save-blocks), assets (serve), search,
changes, targets, sync state, snapshots / rollback. Frontend: Library screen
with status badges driven by real sync_state; BlockNote editor with the two
custom blocks (sketch shown side-by-side inside the forgeImage block UI);
autosave → change log → dirty flags; pending-changes panel with per-target
state and push buttons. Gate: vitest component tests for both custom blocks;
`scripts/smoke.sh` exercises the API happy path against an imported document.

### M6 — Publish targets
`PublishTarget` interface; `LocalFolderTarget` (complete); `GitPagesTarget`
(commit + push exercised against a local bare-repo fixture); `DriveTarget`
(interface, request shapes, mocked client with tests — real OAuth is next
sprint). Publishing snapshots the document, transfers only hash-changed
assets, and updates sync_state atomically; rollback re-points and re-renders.
Gate: integration test — edit → dirty → publish to both real adapters →
clean → rollback restores prior content.

### M7 — Wrap-up
README with quick-start and the morning checklist (section 8); finalise
`SPRINT_REPORT.md` (done / partial / skipped per milestone, decisions log,
round-trip summary, next-sprint backlog); tag `v0.1.0-sprint1`; final push.
Gate: a five-minute read of the report tells Chris exactly what works, what
is partial, what was skipped, and what to do next.

## 6. Explicitly out of scope tonight

Live Google Drive OAuth and uploads; live pushes to any real Pages site;
sketch GENERATION via Gemini (build the interface and load the silhouette
prompt from MemoirForge docs, but imported sketches are the only sketch
source tonight); themes beyond the ported Archive serif (theme interface in,
one implementation); Netlify / Cloudflare adapters; first-run wizard;
index-page editing UI (render it from data; editing comes next sprint).
List anything else consciously deferred in the report's backlog section.

## 7. Self-verification standards

`make check` green at every gate. Prefer real fixtures cut from the published
memoirs over synthetic data. The round-trip report is the sprint's primary
evidence — invest in making its diffs readable. Log every non-obvious
decision in SPRINT_REPORT.md as you go, not retrospectively at 6am.

## 8. Morning checklist (for Chris)

1. Read SPRINT_REPORT.md, then reports/roundtrip.md.
2. `make dev` — open the Library, check badges, open Junior in the editor.
3. Fix the "THE Army Year" index typo in the editor; watch it go dirty.
4. Publish to the local-folder target; eyeball output against the live site.
5. When satisfied: connect Drive OAuth and the Gemini key (Sprint 2 kickoff).
