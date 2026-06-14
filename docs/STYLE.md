# NotebookForge UI Style Guide

## Design language in one sentence
Ink primary buttons · serif accent (wordmark, document titles, group headings only) · sentence case everywhere · two font-weights (400 / 500).

---

## Colour tokens

| Token | Value | Meaning |
|---|---|---|
| `--color-ink` | `#2C2C2A` | Near-black, warmer than the default text |
| `--color-umber` | `#633806` | Warm dark brown — warn foreground |
| `--color-tan` | `#BA7517` | Mid amber — flagged accent |
| `--color-amber` | `#EF9F27` | Bright amber — flag dot |
| `--color-cream` | `#FAEEDA` | Warm pale — warn background |
| `--color-pine` | `#085041` | Dark green — ok / live foreground |
| `--color-mint` | `#E1F5EE` | Pale green — ok / live background |

### Existing base tokens (keep as-is)
`--color-background-primary/secondary`, `--color-text-primary/secondary/tertiary`, `--color-border-primary/tertiary`, `--pill-ok-*`, `--pill-warn-*`, `--pill-danger-*`, `--color-background-info`, `--font-mono`.

---

## Typography

| Use case | Font | Weight | Size |
|---|---|---|---|
| Wordmark | `var(--font-serif)` (Source Serif 4) | 400 | 15px |
| Document titles (cards, editor breadcrumb) | `var(--font-serif)` | 400 | 14px |
| Group headings | `var(--font-serif)` | 400 | — |
| Body / UI / labels / buttons | System sans (`-apple-system …`) | 400 / 500 | — |

**Rule:** `--font-serif` is used ONLY in the three cases above. Never for body text, captions, inputs, or navigation.

Font-weights allowed: **400** (regular) and **500** (medium). Do not use 600 or bold in new UI code.

---

## Sentence case
All section labels, button text, panel headers, and nav links use sentence case. No ALL-CAPS, no Title Case For Every Word. Example: "Pending changes" not "PENDING CHANGES".

---

## Button variants (`<Button>`)

| Variant | Style |
|---|---|
| `primary` | `background: var(--color-text-primary); color: var(--color-background-primary); border: none` — the "ink" style |
| `secondary` | Outline only: `border: 0.5px solid var(--color-border-tertiary); background: transparent` |
| `danger` | `color: var(--pill-danger-fg); border-color: var(--color-border-error)` |
| `ghost` | No border, no background, muted text |

Sizes: `sm` (`3px 10px`, 12px) · `md` default (`5px 12px`, 13px).

---

## Status badges (`<StatusBadge>`)

Pill shape (border-radius 999px, padding 3px 10px, font-size 11px). Leading 6px coloured dot.

| Variant | Tokens | Dot colour |
|---|---|---|
| `live` | `--badge-live-*` | `var(--color-pine)` |
| `changes` | `--badge-changes-*` | `var(--color-tan)` |
| `unpublished` | `--badge-unpublished-*` | `var(--color-text-tertiary)` |
| `polished` | `--badge-polished-*` | `var(--color-pine)` |
| `flagged` | `--badge-flagged-*` | `var(--color-amber)` |
| `never-run` | `--badge-never-*` | `var(--color-text-tertiary)` |
| `stale` | `--badge-changes-*` | `var(--color-tan)` |

---

## Dark mode
Tokens are defined in `:root`. A dark theme would swap only the token values — no new component changes needed. No dark-mode toggle ships yet; it is a clean follow-up.

---

## What NOT to do
- Do not use `@mantine/core` for chrome components.
- Do not use `var(--font-serif)` for body text, meta lines, buttons, labels, or inputs.
- Do not use font-weight 600 or 700 in new UI code.
- Do not use ALL-CAPS `text-transform` on section labels or group headers.
- Do not hard-code hex values outside token definitions and `@font-face`.
