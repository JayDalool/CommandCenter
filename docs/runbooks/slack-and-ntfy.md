# Slack and ntfy

ccd sends what needs Jay to his phone and reads his Slack replies (`server/ccd/notify.py`). Both are **off** until
Jay switches them on.

## One-time setup

1. Create the Slack workspace, the five private channels (`cto`, `commandcenter`, `samvision`, `gyst`, `mfe`) and the
   app from the manifest in the HQ launch plan. Invite `@CommandCenter` to each channel.
2. On jay-server, write the two tokens to `~/.config/command-center/slack.env` (mode 0600, the plan has the command).
   ccd refuses the file if anyone but its owner can read it.
3. Add Jay's Slack member ID to `~/command-center/board/config.json`:

   ```json
   "notify": {"slack": {"jay_member_id": "U0XXXXXXX"}}
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

Other settings: `quiet 22:00 07:00`, `scope answers|answers_low_risk`, `summary` (post the summaries now), `off …`.
The same settings are `GET/PUT /api/notify` for the Settings screen.

## What goes where

| Where | What |
|---|---|
| DM to Jay | each new Needs You item: gates, questions, merges, tasks, red main checks, a blocked agent |
| ntfy | the same items, as a title and a link only |
| `#<project>` | PR opened/closed, failing checks, merges, deploys; the technical summary each morning |
| `#cto` | host and ccd alerts; the owner's summary each morning |

The first tick after start takes the current queue as its baseline instead of sending it; it is in the morning summary.
Quiet hours (22:00 to 07:00 America/Winnipeg by default) hold the DM and the push. Held items that still wait are sent
when quiet hours end. GauzeMate (a client project) carries only IDs and a risk line, and has no channel.

## Replies

ccd reads only messages whose author is `jay_member_id`, never edits or bot messages. In an item's thread:

- **Questions:** the reply is the answer (several questions: numbered lines `1. …`, `2. …`). It goes to the task's
  session, exactly like the Answer button.
- **Gates:** `approve` (or yes, ok, go, lgtm) closes a gate only if it is a blocker (`failure`) or a UI review (`ui`),
  and only while the scope is `answers_low_risk`. This list is fixed in code (`notify.SLACK_GATES`) and checked again
  in `Daemon.slack_confirm`. Plans, merges and deploys are approved in CommandCenter.
- **Anything else** goes to the project's lead through Messages (`Daemon.deliver_to_lead`), and the lead's reply comes
  back in the same thread. Outside a thread, a project channel goes to its lead; `#cto` and the DM go to the CTO.

Every reply is an event (`notify.slack_reply`) with what it did and its length, never its text. A gate closed from
Slack is recorded with `via: "slack"`.
