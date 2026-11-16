# Slack and ntfy

ccd sends what needs Jay to his phone and reads his Slack replies (`server/ccd/notify.py`). Both are **off** until
Jay switches them on.

## One-time setup

1. Create the Slack workspace, the five private channels (`cto`, `commandcenter`, `samvision`, `gyst`, `mfe`) and the
   app from the manifest in the HQ launch plan. Invite `@CommandCenter` to each channel.
   For each seat to post under its own name and icon (Investigator, Technical reviewer, Developer, the leads),
   add the bot scope `chat:write.customize` (OAuth & Permissions) and reinstall the app. Without it, the app posts
   them under its own name with the seat in bold at the start. ccd reads the scopes from Slack's answers, so no
   restart is needed.
2. On jay-server, write the two tokens to `~/.config/command-center/slack.env` (mode 0600, the plan has the command).
   ccd refuses the file if anyone but its owner can read it.
3. Add Jay's Slack member ID to `~/command-center/board/config.json`:

   ```json
   "notify": {"slack": {"jay_member_id": "U0XXXXXXX", "team_id": "T0XXXXXXX"}}
   ```

   Optional keys under `notify.slack`: `team_id` (ignore every other workspace), `link_base` (where CommandCenter opens
   on Jay's devices; default `http://localhost:7777`, the SSH tunnel), `channels` (project key to channel name),
   `cto_channel`, `client_projects` (default `["gauzemate"]`).
4. ntfy uses the `ntfy_url` already in that config file. Subscribe to its topic in the ntfy app.
5. Restart ccd (`systemctl --user restart ccd`) so it reads the config.

## Switch it on

```sh
cd /srv/server/repos/CommandCenter/server
.venv/bin/python -m ccd.notify_cli on both      # or: on slack / on ntfy
.venv/bin/python -m ccd.notify_cli test         # one DM and one push
.venv/bin/python -m ccd.notify_cli status
```

Other settings: `quiet 22:00 07:00`, `scope answers|answers_low_risk|all`, `summary` (post the summaries now), `off …`.
The same settings are `GET/PUT /api/notify` for the Settings screen.

## What goes where

| Where | What |
|---|---|
| DM to Jay | each new Needs You item: gates, questions, merges, tasks, red main checks, a blocked agent |
| ntfy | the same items, as a title and a link only |
| `#<project>` | one thread per ticket: each seat's step (intake, plan, technical review, build, user check, code review, gates, release) under that seat's name; merged, deployed and done also show in the channel. PR opened/closed and failing checks; the technical summary each morning |
| `#cto` | host and ccd alerts; the owner's summary each morning |

The first tick after start takes the current queue as its baseline instead of sending it; it is in the morning summary.
Quiet hours (22:00 to 07:00 America/Winnipeg by default) hold the DM and the push. Held items that still wait are sent
when quiet hours end. GauzeMate (a client project) carries only IDs and a risk line, and has no channel.

## Replies

ccd reads only messages whose author is `jay_member_id`, never edits or bot messages. In an item's thread:

- **Questions:** the reply is the answer (several questions: numbered lines `1. …`, `2. …`). It goes to the task's
  session, exactly like the Answer button.
- **Plans:** a plan waiting for Jay (a risky ticket's, after the technical review) comes as a DM with its summary,
  approach, what it touches, its risk and the technical review. `approve` (or yes, ok, go, lgtm) in that DM's thread
  approves that plan and implementation starts, whatever the scope is (Jay, 2026-11-16). It approves only the plan the
  DM showed: if the plan or the gate changed since, nothing is approved. A plan that would show as [redacted]
  anywhere, or has characters Slack would not show in any of its fields (shown in the DM or not), is approved in
  CommandCenter only. The DM counts the plan's questions and findings, which it does not show. The PR still needs its
  review and Jay's merge.
- **Blockers and UI reviews:** `approve` clears a blocker (`failure`) or accepts a UI review (`ui`) with the scope
  `answers_low_risk` or `all`.
- **Merges** (scope `all`): the "Ready to merge" DM shows the PR, its head and the review. Only `merge` (or "merge
  it", "merge now") merges that one PR at that head, exactly as the Merge button does (`Daemon.slack_merge` →
  `act_merge`): the lead merges it, and nothing is merged if the head, the review, CI or another gate moved. `ok`,
  `yes` or 👍 merges nothing (ccd says so); other text goes to the lead.
- **Deploys** (scope `all`), two replies (Jay, 2026-11-16: "only deploy if asked to"): `approve` (or `deploy`) on the
  "Deploy approval" DM asks the agent to PREPARE (`daemon.SLACK_DEPLOY_TEMPLATE`). It records its plan with
  `pipeline_cli deploy-plan` (at most 40 lines, nothing the secret filter would show as [redacted], no invisible
  characters, no triple backticks), which comes to the DM as a new message with the whole plan in a code block (no Slack
  formatting applies there) and its line count. Only `deploy` (or "deploy it", "go live", "ship it") there tells it to
  deploy by that plan (`Daemon.slack_deploy`, bound to the plan's digest); `ok`, `yes` or 👍 deploys nothing, and other
  text goes to the lead. A plan that cannot be shown whole in one Slack post gets no go from Slack: reply in its
  thread to ask the agent for a shorter one. A deploy approved from Slack is confirmed only from Slack; if the scope
  was lowered since, set it back to `all` and reply `deploy` again. On a live project the go waits for the release
  window like any live deploy: the plan DM says until when, and a `deploy` reply before then is refused (reply again
  once it opens). Until the go `deployed --result pass` is refused for that ticket. A deploy approved in CommandCenter
  is unchanged: Jay confirms it in the agent's pane.
- The scope is `answers` by default; Jay changes it in Settings → Slack and phone, or `notify_cli scope …`, both
  with Developer Unlock. The gate lists are fixed in code (`notify.PLAN_GATES`, `LOW_RISK_GATES`, `SHIP_GATES`) and
  checked again in the daemon, which also checks the scope for merges and deploys. Client projects never approve.
- **A ticket's thread:** the reply goes to the project's lead, tagged with the ticket. It never answers a
  question or approves a gate: answer a question in the DM it came in (its own thread there).
- **Anything else** goes to the project's lead through Messages (`Daemon.deliver_to_lead`), and the lead's reply comes
  back in the same thread. Outside a thread, a project channel goes to its lead; `#cto` and the DM go to the CTO.

Set `team_id` (Slack: workspace settings, or the `T…` id in any Slack URL) and turn on two-factor sign-in for
Jay's Slack account: that account can answer agents' questions, approve plans and instruct leads, and with the
scope `all` merge reviewed PRs and deploy. A reply answers only the questions
its message showed, and approves only the gate it showed; if either changed since, nothing is recorded. Leads treat a
`via: "slack"` message as unable to approve gated actions.

Every reply is an event (`notify.slack_reply`) with what it did and its length, never its text. A gate closed from
Slack is recorded with `via: "slack"`.
