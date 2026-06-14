# NotebookForge UI Style Guide

## Design language in one sentence
Ink primary buttons · serif accent (wordmark, document titles, group headings only) · sentence case everywhere · two font-weights (400 / 500).

---

## Colour tokens

| Token | Value | Meaning |
|---|---|---|
| `--color-ink` | `#2C2C2A` | Near-black, warmer than the default text |
| `--color-umber` | `#633806` | Warm dark brown — warn foreground |
| `--color-tan` | `#BA7517` | Mid amber — flagged accent / changes dot |
| `--color-amber` | `#EF9F27` | Bright amber — flagged dot |
| `--color-cream` | `#FAEEDA` | Warm pale — warn background |
| `--color-pine` | `#085041` | Dark green — ok / live / polished foreground |
| `--color-mint` | `#E1F5EE` | Pale green — ok / live / polished background |

### Existing base tokens (unchanged)
`--color-background-primary/secondary`, `--color-text-primary/secondary/tertiary`, `--color-border-primary/tertiary`, `--pill-ok-*`, `--pill-warn-*`, `--pill-danger-*`, `--color-background-info`, `--font-mono`.

---

## Typography

| Use case | Font | Weight | Size |
|---|---|---|---|
| Wordmark | `var(--font-serif)` (Source Serif 4) | 400 | 15px |
| Document titles (cards, editor breadcrumb h2) | `var(--font-serif)` | 400 | 14px |
| Group headings | `var(--font-serif)` via `<SectionLabel>` | 500 (sans) | 11px |
| Body / UI / labels / buttons | System sans (`-apple-system …`) | 400 / 500 | — |

**Rule:** `--font-serif` is used ONLY in the `<SerifTitle>` component. Never for body text, captions, inputs, navigation, or labels.

Font-weights allowed: **400** (regular) and **500** (medium). No 600 or 700 in UI chrome.

---

## Sentence case
All section labels, button text, panel headers, and nav links use sentence case.  
- ✓ "Pending changes" · "Images" · "Snapshots" · "Sketch generation"  
- ✗ "PENDING CHANGES" · "IMAGES" · "Sketch Generation"

---

## Button variants — `<Button variant="...">` (`frontend/src/ui/Button.tsx`)

| Variant | Style |
|---|---|
| `primary` | `background: var(--color-text-primary); color: var(--color-background-primary); border: none` — the "ink" style |
| `secondary` | Outline: `border: 0.5px solid var(--color-border-tertiary); background: transparent` |
| `danger` | `color: var(--pill-danger-fg); border: 0.5px solid var(--color-border-error)` |
| `ghost` | No border, no background, `color: var(--color-text-secondary)` |

Sizes: `sm` (`3px 10px`, 12px) · `md` (default, `5px 12px`, 13px).

---

## Status badges — `<StatusBadge variant="...">` (`frontend/src/ui/StatusBadge.tsx`)

Pill shape: border-radius 999px · padding 3px 10px · font-size 11px.  
Leading 6px coloured dot.

| Variant | Tokens | Dot colour | Default label |
|---|---|---|---|
| `live` | `--badge-live-*` | `var(--color-pine)` | Live |
| `changes` | `--badge-changes-*` | `var(--color-tan)` | Changes |
| `unpublished` | `--badge-unpublished-*` | `var(--color-text-tertiary)` | Unpublished |
| `polished` | `--badge-polished-*` | `var(--color-pine)` | Polished |
| `flagged` | `--badge-flagged-*` | `var(--color-amber)` | Flagged |
| `never-run` | `--badge-never-*` | `var(--color-text-tertiary)` | Not polished |
| `stale` | `--badge-changes-*` | `var(--color-tan)` | Stale |

All variants accept an optional `label` prop to override the default text.

---

## Polish badge state machine (`computePolishBadge`)

| Condition | Badge |
|---|---|
| `polishLast === null` | `never-run` |
| `polishLast === 'loading'` | `loading` (shown as `never-run` until resolved) |
| `flagged_ids.length > 0` | `flagged` (takes priority over polished/stale) |
| `at > updated_at` | `polished` |
| `at <= updated_at` | `stale` |

---

## Helper primitives

- `<SectionLabel>` — `frontend/src/ui/SectionLabel.tsx`  
  Muted 11px/500 label, no text-transform. Used for panel headings.
- `<SerifTitle as="...">` — `frontend/src/ui/SerifTitle.tsx`  
  Configurable heading tag with `var(--font-serif)` at weight 400.

---

## Dark mode
Tokens are defined in `:root`. A dark theme would swap only the token values — no component changes needed. No dark-mode toggle ships with this restyle; it is a clean follow-up.

---

## What NOT to do
- Do not use `@mantine/core` for chrome components.
- Do not use `var(--font-serif)` outside `<SerifTitle>`.
- Do not use font-weight 600 or 700 in new UI code.
- Do not use `text-transform: uppercase` on section labels or group headers.
- Do not hard-code hex values outside token definitions and `@font-face`.
