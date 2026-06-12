# Plan: Re-import from original sources with sketch reuse

**Status:** approved design, ready to implement.
**Goal:** re-import selected documents from their original DOCX/PDF sources
(replacing the published-HTML-derived text) while reusing every
already-generated sketch from MemoirForge — **zero Gemini calls**. The seven
keeper memoirs carry ~274 figures; regenerating would cost ≈ $35 on
`gemini-3-pro-image` and risk face-gate churn. All of it already exists on
disk.

**Reference data (READ-ONLY — never write to MemoirForge):**

- `/Users/cs/ClaudeCode/MemoirForge/work/<session_id>/source.docx|source.pdf`
  — the archived original source of each memoir, plus `media/` (extracted
  images) and a per-session `manifest.json`.
- `/Users/cs/ClaudeCode/MemoirForge/out/<stem>.manifest.json` — authoritative
  per-figure record: `source_sha256` (sha256 of the **extracted image
  bytes**), `silhouette.file` (path to the sketch PNG in MemoirForge's
  cache), `silhouette.prompt` / `model` / `face_gate` / `approved`,
  `caption`, `caption_source`, `included`, `use_original`,
  `prompt_override`. Top level carries `session_id`, `source_file`, `stem`.
- `/Users/cs/ClaudeCode/MemoirForge/cache/<sha>.png` — the sketch PNGs
  themselves.

**Hard exclusion:** stem `1942-1954_national-service` is an old test run of
the same source as `1953-1954_in-the-navy`. Never re-import, never seed from
it. (Its `work/` dir is already gone, but exclude by stem regardless.)

## 1. Verified facts the design rests on

1. **Same cache-key scheme, transposable sketches.** Both projects key the
   sketch cache as `sha256(image_bytes + prompt + model)` —
   `backend/notebook_forge/sketch_gen.py:27` and MemoirForge
   `memoirforge/silhouette.py:47`. Model strings are identical
   (`gemini-3-pro-image`). **But** the default prompts are equal only after
   `.strip()` (whitespace drift), so MemoirForge cache *filenames do not
   transfer* — seeding NotebookForge's cache requires recomputing the key
   with NotebookForge's `SILHOUETTE_PROMPT`.
2. **Extraction is byte-faithful.** NotebookForge ingests via vendored
   MemoirForge extractors (`backend/notebook_forge/ingest_vendor/`), so the
   image bytes extracted from `source.docx`/`source.pdf` should hash
   identically to the manifest's `source_sha256`. The dry-run (§3.2)
   verifies this empirically before anything mutates.
3. **`reingest_document` carries existing figure work** by content-addressed
   `assetId` match (`backend/notebook_forge/ingestion.py:116`), but requires
   `meta.source_asset_id`. The seven published-imported docs were imported
   from HTML and **have no source asset** — re-import must first "adopt" the
   archived MemoirForge source. (Their current figure assetIds are hashes of
   the published `figure-N-original.jpeg`, which may not byte-match the
   source-embedded images — that's exactly why manifest matching is the
   primary mechanism, not the in-doc carry-over.)
4. **forgeImage props vocabulary** (`blocks.py`, `safe_edition.py`):
   `assetId`, `sketchAssetId`, `caption`, `altText`,
   `approval: "pending"|"approved"`,
   `safeMode: "sketch"(default)|"original"|"omit"`, `displayWidth`.
5. Slugs in the NotebookForge library equal MemoirForge stems (both derive
   from the published `rfs/<stem>.html` filenames). Implement
   slug→manifest lookup on that basis with a clear error (and a
   `--manifest PATH` escape hatch) if no manifest matches.

## 2. What ships

```
backend/notebook_forge/reimport.py    # all new logic (single module)
backend/notebook_forge/cli.py         # new subcommand: reimport
backend/tests/test_reimport.py
reports/reimport-dryrun.md            # generated: 7-doc match-rate table
```

CLI-only on purpose: this is an operator migration tool, run a handful of
times. No API route, no frontend. (A "Re-import from MemoirForge" button can
wrap `reimport_document` later if it earns its keep.)

## 3. Design — `backend/notebook_forge/reimport.py`

### 3.1 Manifest location & parsing

- `find_memoir_manifest(slug) -> ManifestInfo` — scan
  `MemoirForge/out/*.manifest.json` for `stem == slug` (excluding the
  national-service stem), resolve `work/<session_id>/source.*` as the source
  file. Raise `LookupError` with a listing of available stems on miss.
- Build `figures_by_hash: dict[source_sha256 -> figure dict]`. Manifest
  silhouette paths are absolute into `MemoirForge/cache/` — validate
  existence; a missing silhouette file is reported, never fatal for the
  other figures.

### 3.2 Dry run (no DB, no workspace writes)

`dry_run(slug | source_path) -> report` — run the vendored extraction into a
temp dir (reuse the extraction half of `ingestion._extract_blocks`, but hash
the extracted image files directly instead of calling `ingest_file`), then
match hashes against the manifest. Report per doc: figures extracted,
manifest figures, matched, unmatched (with figure `n`/`anchor` so misses are
investigable), silhouette files missing on disk. **This is the go/no-go
evidence** — fact §1.2 is "should", the dry-run makes it "is".

The extraction half should be factored out of `_extract_blocks` so dry-run
and real ingest share one code path (extract → draft → image list), rather
than duplicating extractor calls.

