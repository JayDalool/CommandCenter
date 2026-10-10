# Ticket pipeline V1

The Command Center ticket database is the source of truth for work. GitHub keeps
git, branches, PRs and CI; herdr keeps Claude sessions. This plan adds the
smallest layer that lets one ticket travel PLAN → BUILD → REVIEW → MERGE → VERIFY
→ DONE with durable state, conditional owner gates and deterministic transitions.
General workflow ideas only — no employer code, rules or infrastructure.

## CURRENT CAPABILITY (reused, not rebuilt)

| capability | where |
|---|---|
| canonical statuses INBOX…DONE + BLOCKED/DENIED/CANCELLED, forward-only numbering | `ccd/tasks.py` |
| append-only per-ticket event trail, comments, links (`github/pr`, branch) | `tasks.py` `ticket_events`, `ticket_links` |
| needs flags (needsJay/Legal/UIReview/Deploy) → Needs Jay queue | `tasks.needs()`, web `jayQueue` |
| GitHub automation: PR open → IN_REVIEW, approved+green → READY_TO_MERGE, merged → VERIFYING | `daemon._ticket_automation` |
| Development trail: branch, commits, PR, CI, review, merge | `GET /api/development` |
| one coordinator resolver, session-id bindings, Adopt | `ccd/coordid.py` (CC-017) |
| clean Workspace with ticket context (`?project&ticket`) | CC-018/019 |
| agent roles and models per project | `jay-dev:planner/implementer/reviewer/verifier`, registry `model` |

## MISSING CAPABILITY

1. **Durable work state** per ticket: plan, policy/gates, roles, worktree, review verdict + head SHA, review cycles, verification, handoff, blocked reason.
2. **Review verdicts are not visible to ccd**: our reviewers are fresh agents, not GitHub reviewers, so `reviewDecision` never becomes APPROVED and READY_TO_MERGE never fires.
3. **Conditional gates** (plan / merge+UI / deploy) and their Needs Jay categories.
4. **An agent-facing write path**: a tiny CLI agents call to record stage results.
5. **Ticket detail WORK view**: compact pipeline + the one owner action.
6. **Dispatch through the one resolver** (still matched the herdr agent name).
7. **Per-project pipeline config** in the registry (default branch, tests, merge policy, UI review default, max lanes).

## DATA MODEL CHANGES (tasks.db migration 3 — additive only)

`ticket_work` — one row per ticket that has entered the pipeline:

| column | meaning |
|---|---|
| `ticket_id` PK → tickets | |
| `plan` JSON | `{summary, requirements[], approach, affected[], risk, tests[], questions[]}` |
| `plan_state` | `none · proposed · accepted` |
| `gate` | `NULL · plan · merge · ui · deploy · failure` — the one open owner gate |
| `gate_reason` | why the gate is open (one line) |
| `worktree` | absolute path of the ticket worktree |
| `roles` JSON | `{planner|implementer|reviewer|verifier: {model, session, at}}` — only what an agent reported |
| `review_verdict` / `review_head` | `APPROVE · REQUEST_CHANGES` and the exact PR head SHA it covers |
| `review_cycles` | REQUEST_CHANGES count; 2 → BLOCKED + gate `failure` |
| `verification` JSON | `{result: pass|fail, at, by, evidence}` |
| `handoff` JSON | `{done, decisions, next, blockers}` — replaced at each stage, never a transcript |
| `blocked` JSON | `{stage, reason, at}` |
| `updated_at` | |

`ticket_findings` — structured review findings and owner feedback (Part 20):
`id, ticket_id, at, source (review|owner|verifier), scope (in|out), category, summary, head`.

No existing column changes; nothing is rewritten. Backed up before applying.

## POLICY (derived, not configured per ticket)

