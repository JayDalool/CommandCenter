# ADR 0007 — Auto-merge of reviewed low-risk Command Center PRs (ccd's first GitHub write)

Date: 2026-10-09 · Status: accepted (Jay's decision, option B, 2026-10-09) · Ticket: CC-025 ·
Amended by CC-080 (2026-11-26, see the last section)

## Context

Until now ccd only read GitHub. Merging was done by agents (`gh pr merge` in a night shift, under the registry's
`merge: "auto"`) or by Jay. "auto" meant "any ticket with no gate", and nothing checked which files a PR changed
or how big it was: a PR that edited `server/ccd/security.py` merged the same way as a README fix. CI was
"green" by default, because `.github/workflows/launcher.yml` runs only on `launcher/**`, so an empty check list
counted as green. Jay wants the safe part automated (docs and tests PRs of Command Center itself, after a fresh
review) and everything else to keep waiting for him.

## Decision

1. **Merge values are `owner` (the default) and `low-risk`.** `auto` is removed; any other value is read as
   `owner` (`pipeline.policy`). SamVision, GauzeMate, MyFamilyExpenses and GYST are `owner`. Only
   `commandcenter` is `low-risk`.
2. **Agents never merge.** Not `gh pr merge`, not the button. Only ccd (a PR the classifier accepts) or Jay merges.
   The night-shift skill says so.
3. **`ccd/merge_policy.py` is a pure classifier** (plain dicts in, a decision out, no I/O). A PR is low-risk only if
   every file is added or modified and matches the project's allowlist, which names file types as well as folders
   (Command Center: `server/tests/**/*.py`, `web/app/tests/**/*.ts` and `*.tsx`, `docs/**/*.md`, `README.md`), at
   most 10 files and 300 lines, and none of the denylist (`server/ccd/**`, `scripts/**`, `launcher/**`,
   `.github/**`, `web/app/src/**`, lockfiles and manifests, `plans/**`, `docs/SECURITY.md`, `docs/adr/**`; any
   dot-folder or dot-file at any depth such as `.claude/`, `.mcp.json` and `.codex/`; any `__pycache__`; and
   `AGENTS.md`, `AGENTS.override.md`, `AGENT.md`, `CLAUDE.md`, `CLAUDE.local.md`, `GEMINI.md`, `SKILL.md` anywhere). The denylist always wins. A project with no allowlist never qualifies. A PR that changes this policy can therefore never
   auto-merge. The ticket must carry no needs:jay, needs:legal, UI or deploy flag, no SECURITY / LEGAL / DESIGN
   type, no plan-gate label and no `owner:accept`.
4. **The review must still hold at merge time**: verdict APPROVE, `review_head` equal to the PR's head in a fresh
   `gh pr view`, recorded against this very PR, and the ticket has exactly one open linked PR. The PR is open, not a
   draft, MERGEABLE, based on `main`, not from a fork, and CI has nothing failing or pending. Until CC-080 a PR with
   no checks at all qualified (there was no PR workflow yet; CC-033 added one) and the events said "no CI checks",
   never "green". **CC-080 withdrew that allowance**: a PR with no checks is now held (see the last section).
   The old "approved head X with green checks" text had the same flaw and is fixed.
5. **Three switches, all of which must allow it**: registry `merge: "low-risk"` (code, merged by Jay);
   `auto_merge: true` in `config.json` (default `false`, read at start); and no file
   `~/command-center/state/auto-merge.stop` (checked immediately before every merge; any error reading it counts as
   "stopped"). With `auto_merge` off a low-risk project behaves like `owner`: the ready PR opens a merge gate.
   ccd logs the state at startup as a security event `merge.policy`.
6. **How it merges** (`Daemon._auto_merge`, after `_ticket_automation`, `gh` in `asyncio.to_thread`):
   `gh pr view N --repo R --json …`, classify, then
   `gh pr merge N --repo R --merge --match-head-commit <review_head>`. Never `--admin`, `--auto`, `--squash` or
   `--delete-branch`. `--match-head-commit` makes GitHub itself refuse the merge if the head moved after the check.
   After the merge the existing GitHub poll moves the ticket to VERIFYING (`pipeline.merged`); verify and deploy
   are unchanged and ccd never deploys.
7. **A PR that does not qualify, or a merge that fails, is held**, not retried: `Pipeline.hold_merge` opens a merge
   gate in Needs Jay with the reason, and records `pipeline.auto_merge_held` or `pipeline.auto_merge_failed` for
   that head. ccd does not look at that head again (even after Jay closes the gate: he merges it himself). A new
   head needs a new review and is a new candidate. Two cases are not holds because they change by themselves:
   CI still running and GitHub still computing mergeability (looked at again after a minute), and a PR head that
   differs from the reviewed head (the poll sends the ticket back to review).
8. **Audit**: ticket events `pipeline.auto_merged`, `pipeline.auto_merge_held`, `pipeline.auto_merge_failed`
   (actor `system:auto-merge`), and security events `merge.auto` and `merge.policy` in ccd's event log.

## Alternatives considered

- **A: one-click Merge in Needs Jay.** Every project `owner`; Jay's click (with Developer Unlock) runs the merge.
  Simplest and safest, but Jay clicks for a one-line docs fix and the spec's "merge without Jay when clean" is gone.
- **B (chosen): opt-in, ccd runs it.** Narrow, deterministic, auditable, off by default.
- **Let agents keep merging "ungated" tickets** (the old `auto`). Rejected: no path or size check, an agent's
  judgement was the only control, and the merge happened with the agent's credentials.
- **GitHub auto-merge (`--auto`) or branch protection with required checks.** Needs CI on PRs (CC-033) and still
  would not know which files are low-risk.

## Why this option

It keeps the one decision that matters (is this change safe to merge unseen) in a small pure function with an
allowlist, so it can be tested with plain data and read in one sitting; the allowlist is the part Jay reviews. It
fails closed: any unknown value, missing field, odd path, unknown CI state or switch error means "not low-risk"
or "stopped". It is switched on by Jay, per machine, and one file stops it at once.

## Consequences

- ccd now holds a GitHub credential that can merge: the `gh` login of the user running ccd. That login can merge to
  any repository it has access to; ccd's code only ever calls `gh pr merge` for a project whose registry policy is
  `low-risk` and whose github identity is in the registry. A change to ccd's code is how that boundary could break,
  which is why `server/ccd/**` is on the denylist and Jay merges every such PR.
- **How strong the switches are, plainly.** Agents run as the same Linux user as Jay. They can write
  `~/command-center/board/config.json` and the state folder (`auto-merge.stop`), and their `gh` is logged in as Jay.
  So "agents never merge" and "Jay switches auto-merge on" are written rules and review-time checks, not technical
  blocks: an agent could run `gh pr merge` itself or edit the config, and ccd would not stop it. What does hold
  technically is narrower: ccd reads `auto_merge` once at start (a config edit takes effect only when Jay restarts
  ccd), ccd never merges outside the allowlist, and every ccd merge is bound to the reviewed head and logged. Real
  separation would need a second GitHub identity for agents without merge rights (or branch protection), which is
  not built.
- **The reviewer's freshness is self-reported.** ccd checks that the recorded review is an APPROVE at the PR's
  exact head, from a session other than the implementer's. It cannot check that the reviewer really was a fresh
  agent that read the diff; that is what the reviewer says about itself.
- With no CI on PRs, a docs/tests PR can merge with only the reviewer's approval behind it. Wrong tests can merge.
  CC-033 (PR checks) should land before the allowlist grows.
- With `auto_merge` off (the default) nothing changes for Jay except that agents no longer merge and the other
  four projects now open a merge gate where "auto" used to leave none. Tickets that were already READY_TO_MERGE
  with no gate (approved under the old rules) get their merge gate on the next GitHub poll after ccd restarts
  (`Pipeline.sync_pr`), so they appear in Needs Jay instead of sitting outside it.
- A ticket that is READY_TO_MERGE with no gate while the stop file exists simply waits; Jay can merge it by hand.
- If Jay closes a merge gate (`merge:<head>`), ccd treats that head as decided and never opens another gate or
  merges it. A PR that stays pending (CI running, mergeability unknown) for over 30 minutes opens a gate.

## Future considerations

- A PR test workflow (CC-033), then widen the allowlist deliberately, one folder at a time.
- A UI toggle (deliberately not built: the switch is a config file and a stop file).
- Per-project allowlists for other repositories, only after Jay asks for them.

## Amended by CC-080, slice 1 (2026-11-26)

Jay approved the plan (question 224). Every rule below only adds a refusal to `merge_policy.classify`; nothing it
refused before can qualify now, and anything it cannot decide is a hold for Jay, never a merge.

- **Small tickets only** (Jay's Q170 answer): the ticket's shown size must be `small`. Unsized, standard and risky
  tickets are held, and a plan-gate label makes a ticket read as risky.
- **The user check at the reviewed head**, when the ticket's route has one (a UI ticket, already held, or a
  standard or risky one).
- **An authorized base per project** (`merge_policy.BASE`, Command Center: `main`). A project with no entry never
  qualifies; a stacked PR based on another branch is held.
- **Required CI by name** (`merge_policy.REQUIRED_CHECKS`, Command Center: `ci/backend` and `ci/web`, the jobs of
  `.github/workflows/ci.yml`, which runs on every PR to main). Every GitHub Actions run of each pair must be SUCCESS
  at the PR's head. Absent, failed, cancelled, skipped, neutral or unknown holds; a commit status or a check of
  another workflow with the same job name does not count; running waits, then the 30-minute clock opens a gate.
  `merge_policy.ci_state` is unchanged (autonomy and replay use it), and any other check still pending still waits.
- The size and user-check rules live in `ticket_reasons`, which the daemon re-runs after its last await, right
  before `gh pr merge`, so a size raised or a UI label added while `gh pr view` ran holds the merge.

**`auto_merge` must stay off until slice 2 lands.** Slice 1 does not see a PR retargeted after its approval, or
between `gh pr view` and `gh pr merge` (`--match-head-commit` guards only the head), and does not re-read the base
after the merge. Required CI is checked at the PR's head, not against a base that moved since it ran. It guards
ccd's own merge path only: main has no branch protection, and nothing technical stops an agent running
`gh pr merge` itself. Later slices, each its own PR and review with `auto_merge` off throughout: slice 2 retarget
detection and a post-merge target alert; slice 3 a per-project switch in Settings; slice 4 other projects; slice 5
ccd performing Jay's merges and a guard on agents' merges.
