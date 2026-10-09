---
description: Night shift — work this repo's Command Center tasks while Jay is away (no deploys, ever)
---
Night shift from Jay via command-center. Jay is away until morning. Work this repository's open tasks in
Command Center, one at a time, under the ticket pipeline — then leave him a morning report.

See the tasks: python -m ccd.pipeline_cli tasks <project>   (and `work <KEY>` for one ticket's state)
Project key: <project> is this repo's Command Center project — samvision, gauzemate, commandcenter, gyst or mfe.

Order of work — always pick the first that applies:
1. Finish work already in progress (IN_PROGRESS): complete it, test it, open or update its PR.
2. Review (IN_REVIEW): a FRESH review of the exact PR head by a reviewer that did not write it (a subagent),
   recorded with: pipeline_cli review <KEY> --role reviewer --session <fresh reviewer session> --verdict … --head <sha>.
   Fix what it finds (rework) and review again.
3. Merge (READY_TO_MERGE) only when Command Center shows NO open gate on the ticket (`work <KEY>`: gate null),
   CI is green on that exact head and the review approved that head. An open merge gate means Jay accepts it in
   the morning — leave it. Never force-push, never merge red CI.
4. Verify merged work (VERIFYING): run the checks on main, then record it:
   pipeline_cli verify <KEY> --role verifier --result pass|fail --evidence "…".
5. Plan, think and research (INBOX, PROPOSED, RESEARCHING): read the code, record a plan with acceptance
   criteria (pipeline_cli plan <KEY> …). A plan that needs Jay waits for his approval; move on.
6. Start new implementation (READY_TO_IMPLEMENT) only if `pipeline_cli start` accepts it. It refuses while
   Jay has an open question, plan or blocker in this project (Jay first) or both lanes are busy: then go
   back to 1–5.

Skip, and leave for Jay: a ticket with an open question or gate, anything needing a lawyer (needs:legal),
anything you would need Jay to decide. If you need an answer, ask once
(pipeline_cli ask <KEY> --role coordinator --question "…") and move to another task — never wait.
If something is broken and you cannot fix it safely, record it: pipeline_cli block <KEY> --role coordinator
--reason "…" (with --what --why --action --impact in plain words).

Never, tonight or any night:
- deploy or go live, to production or anywhere else; no `deployed`, no `deploy-request --env live`.
  Going live happens only when Jay presses Go Live himself.
- touch production data, run migrations against production, use --apply, read or print secrets.
- change rules, CI, branch protection, permissions or this workflow; delete branches or files you did not create.
- work in another repository, or start, duplicate or close another Claude session.
- copy licensed data, records, addresses or secrets into tickets, PRs, notes or reports.

Record every stage change in Command Center as you go (plan, start, review, verify, handoff), so Jay's
Dashboard shows it. When nothing actionable is left — or before your context runs out — write the morning
report to ~/command-center/night-shift/<project>/<YYYY-MM-DD>.md: what moved (ticket → stage, PR, merged or
not), what is waiting for Jay and why, what failed. Then stop and say in one line:
<project> night shift: <n> merged, <n> verified, <n> planned, <n> waiting for Jay.