| gate | opens when |
|---|---|
| PLAN (OWNER_PLAN) | needsJay or needsLegal, or a label in `security, migration, destructive, architecture, product-decision, ambiguous, financial, legal, gate:plan`; else AUTO_PLAN |
| MERGE (OWNER_MERGE) | project `merge_policy` = `owner` (default for every project in the pilot); `auto-eligible` only for a later low-risk CC policy |
| UI (OWNER_UI_REVIEW) | needsUIReview, or type DESIGN, or label `ui` |
| DEPLOY (OWNER_DEPLOY) | needsDeploy |

## STATE TRANSITIONS (each audited as a ticket event)

| op (actor) | from | to | gate effect |
|---|---|---|---|
| `plan` (planner/coordinator) | INBOX…READY_TO_IMPLEMENT | RESEARCHING → READY_TO_IMPLEMENT (auto) | OWNER_PLAN: stays RESEARCHING, gate `plan` |
| `approve-plan` (Jay) | RESEARCHING + gate plan | READY_TO_IMPLEMENT | clears |
| `start` (coordinator/implementer) | READY_TO_IMPLEMENT | IN_PROGRESS | branch must be `<KEY>-slug`; refuses past `max_lanes` (2) |
| PR opens (GitHub, existing) | READY_TO_IMPLEMENT / IN_PROGRESS | IN_REVIEW | |
| new PR or head after `rework` (GitHub) | IN_PROGRESS | IN_REVIEW | the rework event records the ticket's open PRs (ref, head); only a (ref, head) that is neither the reviewed head nor in that set returns it (a replacement PR, or a new head on a known one). A later rework re-records the set |
| `review APPROVE --head SHA` (reviewer) | IN_REVIEW | READY_TO_MERGE when CI green, not draft and the full SHA == that PR's head | OWNER_MERGE: gate `merge` (the UI gate comes after verify, on the merged result) |
| `review REQUEST_CHANGES` | IN_REVIEW | IN_REVIEW (cycle+1) | 2 cycles → BLOCKED, gate `failure` |
| new PR head ≠ review_head (GitHub) | READY_TO_MERGE | IN_REVIEW | approval and any merge authorisation invalidated |
| a new `plan` | PLAN stages | as `plan` | a plan Jay approved before is not carried over |
| merged (GitHub, existing) | IN_REVIEW / READY_TO_MERGE | VERIFYING | merge gate clears; once per PR, so a fix PR after a failed verification needs its own review and merge |
| `verify pass` (verifier) | VERIFYING | DONE, or gate `ui`/`deploy` if still owed | |
| `verify fail` | VERIFYING | BLOCKED | gate `failure` |
| `confirm <gate>` (Jay) | gate open | next state (ui after verify → DONE) | clears |
| `block` / `handoff` / `finding` | any | BLOCKED / — / — | |

Only these signals move a ticket. Nothing is inferred from text.

## GATES → NEEDS JAY

One queue. Each item: project · ticket · what is needed · one action.
PLAN → "Plan needs approval" [Open ticket] · MERGE → "Ready to merge" [Open PR] ·
UI REVIEW → "UI review" [Open Workspace] · DEPLOY → "Deploy approval" [Open ticket] ·
FAILURE → reason [Open ticket]. Existing flags (legal, question, permission) stay.

## AGENT LIFECYCLE

| role | model | context | records via CLI |
|---|---|---|---|
| Coordinator | Opus, persistent per project | project | `start`, `handoff`, `block` |
| Planner | Opus, temporary, read-only | ticket + repo | `plan` |
| Implementer | Sonnet, isolated worktree `<KEY>-slug` | ticket + accepted plan | `role implementer`, PR via GitHub |
| Reviewer | fresh Opus | ticket + plan + diff | `review VERDICT --head SHA`, `finding` |
| Verifier | Sonnet, fresh, after merge | ticket + merged/live result | `verify pass|fail` |

CLI: `server/.venv/bin/python -m ccd.pipeline_cli <op> <KEY> …` → ccd's loopback
API with the ccd token (the same token every agent session on this account can
already read). Ticket work sessions are named `<key>` and exist only while the
ticket is worked; the project coordinator stays separate. No AI poller: ccd's
existing GitHub poll and herdr events drive every automatic transition.

