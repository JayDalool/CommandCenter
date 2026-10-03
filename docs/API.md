# ccd API (frozen at P2)

Base: `http://127.0.0.1:7777`. Every request needs `Host: 127.0.0.1:7777` (or
`localhost:7777`). Everything except `/api/health` needs `X-CCD-Token: <token>`
(WebSocket may use `?token=` instead, since browsers cannot set its headers).
Actions need `Content-Type: application/json`. A browser `Origin`, if sent,
must be the same origin. Responses are JSON with `Cache-Control: no-store`.

## Reads

| | |
|---|---|
| `GET /api/health` | `{ok, herdr{ok,connected,protocol,lastEventAt,lastSnapshotAt,reconnects,resyncs,eventsReceived,warning}, gh{ok,projects{key:{asOf,error}}}, git, host, seq, uptimeS, version, pid, calls{gh,git,…}, dbBytes, lastPollAges}` — no token |
| `GET /api/state` | full bootstrap: `seq` (the log position this state reflects), `latestSeq`, `agents[]`, `coordinators{samvision,gauzemate,gyst,mfe}`, `projects[]`, `needs[]`, `blocked[]`, `stale[]`, `alerts[]`, `host`, `sources`, `totals`, `herdr_error`, `brief`. Superset of the legacy board snapshot. `503` while warming up |
| `GET /api/activity?limit=100&before=<seq>&kind=&project=` | event history, newest first; `?since=<seq>` returns oldest first |
| `GET /api/agents/{id}/tail?lines=40` | on-demand pane output (1–200 lines). `id` is a pane id (`wE:p2`) or canonical name (`samvision`). Credential-shaped strings redacted; never stored |

Agent: `{id, agent_name, project, role (coordinator|lane|command-center|other), status (idle|working|blocked|done|unknown), live, cwd, workspace, session_id, blockedSinceMs, blockedForMin, context: null}`.
`context` is the deferred token meter: always `null`, rendered as `—`.

## Live events

`WS /api/events?since=<seq>`

- no `since` → `{"type":"hello","seq":N}`, then live events
- `since` inside the retained log → every event after it, in order, then `{"type":"replay_done","seq":N}`, then live
- `since` outside the log, or a client that falls behind → `{"type":"events_lost","seq":N}`: refetch `/api/state`, reconnect with its `seq`
- every 20 s idle: `{"type":"ping","seq":N}`
- events: `{"type":"event","event":{seq, at, source, kind, severity, project, agentId, ref, text, data}}`

Kinds: `agent.started|exited|state_changed|blocked`, `pr.opened|closed|ci_changed`,
`ci.main_changed`, `task.stage_changed`, `jay.action_required`,
`alert.raised|cleared`, `host.container_down|oom_kill`,
`daemon.started|stopped|herdr_connected|herdr_lost|github_failed|github_recovered`,
`action.answer|focus|ack|dispatch|failed`.

Client recipe: `GET /api/state` → keep `{state, seq}` → `WS ?since=seq` →
apply events; on `events_lost` or disconnect, repeat.

## Actions (the complete list)

| | body | rule |
|---|---|---|
| `POST /api/action/answer` | `{agentId, text}` | agent must be **blocked** right now (re-checked against herdr); text is 1–2000 printable chars, one line. Typed + Enter |
| `POST /api/action/focus` | `{agentId}` | `herdr agent focus` |
| `POST /api/action/ack` | `{alertId}` | acknowledge an active alert |
| `POST /api/action/dispatch` | `{project, taskId, verb, note?}` | coordinators only (`samvision`, `gauzemate`); canonical name only; idle/done only; verb ∈ plan, implement, review, verify, continue, stop; the dispatch skill's message and non-authorisation preamble verbatim |

Every action is written to the event log before it runs (an answer's text is
not stored, only its length). Errors: `400` bad input, `401` token, `403`
host/origin, `404` unknown target, `409` wrong state, `415` not JSON, `429`
too fast, `502` herdr refused, `503` herdr unreachable.

**Not in the API, by design:** merge, deploy, production commands, `--apply`,
secrets, Docker, destructive git, worktree removal, config or rule changes,
issue creation, starting or stopping agents.
