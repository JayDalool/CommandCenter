# P4B RESULT — 2026-10-03 (night shift)

Branch `p4b`, worktree `/srv/server/worktrees/CommandCenter/P4B`, draft PR #1. Live ccd untouched.

**Design:** Studio structure (page titles, quiet 1 px panels, project rail), Operator density (30 px rows, 28 px compact option, hairline tables, mono uppercase micro-headings), Terminal+ personality (graphite with a blue cast, phosphor-sage accent, CRT-amber for anything waiting on Jay, always-on status line). Sans for prose/titles/questions; mono for keys, SHAs, branches, times, metrics, commands, pane ids. Dark first, light designed, system option, reduced motion. Tokens: `web/app/src/styles/tokens.css`.

**Task system:** `server/ccd/tasks.py`, own file `~/command-center/data/tasks.db`, separate from the prunable `ccd.db`. Forward-only migrations (`PRAGMA user_version`). Triggers: no deletes, fixed keys, forward-only counters, append-only audit. ADR 0001.

**Ticket schema:** `task_projects`, `ticket_types`, `tickets` (all requested fields incl. agentRole/PaneId/SessionId, parent, branch, four needs flags, archived, reserved `cycle_id`), `ticket_labels`, `ticket_relations` (blocks/related/duplicates; blocked_by = inverse), `ticket_comments`, `ticket_links` (provider/kind/ref — PRs, legacy IDs, URLs), `ticket_events` (actor, field, from, to, trigger). Keys SV/GM/GYST/MFE/CC-NNN.

**Task API:** `GET/POST /api/tasks`, `GET/PATCH /api/tasks/{key}`, `/context`, `/comments`, `/relations`, `/links`, `GET /api/tasks/import-preview`. Writes need JSON + token; `X-CCD-Actor: agent:<name>` attribution (self-asserted). docs/API.md.

**Task UI:** Table (ID, title, status, priority, project, assignee, updated, PR, flags), Pipeline, Needs Jay, Inbox; filters project/status/priority/type/assignee/label + needs Jay/blocked/has PR/no PR/closed; instant search; large detail pane (inline title, status, priority, assignee human/role/agent, type, branch, labels, flags, description, PR with CI/review/mergeability, agent, dispatch, relations, subtasks, timeline with system events vs notes). N captures in one dialog (project remembered).

**Needs Jay:** one queue = blocked agents → merge-ready PRs → flagged tickets → derived needs (red main, My actions, issue labels). Shown on Overview, Tasks → Needs Jay, top-bar chip, rail badges, project cockpits. Ticket flags reach `/api/state` live.

**Pipeline:** compact rows per status column; Shift+←/→ moves a ticket a step; off-pipeline columns appear when used.

**Agent integration:** `/api/tasks/{key}/context` brief (with non-authorisation line); dispatch accepts existing ticket keys (plan → RESEARCHING, implement → IN_PROGRESS on acceptance); agents map to tickets by pane or `agent:` assignee.

**GitHub linkage:** a PR whose title or branch segment *leads* with a key links automatically; open → IN_REVIEW, approved+green → READY_TO_MERGE (and back if it stops), merged (found via links) → VERIFYING. Never DONE automatically; never undoes a human move; mentions/reverts/look-alikes ignored. GitHub issues not required.

**Workspaces:** herdr workspaces → tabs → real pane rectangles drawn as a map; pane agent/role/model/state/cwd; focus agent/workspace/tab; read-only tail; blocked answer; herdr key hints. ADR 0002.

**Browser Herdr integration:** herdr 0.9.3 researched: `workspace.focus`/`tab.focus` (added to the allowlist), `herdr agent attach <name>` and `herdr` for the interactive session over `ssh -t`; `--remote`/`machine` need a herdr client on Windows (not assumed). Layout changes stay in herdr.

**Future embedded-terminal path:** `WorkspaceTransport` (web/app/src/workspace/transport.ts) — Tauri adds `openTerminal()` = local PTY running `ssh -t jay-server herdr agent attach <name>`. ccd never carries terminal bytes.

**Overview:** five-answer glance strip, Needs Jay, Active agents, Task pipeline, Server health, Recent activity; status line carries source freshness.

