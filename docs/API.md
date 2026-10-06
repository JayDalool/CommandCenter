# ccd API (P2 surface, extended in P4B)

Base: `http://127.0.0.1:7777`. Every request needs `Host: 127.0.0.1:7777` (or
`localhost:7777`). Everything except `/api/health` needs `X-CCD-Token: <token>`
(the WebSocket may instead offer it as a subprotocol, `ccd-token.<token>` next to
`ccd.v1` — what the UI does — or, for older clients, `?token=`). Every write
(POST/PATCH) needs `Content-Type: application/json`. A browser `Origin`, if sent,
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

P4B additions to `/api/state`: `workspaces[]` (herdr workspaces → tabs → panes
with `rect`, agent name, role, status, project, cwd — never terminal titles),
`worktrees{project: [paths]}`, `host.procs[]` (pid, comm, RSS MB — never command
lines), `host.containers[]`, `host.claudeCount`, `sources.tasks`,
`totals.tickets{status: n}`, PR rows gain `review`, `mergeable`, `branch`,
`updatedAt`, and `needs[]` gains `kind: "ticket"` items (`ref` = key, `flags`,
`status`, `since`).

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
`action.answer|focus|ack|dispatch|failed`,
`task.created|updated|commented` (ref = ticket key; data.kind = field).

Client recipe: `GET /api/state` → keep `{state, seq}` → `WS ?since=seq` →
apply events; on `events_lost` or disconnect, repeat.

## Actions (the complete list)

| | body | rule |
|---|---|---|
| `POST /api/action/answer` | `{agentId, text}` | agent must be **blocked** right now (re-checked against herdr); text is 1–2000 printable chars, one line. Typed + Enter |
| `POST /api/action/focus` | `{agentId}` or `{workspaceId}` or `{tabId}` | herdr `agent.focus` / `workspace.focus` / `tab.focus`; changes no layout |
| `POST /api/action/ack` | `{alertId}` | acknowledge an active alert |
| `POST /api/action/dispatch` | `{project, taskId, verb, note?}` | `taskId` may also be an existing ticket key of that project (then plan→RESEARCHING, implement→IN_PROGRESS when accepted); coordinators only (`samvision`, `gauzemate`); canonical name only; idle/done only; verb ∈ plan, implement, review, verify, continue, stop; the dispatch skill's message and non-authorisation preamble verbatim |

Every action is written to the event log before it runs (an answer's text is
not stored, only its length). Errors: `400` bad input, `401` token, `403`
host/origin, `404` unknown target, `409` wrong state, `415` not JSON, `429`
too fast, `502` herdr refused, `503` herdr unreachable.

**Not in the API, by design:** merge, deploy, production commands, `--apply`,
secrets, Docker, destructive git, worktree removal, config or rule changes,
issue creation, starting or stopping agents.


## Tickets (P4B)

| | |
|---|---|
| `GET /api/tasks?project=&archived=1` | `{tickets[], projects[{key,name,prefix,nextNumber,legacyPrefixes[]}], meta{statuses, offPipeline, priorities, types, roles, flags, relationKinds, schemaVersion}, seq}`. Tickets are compact (no description). `prefix` is the live one (GauzeMate: `GZ`); `legacyPrefixes` are retired ones whose keys still resolve (`GM`) |
| `GET /api/development?project=` | `{rows[], seq, gitAsOf, stages[], notes[]}`. One row per ticket with development work or in flight: `{key, project, title, status, branch{name,evidence,exists,commits,head,at,countOk}, prs[], pr, commits, ci, review, merge, verify, deploy, roles{planner|implementer|reviewer|verifier: {model,at}}, pipelineReview{verdict,head}|null}`; `roles` holds only recorded roles (`{}` when none). Associations use strong evidence only (see ARCHITECTURE.md); `deploy` is always `null` because ccd observes no deployments |
| `POST /api/tasks` | `{project, title, description?, status?, priority?, type?, assignee?, agentRole?, parent?, branch?, labels?, flags?, needs_jay?…, dueAt?, estimate?}` → 201 ticket. Anything else is 400 |
| `GET /api/tasks/import-preview` | read-only migration preview (see ARCHITECTURE.md) |
| `GET /api/tasks/{key}` | ticket + `relations{blocks, blocked_by, related, duplicates, duplicated_by}`, `subtaskList`, `links`, `comments`, `timeline` (audit rows: actor, kind, field, from, to, trigger) |
| `PATCH /api/tasks/{key}` | any of the create fields plus `archived`, `agentPaneId`, `agentSessionId`; `labels` replaces the set; flags as booleans or `flags{needs_x: bool}` |
| `GET /api/tasks/{key}/context` | `{ticket, parent, brief, coordinator, dispatchable}` — the agent brief |
| `POST /api/tasks/{key}/comments` | `{body}` (multi-line allowed, ≤ 20 000 chars) |
| `POST /api/tasks/{key}/relations` | `{kind: blocks|blocked_by|related|duplicates, target, remove?}` |
| `POST /api/tasks/{key}/links` | `{provider: github|legacy|url, kind: pr|issue|legacy_id|commit|url, ref, url?, title?, remove?}` |