### 3.3 Re-import orchestration

`reimport_document(session, workspace, doc, *, manifest) -> dict`:

1. **Adopt the source** if `meta.source_asset_id` is empty: `ingest_file`
   the archived `source.*` (kind `"sources"`), set `source_asset_id` and
   `source_file` (use the manifest's original `source_file` name, e.g.
   `"Junior.pdf"`, not `"source.pdf"`).
2. **Re-ingest** via the existing `reingest_document` (it snapshots first —
   Restore undoes everything). Any figure work already done inside
   NotebookForge still carries over by assetId and **takes precedence** over
   manifest seeding.
3. **Seed sketches** — for each `forgeImage` block whose `sketchAssetId` is
   empty, look up `props.assetId` in `figures_by_hash`:
   - `ingest_file` the silhouette PNG (kind `"sketches"`, filename
     `{slug}-fig{n}-sketch.png`) → `sketchAssetId`.
   - `approval` = `"approved"` if the manifest figure was `approved` (these
     are the published, human-reviewed sketches) else `"pending"`.
   - `caption`/`altText`: take the manifest caption when the block's caption
     is empty or differs — manifest captions are the curated published ones;
     the freshly-extracted nearby-text guesses are worse.
   - `included == False` → `safeMode: "omit"`; `use_original == True` →
     `safeMode: "original"`.
4. **Seed the generation cache** for each matched figure whose
   `prompt_override` is empty and `silhouette.model` equals the current
   configured model: write the silhouette bytes to
   `workspace/sketch-cache/{sha256(original_bytes + current_default_prompt
   + model)}.png` (key per `sketch_gen.cache_key`, prompt from
   `sketch_service.sketch_settings`). Future "Generate sketch" clicks on
   these figures become free cache hits instead of $0.13 API calls.
5. `services.save_blocks(..., summary="seeded N sketches from MemoirForge
   manifest")` + `services.record_change` with per-figure detail; return a
   report dict `{slug, figures, carried_over, seeded, cache_seeded,
   unmatched: [...]}`.

Steps 3–5 must also work standalone (`seed_sketches(session, workspace,
doc, manifest)`) so a doc that was already re-ingested — or freshly ingested
via "+ Add document" — can be seeded without another text replacement.

### 3.4 CLI

```
notebook-forge reimport <slug>... [--dry-run] [--all]
```

- `--dry-run` prints the §3.2 report and writes/updates
  `reports/reimport-dryrun.md`; touches nothing else.
- `--all` = every library doc with a matching manifest (minus the excluded
  stem — refuse it even if named explicitly, with a message saying why).
- Without `--dry-run`: print the §3.3 report per doc. Never publishes —
  re-imported text differs from the live pages until the operator reviews,
  polishes and pushes deliberately.

## 4. Tests (`backend/tests/test_reimport.py`)

Fixture: temp workspace + a fabricated mini-manifest with 3 tiny generated
images (PNG bytes made in-test) standing in for original/silhouette pairs.
Cover at minimum:

1. Hash matching: figure matched by `source_sha256` gets `sketchAssetId`,
   `approval: "approved"`, manifest caption.
2. Props mapping: `included False` → `safeMode "omit"`; `use_original True`
   → `safeMode "original"`; unapproved manifest figure → `"pending"`.
3. Unmatched figure is left `sketchAssetId: ""` / `approval: "pending"` and
   listed in the report.
4. Cache seeding writes exactly `sha256(original + prompt + model).png` and
   a subsequent `GeminiSketchGenerator.generate` (with a poisoned
   `_call_gemini` that raises) returns the cached bytes — proves no API
   call.
5. Figure work already present in the doc survives re-import unchanged
   (precedence over manifest).
6. Missing silhouette file → figure reported, run continues.
7. Excluded stem is refused by `find_memoir_manifest` and by the CLI.
8. Dry-run leaves DB row counts and the workspace tree untouched.

## 5. Acceptance / verification

- `pytest` green, `ruff` clean (existing repo standards).
- `reimport --all --dry-run` against the real MemoirForge data: the seven
  keepers report their match rates in `reports/reimport-dryrun.md`. Expect
  ≈100% (fact §1.2); investigate and document any miss — **do not** paper
  over with order-based matching without evidence it's needed.
- End-to-end proof in a **scratch workspace** (`NOTEBOOK_FORGE_WORKSPACE`
  pointing at a temp dir): ingest one real archived source (e.g. Junior,
  9 figures) via `ingest_document`, run `seed_sketches`, confirm every
  figure has a sketch, zero Gemini traffic (no API key is ever loaded), and
  the seeded cache key matches what `generate_sketch_for_block` would look
  up. The real `~/NotebookForge-workspace` is not touched by verification.
- Which docs actually get re-imported is the operator's call later; this
  work ships the tool plus the dry-run evidence, and mutates no real
  document.

## 6. Guardrails (standing project rules)

- `/Users/cs/ClaudeCode/MemoirForge/` is **read-only**. Open files, never
  write, never run its code against its own dirs.
- Never call the Gemini API in this work (no key needed anywhere).
- Never publish/push to live targets as part of re-import.
- Git: commit on the current branch with the repo-local identity (GitHub
  noreply email — already configured); do not push unless asked.
