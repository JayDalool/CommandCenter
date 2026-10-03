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

- **herdr owns every Claude pane.** ccd never starts, stops, splits, closes or
  supervises an agent. Stopping or restarting ccd affects no agent.
- **Loopback only.** ccd binds `127.0.0.1:7777`, fixed in code. No public port,
  no Cloudflare, no Tailscale Serve, and the herdr socket is never bridged to TCP.
  The Windows client will reach it with `ssh -L 7777:127.0.0.1:7777 jay-server`.
- **No dangerous endpoints.** There is no API for merge, deploy, production,
  secrets, Docker, destructive git, or config/rule changes. A test asserts the
  route table exactly. See [docs/API.md](docs/API.md).
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
```

From Windows: `ssh -N -L 7777:127.0.0.1:7777 jay-server`, open
http://127.0.0.1:7777, paste the token (`ssh jay-server cat
.config/command-center/ccd.token | clip`). Tickets live in
`~/command-center/data/tasks.db` — back it up as data.

## Roll back

`scripts/install-user-unit.sh --remove`. The legacy board falls back to local
builds on its own; nothing else depends on ccd yet.
