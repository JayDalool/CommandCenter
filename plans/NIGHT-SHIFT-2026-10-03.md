# Night shift — 2026-10-02 22:56 → 2026-10-03 ~03:45 CDT

## Attempted and completed

| unit | result |
|---|---|
| P4B-3 ticket backend | done — tasks.db, migrations, audit, API, automation, needs merge (70df094) |
| review of P4B-3 (fresh Opus) | REQUEST CHANGES, 8 findings → all fixed (dc0ddf0) |
| P4B-8 server data | top processes, containers, Claude count, worktrees in state (9b6a239) |
| P4B-1/2/4/5/6/7/8/9/10 UI | done in one new app (e202509) |
| review of UI (fresh Opus) | REQUEST CHANGES, 6 findings → all fixed (12f0799) |
| P4B-11 migration preview | done, read-only; real-data run reported in P4B-RESULT |
| docs | ARCHITECTURE, API, SECURITY, ADR 0001–0003 (65e992d) |
| dev preview | `scripts/dev-ccd.py`, running as `cc-dev-preview` on 127.0.0.1:7788 |
| Windows launcher | `scripts/windows/CommandCenter.ps1` (not used yet) |
| PR | draft #1, not merged |

## Failed / not done

- **No browser verification.** Chrome/Playwright on jay-server were off-limits; the UI was checked with jsdom component tests and HTTP smoke only. First visual check is Jay's (UI_TESTS).
- Agent self-report transitions ("planner starts", "plan accepted", "verification complete") are not automatic: there is no deterministic signal for them yet. Dispatch acceptance covers plan/implement; the rest are manual or via the API with `X-CCD-Actor`.
- Migration not applied (by rule). Tauri not started (by rule).
- Frontend landed as one large commit (new app); review happened on it as a unit.

## Commits (branch p4b)

70df094 ticket system · dc0ddf0 review fixes · 9b6a239 server data · e202509 frontend · 65e992d docs · 12f0799 frontend review fixes · (this commit) reports, launcher

## Tests

Backend 118 OK (54 s). Frontend 53 passed, `tsc -b` clean, `vite build` OK (102 KB gzip JS). Dev smoke: create 201, no-token 401, form-encoded 415, foreign Origin 403, CSP present.

## Reviews

Two independent reviews (backend, frontend), both REQUEST CHANGES, all 14 findings fixed with regression tests. Fixes were not re-reviewed by a third pass.

## Architecture changes

- New durable store `tasks.db` (product data) beside `ccd.db` (ops data).
- ccd serves the UI same-origin; Guard requires the token only on `/api/*` and websockets (static files are public code).
- WS token accepted as subprotocol `ccd-token.<t>` (old `?token=` still works).
- herdr allowlist + `workspace.focus`, `tab.focus`. No other control surface added.
- New write routes: `/api/tasks*` (product data only). Route-table test updated.

## Outstanding risks

1. ~~**herdr is down** since 23:41:59 — exited with the SSH session.~~ **Fixed and verified 2026-10-03:** herdr runs as `herdr.service` under systemd --user; Jay's disconnect test passed (MainPID unchanged, NRestarts=0, coordinator panes survived, ccd stayed active). The proposal needed an explicit `Environment=PATH=` (claude lives in `~/.local/bin`, which a user service does not inherit). `scripts/herdr.service` now matches the installed unit.
2. `X-CCD-Actor` is self-asserted; any token holder (incl. agents as `jay` user) can write tickets.
3. Ticket text has no redactor; don't paste secrets/licensed data into tickets.
4. tasks.db needs to join the backup set once real tickets exist.
5. Deploying P4B restarts ccd (resets the soak) and changes the GraphQL query (`mergeable`); watch the first GitHub poll.

## P2 soak (03:36 CDT)

ccd active since 2026-10-02 22:56:08 · NRestarts=0 · MemoryCurrent 36 MB · ~4.7 h elapsed (NOT a 24 h pass) · herdr unreachable (473 reconnects, alert raised) · agents herdr reports: 0 · ccd errors since start: none (10 ERROR lines are from the 22:39–22:40 canary).
