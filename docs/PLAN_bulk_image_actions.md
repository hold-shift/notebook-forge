# Plan: bulk image actions

**Branch:** `feat/bulk-image-actions`  
**Sprint:** 5 (June 2026)

## 1. Goal

Add a sticky IMAGES sidebar card to the editor that lets the operator:
- See figure counts at a glance (total / sketched / pending review)
- Navigate to any figure card with a prev/next stepper
- Generate sketches for all eligible figures in one click (sequential, polling)
- Caption all images without a caption
- Approve all pending sketches
- Toggle the batch face-gate (warn | block) per run

## 2. Milestones

| ID | Name | Scope |
|---|---|---|
| M0 | Discovery | Answer 3 questions; ensure eligibility rule is computable |
| M1 | Backend endpoint + job registry | POST + GET status; eligibility filter; tests |
| M2 | IMAGES sidebar card | UI panel above PENDING CHANGES; nav stepper; job polling |
| M3 | Relocate buttons | Remove Caption/Approve from MetaBar; add to IMAGES card |
| M4 | Pre-publish face scan | Optional; ship only after M1–M3 green |

## 3. Discovery answers (M0)

**Q1: Where is per-image safe mode stored?**  
In block props as `safeMode: 'sketch'|'original'|'omit'` (default `'sketch'`).
Stored in the `documents.blocks` JSON column — no separate DB column needed.
The schema already declares it as a prop in `forgeImageSpec`.

**Q2: What is the sidebar/figure component?**  
Sidebar: `PendingPanel` and `SnapshotsPanel` in `frontend/src/views/Editor.tsx`
(inside `.editor-side`). Figure: `ForgeImageView` in
`frontend/src/forge/ForgeImageView.tsx`, rendered as a BlockNote custom block
via `forgeImageSpec` in `frontend/src/forge/schema.tsx`.

**Q3: How does figure state reach the frontend?**  
`GET /api/documents/{slug}` returns the full `blocks` array. The editor mounts
these as BlockNote `initialContent`. Changes flow through BlockNote's
`onChange` → autosave (1200 ms debounce) → `PUT /api/documents/{slug}/blocks`.
The ImagesPanel reads figure state directly from `editor.document` (live,
no fetch needed after mount).

## 4. Eligibility rule

A `forgeImage` block is eligible for batch sketch generation if **all** hold:
1. `props.assetId` is non-empty (has an original photo)
2. NOT (`props.sketchAssetId` is non-empty AND `props.approval === 'approved'`)

Rule 2 is the guard against clobbering approved work. A block is eligible if
it has no sketch yet, OR has a sketch that has not been approved.

## 5. Backend design

### 5.1 Eligibility helper

```python
def eligible_figure_block_ids(blocks: list[dict]) -> list[str]:
    out = []
    for b in blocks:
        if b.get('type') != 'forgeImage':
            continue
        props = b.get('props', {})
        if not props.get('assetId'):
            continue
        if props.get('sketchAssetId') and props.get('approval') == 'approved':
            continue
        out.append(b['id'])
    return out
```

### 5.2 In-memory job registry

```python
_sketch_jobs: dict[str, dict] = {}
# key: "{slug}:{job_id}"  value: {status, done, total, failed, results, error}
```

### 5.3 Endpoints

```
POST /api/documents/{slug}/figures/generate-all-sketches
  body: { batch_face_gate: 'warn' | 'block' }  (default: 'warn')
  response: { job_id, eligible: int }
  → starts a background thread; returns immediately

GET /api/documents/{slug}/figures/generate-all-sketches/status
  query: ?job_id={job_id}
  response: { status: 'running'|'done'|'failed', done, total, failed,
              results: [{block_id, ok, face_gate, error?}] }
```

### 5.4 Batch face-gate

Default `warn` (a flagged face does not abort the batch, just marks the result).
The per-run toggle overrides the operator's global setting for the duration of
the batch only. Global setting is unchanged.

### 5.5 Tests (M1)

- `test_eligible_filter_excludes_approved` — approved sketch not in eligible set
- `test_eligible_filter_includes_unapproved_sketch` — pending sketch IS eligible
- `test_eligible_filter_includes_no_sketch` — no sketch IS eligible
- `test_eligible_filter_excludes_no_asset` — block without assetId excluded
- `test_generate_all_endpoint_returns_job_id` — POST returns job_id + eligible
- `test_status_endpoint_tracks_progress` — GET shows running→done

## 6. Frontend design

### 6.1 Figure card ids

Add `id={`figure-${blockId}`}` to the `<figure>` element in `ForgeImageView`.
Pass `blockId` as a new optional prop from the block renderer in `schema.tsx`.

### 6.2 ImagesPanel component

Placed in `.editor-side` **above** `PendingPanel`. Props:

```ts
{
  slug: string
  editor: BlockNoteEditor  // read editor.document for live block state
  onApproveAll: () => void
  onGenerateCaptions: () => Promise<void>
  generatingCaptions: boolean
}
```

Layout (top → bottom):

1. **Summary line** — `X figures · Y sketched · Z pending review`
2. **Nav stepper** — `‹ [3/7] ›` scrolls/highlights `figure-{id}` cards;
   flagged-review mode filtered to pending when job done
3. **"Generate all sketches"** button + eligible count badge
4. **Caption / Approve row** — Caption images (count) + Approve all (count)
5. **Gate toggle** — `warn | block` radio (default warn), visible only when ≥1 eligible
6. **Helper** — "Approved sketches are skipped"
7. While running → replace with JOB card: progress bar, cancel (not wired)
8. After done → result summary (N generated, F flagged faces) + flagged stepper

## 7. Flagged-review stepper (M2)

After a batch job completes, the stepper filters to block_ids where
`face_gate === 'flagged'`. Same scroll-and-flash logic as the normal stepper.

### 7.2 Result summary

```
Generated N sketches   [F face flags — review]
```
The "review" link activates the flagged stepper.

## 8. Commit messages

```
chore(images): M0 discovery — plan docs + eligibility answers
feat(api): M1 bulk generate-all-sketches endpoint + job registry
feat(ui): M2 IMAGES sidebar card with bulk generate + nav stepper
refactor(ui): M3 relocate Caption/Approve into IMAGES card
```

## 9. Constraints

- `generate_sketch_for_block` is reused unchanged (no changes to prompt/model/retry/gate)
- Sequential generation only; no parallel calls
- Polling not websockets (same pattern as `/polish/progress`)
- In-memory job registry (no DB table); jobs lost on server restart
- `make check` green before every commit

## 10. M4 (optional)

Pre-publish face scan of safe-edition originals. Ship only after M1–M3 are
green. Deferred to follow-up if time is short.