**Projects:** cockpit per project: state strip (summary, coordinator, main CI, GitHub freshness, Jay checks, repo), Needs Jay, tickets, PRs, activity, agents, workspace access, branches/worktrees (limit warning, never deletes), handoff.

**Agents:** table (project, agent, role, model for coordinators, state, task, branch, PR, elapsed, last event, pane), inline expansion with Focus, Read tail, Answer, Open workspace, attach command.

**Server:** CPU/RAM/swap/disk/load/uptime meters, herdr, ccd, Claude count, containers, top processes (comm + RSS only), worktrees with warnings, OOM, stale items.

**Activity:** meaningful events, filters ALL/AGENTS/TASKS/PRS/CI/JAY/HOST, project filter, load older.

**Alerts:** severity, source, project, message, since, acknowledge.

**Command palette:** Ctrl+K; projects, agents, workspaces, tasks (exact key wins), PRs, safe actions (new task, focus coordinator, open workspace, console, theme, density, needs queue, import preview). No merge/deploy (tested).

**Offline/reconnect:** last data kept; OFFLINE banner with last update time and retry; status line demotes every source to stale; WS resumes from last seq; `events_lost` → refetch, restart from fresh seq; backoff to 30 s; 45 s silence watchdog; one socket only; stale responses ignored.

**Auth/token handling:** UI served same-origin by ccd with strict CSP; token pasted once, kept in memory + sessionStorage (localStorage only if "remember"); REST header, WS subprotocol; never URL, HTML, logs. ccd checks unchanged. Windows launcher script (tunnel + reconnect + token to clipboard). ADR 0003.

**Tests:** backend 118 (unittest, 54 s) incl. 52 new (numbering, recycling, audit, status, relations, flags, needs aggregation, migrations, import preview, API, WS, automation incl. review regressions, workspaces, static UI, subprotocol auth); frontend 53 (vitest: model, freshness, adapter, token storage, live stream, controller offline/resync/coalescing, DataTable keys, palette, global keys, capture, tasks filters/board/needs, overview, offline banner, status line, workspaces, console). `tsc -b` clean; build 346 KB (102 KB gzip).

**ccd status:** live, active since 2026-10-02 22:56:08 CDT, NRestarts=0, ~35 MB, not restarted; still runs main `e6fced3` (P4B is not deployed).

**Herdr status:** fixed and verified 2026-10-03. herdr had exited with Jay's SSH disconnect at 2026-10-02 23:41:59 CDT (all panes SIGHUP). It now runs as `herdr.service` under systemd --user (enabled, Linger, `Restart=always`); `scripts/herdr.service` is the installed unit. Jay's manual test (~13:40 CDT) PASSED: herdr survived an SSH disconnect with `MainPID` unchanged, `NRestarts=0`, samvision and gauzemate panes survived, ccd stayed active. Confirmed at 13:53 CDT: active/running, MainPID 3984916, started 13:40:43, coordinator panes PIDs 3985123 (samvision) and 3985139 (gauzemate) inside the unit's cgroup. Correction Jay made to the night-shift proposal: an explicit `Environment=PATH=` with `/home/jay/.local/bin` first (without it panes had no `claude`), the literal ExecStart path instead of `%h`, and `Restart=always`. See docs/ARCHITECTURE.md.

**P2 soak:** ~4.7 h at 03:36 CDT, clean for ccd (no errors since start). Not a 24 h pass. herdr down means the agent path is not being exercised.

**Preview URL:** http://127.0.0.1:7788 (dev ccd: fake herdr, canned GitHub, seeded tickets; unit `cc-dev-preview`).

**Windows SSH tunnel command:** `ssh -N -L 7788:127.0.0.1:7788 jay-server` (preview). After deploy: `ssh -N -L 7777:127.0.0.1:7777 jay-server`.

**Migration preview status:** READY (not run against tasks.db). Real sources, read-only: would create 149 (samvision 66, gyst 50, gauzemate 28, mfe 5), update 0, ambiguous 2 (GYST OPS1, VN-009), duplicates 2 (SV-062, SV-042 merged), skipped 3.

**Anything Jay must decide:** see docs/jay/TOMORROW.md — restart herdr (and how), when to deploy P4B, three migration calls.
