# ADR 0008 — The Autonomy Engine starts in shadow mode

Date: 2026-10-21 · Status: accepted (Jay, "Start Phase 0 + Phase 1", decisions D-007 and D-008)

## Context

Jay's agreed policy for each project (D-001 to D-006) now lives in `policy/projects/<key>.toml` under `[target]`
(v2 Phase 1, PR 2). The eventual Command Center policy is full experimental autonomy, but Jay wants it
earned: "The Autonomy Engine must begin in SHADOW MODE. For every decision: calculate the new engine result;
calculate/observe the existing behavior; record any disagreement; DO NOT change existing merge/deploy behavior yet."
No autonomous merge or deployment is enabled in Phase 0 or Phase 1.

## Decision

1. `ccd/autonomy.py` is a pure engine: `evaluate(action, profile, facts)` for the actions ccd decides today (plan,
   merge, deploy) returns `auto`, `jay` or `refuse` with the rule, reasons and the facts it lacked.
2. It is conservative: a missing or invalid profile, an unknown fact, or a human-only boundary (needs:jay,
   needs:legal, LEGAL) is `jay`; a paused project is `refuse`; a change to `self_protection.require_jay_for_paths`
   (D-007) or a personal-data path (D-005) is `jay`; live deploys need capabilities that do not exist yet.
3. What ccd did is read from the pipeline's own events (`autonomy.observed`), after the step is applied. The pair is
   recorded in `tasks.db` `autonomy_shadow` (migration 6): append-only, with a CHECK that `agree` is true exactly
   when the two outcomes match.
4. Nothing reads the engine's verdict to act. The record is shown read-only (`GET /api/autonomy`, Settings →
   Policies). A failure in the engine or the record is logged and changes nothing.
5. `server/ccd/autonomy.py` is under `server/ccd/**` (auto-merge denylist) and in Command Center's
   `self_protection` paths: a change to it needs Jay.

## Consequences

The disagreement record shows where the target policy is stricter or looser than today, and which missing facts
(most often a risk assessment) stop the engine from deciding. Turning any part of the target on is a later, separate
decision by Jay, with this evidence; it is not a config switch in this change.
