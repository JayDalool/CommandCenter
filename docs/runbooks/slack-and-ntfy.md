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
   For leads' files to upload (Settings → Slack and phone → Files in Slack, below), add the bot scope
   `files:write` the same way and reinstall the app. Without it, a switched-on project's files are listed by name and
   size with a note that Slack has not granted `files:write`.
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

- **Questions:** the reply is the answer (several questions: numbered lines `1. …`, `2. …`). An option's number or
  letter picks it, and several (`1, 3`, `a and c`) pick several. It goes to the task's session, exactly like the
  Answer button. A reply that ends with `?` is Jay's question back, not an answer: it is typed into the task session
  (`Daemon.slack_ask_back`), which answers with `pipeline_cli reply KEY --text …` into the same thread; the questions
  stay open. With no task session running it goes to the project's lead.
- **Claude's own question prompt** (AskUserQuestion) never waits in a pane for Jay (Jay, 2026-11-16).
  `scripts/cc-ask-hook`, a PreToolUse hook that go-live sets in `~/.claude/settings.json`, hands the questions to ccd
  (`POST /api/hooks/ask`). A ticket's task session's questions become the ticket's questions (this DM, and choice
  buttons on the ticket); a project lead's or the CTO's go to its Messages conversation, so they reach Slack as its
  replies do. The agent is told to end its turn and wait, and the answers are typed back into it. Any other Claude
  session, or ccd not answering, keeps Claude's own prompt. Sessions started before go-live pick the hook up when
  they restart.
