# Command Center V2

The control plane for Jay's agent fleet on jay-server.

```
server/ccd/   the headless daemon: observes herdr, GitHub and the host; owns no agent
server/tests/ unit + integration tests (a fake herdr that speaks the real protocol)
scripts/      systemd user unit, installer, live canary
web/app/      the browser UI (P4B): React + TypeScript + Vite, served by ccd at /
web/prototypes/ P4A design review (historical)
docs/         API, security model, architecture
```

The legacy board in `~/command-center` keeps working throughout. When ccd
answers, it reads ccd's `/api/state` and makes no GitHub or git calls of its
own; when ccd is down, it builds locally exactly as before.

## Rules that do not bend

- **herdr owns every Claude pane.** ccd never starts, splits or supervises an
  agent, and never touches a coordinator's lifecycle. Stopping or restarting ccd
  affects no agent. Three deliberate exceptions (control room, spec §8–§9), all
  through herdr's existing `agent.prompt` on an idle pane: Jay's answers resume
  the ticket's EXISTING task session (`sv-071`), when a ticket closes (a
  pipeline step, or Jay with Developer Unlock) its task session is asked to
  `/exit` once idle, and **Check tasks** (Jay with Developer Unlock) sends a
  project's idle coordinator one fixed message asking it to propose stale
  tasks — only Jay's "Cancel it" cancels one; **Night shift** sends each idle
  coordinator the `/night-shift` skill (`server/ccd/skills/night-shift/SKILL.md`):
  work every task that does not wait for Jay end to end, merge only where no gate
  is open (SamVision and GauzeMate: Jay merges), never deploy. ccd then reminds an
  idle night-shift coordinator to continue until its morning report says
  `Status: complete` (or nothing moves after 3 reminders). A coordinator is never a task session.
- **Waiting for Jay is per task.** A task does not start while it, or a task it
  is blocked by, has an open question, plan or blocker for Jay; everything else
  keeps moving (tasks that need a lawyer never hold anything).
- **Loopback only.** ccd binds `127.0.0.1:7777`, fixed in code. No public port,
  no Cloudflare, no Tailscale Serve, and the herdr socket is never bridged to TCP.
  The Windows client will reach it with `ssh -L 7777:127.0.0.1:7777 jay-server`.
  CommandCenter.exe also signs in over that SSH login (`scripts/cc-session`), so nothing is pasted.
- **No dangerous endpoints.** There is no API that merges or deploys, and none
  for production, secrets, Docker, destructive git, or config/rule changes. Merges and deploys
  are done by agents under the pipeline's gates; ccd only records them, and a
  LIVE deploy cannot be recorded before Jay approved it. **Go Live** is a deploy
  API that **prepares only** (`POST /api/go-live`, Jay + Developer Unlock): it
  approves the project's open live-deploy gates and asks its coordinator to
  prepare the deploy (runbook steps, checks, rollback plan) and wait. Jay confirms
  the deploy himself in the coordinator's pane. The message orders no deploy, but
  the approval it records is a full live-deploy approval, so that wait rests on
  the message text, not on ccd (ADR 0006). The per-ticket **Approve live deploy**
  button works the same way: a real live-deploy approval, marked `jay:gate`, and
  a message that asks Claude to prepare and wait for Jay in the pane (the wait
  rests on the message text only). ccd runs no deploy. Terminals, Claude
  input, answers and file writes need a second credential, Developer Unlock
  (once per app session, [docs/SECURITY.md](docs/SECURITY.md)). A test asserts
  the route table exactly. See [docs/API.md](docs/API.md).
- **One project registry.** A project's name, ticket prefix and retired prefixes
  live in `server/ccd/registry.py` and nowhere else. GauzeMate is `GZ`; `GM-*`
  keys are history and keep working. A project with no registry row and no
  explicit prefix can hold no tickets.
- **SQLite holds operational metadata only.** No secrets, transcripts, pane
  output, property or licensed data. See [docs/SECURITY.md](docs/SECURITY.md).

## Run

```
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
../scripts/install-user-unit.sh            # install + start the user service
systemctl --user status ccd                # state
journal: ~/command-center/state/ccd.log    # JSON lines, rotated at 10 MB
```

Configuration comes from the legacy board's `config.json` (one project list
during migration); see `server/config.example.json`. State lives in
`~/command-center/state/ccd.db`; the local API token in
`~/.config/command-center/ccd.token` (0600).

## Test

```
cd server && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -t .
../scripts/ccd-canary.py check|stop-start|degrade|replay <seq>|ws-listen <s>|measure <s>
```

## Web UI

```
cd web/app && npm ci && npm run build      # → web/app/dist, served by ccd at / (same origin)
npm test                                   # vitest: model, stream, controller, components
../../scripts/dev-ccd.py                   # dev ccd on 127.0.0.1:7788 (fake herdr, seeded tickets)
../../scripts/dev-ccd.py --port 7789       # a second preview beside a running one
```

From Windows: `ssh -N -L 7777:127.0.0.1:7777 jay-server`, open
http://127.0.0.1:7777, paste the token (`ssh jay-server cat
.config/command-center/ccd.token | clip`). Tickets live in
`~/command-center/data/tasks.db` — back it up as data.

## Go live with a branch (one step)

```
scripts/go-live.sh                 # backs up tasks.db, switches the live checkout, builds the UI, restarts ccd
scripts/reconcile-cc-ui.py         # dry run: what the control room does to the old CC UI tickets
scripts/reconcile-cc-ui.py --apply
```

`go-live.sh` prints the exact rollback (previous branch + the tasks.db backup) when it finishes.

## Roll back

`scripts/install-user-unit.sh --remove`. The legacy board falls back to local
builds on its own; nothing else depends on ccd yet.

## Deploying the UI

```
scripts/deploy-web.sh        # build → ~/.local/share/command-center/web/releases/<stamp>-<rev>/ → atomic `current` switch
```

ccd serves `~/.local/share/command-center/web/current` when it exists (else
`web/app/dist`), resolving the link per request, so a UI deploy needs no ccd
restart — except the very first, because ccd picks the directory when it
starts: restart ccd once after the first `deploy-web.sh`. Never `npm run build` into the served directory: Vite empties it, and
windows still running the previous build lose their lazy chunks ("Failed to
fetch dynamically imported module"). Each release carries the hashed assets of
the last 3 releases; `index.html` is `Cache-Control: no-cache`, hashed
`/assets/*` are `public, max-age=31536000, immutable`, and a missing asset is a
plain 404 (never the app shell). A window that still hits a missing chunk shows
"Command Center was updated" and reloads once (never over unsaved edits).

