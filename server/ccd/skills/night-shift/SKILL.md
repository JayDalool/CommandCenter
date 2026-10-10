---
name: night-shift
description: Night shift — work this repo's Command Center tasks end to end while Jay is away; never deploys. Run only when Jay asks (/night-shift or Command Center's Night shift button).
disable-model-invocation: true
---
Night shift from Jay via command-center. Jay is away. Keep working this repository's open tasks in Command Center
until nothing is left that can move without him, then leave a morning report he can approve as one release batch.

Project key: <project> is this repo's Command Center project — samvision, gauzemate, commandcenter, gyst or mfe.
Tasks: python -m ccd.pipeline_cli tasks <project>      One task's state: python -m ccd.pipeline_cli work <KEY>

HOW you do each step is this repo's own workflow: AGENTS.md, CLAUDE.md and its pipeline agents (planner,
implementer, reviewer, verifier) win over anything here. This file says WHAT to work on, in which order, and
what is never allowed.

## 1. Sort the tasks

For every open task decide:
- WAITS FOR JAY — it has an open question, a plan waiting for his approval or a blocker only he can clear, or
  it is blocked by a task that does (`pipeline_cli start` refuses it), or it needs a lawyer (needs:legal).
  Leave it. Never answer, approve or work around Jay's decision yourself.
- FREE — everything else. Work these.

## 2. Work free tasks end to end, in this order

1. Finish work in progress (IN_PROGRESS): complete it, test it, open or update its PR.
2. Review (IN_REVIEW): a FRESH reviewer that did not write it, on the exact PR head; record it with
   pipeline_cli review <KEY> --role reviewer --session <fresh reviewer session> --verdict … --head <sha>.
   Fix what it finds (rework) and review again.
3. Merge (READY_TO_MERGE) only when `work <KEY>` shows gate null, CI is green on that exact head and the review
   approved that head. An open merge gate is Jay's: leave it. SamVision and GauzeMate: Jay merges every PR —
   take them to Ready to Merge and stop there.
4. Verify merged work (VERIFYING) on main and record it: pipeline_cli verify <KEY> --role verifier …
5. Plan (INBOX, PROPOSED, RESEARCHING): investigate the code, record a plan with acceptance criteria
   (pipeline_cli plan <KEY> …). A plan that needs Jay waits for him; move on.
6. Start (READY_TO_IMPLEMENT) when `pipeline_cli start` accepts it — at most 2 lanes in this project, each in its
   own worktree. One concern per PR. Then back to 1.

Need an answer? Ask once (pipeline_cli ask <KEY> --role coordinator --question "…") and take another task.
Broken and not safely fixable? pipeline_cli block <KEY> --role coordinator --reason "…" --what … --why …
--action … --impact … in plain words. Record every stage change as you go, so Jay's Dashboard shows it.

## 3. Nothing free? Look for showstoppers — only showstoppers

Walk through the app's main workflows as its real user would (read the code, run the tests, run it locally).
A finding counts only if it is one of:
- data loss, corruption or wrong data saved
- a security or privacy hole (auth, tenant isolation, secrets, licensed data leaving where it may be)
- a crash, outage or a core flow that cannot be completed
- wrong numbers or results in a core flow
- a broken deploy, backup or rollback path
and you can show it: reproduction steps or a failing test. Not findings: style, naming, refactors, small UX polish,
missing tests for non-critical code, "might happen" without a realistic path. At most 3 per night. Record each as
an Inbox task: pipeline_cli add <project> --role coordinator --label night-finding --title "…" --note "<evidence>". Do not fix findings tonight; Jay triages them.

## Never, tonight or any night

- deploy or go live, anywhere; no `deployed`, no `deploy-request --env live`. Jay's Go Live and Approve live deploy only ask for a prepared deploy, and he confirms it himself.
- touch production data, run migrations against production, use --apply, read or print secrets.
- merge where a gate is open, merge red CI, force-push, rewrite history, delete branches or files you did not create.
- change rules, CI, branch protection, permissions or this workflow.
- work in another repository, or start, duplicate or close another Claude session.
- copy licensed data, records, addresses or secrets into tasks, PRs, notes or reports.

## Morning report — a release candidate

Keep ~/command-center/night-shift/<project>/<YYYY-MM-DD>.md up to date as you go (the date the shift started).
Its FIRST line is exactly one of:
  Status: working     — you are still going
  Status: complete    — nothing free is left (everything open waits for Jay, or there is nothing open)
Command Center reads that line: while it says working and you go idle, it reminds you to continue.

Then, in plain words:
1. Ready to deploy — every PR merged to main since the last deploy: ticket, PR, one line of what changed, and
   SAFE (no visible change, covered by tests) or TEST AFTER DEPLOY with 2–3 exact steps Jay runs right after.
2. Migrations in this batch: none, or which, and whether each can be undone.
3. Rollback: the version live now and the exact rollback command from this repo's deploy runbook.
4. Waiting for Jay — merges to accept, questions, plan approvals, blockers — each with its ticket.
5. Night findings (showstoppers only), with evidence.
6. What failed or was left half done, and why.
End with one line: <project> night shift: <n> merged, <n> ready to merge, <n> verified, <n> planned, <n> waiting for Jay.
