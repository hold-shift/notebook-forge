# Mockup: IMAGES sidebar card

## Layout

The IMAGES card is sticky, placed **above** the existing PENDING CHANGES card
in `.editor-side`. It uses the same `pending-panel` card chrome (border, padding,
`h3` header) so it blends with the existing sidebar aesthetic.

### Information hierarchy (top → bottom)

```
IMAGES                                    [collapse ▾]
────────────────────────────────────────
7 figures · 4 sketched · 3 pending review

  ‹   Figure 3 of 7   ›                  [jump]

  [✏ Generate all sketches]   3 eligible
  ○ warn   ● block   (face gate)
  Caption images (3)   Approve all (2)
  Approved sketches are skipped.

────────────────────────────────────────
```

### While running (JOB card replaces the button row)

```
IMAGES
────────────────────────────────────────
Generating sketches… (2 / 5)
████████░░░░░░░░░░░░  40 %
```

### After done (result summary + flagged stepper)

```
IMAGES
────────────────────────────────────────
5 figures · 5 sketched · 5 pending review

  ‹   Figure 1 of 5   ›

Generated 5 sketches — 1 face flag  [review ›]

  [↻ Generate again]   0 eligible
  Approved sketches are skipped.
```

## Reference HTML snapshot

```html
<div class="pending-panel images-panel">
  <div class="pending-panel-header">
    <h3>Images</h3>
  </div>
  <!-- Summary -->
  <div class="images-summary">
    <span>7 figures</span>
    <span class="sep">·</span>
    <span>4 sketched</span>
    <span class="sep">·</span>
    <span class="pending-badge">3 pending review</span>
  </div>

  <!-- Nav stepper -->
  <div class="images-stepper">
    <button class="stepper-prev" aria-label="Previous figure">‹</button>
    <span class="stepper-label">Figure 3 of 7</span>
    <button class="stepper-next" aria-label="Next figure">›</button>
  </div>

  <!-- Generate row -->
  <div class="images-generate-row">
    <button class="btn-primary images-gen-btn" disabled>
      ✏ Generate all sketches
    </button>
    <span class="eligible-badge">3 eligible</span>
  </div>

  <!-- Face gate toggle -->
  <div class="images-gate-row">
    <label><input type="radio" name="batchFaceGate" value="warn" checked /> warn</label>
    <label><input type="radio" name="batchFaceGate" value="block" /> block</label>
  </div>

  <!-- Caption / Approve row -->
  <div class="images-actions-row">
    <button>✨ Caption images (3)</button>
    <button>🖼️ Approve all (2)</button>
  </div>

  <!-- Helper -->
  <p class="images-helper">Approved sketches are skipped.</p>
</div>
```

## Tokens

Match the existing sidebar card tokens exactly:
- `pending-panel` — outer card chrome (same class as PendingPanel / SnapshotsPanel)
- `pending-panel-header` — header row with `h3`
- `pending-row` — row within the card
- `btn-primary` — primary action button
- `btn-danger-sm` — destructive small button
- New classes: `images-panel`, `images-summary`, `images-stepper`,
  `images-generate-row`, `images-gate-row`, `images-actions-row`,
  `images-helper`, `eligible-badge`, `stepper-prev`, `stepper-next`,
  `stepper-label`
