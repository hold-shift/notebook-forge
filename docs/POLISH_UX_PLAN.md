# Plan: Polish UX improvements (progress modal, review modal, diff highlight, apply-all)

**Status:** approved design, ready to implement.
**Reference implementation:** `/Users/cs/ClaudeCode/MemoirForge/` (READ-ONLY —
port patterns from it, never modify it). The live-progress pattern requested
here already exists there and is battle-tested:

- `memoirforge/app.py:177-190` — in-process `_polish_progress` registry,
  written by the run worker, read by a polling GET endpoint.
- `memoirforge/app.py:955-1015` — `/llm-polish/run` (synchronous POST that
  publishes per-chunk progress) + `/llm-polish/progress` (poll endpoint).
- `memoirforge/llm_polish/runner.py:94-143` — `on_progress` callback fired
  once per chunk as it completes; callback errors must never tank the run.
- `static/app.js:975-1030` — the SPA modal: progress bar + "Polishing chunk
  N of M · k failed (pct%)" polled every 1.2 s while the synchronous POST
  is in flight.

## 1. What we're changing and why

Four problems with the current polish flow
(`frontend/src/views/PolishReview.tsx`, `Editor.tsx`,
`backend/notebook_forge/polish/`):

1. **No progress feedback.** `POST /api/documents/{slug}/polish` is
   synchronous and a big memoir takes minutes; the only feedback is the
   meta-bar button reading "Polishing…", which looks hung.
   → Progress modal with a live chunk counter (MemoirForge pattern).
2. **Cramped review UI.** The review panel renders in the narrow
   `.editor-side` column (`Editor.tsx:637-662`) — long blocks are
   unreadable, and it evicts the pending/snapshots panels while open.
   → Move review into a wide modal (the `ChangesModal` pattern,
   `Editor.tsx:33-70`), with a small "resume review" stub in the side
   column when the modal is dismissed.
3. **No visible diff.** Original and polished text render as two plain
   paragraphs; the operator must spot the changed word by eye.
   → Word-level diff segments computed server-side (we already tokenise
   and `SequenceMatcher` in `fidelity.py`) and rendered with
   red-strikethrough / green marks.
4. **No batch action.** Each flagged block needs an individual click;
   13+ to review is tedious when most are obviously fine.
   → "Apply all" (+ "Skip all") buttons in the modal footer.

Non-goals (explicitly out of scope): retry-failed-chunks endpoint,
whole-doc HTML diff (`preview-diff` in MemoirForge), accept/discard
server-side state, SSE/websockets, any change to chunking/fidelity rules.

## 2. Backend

### 2.1 Progress plumbing

`backend/notebook_forge/polish/runner.py` — `run_chunks()` gains an
optional callback:

```python
def run_chunks(chunks, runner, *, extra_rules="",
               on_chunk_done: Callable[[bool], None] | None = None):
```

Called once per completed chunk inside the `as_completed` loop with
`failed: bool`. Wrap the call in `try/except: pass` — a progress callback
error must never tank the run (MemoirForge `runner.py:139-143` does
exactly this).

`backend/notebook_forge/polish/service.py` — `polish_document()` gains an
optional mutable progress dict:

```python
def polish_document(session, workspace, doc, *, runner=None,
                    progress: dict[str, Any] | None = None):
```

After step 3 (`chunks = chunk_blocks(poly)`) set
`progress["total"] = len(chunks)`; pass an `on_chunk_done` into
`run_chunks` that increments `progress["done"]` (and `progress["failed"]`
when the flag is set). Guard everything with `if progress is not None`.
No other service logic changes.

### 2.2 API (`backend/notebook_forge/api.py`, polish endpoint at ~line 334)

Module-level registry, same comment rationale as MemoirForge
(`app.py:177-182` — GIL-safe dict mutations, not persisted, tiny):

```python
_polish_progress: dict[str, dict] = {}
```

`POST /api/documents/{slug}/polish` (existing): before calling
`polish_document`, create
`prog = {"running": True, "done": 0, "total": 0, "failed": 0}`, store it
in `_polish_progress[slug]`, pass `progress=prog`, and set
`prog["running"] = False` in a `finally:`. The endpoint stays a sync
`def` — FastAPI runs it in the threadpool, so the GET below is served
concurrently. Do not change the response shape (other than §2.3).

New endpoint:

```python
@app.get("/api/documents/{slug}/polish/progress")
def polish_progress(slug: str) -> dict[str, Any]:
    p = _polish_progress.get(slug)
    if not p:
        return {"running": False, "done": 0, "total": 0, "failed": 0}
    return dict(p)
```

No DB session needed; do NOT 404 on unknown slug (the poll may race the
POST).