- **Plans:** a plan waiting for Jay (a risky ticket's, after the technical review) comes as a DM with its summary,
  approach, what it touches, its risk and the technical review. `approve` (or yes, ok, go, lgtm) in that DM's thread
  approves that plan and implementation starts, whatever the scope is (Jay, 2026-11-16). It approves only the plan the
  DM showed: if the plan or the gate changed since, nothing is approved. A plan that would show as [redacted]
  anywhere, or has characters Slack would not show in any of its fields (shown in the DM or not), is approved in
  CommandCenter only. The DM counts the plan's questions and findings, which it does not show. The PR still needs its
  review and Jay's merge.
- **Blockers and UI reviews:** `approve` clears a blocker (`failure`) or accepts a UI review (`ui`) with the scope
  `answers_low_risk` or `all`.
- **CommandCenter and GYST blockers, whatever the scope** (Jay, 2026-11-26, `notify.UNBLOCK_PROJECTS`): the Blocked
  DM takes the blocked card's three steps. `approve` clears the blocker and the task resumes; `fix` (or
  `fix and continue`, or `fix:` with what needs fixing) sends it back to implementation exactly as Fix and continue
  does (with no words, the blocker's recommended action is what Claude is told); `replan:` with why sends it back to
  planning (`Daemon.slack_unblock`). Only on the blocker the DM showed; anything else goes to the lead. The same
  `fix` and `replan` words work on any project whose blockers the scope lets Slack clear. Client projects never.
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

## Files

A lead's message in Messages can carry files (`cc-reply --file`: images, PDF, Markdown or text). Its words reach
Slack as above; its files (Jay, 2026-11-17, "Upload, chosen projects only"):

- **Projects switched on** in Settings → Slack and phone → Files in Slack (off for every project by default; Developer
  Unlock, like the other settings): each file is uploaded into the same thread as the lead's words, as the app.
  A file that fails to upload (no `files:write`, Slack down) is listed by name and size instead, with the reason. So
  is a text or Markdown file that the secret filter (`security.redact`, the one every Slack post goes through) would
  change.
- **Every other project:** each file's name and size, and that it is in CommandCenter → Messages.
- **Never uploaded, whatever the setting says:** SamVision (its licensed WRREB data never leaves the server) and the CTO
  (it works across projects, SamVision's among them) get a count of files only, since a file name can carry an
  address or an MLS number. Client projects (GauzeMate) get "replied" only.
  This is fixed in code (`notify.NO_SLACK_FILES`, `client_projects`); the Settings screen does not offer them and
  ccd refuses them, and checks again on every send.

Slack keeps uploaded files under its own plan's rules (on the free plan, messages and files older than 90 days are
hidden). A file is at most 20 MB in Messages; ccd uploads at most 50 MB.

Set `team_id` (Slack: workspace settings, or the `T…` id in any Slack URL) and turn on two-factor sign-in for
Jay's Slack account: that account can answer agents' questions, approve plans and instruct leads, and with the
scope `all` merge reviewed PRs and deploy. A reply answers only the questions
its message showed, and approves only the gate it showed; if either changed since, nothing is recorded. Leads treat a
`via: "slack"` message as unable to approve gated actions.

Every reply is an event (`notify.slack_reply`) with what it did and its length, never its text. A gate closed from
Slack is recorded with `via: "slack"`.

## Release email (CC-078)

One digest email per live app, to you only, 24 hours before its release window (default Tuesday 22:00 Winnipeg for the
Wednesday 22:00 window), whatever quiet hours say. Three headings: Scheduled this release, Verified in production since
last digest, Held. Every line starts with its ticket key. It is off until you switch it on, and it never deploys anything.

1. Create `~/.config/command-center/mail.env`, mode 0600, owned by the user ccd runs as:

   ```
   MAIL_HOST=smtp.your-provider.example
   # 465 (implicit TLS) or 587 (STARTTLS); nothing else is accepted
   MAIL_PORT=465
   MAIL_USER=...
   # an app password, not your main one
   MAIL_PASSWORD=...
   MAIL_FROM=ccd@your-domain.example
   # exactly one address
   MAIL_TO=you@example.com
   ```

2. Settings > Notifications > Slack and phone: Release email On (Developer Unlock), then Send a test. The row says what is
   missing until the file is usable. A due digest is held, not lost, while the file is wrong: fix it before the window starts.
3. A project gets a digest only while it is marked live (Release window).

Read the ledger: `sqlite3 ccd.db "select value from kv where key='release_mail:<project>'"`. Each row has `state`:

| state | meaning |
|---|---|
| `sending` | written before the SMTP call; a row still `sending` when ccd starts is closed as `failed` + `uncertain` |
| `delivered` | the server accepted the message (250 after DATA); never sent again |
| `failed` | the first failure before DATA is retried once, 300 s or more later and only before the window starts |
| `failed` + `uncertain` | the connection broke during or after DATA, so the message may have gone: never retried, and Jay sees an alert ("may not have been sent"). Check the inbox before sending it by hand |

A failed digest raises the alert `mail:<project>:<window>` until a later digest is delivered or Release email is switched
off, and each failure is a `notify.failed` event. Changing the window within the mailed release sends nothing more; a
window moved to a later day after the mailed one ended gets its own digest.

### Pull an item by Slack (CC-088)

With Slack and Release email on, each delivered digest is followed by one DM per app listing its Scheduled items,
held until quiet hours end (07:00 Wednesday for the Tuesday 22:00 digest). Reply in that message's thread with ticket
IDs only (`GYST-12`, or `pull GYST-12, GYST-13`): all of them must be in that list, or nothing is pulled. ccd answers
in the thread. A pulled item is held for the next release: Go Live leaves it out of what it approves and shows it
under "look at these first" with "pulled from this release: its code still ships until reverted". Its code is on main,
so revert it before Go Live if it must not ship. A pull lasts until the app's next digest. It is refused after the
window ends or once Go Live was sent. Anything else typed there (ok, approve, deploy, add) does nothing.

Each pull, and each urgent live deploy you approve after the digest, sends one correction email ("Correction: <App>
release <time>", threaded under the digest) while Release email is on and the window has not ended; at most 10 per
digest. Ledger fields on the digest's row:

| field | meaning |
|---|---|
| `slack` | the list's post: `state` `posting` (written before the post), `posted` (with `channel` and `ts`), or `failed` (retried once after 300 s; `uncertain` when ccd stopped during the post, never re-posted). A final failure raises `mail:<project>:<window>:slack` ("pulls by Slack unavailable") |
| `pulls` | `{KEY: {at, by: "jay:slack"}}` |
| `corrections` | `[{n, keys, urgent, state, uncertain, attempts, at, sentAt, messageId, error}]`, with the digest's states and retry rules; a failure raises `mail:<project>:<window>:c<n>` |

A message from anyone else in a release list's thread changes nothing; you get one DM saying so (at most one per thread
every 10 minutes). That DM and ccd's answers in a release thread wait while quiet hours last, in `ccd.db` kv
`release_mail:outbox`, and leave it only once Slack took them (a post whose outcome is unknown is not sent again).
A list longer than one post continues in its thread; only the keys Slack showed can be pulled. A list post whose
outcome is unknown is never re-posted: its alert says "may not have been posted".