Concurrency: `max_lanes` = 2 tickets IN_PROGRESS with an implementer at once **per project**
(2026-10-09, Jay: was all projects; a registry pipeline `max_lanes` overrides it); `start` refuses the third. Overlap classification stays the
coordinator's judgement (recorded in the handoff).

## UI CHANGES

Ticket detail → **Work** section: `PLAN ✓ · BUILD ✓ · REVIEW ● · MERGE — · VERIFY —`,
the open gate's one action, plan summary, branch / worktree / PR / reviewed head,
verification, handoff. Needs Jay gains the gate categories. No new screens.

## EVENTS

`pipeline.plan`, `pipeline.plan_approved`, `pipeline.started`, `pipeline.review`,
`pipeline.review_stale`, `pipeline.ready_to_merge`, `pipeline.verified`,
`pipeline.gate_opened`, `pipeline.gate_confirmed`, `pipeline.blocked`,
`pipeline.handoff` — plus the existing status/link events. System events stay
separate from human comments.

## FAILURE / RESUME

Every op validates the current state and fails with 409 rather than skipping a
stage. Failures set BLOCKED with `{stage, reason, at}` and a `failure` gate.
Everything a new coordinator needs (stage, plan, branch, worktree, PR, reviewed
head, gate, handoff) is in tasks.db and survives Claude, herdr, ccd or server
restarts; `GET /api/tasks/{key}/work` returns it in one call.

## SECURITY

Ops are ticket-state writes with the ordinary ccd token (as ticket edits are
today); owner ops (`approve-plan`, `confirm`) additionally require Developer
Unlock so an agent cannot open its own gate. Inputs are length-limited printable
text; SHAs and branch names are pattern-checked; no shell, no paths executed.
Loopback, token separation and Developer Unlock are unchanged.

## TEST PLAN

Backend: policy derivation; every transition and its refusal; review head
binding and invalidation on a new PR head; two-cycle block; lane limit; owner
ops need Developer; migration 3 on a copy of a v2 DB; CLI against the API.
Frontend: Work section stages and the one action; Needs Jay categories.
Pilot: one real SamVision ticket end to end.

## ROLLBACK

Migration 3 only adds tables, but a previous ccd refuses a newer schema version,
so code rollback = restore the pre-migration tasks.db backup (taken before the
deploy) and switch back to the previous checkout. UI: atomic release switch back to the previous release.

## DEFERRED (CC follow-ups)

Desktop notifications from the launcher; auto-merge for low-risk CC; overlap
classifier; worktree auto-removal after DONE; pattern learning over findings;
Jira/Slack/email (drafts-first principle documented only).

## RESULT (2026-10-06)

Live since #17 (backend, schema 3) and #18 (WORK view, Needs Jay gates).

- **Dogfood, CC-026** (Development shows recorded roles): plan (auto) → start
  `CC-026-development-roles` + worktree → PR #19 linked by the GitHub poll →
  review REQUEST_CHANGES (3 in-scope) → implementer fixed → fresh APPROVE at
  `a90cf2e` → READY_TO_MERGE + merge gate → merged `0bf6105` (standing CC
  authorisation) → VERIFYING → fresh verifier pass on the live API/UI → DONE.
  Every step is an attributed event; roles planner/implementer/reviewer/verifier recorded.
- **Project pilot, SV-064** (SamVision number fields): plan (auto) → start →
  PR #114 → REQUEST_CHANGES (stylesheet CI: a comment read by Tailwind; a
  docs/jay edit SamVision forbids) → fixed → fresh APPROVE at `f430e8e`, CI
  green → READY_TO_MERGE, merge gate in Needs Jay. Stops there: SamVision
  merges need Jay.
- Found on the way: Command Center's own repo was not in ccd's GitHub poll
  (board config), so CC PRs never linked; added. Backend tests leaked a temp
  dir per database (CC-027).