Assignee strings: `jay`, `role:COORDINATOR|PLANNER|IMPLEMENTER|REVIEWER|VERIFIER`,
`agent:<name or pane id>`. Optional header `X-CCD-Actor: agent:<name>` records an
agent as the actor (default `jay`); it is self-asserted.

Still not in the API: deleting a ticket (archive instead), applying the import,
closing or editing GitHub issues.


## Workspace (go-live)

DEV = also needs `X-CCD-Developer: <session>` from `/api/developer/unlock`.

| | |
|---|---|
| `GET /api/workspace/projects` | `{projects[{key,name,prefix,root,exists,branch,github{owner,repo,slug,url},coordinator,coordinatorState{state,how,candidates[{paneId,sessionId,status}]}}]}`. Roots come from `ccd/registry.py` only. `state` is `ready`, `found` (one unnamed Claude at the root: adopt it), `multiple` (pick one) or `none`, from the one resolver `ccd/coordid.py` |
| `GET /api/tasks/{key}/work` | The ticket's durable pipeline state in one object: `stage`, `stages[]`, `plan`, `planState`, `policy`, `gate`, `roles`, `branch`, `worktree`, `prs`, `review{verdict,head,cycles}`, `verification`, `merge`, `handoff`, `blocked`, `findings[]` (plans/TICKET-PIPELINE-V1.md) |
| `POST /api/tasks/{key}/work/{op}` | One pipeline step, recorded as `X-CCD-Actor` (`agent:<role>`): `plan {plan}`, `start {branch, worktree}`, `review {verdict, head, findings}`, `verify {result, evidence}`, `handoff`, `block {reason}`, `role`, `finding`. `confirm {gate}` closes an owner gate and needs Jay AND Developer Unlock. Agents use `python -m ccd.pipeline_cli` |
| `POST /api/coordinators/adopt` | DEVELOPER. `{project, sessionId}` binds that EXISTING Claude (a live one at the project root) as the coordinator; recorded by session id in `state/coordinator-bindings.json`, so a title change or a new pane id never breaks it. Never starts, resumes, renames or types into Claude |
| `GET /api/files/list?project=&path=&git=1` | one folder: `{entries[{name,kind,size,mtime,protected,link,git?}], crumbs, truncated}`; `.git` never listed |
| `GET /api/files/read?project=&path=` | `{kind: text|binary|large, text, sha, size, mtime, mode}`; text ≤ 2 MB UTF-8 |
| `GET /api/files/download?project=&path=` | the file, `application/octet-stream`, attachment |
| `POST /api/files/save` DEV | `{project, path, text, baseSha|null}` → atomic save; 409 if changed since `baseSha`, or if `null` and the name exists |
| `POST /api/files/upload?project=&dir=&name=&conflict=fail|replace|rename` DEV | raw `application/octet-stream`; 409 `{exists:true}` on a clash; 413 over the cap |
| `GET /api/attachments?owner=ticket|project&key=` | `{attachments[{id,name,size,sha256,uploadedAt,uploadedBy}]}` |
| `POST /api/attachments?owner=&key=&name=` DEV | raw `application/octet-stream` |
| `GET /api/attachments/{id}/download` | always `application/octet-stream`, attachment, sandboxed |
| `DELETE /api/attachments/{id}` DEV | remove (audited) |
| `GET /api/developer` · `POST /api/developer/unlock {token}` · `POST /api/developer/lock` | Developer Unlock |
| `GET /api/development/{key}/commits` | `{branch, base, branchUrl, commits[{sha,short,message,author,at,url}]}` |
| `GET /api/desktop/launcher` · `GET /api/desktop/launcher/download` | Windows launcher metadata (`version, sha256, commit, built_at, size`) and the exe |

Every GitHub URL ccd returns (repo, PR, issue, commit, branch) is rebuilt from
the project's registry identity on `https://github.com`; a stored URL string is
never trusted.
