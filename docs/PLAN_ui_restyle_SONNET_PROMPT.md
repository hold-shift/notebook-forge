# Sonnet implementation prompt — UI restyle + polish status

Copy the block below to Claude Sonnet in Claude Code.

---

IMPLEMENTATION TASK — execute the plan, do not redesign.

Read docs/PLAN_ui_restyle.md in full — it is the source of truth. Also read
SPRINT_REPORT.md for current state, and skim frontend/src/index.css,
frontend/src/views/{Library,Editor,Settings}.tsx, and
backend/notebook_forge/polish/service.py before starting.

Implement milestone by milestone in order: M1 token foundation → M2 shared
primitives → M3 Library + Homepage → M4 Editor + Settings + BlockNote
agreement → M5 polish backend additions → M6 polish status UI → M7 wrap-up.
Do not redesign; where the plan offers a fallback, take the simplest option
consistent with existing code and note it in the commit body.

KEY CONSTRAINTS (full detail in the plan)
- This is a TOKEN-BASED CSS restyle, NOT a kit migration. Do NOT add
  @mantine/core. Evolve frontend/src/index.css tokens and add thin styled
  primitives under frontend/src/ui/. Mantine stays only as BlockNote's
  renderer.
- Design language (plan §3): ink primary buttons
  (background var(--color-text-primary), inverted text); ONE self-hosted
  serif (Source Serif 4 woff2) used ONLY for wordmark, document titles, and
  group headings — never body/UI/labels; one StatusBadge system replacing all
  ad-hoc pills; warm archival accent tokens; sentence case everywhere (kill
  the tracked ALL-CAPS section labels); font-weights 400/500 only.
- Dark mode (plan §4): ship dark-mode-CLEAN but DEFER the dark theme — use
  tokens throughout, no hardcoded hex outside token defs and @font-face, no
  toggle, no dark QA this PR.
- Do NOT change published document output, polish/sketch/publish/import
  behaviour, or forge block behaviour. After M4, verify all four forge blocks
  (image, footnote, narrative, doc-group) still render.

POLISH STATUS (plan M5–M6)
- Backend: persist flagged BLOCK IDS in the polish change detail
  (`flagged_ids`), keep the count; add GET
  /api/documents/{slug}/polish/last returning the latest run summary (or null).
- UI: a StatusBadge by "Polish text" with states never-run / fresh / stale
  ("Edited since last polish", compared against document last-modified) /
  flagged; clicking opens a popover (timestamp, model, cleaned/unchanged
  metric cards, flagged+chunks, "Review flagged" via flagged_ids reusing the
  existing PolishReview path, "Restore pre-polish" via the service's
  "before polish" snapshot). Add a quiet polish hint to each Library row's
  metadata line.

WORKFLOW
- Branch feat/ui-restyle. One conventional commit per milestone (messages in
  plan §10). `make check` green before every push.
- Inline-style sprawl is real in Editor/Library (100+ blocks). Migrate to
  primitives per screen; do NOT attempt one sweeping refactor. If a screen is
  too risky to fully convert, convert buttons/badges/titles (the visible
  restyle) and leave layout inline, noting it in the commit body.
- Put before/after screenshots of each restyled screen in the PR description.
- Update SPRINT_REPORT.md changelog at each milestone and confirm docs/STYLE.md
  (created in M1) matches what shipped.

When done: summarise in SPRINT_REPORT.md what shipped, what's partial (e.g.
any screen left with inline layout), and confirm dark mode remains a clean
token-swap follow-up. Push the branch.
