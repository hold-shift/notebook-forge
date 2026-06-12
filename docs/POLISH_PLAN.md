# Plan: LLM Polish for NotebookForge

**Status:** approved design, ready to implement.
**Reference implementation:** `/Users/cs/ClaudeCode/MemoirForge/memoirforge/llm_polish/`
(READ-ONLY — port logic from it, never modify it). The serializer protocol,
prompt rules, fidelity guard and chunker there are battle-tested; deviate
only where this plan says so.

## 1. What it is

A **mechanical** cleanup pass over a document's prose using Gemini Flash:
wrong-locale quotes, stray whitespace, page-break paragraph joins, and
unambiguous one-for-one spelling typos. It is NOT a rewrite tool — the
fidelity guard word-diffs every block and anything beyond typography is
quarantined for human review, never auto-applied. Primary use: documents
ingested from raw PDF/DOCX (the published seven were already polished
upstream and don't need it).

## 2. Where it sits in NotebookForge

- Trigger: a **"Polish text" button** in the editor meta bar (next to
  Re-ingest from source), with a confirm dialog stating scope and cost.
- Safety: **snapshot first** (`note="before polish"`), like re-ingest.
- Effect: clean (typography-only) blocks are applied server-side via
  `services.save_blocks` (one change-log entry, doc goes dirty as normal);
  flagged blocks are returned to the UI for per-block review and are NOT
  applied automatically.
- The editor **reloads** after polish (same pattern as re-ingest) so
  BlockNote shows the applied text; flagged proposals render in a review
  panel.

## 3. Architecture (new files)

```
backend/notebook_forge/polish/
  __init__.py
  textmap.py      # block tree ⇄ polishable text (the NotebookForge-specific part)
  chunker.py      # port of llm_polish/chunker.py (BlockRef carries block UUID)
  serializer.py   # port of llm_polish/serializer.py (prompt + JSONL parse)
  fidelity.py     # port of llm_polish/fidelity.py — near-verbatim
  runner.py       # Gemini-only dispatch via httpx (pattern: sketch_gen.py)
  service.py      # orchestration: snapshot → chunk → run → guard → apply
frontend/src/views/PolishReview.tsx   # flagged-block review UI (in Editor)
backend/tests/test_polish.py
frontend: extend existing editor tests only if cheap
```

### 3.1 textmap.py — the only genuinely new logic

NotebookForge blocks are BlockNote JSON (inline runs with styles), not flat
text. Polish operates on text, so:

- `block_to_polish_text(block) -> str` — serialize inline content to
  Markdown-ish text: `**bold**`, `*italic*`, `***both***`,
  links `[text](url)`, and **fnRef runs as `[^N]`** (the exact marker the
  ported prompt already protects). Reuse/extract from
  `safe_edition.inline_md` BUT emit `[^N]` (not `[N]`) for fnRef runs.
- `polish_text_to_content(text) -> list[InlineRun]` — the inverse. Reuse
  `ingestion._md_inline_runs` (it already parses `[^N]` → fnRef via
  `ingest_vendor.footnotes.MARKER_RE`, plus `**`/`*`). Move/share these
  two functions into `polish/textmap.py` (or a small shared module) rather
  than duplicating; keep `ingestion.py` importing from the shared home.
  NOTE: `_md_inline_runs` does not parse links — add `[text](url)` run
  parsing there (returns a link run) since polish must round-trip links.
- **Round-trip invariant (must be unit-tested):**
  `polish_text_to_content(block_to_polish_text(b)) == b.content` for every
  text block of the real Junior fixture
  (`frontend/src/test/fixtures/junior.blocks.json` — readable from Python
  tests via its path; or regenerate from the workspace DB).
- Scope of polishable blocks: `paragraph`, `heading`, `quote`,
  `bulletListItem`, `numberedListItem`. forgeImage captions and
  forgeFootnote bodies are **out of scope v1** (note in report).
- `kind` string for the serializer: `p`, `h1`/`h2`/`h3` (from heading
  level), `p` for quote/list items (the model must not see unfamiliar
  kinds; their kind is restored from the original block on apply — the
  model never changes block type anyway, rule enforced).

### 3.2 chunker.py — port with one change

Port `chunk_blocks` from the reference. `BlockRef.id` becomes the
**BlockNote block UUID** (string), not a synthetic index — that is the key
that survives all the way to `editor.updateBlock`. Keep: target_tokens
3500, max_tokens 2×, overlap_blocks 1 (context block tagged CONTEXT, never
returned). Keep the heading-grouping behaviour as-is from the reference.

### 3.3 serializer.py — port verbatim

Port `_DEFAULT_POLISH_RULES`, `_PROMPT_STRUCTURE`, `_build_preamble`,
`serialize_chunk_for_prompt`, `_format_line`, `parse_polished_jsonl`,
`coverage_ratio` unchanged (line format: `POLISH  <uuid> <kind> :: <text>`;
UUIDs are longer than the reference's ids — that's fine, the parser keys
on the id field). The rules text already protects `[^N]` markers,
hyphens, ellipses, British spellings. `extra_rules` comes from settings.

### 3.4 fidelity.py — port near-verbatim

`check_block_fidelity` + helpers, unchanged. One addition: also normalise
`**`/`*` emphasis markers away in `_normalise` (add `("**",""),("*","")`
BEFORE the existing pairs) so an emphasis-marker move never counts as a
word change — our text carries Markdown markers, the reference's didn't.
**Also hard-verify footnote markers**: extract the multiset of `[^N]`
markers from original vs polished; if they differ, the block is flagged
regardless of word diff (rule: dropped marker = automatic flag).

### 3.5 runner.py — Gemini via httpx (do NOT port the reference runner)

The reference supports Anthropic+Gemini SDKs; we need only Gemini REST,
same pattern as `sketch_gen.py`:

```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
headers: x-goog-api-key: <get_gemini_key()>
body: {"contents":[{"parts":[{"text": prompt}]}],
       "generationConfig": {"temperature": 0}}
```

- Response text: first candidate's first text part.
- `transport=None` constructor arg for httpx.MockTransport in tests
  (copy the pattern from `GeminiSketchGenerator`).
- Per-chunk retry: ONE retry on parse failure / coverage < 1.0 (reference
  behaviour), appending a terse "your previous reply failed because …"
  note. A chunk failing twice is recorded as failed; its blocks are left
  untouched and reported.
- Run chunks **concurrently, 4 workers** (ThreadPoolExecutor) — Flash is
  fast but a 30-chunk memoir shouldn't run serially. Results keyed by
  block id so ordering doesn't matter.
- No key in keychain → raise RuntimeError("polish is not configured…"),
  endpoint surfaces as 409 (same pattern as sketch generation).

### 3.6 service.py — orchestration

```python
def polish_document(session, workspace, doc, *, runner=None) -> dict:
    1. texts = [(block_id, kind, text)] via textmap over doc.blocks
    2. snapshot_document(session, doc, note="before polish")
    3. chunks = chunk_blocks(texts)
    4. results = run all chunks (runner injectable for tests)
    5. for each returned block: verdict = check_block_fidelity(...)
         + footnote-marker hard check
    6. clean blocks (typography_only AND text actually changed):
         new_content = polish_text_to_content(polished)
         replace block's content in a deep-copied block list
    7. services.save_blocks(..., summary=f"polish: {n} blocks cleaned")
       (only if ≥1 clean change; identical text → no-op, no change entry)
    8. record_change detail: model, chunks, blocks_changed,
       flagged count, failed chunks
    9. return {
         "blocks_polished": n_changed,
         "blocks_unchanged": ...,
         "flagged": [ {block_id, kind, original, polished, summary,
                       polished_content (runs)} ],
         "failed_chunks": [...notes...],
         "model": ...,
       }
```

Settings: `Setting key="polish"` → `{model: "gemini-2.5-flash",
extra_rules: ""}` with defaults via a `polish_settings(session)` helper
(copy `sketch_settings` pattern). Settings UI: a small "Text polish"
section (model input + extra-rules textarea) under Sketch generation.

### 3.7 API

```
POST /api/documents/{slug}/polish          → run, returns the report above
PUT  /api/documents/{slug}/blocks          (existing — used by review apply)
PUT  /api/settings/polish                  (mirror of /settings/sketch)
GET  /api/settings                         → add "polish" key
```

Polish endpoint is synchronous (operator watches a spinner; Junior ≈ 8–10
chunks ≈ ~1 min with 4 workers). Frontend fetch must pass a long timeout
expectation (no AbortController timeout).

### 3.8 Frontend

- Meta bar: **"✨ Polish text"** button (hidden while saving), confirm
  dialog: "Runs a mechanical Gemini cleanup … typography fixes are applied
  automatically; anything that changes words is held for your review. A
  snapshot is taken first."
- On response: if `flagged.length === 0` → alert summary → reload.
- Else render **PolishReview** panel (modal or replaces the side column):
  one card per flagged block — original vs polished text with the summary
  line ("+2 words, ~1 word replaced"), buttons **Apply** / **Skip**.
  Apply = `editor.updateBlock(block_id, {content: polished_content})`
  (content runs came in the response), then the normal autosave persists
  it. A "Done" button closes the panel and reloads.
- Show `failed_chunks` notes as a warning line if present.

## 4. Tests (backend; mock transport throughout)

1. **textmap round-trip** on real Junior blocks (fixture) — every
   paragraph/heading survives `text→content→text` unchanged, including
   the italic intro and fnRef markers in In-The-Navy fixture blocks.
2. **serializer parse**: well-formed JSON array, fenced output, missing
   block (coverage<1), id mismatch → SerializationError.
3. **fidelity**: typography-only passes (quotes/dashes/emphasis moves);
   word add/delete/replace flags; hyphen-space collapse not flagged;
   `[^N]` marker dropped → flagged even when words match.
4. **service end-to-end with MockTransport**: echo-model (returns input
   verbatim) → zero changes, no change-log entry, no snapshot? — NO:
   snapshot always taken (cheap, predictable); assert snapshot exists.
   Typo-fix model (scripted response) → block content updated in DB,
   change entry written, doc dirty; flagged response → block NOT applied,
   report carries it with polished_content runs.
5. **chunk failure**: transport 500s once → retried; twice → failed chunk
   reported, blocks untouched.
6. Settings round-trip (mirror existing sketch-settings test).

Run `make check` green; manual check: `make dev`, polish the re-ingested
Junior draft (`1930-1945_junior`) — it has genuine PDF-extraction
artefacts. NEVER polish the seven published memoirs as a test (they're
clean; snapshot makes it recoverable but don't).

## 5. Out of scope (state in SPRINT_REPORT when done)

- Captions / footnote bodies (v1 polishes body prose only)
- Anthropic provider (Gemini-only; the reference's provider switch is
  deliberately not ported)
- Async/queued runs with progress streaming
- The reference's heading-nesting validators (our outline navigator lint
  covers the review need)

## 6. Done means

- `make check` green (existing 71 backend + 20 frontend still pass).
- New tests above pass.
- SPRINT_REPORT.md changelog updated.
- Commit: `feat: LLM polish — Gemini mechanical cleanup with fidelity
  guard and review UI`. Push to origin.
- Do not run a real Gemini polish without the operator asking (costs
  tokens); the mock-tested path + operator's own click is the proof.
```
