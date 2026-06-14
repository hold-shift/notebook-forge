# Sonnet implementation prompt — bulk image actions

Copy the block below to Claude Sonnet in Claude Code.

---

IMPLEMENTATION TASK — execute the plan, do not redesign.

Read these two files in full before writing any code:
- docs/PLAN_bulk_image_actions.md — the source of truth for behaviour,
  endpoints, eligibility rule, milestones, and tests.
- docs/screenshots/mockup-sidebar.md — the target UI for the sticky IMAGES
  sidebar. Its information hierarchy is authoritative; match tokens to the
  app's existing sidebar cards (PENDING CHANGES / SNAPSHOTS).

Implement milestone by milestone (M0 → M1 → M2 → M3 → M4). M4 is OPTIONAL —
do it only if M1–M3 are green and time allows; otherwise leave it for a
follow-up and say so in SPRINT_REPORT.md. Do not redesign; where the plan
leaves a fallback, take the simplest option consistent with existing code
and note it in the commit body.

MOCKUP REFERENCE — what to build the UI against
- The sticky IMAGES card goes ABOVE the existing PENDING CHANGES card.
  Layout, contents, and the running-job / flagged-result states are
  specified in docs/screenshots/mockup-sidebar.md (sections "Layout" and
  "Reference HTML snapshot"). Follow that ordering exactly:
  summary counts → image nav stepper → "Generate all sketches" + eligible
  badge → Caption/Approve row → gate toggle (warn|block, default warn) →
  helper line; replaced by the JOB card while running; collapsing to a
  persistent result summary with the flagged-review affordance.
- Relocate the existing top-of-page "Caption images" and "Approve all"
  buttons into this card — remove the originals, do not duplicate.
- Each figure review card gets a stable id `figure-{block_id}` so the nav
  stepper can scroll/highlight it (plan section 6.1). The flagged-review
  stepper is the same control filtered to flagged block_ids (plan 7.2).

STEP 1 — M0 discovery. Before any code, answer the three discovery questions
in plan section 3 (where per-image safe mode is stored; the sidebar/figure
component; how figure state reaches the frontend) and record the answers in
the PR description. The eligibility rule (plan section 4) MUST be computable
from real state before building M1. If safe mode is not persisted, add the
safeMode prop + migration exactly as the plan specifies.

CONSTRAINTS
- Branch feat/bulk-image-actions. One conventional commit per milestone
  (messages in plan section 12). `make check` green before every push.
- Reuse generate_sketch_for_block unchanged for execution; do not alter the
  sketch prompt, model, retry count, or the gate algorithm.
- The eligibility rule is the critical guard against clobbering approved
  sketches — implement and test it first and hardest (plan sections 4, 5.5).
- Sequential generation only (no parallel calls); polling not websockets;
  in-memory job registry (no DB table).
- Update SPRINT_REPORT.md changelog at each milestone.

DECISIONS ALREADY MADE (do not relitigate)
- Batch face-gate defaults to `warn` with a per-run toggle — plan 5.4.
- M4 (pre-publish face scan of safe-edition originals) is included in the
  plan but fenced optional — ship it only after M1–M3 are green.

When done: summarise in SPRINT_REPORT.md what shipped, what's partial, and
whether M4 was included or deferred. Push the branch.