### 2.3 Diff segments (`backend/notebook_forge/polish/fidelity.py`)

New pure function used only for display (the fidelity verdict logic is
untouched — keep them separate; the verdict normalises typography away,
the display diff must NOT):

```python
def diff_segments(original: str, polished: str) -> list[dict[str, str]]:
    """Word-level diff of the RAW texts for display highlighting.

    Returns [{"op": "equal"|"delete"|"insert"|"replace", "a": str, "b": str}]
    where the concatenation of all "a" == original and all "b" == polished.
    """
```

Implementation: tokenise with `re.findall(r"\S+\s*", text)` (words keep
their trailing whitespace so concatenation round-trips), run
`difflib.SequenceMatcher(a=..., b=..., autojunk=False)`, map opcodes to
segments with `"a": "".join(orig_tokens[i1:i2])`,
`"b": "".join(pol_tokens[j1:j2])`. Merge nothing; the frontend handles
adjacent segments fine.

In `service.py` step 5, add to each flagged dict:
`"diff": diff_segments(original, polished)`.

### 2.4 Backend tests (`backend/tests/test_polish.py`, extend)

- `diff_segments` unit tests: pure equal; single word replace; insert at
  end; smart-quote-only change (shows as replace — that's correct, it IS
  the change being reviewed); round-trip property (`"".join(a) ==
  original`, `"".join(b) == polished`) on a few inputs.
- Progress: run `polish_document` with the existing
  MockTransport-injected runner and a `progress` dict; assert `total` set
  to the chunk count and `done == total` afterwards; with a failing chunk
  assert `failed` incremented.
- API: `GET .../polish/progress` for an idle slug returns the zero shape;
  flagged blocks in the POST response carry a `diff` list.

## 3. Frontend

### 3.1 Types and API (`frontend/src/api.ts`)

```typescript
export interface DiffSegment { op: 'equal' | 'delete' | 'insert' | 'replace'; a: string; b: string }
// FlaggedBlock gains: diff: DiffSegment[]
// new: polishProgress(slug) => GET /api/documents/{slug}/polish/progress
//      -> { running: boolean; done: number; total: number; failed: number }
```

Poll with `{ cache: 'no-store' }`.

### 3.2 Progress modal

New component (suggest `frontend/src/views/PolishProgress.tsx`), rendered
by `EditorInner` whenever `polishing === true`. Reuses the existing
`.modal-backdrop` / `.modal-box` CSS (see `ChangesModal`,
`Editor.tsx:33-70`) but with NO close button and no backdrop-click
dismiss — the run can't be cancelled, so don't pretend it can.

Content:

- Title: "Polishing with Gemini…"
- While `total === 0`: "Snapshotting and chunking…" (indeterminate).
- Once `total > 0`: progress bar (`.polish-progbar` outer /
  `.polish-progbar-fill` inner, width = pct%) and the line
  `Polishing chunk {done} of {total}` + ` · {failed} failed` when
  failed > 0 + ` ({pct}%)`.
- Note line (muted): "Runs in parallel — a long document takes a few
  minutes."

Polling: `useEffect` keyed on `polishing` — `setInterval` ~1200 ms
calling `api.polishProgress(doc.slug)`; swallow fetch errors (transient —
keep polling, MemoirForge `app.js:1000-1010`); clear the interval on
unmount/`polishing` false. The existing `onPolish` promise resolution
(`Editor.tsx:558-576`) already flips `polishing` off and opens the
review — keep that flow; just delete the success `alert()` when
`flagged.length === 0` and replace it with the reload (the modal itself
has shown completion; an alert on top is noise). Keep the failure
`alert()`.

### 3.3 Review modal (rework `frontend/src/views/PolishReview.tsx`)

Convert the side-panel into a modal following `ChangesModal` exactly
(backdrop, `.modal-box`, Escape listener, header with `.modal-close`),
but wider: new class `polish-modal` with
`width: min(780px, 94vw); max-height: 85vh`.

Layout:

- **Header**: "Polish review" + the existing stats line (auto-applied /
  to-review / unchanged · model). Failed chunks: keep the one-line
  warning but make it a `<details>` whose body lists each
  `report.failed_chunks` string (they're real error messages — currently
  invisible).
- **Body** (scrollable): the flagged cards. Each card:
  - Diff rendering instead of the two plain paragraphs: keep the
    Original (`.polish-orig`) and Polished (`.polish-new`) boxes, but
    build their text from `block.diff` — Original box concatenates `a`
    parts wrapping `delete`/`replace` segments in
    `<mark className="diff-del">`; Polished box concatenates `b` parts
    wrapping `insert`/`replace` in `<mark className="diff-ins">`.
    Fall back to plain `block.original`/`block.polished` when `diff` is
    missing or empty.
  - Keep the summary line and per-card Apply / Skip.
  - New "jump to block" affordance (icon button, `ti-crosshair` or
    similar): scrolls the editor to the block — same mechanism as
    `selectHeading` (`Editor.tsx:457-464`):
    `document.querySelector('.editor-canvas [data-id="${block_id}"]')`,
    `scrollIntoView`, add/remove `nf-flash`. Pass a callback prop from
    `EditorInner`; the modal must NOT close when jumping (operator peeks,
    then continues).
