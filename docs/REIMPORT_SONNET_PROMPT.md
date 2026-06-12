# Prompt for the implementing agent (Sonnet)

Copy everything below the line into a fresh Claude Code session running in
the NotebookForge repo.

---

Implement the re-import-with-sketch-reuse tool specified in
`docs/REIMPORT_PLAN.md`. Read that file first and follow it exactly — it
contains the verified facts, design, test list, and acceptance criteria.
Where the plan and this prompt disagree, the plan wins.

Context in one paragraph: the NotebookForge library holds seven memoirs
imported from published HTML. We want to be able to re-import them from
their original DOCX/PDF sources, which are archived in MemoirForge at
`/Users/cs/ClaudeCode/MemoirForge/work/<session_id>/source.*`, WITHOUT
regenerating any sketches. Every sketch already exists in
`/Users/cs/ClaudeCode/MemoirForge/cache/` and is mapped per-figure by
`/Users/cs/ClaudeCode/MemoirForge/out/<stem>.manifest.json` via
`source_sha256` = sha256 of the extracted image bytes. You are building the
plumbing (a `reimport` CLI with dry-run, manifest-driven sketch seeding,
generation-cache seeding) plus tests and a dry-run evidence report. You are
NOT re-importing any real document — which docs to re-import is the
operator's decision later.

Hard rules:

1. `/Users/cs/ClaudeCode/MemoirForge/` is READ-ONLY. Read anything, write
   nothing, never push there.
2. Never call the Gemini API. No code path you add may need an API key.
   Sketch bytes come from MemoirForge's cache files only.
3. Never modify documents in the real workspace
   (`~/NotebookForge-workspace/`). Real-data verification is read-only
   (dry-run) or happens in a scratch workspace via the
   `NOTEBOOK_FORGE_WORKSPACE` env override, per plan §5.
4. `1942-1954_national-service` is an old test run — hard-excluded
   everywhere, refused by the CLI even when named explicitly.
5. Never publish or push to any live target.
6. Backend is run with `uv` from `backend/` (e.g. `uv run pytest`,
   `uv run ruff check`). Match existing code style — look at
   `ingestion.py`, `sketch_service.py`, and `tests/` for the house idiom
   before writing anything.

Key files to read before coding (all paths relative to repo root):

- `docs/REIMPORT_PLAN.md` — the spec.
- `backend/notebook_forge/ingestion.py` — `_extract_blocks`,
  `reingest_document`, `ingest_document`. You will factor the extraction
  half out of `_extract_blocks` for dry-run reuse (plan §3.2).
- `backend/notebook_forge/assets.py` — content-addressed store,
  `ingest_file`, `sha256_file`, `asset_path`.
- `backend/notebook_forge/sketch_gen.py` (`cache_key`) and
  `backend/notebook_forge/sketch.py` (`SILHOUETTE_PROMPT`, `SKETCH_MODEL`)
  and `backend/notebook_forge/sketch_service.py` (`sketch_settings`) — the
  cache-seeding key must be computed exactly as `generate_sketch_for_block`
  would compute it at lookup time.
- `backend/notebook_forge/blocks.py` + `safe_edition.py` — forgeImage props
  (`approval`, `safeMode`) you'll be setting.
- `backend/notebook_forge/cli.py` — subcommand pattern to extend.
- One real manifest, e.g.
  `/Users/cs/ClaudeCode/MemoirForge/out/1934-1945_junior.manifest.json`,
  to confirm the figure schema before writing the parser.

Known traps (already verified, don't rediscover them the hard way):

- MemoirForge's cache filenames do NOT transfer: the two projects' default
  prompts differ by whitespace (equal only after `.strip()`), so the cache
  key must be recomputed with NotebookForge's current default prompt and
  model from `sketch_settings`. Only seed the cache for figures with no
  `prompt_override` and a matching model string.
- The seven library docs have no `meta.source_asset_id` (they were imported
  from HTML) — `reingest_document` raises without the adopt step (plan
  §3.3.1).
- Their current figure `assetId`s hash the published `figure-N-original.jpeg`
  files, which may not byte-match the source-embedded images — so manifest
  matching by `source_sha256` is the primary mechanism; in-doc carry-over is
  a bonus that must still take precedence when it fires.
- Manifest `silhouette.file` paths are absolute into MemoirForge's cache;
  validate existence per figure and keep going on a miss (report it).

Order of work:

1. Read the plan and the listed files.
2. Implement `backend/notebook_forge/reimport.py` + CLI subcommand.
3. Write `backend/tests/test_reimport.py` covering plan §4 (all 8 cases).
4. Run the full backend test suite and lint; fix what you broke.
5. Run `reimport --all --dry-run` against the real MemoirForge data and
   write `reports/reimport-dryrun.md` with the per-doc match table. If any
   doc matches below 100%, dig into WHY (compare the unmatched figure's
   bytes in `work/<sid>/media/` against your extraction) and document the
   finding in the report — do not add fallback matching heuristics without
   that evidence.
6. End-to-end proof in a scratch workspace per plan §5 (Junior is the
   cheapest: 9 figures). Include the outcome in the report.
7. Commit on the current branch in logical commits (repo-local git identity
   is already configured — do not change it, do not push).

Done means: tests green, lint clean, dry-run report written with ≈100% match
rates (or documented reasons), scratch-workspace e2e proof in the report, no
real document modified, no Gemini call anywhere, MemoirForge untouched.
