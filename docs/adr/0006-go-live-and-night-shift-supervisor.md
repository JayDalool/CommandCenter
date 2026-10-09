# ADR 0006 — Go Live prepares only; the night-shift supervisor has a hard stop

Date: 2026-10-09 · Status: accepted (Jay's decision, option A) · Tickets: CC-029 (review of PR #22)

## Context

Night shift (a coordinator Claude works a project's tickets while Jay is away) and Go Live (one press that
starts the morning deploy) were added with two features that type into a Claude pane without Jay watching:

- **Go Live** first sent a message saying "Authorized by this message: this one deploy", so a Command Center
  message was a deploy order. Jay's global rule is that a message from command-center never authorizes a
  merge, deploy, production step, `--apply`, secret access or rule change.
- **The supervisor** reminds an idle coordinator to continue. It counted "seen working" as progress, counted a
  reminder even when it was not delivered, and had no upper limit, so it could remind for ever and, in the
  morning, type a line and Enter into a draft Jay was writing in the same pane.

## Decision

1. **Go Live prepares only.** `POST /api/go-live` (since moved to `POST /api/jay/go-live`) (Jay + Developer Unlock) approves the live-deploy gates
   of the tickets the confirm box listed that are still open (any others: `skipped`) and sends one fixed message (`daemon.GO_LIVE_TEMPLATE`) asking the idle coordinator to
   PREPARE the deploy by the repository's runbook: steps, migrations, checks, rollback plan, saved to
   `~/command-center/deploys/<project>/` — and then wait. The message says Jay will confirm the deploy himself in
   that pane and lists what is not authorized. ccd runs no deploy and sends no deploy order.
2. **Go Live is guarded on the server**, not only by the button: 409 while the project's night shift runs, within
   30 minutes of the last Go Live, and while the last one is unfinished (a ticket it approved has no `deployed`
   record yet, for at most 12 hours). Every check that can refuse runs before the message is sent; after it, a
   ticket that cannot be approved comes back in `errors` and does not stop the others.
3. **The confirm box shows what Go Live does**: the tickets it approves, and merged tickets that are unverified
   or wait on a UI review (`goLive` in `GET /api/night-shift`). The press sends those keys and nothing else is
   approved: a gate that opened after the page loaded stays open for Jay.
   **What the approval is.** A gate Go Live confirms is a full live-deploy approval in the pipeline: afterwards any
   agent may record `deployed --env live` for that ticket. That the deploy waits for Jay's confirmation in the
   coordinator's pane is enforced by the text of the message, not by ccd. What ccd adds is a distinct record:
   `approvedBy: "jay:go-live"` and the event "approved for a prepared deploy (Jay confirms in the pane)".
4. **The supervisor has a hard stop.** At most 6 reminders per shift and a morning cutoff (07:00 local, set by
   `CCD_NIGHT_CUTOFF`), whatever the coordinator does. Progress is only a ticket or report change; "working" is
   not progress. A reminder counts only after it was delivered to an idle pane **whose input line is empty**:
   herdr "idle" only means ready for input, and `agent.prompt` pastes and presses Enter, so before each reminder
   ccd reads the pane's text and skips (without counting) unless Claude's prompt line is plainly empty. That is a
   best-effort check on screen text: a prompt it cannot parse is skipped, but a draft it misreads, or typed in the
   moments between the read and the paste, can still be submitted. The cutoff and the 6-reminder cap bound it. The reminder text says whether a
   report exists. With herdr down, the cutoff still ends the shift. Ending the shift at the cutoff types nothing.
5. **End night shift sends the message only**, never Esc: an interrupt can leave a half-finished repository
   operation.

## Alternatives considered

- **Go Live deploys** (what was built): one press, but a Command Center message becomes a deploy order, against
  Jay's rule. Rejected by Jay.
- **No Go Live at all**: Jay approves each deploy gate by hand. Safe, but slower, and nothing prepares the runbook
  and rollback plan for him to read before he confirms.
- **Supervisor without a cutoff, only "no progress"**: a coordinator that changes a ticket after every reminder
  would still be reminded all night and into the morning. The two hard limits are independent of its behaviour.
- **Esc before the stop message**: kept Claude from finishing its step, and can interrupt a git or build step.

## Consequences

- The message itself orders no deploy and asks Claude to wait for Jay in the pane. That wait is a convention
  carried by the message text: the approval Go Live records would let an agent record a live deploy, and ccd
  cannot check what Jay said in the pane. The per-ticket deploy button had the same gap; see the CC-034 update below.
- Go Live can be refused for up to 12 hours after a press if the coordinator never records the deploy. Jay can
  still deploy by hand; a later Go Live needs that record (or the 12 hours) first.
- A long, quiet night can end at the cutoff with work left. The morning report says what is left.
- The seam is a constant message plus approvals; nothing in ccd learns Codex or Claude commands.

## Future considerations

- A per-project cutoff or reminder limit in the registry, if one global value stops fitting.
- Recording the plan file path on the ticket so the Dashboard can link to it.
- `Pipeline.held` follows direct `blocks` relations only; making it transitive is a separate decision.

## Update 2026-10-09 (CC-034)

The per-ticket deploy gate now follows the same rule. The button is **Approve live deploy** (`GateCard.tsx`; WorkPanel
uses the same path). It is still a real live-deploy approval, but it is marked `approvedBy: "jay:gate"` with the event
"approved for a prepared deploy (Jay confirms in the pane)", and the message typed into the task session
(`daemon.GATE_DEPLOY_TEMPLATE`) asks Claude to PREPARE (steps, migrations, checks, rollback) and wait for Jay to confirm in
the pane. "Deploy it now" is gone. As with Go Live, the wait rests on the message text only: `deployed` checks just
`approvedAt`. The plan stays in the pane; it is not saved to a file.
