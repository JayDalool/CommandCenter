# Project lead automation rules

**Review copy · November 24, 2026**

The first rollout is implemented in the local CommandCenter working tree.
The later rules record the agreed direction for review before implementation
and activation. CommandCenter's GitHub `main` and the local base both point to
`9718009`. The first rollout is uncommitted, unpushed and undeployed.

| Status | Rules |
| --- | --- |
| Implemented locally | Four engineering slots per project, blocker triage, clearer Slack updates and target-aware PR tracking |
| Planned | Slack and Messages approvals, reviewed auto-merge, lead context reset, weekly release emails and deployment, CTO access |

## Implemented locally

### Four slots per project

Each project gets four engineering slots. Work in investigation, build, review,
ready to merge, blocked, or waiting for a decision uses a slot. A merged ticket
with passing verification and only release work left frees its engineering slot.
Its deployment still belongs on the release list.

### Blocked work

When Work Mode is enabled, prioritize work already admitted and remind the
lead about blockers that still need a next step. The lead records the next
action, reworks an in-scope fix, replans changed scope, or sends Jay a specific
decision with a recommendation. A blocked ticket keeps its slot. A
project that starts over capacity can finish existing work as usual.

### Slack ticket updates and stacked PRs

Ticket threads keep the seat labels. Handoffs show completed work, the next
step and any blocker. User checks show what was checked. A merged PR advances a
ticket only when its target matches the configured project branch. A linked
stacked PR remains visible as related work. A merge with an unknown target
cannot advance the ticket.

## Planned rules

### Lead communication and routine intake

GYST and CommandCenter should accept a clear feature request from Jay in Slack
or Messages, record criteria and start when the project has capacity. Ask
about decisions that materially change scope or risk. Keep seat updates in
the ticket thread. Send direct answers to the message they answer. When Jay
needs to decide, state the decision, the recommendation and what approval
authorizes.

### Approvals and reviewed merges

Use one decision record for Slack and Messages. Match the authenticated owner
reply to one displayed decision version with its project, ticket, action and
subject. An ambiguous reply asks for the exact decision. A stale reply points
to its replacement. A duplicate reply returns the existing record. Treat
approval, handoff and completed execution as distinct events.

- GYST and CommandCenter accept Jay's plan approval in Slack or Messages,
  including risky plans that can be shown safely in the conversation.
- SamVision and MFE accept routine decisions in either conversation. Risky
  plans require approval in CommandCenter with the full review evidence.
- For the first expansion of auto-merge, a ticket must be sized small and
  independently assessed as low risk. The plan must be accepted, any review
  send-back must be resolved, and every required decision must be recorded
  against the current plan or revision. Any open owner gate, unanswered
  required question, or unmet project requirement holds the merge.
- Use a project-specific allowlist of eligible change paths. Exclude protected
  paths, changes to policy or authority, and any PR whose scope or risk is
  unknown. CommandCenter's exclusions include the full protected-path list in
  AGENTS.md, including `server/ccd/**`, `policy/**`, and agent rules. Keep Jay's
  explicit approval for protected changes. Apply the same principle to GYST's
  repository rules and personal-data boundaries.
- Require independent code and user checks on the exact delivery PR head,
  fresh passing required CI, and the authorized target. A missing required
  check or a changed head or target holds the merge until revalidated.
- The enabling PR must align AGENTS.md, the project profile and the applicable
  merge policy. Jay approves that PR under the current rules. The new authority
  applies only after the approved change lands.
- Gate release eligibility independently of the merge. Keep SamVision and MFE's
  stricter release policy, including client impact and migration checks.

Before enabling, replay a stale approval, a duplicate reply, an ambiguous
reply, a stacked PR merge, a retargeted PR, a PR with no checks, and a new
commit between approval and merge. Check that GYST's repository rules and the
effective CommandCenter policy agree with the selected merge authority.

### Lead context reset

Record the closing note, evidence links and any unfinished handoff before
reset. Use a fresh task session when possible. For a shared lead session,
attempt reset only when the lead has no unsaved work, no draft input and no
pending Messages delivery. The scheduled reset must survive a restart and
must run at most once for a given completed task. Keep ticket records and
conversation history available to rebuild context. If the guards still
prevent reset after 24 hours, tell Jay once which guard is holding it and keep
the reset pending. The 24-hour escalation is proposed for review.

### Weekly release email

Send Jay one email per live app 24 hours before its configured release window.
Include changes scheduled for that release and changes verified in production
since the previous digest under separate headings. Keep held items explicit.
Use the actual release window's timezone when calculating the send time.
Deduplicate by app and window, and record the mail delivery result.

Use the emailed list as the normal release manifest. Give Jay an authenticated
**Hold from this release** control in CommandCenter with a link from the
email. Binding the hold to the app, release window and item keeps it from
affecting a later release. Record the hold, remove the item from that release,
and send a correction for withdrawals or urgent additions. Verify scheduling,
deduplication and corrections across restarts, window changes and failed sends.

### Automatic production release

Make unattended production release a separate owner decision from the email
and from merge authority. The email ticket follows today's Go Live rules. A
separately approved rollout can allow eligible GYST and CommandCenter releases
at the weekly window once health checks and rollback are configured and
rehearsed. The enabling PR must reconcile the Go Live and owner-approval rules.
Verify eligibility against the release manifest, record the actual outcome
and use the project's runbook to stop or roll back on failure.

### CTO access

For an approved maintenance action, Jay defines the host, operation and
limits. The CTO may decide when the approved conditions are met and execute
within the grant. Installing or changing a recurring timer, adding a host or
expanding the cleanup scope needs a separate decision from Jay. Log the
operation and its result.

Start app access with read-only account counts, defined active-user counts,
and service health for each connected owned app. Show which apps answered
and which could not be checked. Label a cross-app sum as accounts unless
there is reliable identity resolution. Report GYST's single-user status
separately.

Prepare name lookup as a later decision. Require authorization per app and
check Jay's identity in a private, authenticated CommandCenter view. Keep
lookup requests and results out of Slack and shared channels. Record who
made the query, which app was checked and the outcome category in the audit
trail. Keep names, raw query text and matched records out of the audit trail.

## Recommended ticket sequence

Use five separately scoped tickets. Keep the existing local rollout as its
own review item. Queue the tickets and admit them under the four-slot cap.

1. Automatic lead context reset, including the 24-hour escalation.
2. Weekly release email and owner hold control under the current release rules.
3. CTO read-only app counts and health. Review name lookup and server action
   grants separately.
4. Decision-bound Slack and Messages approvals and reviewed merge authority.
   Use two sequential tickets if routing and merge authority cannot be reviewed
   independently in one PR.
5. Automatic production release, after the email and manifest are verified and
   Jay approves the separate release authority.

Use Codex as an independent reviewer for merge authority and automatic release
when Codex did not implement the change. Otherwise use Claude or another
independent reviewer. Jay approves protected changes and grants.

## Independent review request

Please review the rules against the current repository behavior. Return your
top findings by severity, with code or policy references and a concrete
change or test for each. Focus on these questions.

1. Can a fifth ticket enter through any supported path? Can blocker triage or
   handing work to the weekly release queue lose ownership?
2. Can a stacked, retargeted or outdated PR still advance a ticket or qualify
   for automatic merge? Are review, owner authorization and execution
   represented independently?
3. Can an approval in Slack or Messages be replayed, matched to the wrong
   decision, or applied after the subject changes?
4. Can an automatic reset discard work in a shared lead session? Can the
   release email and the production manifest diverge?
5. Do CTO grants cover the requested operational and app questions while
   keeping each app's authorization and data boundaries enforceable?
