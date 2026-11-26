# ADR 0010: Automatic weekly release, in slices (dry run first)

Date: 2026-11-26 · Status: proposed (slice 1 approved by Jay, question 230; slices 2 and 3 not decided) · Ticket:
CC-081

## Context

Jay wants low-risk apps (GYST and Command Center) to release on their own at the weekly window, shipping only what
the release email (CC-078) listed. Today nothing deploys automatically. ccd only records deploys (README "No
dangerous endpoints", ADR 0006). A live deploy can be recorded only after Jay's approval (`pipeline.deployed` needs
`approvedAt`). D-004 holds any unattended release until the profile capabilities `health_checks` and
`auto_rollback` are true, and both are false for every project. Command Center releases all of `main`, not single
tickets, and the release script restarts ccd, so ccd cannot be the parent of a release. Risky tickets have converged
poorly in one round (CC-057, 063, 070, 071).

## Decision

1. **Slice 1 (this ticket): a dry run that only records.** `ccd/autorelease.py`, behind `auto_release` (`"off"`
   default, `"dry_run"`; nothing else is accepted, and no value releases), with a stop file. For each window it
   records the manifest, eligibility with reasons, and later the actual deploy outcome per ticket. It deploys,
   restarts, approves, rolls back and changes no gate, ever. No new route: `GET /api/release` gains `autoRelease`.
2. **Eligibility is its own check** (c4), not merge readiness: the project is on the allow list (GYST, Command
   Center), live and not paused; a delivered digest exists; each item is verifying, with a live deploy requested,
   verification passed and its window open; capabilities true and a passing rehearsal recorded; no failed or
   inconclusive release since the last pass; and for Command Center every commit in `live..pinned` is a manifest
   ticket.
3. **Pinned sha** (Jay, question 230): the release target is `origin/main` as the checkout's reflog had it when the
   digest was delivered, so a merge after delivery never joins it. No reflog entry that old means no pin, and the
   release holds. The shipped range must carry only tickets that would release, including what each merge carries.
4. **A failed release holds** further automatic releases for that project until Jay clears it. No automatic
   rollback; rollback stays Jay's, per the project runbook (question 230). Slice 1 has no clear at all: the hold
   stays in the dry-run record, which acts on nothing. Jay's clear arrives with slice 3.

## Later slices (each needs Jay's decision before it is built)

- **Slice 2, rehearsal:** a release drill on the preview that runs the release with a forced failing check and the
  printed rollback, writing `rehearsals.jsonl`. Jay then sets the capabilities in `policy/projects/*.toml` (Jay
  only). A GYST ticket adds its release script, health check and rollback runbook, and Jay changes GYST's
  AGENTS.md rule that deploys stay his.
- **Slice 3, real release:** `auto_release` accepts `"on"`. A systemd user timer outside ccd (in `scripts/`,
  installed by Jay) asks `GET /api/release` for the eligible manifest and pinned sha and runs the project's release
  script with an expected sha. It records each deploy under a new approval source (`system:release-window`, a grant
  Jay approves, never recorded as Jay). Clearing a failed-release hold is added here, as a Jay-only action
  (Developer Unlock), with a test that every refusal leaves the ledger unchanged.

Rails slice 3 changes, each Jay's: the `approvedAt` rule in `pipeline.deployed` and the release-window hold; README
and AGENTS "No dangerous endpoints" and ADR 0006 "ccd deploys nothing"; FLOW.md "nothing deploys automatically";
D-004 capabilities and `requires` in the GYST and Command Center profiles; `autonomy.py` deploy rules; the broker's
action list; the release script; new systemd units and SECURITY.md's systemd scope list; the route-table test.

## Consequences

- Jay sees, for weeks before anything can act, what an automatic release would have shipped and why it would have
  held. Until slice 2 both projects read "not eligible" (capabilities false, no rehearsal).
- The dry run is as trustworthy as its inputs: agents run as the same user and could edit `config.json`, the stop
  file, the logs or the ledger. Slice 1 is acceptable because nothing reads it to act. Slice 3 needs an
  authority an agent cannot write.
- SamVision and MFE never release automatically: their client-impact and migration checks stay.
