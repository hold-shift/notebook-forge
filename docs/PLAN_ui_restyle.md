# Build plan — UI restyle (design system) + polish status

**Workflow:** Fable wrote this plan; Sonnet implements it. Every decision is
made here. Do not redesign; where a fallback is offered, take the simplest
option consistent with existing code and note it in the commit body.

**Repo:** notebook-forge (this directory). Branch: `feat/ui-restyle`.
Conventional commits, one per milestone. `make check` green before each push.

---

## 1. Goal & scope

Two things, sequenced as one effort:
1. A cohesive visual restyle of the TOOL CHROME — modern monochrome "ink"
   buttons replacing the dated glossy blue, a serif accent for wordmark /
   document titles / group headings, one unified status-badge system, warm
   archival accent palette, and sentence-case labels replacing tracked
   all-caps. Applied across Library, Editor, Homepage, Settings.
2. A "polish status" feature: surface whether/when text-polish last ran on a
   document and a short adjustments summary, integrated into the restyled UI.

NON-goal: changing the PUBLISHED document output (the Archive serif house
style is unaffected — these tokens style only the app, as index.css already
notes). No behavioural changes to polish, sketch, publish, or import logic.

---

## 2. Grounding — how the frontend is actually built (verified)

- React + Vite + TypeScript. Views in `frontend/src/views/`
  (Library, Editor, Settings, PolishReview, PolishProgress, ManageGroupsModal),
  custom blocks in `frontend/src/forge/`.
- Styling is a TOKEN-BASED CSS system in `frontend/src/index.css` (CSS custom
  properties: `--color-*`, `--pill-*`, `--border-radius-*`, `--narrative-*`)
  PLUS heavy inline `style={{…}}` in views (Library 48, Editor 102 inline
  blocks). There is NO `@mantine/core` usage — Mantine is present only as
  BlockNote's renderer (`@blocknote/mantine`). Do NOT introduce `@mantine/core`
  as a component kit; that would be a second design language. Evolve the
  existing token system instead. (This supersedes earlier "adopt Mantine"
  discussion — the codebase reality is token-based CSS, so that is what we
  refine.)
- BlockNote is themed via `<BlockNoteView theme="light">` in Editor.tsx and
  `@blocknote/mantine/style.css`. The editor surface must visually agree with
  the new chrome tokens (see M4).
- Polish backend (verified, do not rebuild): every run writes a change-log
  entry via `services.record_change(..., "edit", "polish run: N cleaned, M
  flagged…", detail={model, chunks, blocks_changed, flagged (int), failed_
  chunks})` and takes a "before polish" snapshot. The detail stores flagged
  COUNT, not block ids (see M5 — one small backend addition).

---

## 3. Locked design decisions

- **Primary buttons:** solid "ink" — `background: var(--color-text-primary);
  color: var(--color-background-primary); border: none`. This inverts
  correctly if dark mode is added. Replaces every glossy-blue primary
  (Save, Add document, Push to all targets, Update, the Save * settings
  buttons). Secondary buttons stay outline (current default). Destructive
  buttons use the danger tokens.
- **Serif accent:** ONE open-licence serif (Source Serif 4 — self-host the
  woff2 in `frontend/src/assets/fonts/`, do not hot-link Google Fonts at
  runtime; add an `@font-face` and a `--font-serif` token). Used ONLY for:
  the "Notebook Forge" wordmark, document titles (breadcrumb + list rows +
  editor meta), and group headings. NEVER body text, form labels, buttons,
  or badges — those stay sans for legibility.
