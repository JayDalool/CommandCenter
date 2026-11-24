# How work flows

The one rule set for every ticket in every project Command Center runs. Each project's `AGENTS.md` and `CLAUDE.md`
link here and keep only their own project rules. Jay approved this flow on 2026-11-14 ("How work should flow",
seven decisions). The server side is specified in the flow contract; where a step below says **(flow PR)**, the
command arrives with that change and is refused until then.

Read your seat's page, not all of them: [seats/](seats/).

## The idea in four lines

1. One ticket, one owner at a time. You work only on the ticket and stage you were given.
2. A stage is finished when its result is **written into the ticket** through `pipeline_cli`, never when it is
   said in a chat. The next seat starts from the ticket, not from your memory or session.
3. Finish before you start. A ticket waiting for a review is more important than a new one.
4. Code comments say **why**, so the next investigator and reviewer understand the change without you.

## Nine stages

| # | Stage | Seat | Ends when the ticket has |
|---|---|---|---|
| 1 | Intake | [lead](seats/lead.md) | description, size, priority, due date, at least one acceptance criterion, requirements, parent if any |
| 2 | Investigate | [investigator](seats/investigator.md) | reproduced yes/no/n.a., findings, plan (approach, files affected, risk, tests), "before" screenshots |
| 3 | Technical review | [tech-reviewer](seats/tech-reviewer.md) | APPROVE or SEND_BACK, the blast radius, the tests that must exist |
| 4 | Build | [developer](seats/developer.md) | a PR with the change, its tests, and why-comments; handoff written |
| 5 | User check | [user-reviewer](seats/user-reviewer.md) (+ [design-reviewer](seats/design-reviewer.md) when a screen changes) | every criterion pass/fail on the PR's exact head, "after" screenshots |
| 6 | Code review | [code-reviewer](seats/code-reviewer.md) | APPROVE or REQUEST_CHANGES on the exact head, findings |
| 7 | Merge | Jay (ccd only for CommandCenter low-risk docs/tests, flag off today) | merged to main |
| 8 | Release | [verifier](seats/verifier.md) | deployed (or release-ready) and checked, with evidence |
| 9 | Done | [lead](seats/lead.md) | closing note: what changed, why, how it was checked, docs updated |

The ways back: technical review sends a plan back to Investigate; a failed user check sends the build back to Build;
a code review asking for changes sends it back to Build. Two rounds at most at each of those three stages: the second send-back
blocks the ticket for the lead (and Jay) to decide. For the user check and code review send-backs, round 1 is run by the lead alone: record rework (code review only; a failed user check
already moves the ticket back), send the findings to the same developer, then a fresh user check (where the route has one) and code review on the new head; Jay hears only at ready to merge or blocked after round 2.

## Three sizes

The lead sets the size at intake. The technical reviewer may raise it. Only Jay lowers a `risky`.

| Size | For | Route |
|---|---|---|
| small | wording, a setting, a one-file fix with a test | Intake, Build, Code review, Merge, Release, Done. User check too when the ticket is a UI ticket (`ui` label, needs-ui-review flag or DESIGN type) |
| standard | a feature or a bug across several files | all nine |
| risky | security, sign-in, money, data migration, licensed or personal data, a redesign clients notice | all nine, plus Jay approves the plan after Technical review and approves the release |

A ticket with a plan-gate label (`security`, `migration`, `destructive`, `architecture`, `product-decision`,
`ambiguous`, `financial`, `legal`, `gate:plan`), a SECURITY or LEGAL type, or a needs-Jay or needs-legal flag is risky whatever
was typed. The route decides which stages run; a skipped stage is refused by ccd, never chosen by an agent.

## What a ticket carries

| Part | Written by |
|---|---|
| Description: the problem or request in plain words | lead or Jay |
| Acceptance criteria: up to 20 lines that must be true when it is done | lead or Jay (only Jay edits them after Investigate) |
| Requirements: what must not change, what it depends on | lead |
| Size, parent | lead |
| Priority (urgent, high, medium, low) and due date | lead at intake, and at any stage while the ticket is open; Jay any time. No due date given: the ticket's own, even a past one (it shows overdue and comes first), else 2, 5 or 10 days from intake for small, standard or risky |
| Findings and plan | investigator |
| Blast radius and required tests | tech-reviewer |
| Screenshots: before (investigator), after (user-reviewer) | `pipeline_cli evidence` |
| Criteria results | user-reviewer only |
| Closing note | lead |
| History: who had it, when, what they handed over | ccd, from the event trail |

Never put secrets, tokens, customer data, licensed data or pasted terminal output in a ticket.

## Parents and children

