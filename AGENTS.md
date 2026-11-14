# Command Center: rules for agents

Command Center (ccd) is the control plane for Jay's agent fleet on jay-server: a loopback-only daemon in
`server/ccd/` and the browser UI in `web/app/`. These rules apply to every agent, Claude or Codex, working in this
repository. How tickets move between seats is in **[docs/flow/FLOW.md](docs/flow/FLOW.md)**; read it, then your
seat's page in [docs/flow/seats/](docs/flow/seats/).

## Layout

    server/ccd/      the daemon (Python 3.14, standard library first; see server/requirements.txt)
    server/tests/    unittest suite, with a fake herdr that speaks the real protocol
    web/app/         React + TypeScript + Vite UI, served by ccd at /
    policy/          project profiles and Jay's decisions (TOML)
    docs/            API.md, SECURITY.md, ARCHITECTURE.md, decisions, ADRs, runbooks, flow/
    scripts/ launcher/  systemd units, installer, CLIs, the Windows launcher

## Before you push

    cd server && python -m unittest discover -s tests -t .      # the backend suite CI runs
    cd web/app && npm ci && npm run typecheck                    # when you touched web/app

CI (`.github/workflows/ci.yml`) runs both on every PR; `web-e2e.yml` runs the browser tests when `web/app/**` or
`server/ccd/api.py` changes. Never skip, disable or loosen a test to get green.

## Rules that do not bend

- **Loopback only.** ccd binds 127.0.0.1:7777. Never add a public listener, tunnel or TCP bridge to the herdr socket.
- **herdr owns every Claude pane.** ccd does not start, split or supervise agents beyond the exceptions in README.md.
- **No dangerous endpoints.** No API merges, deploys, touches production, secrets, Docker, destructive git or rule
  files. A test asserts the route table exactly; a new route needs its test updated and a reason in the PR.
- **One project registry.** Project names, ticket prefixes and roots live in `server/ccd/registry.py` only.
- **tasks.db changes are additive** (new columns with defaults, new tables) with a numbered migration, a rollback
  runbook in `docs/runbooks/`, and a migration drill.
- **No secrets or customer data** in code, tests, fixtures, tickets, logs or docs. SQLite holds operational metadata only.
- **New and changed API routes** are documented in `docs/API.md` in the same PR.
- **Comments say why**, not what: the bug, constraint or decision (with its ticket or D-number) behind a non-obvious line.

## Protected paths: Jay approves every change (D-007, `policy/projects/commandcenter.toml`)

`server/ccd/**`, `scripts/**`, `launcher/**`, `.github/**`, `policy/**`, `web/app/src/**`, `.claude/**`,
`AGENTS.md`, `CLAUDE.md`. The autonomy engine, broker, `security.py`, `profiles.py`, `merge_policy.py` and agent
permission rules are the rails themselves: never weaken them, and never change your own or another agent's authority.
CI configuration is never changed without Jay's explicit approval.

## Git and pull requests

- One ticket, one branch, one worktree, one PR. Branch names start with the ticket key (`CC-123-short-name`).
- PR title starts with the ticket key; the body lists each acceptance criterion and how it is met.
- Never force-push a shared branch, rewrite main's history, merge, tag or release. Jay merges (ADR 0007's low-risk
  policy is the only exception, and it is off).
- Feature flags stay off unless Jay turns them on: `auto_merge`, `onboarding_groundwork`, `phase2_*`, `chat_start_leads`.

## Who decides

Jay decides anything the project profile, D-005 or D-007 sends to him, every merge, every live deploy, and every
staffing change. Ask with a multiple-choice question (2 or 3 options, one recommended, one-line why) through
`pipeline_cli ask`; see FLOW.md.