- **Status badges — one system.** A single `<StatusBadge>` component (or a
  shared CSS class set if components aren't the pattern) with variants:
  `live` (success tokens), `changes` (warning tokens), `unpublished`
  (neutral: secondary bg + tertiary border + secondary text), each a pill
  with a 6px leading dot. Polish/face variants reuse the same shape
  (see M5, and the bulk-image plan). Replace ALL ad-hoc pill styling.
- **Accent palette:** warm archival, sampled from the published pages —
  ink #2C2C2A, umber #633806, tan #BA7517, amber #EF9F27, cream #FAEEDA,
  pine #085041, mint #E1F5EE. These map onto existing/added tokens; the
  generic blue `--color-*-info` set is retained only where a genuinely
  informational accent is needed, otherwise superseded by ink + warm.
- **Labels:** sentence case everywhere. Replace tracked all-caps section
  headers ("IMAGES", "PENDING CHANGES", "OUTLINE", "SNAPSHOTS") with
  sentence-case muted labels (`color: var(--color-text-secondary)`, normal
  case, optional small letter-spacing). No ALL CAPS, no Title Case.
- **Weights:** two only — 400 and 500. Remove any 600/700 usage.
- **Radius:** cards `--border-radius-lg`, controls `--border-radius-md`.
  No rounded corners on single-sided (left-border) accents.

## 4. Dark mode decision (LOCKED)

Ship the restyle dark-mode-CLEAN but DEFER a dark theme. That means: all new
styling uses tokens (never hardcoded #hex except inside the token
definitions and the @font-face), so a future dark theme is a token-swap, but
this PR does not add a theme toggle or a dark token set, and does not budget
dark-mode QA. Rationale: keeps the restyle focused and shippable; dark mode
becomes a cheap follow-up precisely because tokens are used throughout. If
any view currently hardcodes colours inline, migrating them to tokens is
in-scope (it is the mechanism that makes dark mode cheap later).

## 5. Sequencing decision (LOCKED)

Design-system pass FIRST (M1–M2), then apply per screen (M3–M4), then the
polish-status feature (M5–M6). Landing tokens + shared components before the
screen work means each screen inherits the look rather than re-inventing it.

---

## 6. Milestones

### M1 — Token foundation
Extend `frontend/src/index.css`: add the warm accent tokens (umber, tan,
amber, cream, pine, mint named tokens), `--font-serif` + self-hosted
`@font-face` (Source Serif 4), success/warning/neutral badge token triplets
(bg/fg), and confirm radius tokens. Keep existing token names working
(no breakage). Add a one-screen `docs/STYLE.md` documenting the token meaning
and the "ink primary / serif accent / sentence case / two weights" rules so
later features stay consistent.
Gate: app builds; existing screens visually unchanged except where tokens
were already used; `make check` green.

### M2 — Shared styled primitives
Create reusable primitives used by every screen, matching the codebase's
existing pattern (small components in a new `frontend/src/ui/`):
`Button` (variants: primary=ink, secondary=outline, danger, ghost; sizes
sm/md), `StatusBadge` (variants live/changes/unpublished/polished/flagged;
optional leading icon + dot), `Pill`, `SectionLabel` (sentence-case muted),
`SerifTitle`. Each is a thin wrapper over tokens — no logic. Vitest render
tests for Button variants and StatusBadge variants.
Gate: primitives covered by tests; Storybook NOT required.

### M3 — Apply to Library + Homepage
Library.tsx: serif wordmark + nav, sentence-case controls, softened cards
(radius-lg, more padding), serif document/group titles, `StatusBadge`
everywhere, ink "Add document". Homepage view + ForgeDocGroupView: serif
title, ink "Push", consistent group-block chrome. Replace inline pill/button
styles with the M2 primitives.
Gate: no visual regressions to behaviour; existing Library/group tests still
green; screenshots in PR.

### M4 — Apply to Editor + Settings + BlockNote agreement
Editor.tsx meta bar: serif breadcrumb title, ink Save, quiet secondary
actions (Re-ingest, Polish text), tidy the action row. Right sidebar
(Images / Pending changes / Snapshots): sentence-case section labels,
`StatusBadge`, consistent card chrome. Settings.tsx: section cards, ink
"Save *" buttons, consistent inputs. Ensure the BlockNote editor surface
(via @blocknote/mantine) visually agrees with the chrome — set BlockNote
theme variables (CSS) to match token bg/text/borders so the editing canvas
doesn't look foreign. Do NOT change block behaviour.
Gate: editor-load and forge-block tests green; screenshots in PR.

### M5 — Polish status: backend additions (small)
Two minimal, backward-compatible changes to the polish service
(`backend/notebook_forge/polish/service.py`):
1. Persist flagged BLOCK IDS (not just the count) in the change `detail`,
   e.g. `detail["flagged_ids"] = [block_id, …]`. The count stays for
   compatibility. This lets "Review flagged" jump to the right blocks
   without re-diffing a snapshot.
2. Ensure the change `detail` carries a usable timestamp source. The change
   row already has a created_at; expose it through whatever endpoint the
   frontend will read (see M6). If no read path exists, add
   `GET /api/documents/{slug}/polish/last` returning the most recent polish
   change as `{at, model, blocks_changed, blocks_unchanged, flagged_ids,
   chunks, failed_chunks}` or `null` if never polished. Unchanged count =
   derivable; if not stored, compute and include it.
Tests: service writes `flagged_ids`; the endpoint returns the latest run and
`null` when none; idempotent across repeated polishes.

### M6 — Polish status: UI
- **Staleness rule:** "polished" state is fresh if the latest polish change
  timestamp is newer than the document's last content-modification; otherwise
  show "Edited since last polish" (muted). Compute from data already
  available client-side (document updated_at vs polish `at`).
- **Editor meta bar:** a `StatusBadge` next to "Polish text":
  never-run → muted "Not yet polished"; fresh → success
  "Polished · {relative} · {N} cleaned"; stale → muted "Edited since last
  polish"; runs with flags → include an amber flag affordance. Clicking the
  badge opens a popover: timestamp, model, metric cards (cleaned / unchanged),
  flagged + chunks line, and actions "Review flagged" (jumps via flagged_ids,
  reuse the existing PolishReview path) and "Restore pre-polish" (the
  service's "before polish" snapshot).
- **Library rows:** append a quiet polish hint to each row's metadata line
  ("· polished 2 days ago" / "· not yet polished"), same data source.
Tests: badge state machine (never/fresh/stale/flagged) from fixture data;
popover renders metrics; library hint renders.

### M7 — Wrap-up
Update SPRINT_REPORT.md changelog; ensure `docs/STYLE.md` matches what
shipped; screenshots of all four restyled screens in the PR. Tag if the
project tags releases.

## 7. Edge cases
- A document polished, then edited, then polished again → staleness compares
  against the LATEST polish only.
- "no polishable blocks" run (blocks_changed 0) still records a change →
  badge shows "Polished · {relative} · 0 cleaned", not "Not yet polished".
- Homepage is excluded from polish (API returns 409) → no polish badge on the
  Homepage view.
- Restore pre-polish is a snapshot restore → it marks targets dirty; that is
  expected, not a bug.

## 8. Non-goals
Dark theme/toggle (deferred, see §4); changing published output; adding
@mantine/core; new polish behaviour; redesigning the BlockNote block UIs
beyond chrome agreement.

## 9. Risks
- Inline-style sprawl: Editor/Library carry 100+ inline style blocks. Migrate
  to primitives incrementally per screen; do not attempt a single sweeping
  refactor. If a screen is too risky to fully convert, convert the
  buttons/badges/titles (the visible restyle) and leave layout inline,
  noting it.
- Font loading flash: self-host woff2 + `font-display: swap`; serif is accent
  only, so a swap is invisible on body text.
- BlockNote theme drift: changing BlockNote CSS vars can affect block
  rendering — verify forge blocks (image, footnote, narrative, doc-group)
  still render after M4.

## 10. Commit order
M1 `style: token foundation + serif accent` → M2 `feat(ui): shared styled
primitives` → M3 `style(library,homepage): apply design system` →
M4 `style(editor,settings): apply design system + blocknote agreement` →
M5 `feat(api): persist polish flagged ids + last-run endpoint` →
M6 `feat(editor): polish status badge, popover, library hint` →
M7 `docs: style guide + sprint report`.