- Two levels only: a parent and its children. A child cannot have children.
- **Children finish first, then the parent.** ccd refuses to close a parent while any child is open.
- When the last child closes and the parent is otherwise finished, the parent waits for its lead's closing note.
  Nothing closes it automatically.
- `blocks` stays for order between tickets that are not parent and child.

## Limits that stop half-finished work

- Per project: admit at most four tickets beyond the backlog. Tickets in review, ready to merge or blocked still
  take a slot. A verified merge waiting only for release no longer takes an engineering slot. Existing work can
  continue when importing or reopening tickets puts the project above four. The cap is on agent
  work only: a new ticket is always made, and its intake (size, criteria, priority) is always saved. While all four
  slots are in use it waits in the backlog, and the lead runs `intake` again when a slot opens to admit it.
- Within those four: at most 2 tickets in Investigate and 2 in Build.
- Finishing first: no `start` and no first `plan` while another ticket in the same project has waited more than
  4 hours in Technical review, User check or Code review with nobody in that seat. Fill that seat instead.
- Stale: 48 hours with no recorded step in stages 2 to 6 marks the ticket stale. The lead moves it, sends it back
  or proposes cancelling it (`pipeline_cli stale`; only Jay cancels).
- Two rounds at most per review stage: the second send-back blocks the ticket. The lead reads the blocker and
  records the next action. For an ordinary fix within the accepted scope, use `rework` and get fresh checks.
  If the assumptions or scope changed, use `replan`. If the lead needs Jay to choose, use `ask` with options
  and a recommendation. Keep the blocker visible until there is a recorded decision or a path forward.

## Work mode: work keeps moving

A lead acts when someone messages it. With **work mode** on for a project (Jay's switch in Settings › Operating
profiles; every project starts off), ccd checks once a minute and reminds the idle lead, at most every 10 minutes,
of the tickets that can move without Jay, in this order: priority, then the earliest due date, then the later stage, then the
oldest. Take them in that order, within the limits above. A ticket that needs Jay: ask or block it, then take the
next one. A ticket in intake flagged needs-Jay is not named; a release-stage ticket is named for verifying only.
The reminder grants nothing; every gate still waits for Jay. It stays quiet while the project is paused,
the night shift runs or a budget is on hold. The reminder puts existing work ahead of more intake and includes
blockers that still need a next step. Work mode rests 2 hours after 3 reminders with no ticket change and stops for
the day after 36 (per Winnipeg day, even if the switch goes off and on).

## Who answers a question

A developer's question goes to the technical reviewer first, then the lead, then Jay. A question for Jay is a
multiple-choice question with 2 or 3 options, one recommended with a one-line why
(`pipeline_cli ask … --option … --recommend N --why "…"`). Jay always also gets "Something else" and "Talk it
through". Asking does not end your session; the answer comes back to it, or to the lead when it has ended.

## Releases

Each project is **Live** or **Not live**; only Jay changes it. Not live: no release window, no banner. Live: one release
a week, Wednesday 10 p.m. America/Winnipeg; merged after noon on release day waits a week; a risky urgent fix needs
Jay's approval to go outside the window. Who runs a deploy does not change: nothing deploys automatically, and a live deploy always waits for Jay. No app is
live today.

## Never, in any seat

- Merge or deploy to production without Jay's recorded approval (his merge, Merge ready or Go Live), run a
  migration on production, or touch secrets.
- Approve, review or user-check work you planned, built or assigned.
- Change your own or another agent's permissions, or create an agent. A lead may propose staffing; Jay decides.
- Mark a stage done that you did not do, or skip one.
- Edit the protected rails without Jay: see the repository's `AGENTS.md`.
- Work on a paused project (GauzeMate today).

## Seats and the pipeline roles

| Seat | `--role` | Page |
|---|---|---|
| lead | `coordinator` | [lead](seats/lead.md) |
| investigator | `planner` | [investigator](seats/investigator.md) |
| tech-reviewer | `tech-reviewer` (flow PR) | [tech-reviewer](seats/tech-reviewer.md) |
| developer | `implementer` | [developer](seats/developer.md) |
| user-reviewer | `user-reviewer` (flow PR) | [user-reviewer](seats/user-reviewer.md) |
| design-reviewer | `design-reviewer` (flow PR) | [design-reviewer](seats/design-reviewer.md) |
| code-reviewer | `reviewer` | [code-reviewer](seats/code-reviewer.md) |
| verifier | `verifier` | [verifier](seats/verifier.md) |

First record yourself in your seat: `python -m ccd.pipeline_cli role KEY --role <role> --model <model>
--session <your session>`. All commands run from `server/` on jay-server. Every write is
recorded as `agent:<role>`. A refused step prints one line saying why and exits 1: read it and do what it says,
never retry the same command unchanged.