- **Footer** (sticky, border-top): left side
  `Apply all ({pending.length})` (btn-primary, `confirm()` first:
  "Apply all N remaining changes? Each replaces the block text with the
  polished version.") and `Skip all`; right side the existing
  "Done — reload editor" button.

Dismissal semantics: Escape / backdrop / × **hides** the modal but keeps
the report. `EditorInner` gets a `polishReviewOpen` boolean next to
`polishReport`; when a report exists and the modal is hidden, the
`.editor-side` column shows a small stub panel (in addition to the normal
Pending/Snapshots panels — do NOT evict them like today):
"Polish review — N pending" + "Resume review" button + the existing
"Done — reload editor". Opening the report after a polish run sets
`polishReviewOpen = true`.

### 3.4 Apply all / Skip all (frontend-only)

In `EditorInner`, generalise the existing handlers:

- `onApplyAll`: for each `report.flagged` block still in
  `polishRemaining`, call
  `editor.updateBlock(block_id, { content: polished_content })` (same
  call as the single Apply, `Editor.tsx:642-648`), then clear
  `polishRemaining`. BlockNote's `onChange` fires on programmatic
  updates, so the existing autosave debounce persists it — verify this
  during implementation; if `onChange` does NOT fire, call `save()`
  explicitly after the loop.
- `onSkipAll`: `setPolishRemaining(new Set())`.

### 3.5 CSS (`frontend/src/index.css`)

New: `.polish-modal` (width/height as above), `.polish-progbar` (height
~8px, radius, background var(--border or similar)),
`.polish-progbar-fill` (background accent colour, `transition: width
.4s`), `mark.diff-del` (background #ffd7d7, `text-decoration:
line-through`, no padding jump), `mark.diff-ins` (background #c6f6d5),
`.polish-review-stub` (the side-column stub), sticky modal footer class.
Match the existing palette — the diff marks should be a stronger shade of
the existing `#fff3f3` / `#f0fff4` box colours.

## 4. Verification

- Backend: `cd backend && uv run pytest && uv run ruff check`. All new
  logic (progress dict, diff_segments, API shapes) is covered by tests
  with the MockTransport runner — **never call the live Gemini API in
  tests or verification**.
- Frontend: `cd frontend && npm run build` (and `npm run lint` if
  defined in package.json).
- UI walkthrough with the Vite dev server + backend, using a scratch
  workspace via `NOTEBOOK_FORGE_WORKSPACE` (never mutate
  `~/NotebookForge-workspace/`). To exercise the full flow without a live
  API call, monkeypatch/inject is not available over HTTP — so verify the
  progress modal mechanics by hand: confirm the modal opens, shows the
  indeterminate state, and that `GET .../polish/progress` returns the
  zero shape; the chunk-counting path is proven by the backend tests.
  Screenshot the review modal with a hand-built report if needed (e.g.
  temporarily seed `polishReport` state) — remove any scaffolding before
  committing.
- Gotcha (from project memory): the Claude Preview browser tab is shared
  across servers — restarting the backend re-points it to :8400;
  navigate back to :5173 explicitly before UI checks.

## 5. Acceptance criteria

1. Clicking "✨ Polish text" opens a modal immediately; during a run the
   modal shows "chunk N of M" movement (backend test proves the counter;
   UI shows it when total > 0) and cannot be dismissed.
2. `GET /api/documents/{slug}/polish/progress` returns
   `{running, done, total, failed}`; idle slugs return the zero shape
   with 200.
3. Flagged blocks arrive with a `diff` array whose `a`/`b`
   concatenations equal the original/polished strings exactly.
4. The review renders in a wide modal: word-level red/green highlights,
   per-card Apply/Skip/jump-to-block, failed-chunk details expandable,
   sticky footer with Apply all (with confirm), Skip all, Done.
5. Dismissing the review modal keeps the report; a stub panel in the
   side column reopens it; the Pending/Snapshots panels remain visible
   throughout.
6. Apply all updates every remaining block in the editor and the
   autosave persists it (or an explicit `save()` does).
7. No changes to chunking, fidelity verdicts, auto-apply rules, or the
   snapshot-first behaviour. `uv run pytest`, `uv run ruff check`, and
   the frontend build all pass.
