# Prompt for the implementing agent (Sonnet)

Copy everything below the line into a fresh Claude Code session running in
the NotebookForge repo.

---

Implement the polish UX improvements specified in
`docs/POLISH_UX_PLAN.md`. Read that file first and follow it exactly — it
contains the verified design, file anchors, test list, and acceptance
criteria. Where the plan and this prompt disagree, the plan wins.

Context in one paragraph: the editor's "✨ Polish text" button runs a
synchronous multi-minute Gemini cleanup pass with zero progress feedback,
then dumps the review into a cramped sidebar with no diff highlighting and
no batch actions. You are adding (1) a live progress modal backed by a
polled progress endpoint, (2) a wide review modal replacing the sidebar
panel, (3) server-computed word-level diff highlighting, and (4)
Apply all / Skip all. The backend pattern is a direct port from
MemoirForge (paths in the plan §"Reference implementation") — read those
reference files before writing the backend half.

Hard rules:

1. `/Users/cs/ClaudeCode/MemoirForge/` is READ-ONLY. Read anything, write
   nothing, never push there.
2. Never call the live Gemini API. All backend tests use the existing
   MockTransport-injected runner pattern in `backend/tests/test_polish.py`.
3. Never modify documents in the real workspace
   (`~/NotebookForge-workspace/`). Live UI checks use a scratch workspace
   via the `NOTEBOOK_FORGE_WORKSPACE` env override.
4. Never publish or push to any live target.
5. Do not change the polish core: chunking, fidelity verdicts, auto-apply
   rules, snapshot-first, and the prompt/serializer are all untouched.
6. Backend is run with `uv` from `backend/` (`uv run pytest`,
   `uv run ruff check`). Match the house style — read
   `backend/notebook_forge/polish/service.py` and `runner.py`, and the
   frontend's `Editor.tsx` `ChangesModal`, before writing anything.

Key files to read before coding (paths relative to repo root):

- `docs/POLISH_UX_PLAN.md` — the spec.
- `/Users/cs/ClaudeCode/MemoirForge/memoirforge/app.py` lines ~177-190 and
  ~955-1015, and `/Users/cs/ClaudeCode/MemoirForge/static/app.js` lines
  ~975-1030 — the progress pattern you are porting.
- `backend/notebook_forge/polish/runner.py` (`run_chunks`),
  `service.py` (`polish_document`), `fidelity.py` (tokenisation style),
  `backend/notebook_forge/api.py` (polish endpoint, ~line 334).
- `frontend/src/views/Editor.tsx` — `ChangesModal` (modal idiom, ~line 33),
  `onPolish` (~line 546), the `.editor-side` render (~line 637),
  `selectHeading` (~line 457, jump-to-block mechanism).
- `frontend/src/views/PolishReview.tsx`, `frontend/src/api.ts`
  (types ~lines 34-49), `frontend/src/index.css` (`.modal-*`, `.polish-*`).

Known traps:

- The progress callback runs on worker threads — it must only do GIL-safe
  dict mutations and must be wrapped so an exception never tanks the run.
- The diff for display uses RAW text (whitespace-preserving
  `re.findall(r"\S+\s*", ...)` tokens); do NOT reuse the fidelity
  normalisation — the typography changes it strips are exactly what the
  reviewer needs to see.
- The progress GET must not 404 on unknown slugs (the poll can race the
  POST) and must not open a DB session.
- Verify whether BlockNote's `onChange` fires on programmatic
  `editor.updateBlock` calls; if not, Apply all must call `save()`
  explicitly (plan §3.4).
- The Claude Preview browser tab is shared across servers — restarting the
  backend re-points it to :8400; navigate back to :5173 explicitly before
  UI checks.

Definition of done: all seven acceptance criteria in plan §5 pass;
`uv run pytest` and `uv run ruff check` clean from `backend/`; frontend
build clean; commit on a feature branch with the repo's existing commit
style. Do not push unless told.
