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
| `GET /api/health` | `{ok, herdr{ok,connected,protocol,lastEventAt,lastSnapshotAt,reconnects,resyncs,eventsReceived,warning}, gh{ok,projects{key:{asOf,error}}}, git, host, tasks, gates{open,last}, seq, uptimeS, version, pid, calls{gh,git,…}, dbBytes, lastPollAges}` — no token. `gates` is two integers: `open` = open owner gates (the gate rows of Needs Jay; questions are not counted), `last` = id of the newest `pipeline.gate_opened` / `pipeline.blocked` event in the append-only `ticket_events` (0 when none; it only grows). The launcher reads them to show a tray notice; no keys, titles or reasons |
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
`task.created|updated|commented` (ref = ticket key; data.kind = field),
`task.pipeline` (ref = ticket key; data.kind = the pipeline step, e.g. `pipeline.started`,
`pipeline.worktree_removed` — the DONE ticket's worktree was removed after ccd's git poll found it
clean and fully pushed; `pipeline.worktree_kept` — it was kept, data.reason says why, recorded once
per reason, not every poll).

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
secrets, Docker, destructive git, worktree removal by request, config or rule changes,
issue creation, starting or stopping agents. (ccd itself removes a DONE ticket's clean,
fully pushed worktree after its git poll; there is no route for it. See the `pipeline.worktree_*`
events below.)


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
| `POST /api/developer/handoff {token}` | SSH sign-in, used by `scripts/cc-session` (as jay): ccd token + developer token → `{code, expiresIn: 120}`; the code is single-use and the session lasts 12 h |
| `POST /api/developer/redeem {code}` | **No ccd token** (Host/Origin checked, JSON only): the code, once → `{token, session, expiresIn}`. Wrong/reused codes are refused (403), never counted |
| `GET /api/development/{key}/commits` | `{branch, base, branchUrl, commits[{sha,short,message,author,at,url}]}` |
| `GET /api/desktop/launcher` · `GET /api/desktop/launcher/download` | Windows launcher metadata (`version, sha256, commit, built_at, size`) and the exe |

Every GitHub URL ccd returns (repo, PR, issue, commit, branch) is rebuilt from
the project's registry identity on `https://github.com`; a stored URL string is
never trusted.

## Control room (plans/COMMAND-CENTER-CONTROL-ROOM.md, tasks.db schema 5)

| | |
|---|---|
| `GET /api/tasks` · `GET /api/tasks/{key}` | every ticket row also carries `gate`, `gateReason`, `openQuestions`, `deploy{env,requestedAt,approvedAt,result}` and `visibleStage` — one of `Planning · Implementing · Reviewing · UI Testing · Verifying · Ready to Merge · Deploying · Needs Jay · Blocked · Closed` (`pipeline.visible_stage`). `meta.visibleStages` lists them |
| `GET /api/tasks/{key}/work` | adds `questions[]` (`{id,batch,position,text,kind: text\|choice\|yesno,options,answer,answeredAt}`), `openQuestions`, `evidence[]`, `writer`, `checkpoint`, `deploy`, `released`, `visibleStage`, `session{state: ready\|multiple\|none, paneId, status}` (the task Claude session, `coordid.task_session`), `project`; a step Jay takes returns `nudge{delivered, reason}` when it told the task session |
| `POST /api/tasks/{key}/answers` | Jay **and** Developer Unlock. `{answers: [{id, answer}], scopeChange?}` → `{work, complete, delivered, reason, replanned}`. Answers are stored once each; when the last open one is answered, the answers go to the SAME task Claude session (herdr `agent.prompt`, idle pane only) with the scope guard. `scopeChange: true` first sends the ticket back to Planning. `answers: []` re-sends the latest answers. Never starts a session |
| `POST /api/tasks/check` | Jay **and** Developer Unlock. `{project, copy?}` → `{ok, project, coordinator, openTasks, text?}`. **The task check**: one fixed message (`daemon.TASK_CHECK_TEMPLATE`, with the project's open tickets) to the project's idle coordinator Claude, asking it to compare them with the repo and every .md file that held tasks, propose stale ones (`stale`), add missing ones (`pipeline_cli add`, Inbox, label `task-check`) and ask about unclear ones. It changes no code and never cancels. 409 when the coordinator is not identified or busy. `copy: true` sends nothing and returns the message to paste into any Claude in that repo |
| `POST /api/tasks/night-shift` | Jay **and** Developer Unlock. `{project, copy?}` → `{ok, project, coordinator, text?}`. **Night shift / away mode**: `server/ccd/skills/night-shift/SKILL.md` (the same file Claude's `/night-shift` skill links to, `scripts/install-claude-commands.sh`) to the project's idle coordinator: finish work in progress, fresh reviews, merge only where no gate is open, verify, plan/research, start new work only when `start` allows; never deploy; a morning report in `~/command-center/night-shift/<project>/<date>.md`. `copy: true` returns the text instead. **Supervisor** (`ccd/nightshift.py`, `Daemon.night_loop`, every 60 s): an idle coordinator (3 min) gets one fixed reminder at most every 10 min (`nightshift.NUDGE_WITH_REPORT` when this shift's report exists, `NUDGE_NO_REPORT` when not). A reminder counts only once it was delivered to an idle pane whose input line is empty (best effort: ccd reads the pane's text and skips, uncounted, when the prompt line holds text or cannot be parsed). Hard stops, whatever the coordinator does: **6 reminders per shift** and the **morning cutoff** (first 07:00 local after the start; `CCD_NIGHT_CUTOFF=HH:MM`; it also ends the shift with herdr down and types nothing). `Status: complete` ends the shift, and so do 3 reminders in a row with no progress. Progress is only a ticket of the project changing or the report being rewritten: seeing the coordinator "working" is not progress. State: `~/command-center/night-shift/.state.json` |
| `POST /api/tasks/ui-test` | Jay **and** Developer Unlock. `{project, copy?}`. **A UI test run, on request only**: `skills/ui-test/SKILL.md` (Claude's `/ui-test`) to the project's idle coordinator, with its fix mode (registry `ui_fix`: `ask` — the default, Jay decides every finding — or `auto`). Claude tests the user-visible features merged since the last run with Playwright against a local/preview app (never production; SamVision text snapshots only), keeps the tests (one PR, repo merge rules), and writes `~/command-center/ui-tests/<project>/<YYYY-MM-DD-HHMM>/report.md` + `findings.json`. Paused projects refused |
| `GET /api/ui-tests` | per project `{paused, fixMode, runs[], latest{run, status, report, summary, findings[{id, severity, title, feature, steps, expected, actual, evidence, decision}]}}`. `findings.json` is validated field by field (`uitests.clean_findings`) |
| `POST /api/ui-tests/decide` | Jay **and** Developer Unlock. `{project, run, finding, decision: fix\|skip}`, once per finding. fix: a BUG ticket `UI: <title>` labelled `ui-finding` (priority by severity) enters the pipeline; skip: recorded in the run's `decisions.json` |
| `GET /api/profiles` | **Project Operating Profiles** (`policy/`, `ccd/profiles.py`), read-only: `{fingerprint, problems[], projects: {key: {file, sha256, valid, errors[], drift[{field, profile, registry}], mode, decisions[], learning, enforced{merge, night, paused, max_lanes, ui_fix}, target{…}, capabilities{health_checks, auto_rollback}}}, decisions: {D-NNN: {id, date, decided_by, projects, question, decision, rationale, rules, reconsider, supersedes, valid}}}`. `enforced` mirrors what the registry makes ccd do today (any difference is `drift` and an alert); `target` is Jay's agreed policy and is **not enforced** (decision D-008). There is no write route: policy changes in the repository, by Jay |
| `GET /api/autonomy` | **Autonomy Engine, shadow mode** (`ccd/autonomy.py`, D-008, ADR 0008), read-only: `{mode: "shadow", engine, available, policy, total, agree, disagree, counts: {project: {action: {total, agree, pairs{"observed->engine": n}}}}, missing: {fact: n}, disagreements[{id, at, key, project, action, observed, engine, rule, reasons[], missing[]}]}`. `action` is plan, merge or deploy; outcomes are auto, jay or refuse. The engine's answer is recorded and never acted on |
| `GET /api/decisions` | **Decision and Approval records** (`ccd/ledger.py`, tasks.db v7), read-only. `?project=` filters decisions, `?state=pending|approved|rejected|consumed|void` filters approvals, `?limit=` (≤ 500). `{available, decisions[{id, ref, project, key, question, options, decision, rationale, decidedBy, via, reconsider, decidedAt, supersedes, source: policy|question, sourceRef, sha256, current}], approvals[{id, project, key, subject: plan|merge|ui|deploy|failure, subjectHash, action, state, reason, requestedAt, requestedBy, expiresAt, overdue, decidedAt, decidedBy, via, consumedAt, voidedAt, voidReason}], counts{state: n}}`. A mirror of the gates (which still decide); nothing writes these over HTTP |
| `GET /api/night-shift` | every project's night shift: `{projects: {key: {active, startedAt, endedAt, endReason, nudges, cutoffAt, goLiveAt, coordinator{name,state,status}, report{name,mtime,status,text}, goLive{approves[], warnings[]}}}}`. The report is agent-written text: the newest `<YYYY-MM-DD>.md` in `~/command-center/night-shift/<project>/` (other `.md` files there are ignored; 64 KB max); `status` is its first line, `Status: working\|complete`. `goLive.approves` are the open tickets whose live-deploy gate Go Live would approve `{key, title}`; `goLive.warnings` are merged (VERIFYING) tickets that are `merged, not verified` or have the `UI review still open`, which ride along in main |
| `POST /api/night-shift/end` | Jay **and** Developer Unlock. `{project}`: no more reminders; the coordinator is sent the stop-safely message (no Esc, no interrupt, never to a pane that waits on a prompt) and asked to finish the report |
| `GET /api/jay/merge` | per project `{ready: [{key, title, pr, head, gate}], skipped: [{key, reason}], paused}`: Ready-to-Merge tickets whose recorded APPROVE covers the PR head the last GitHub poll sees open, green and not a draft, in merge order (a ticket another ready one is blocked by first, then oldest PR). Order only: a ready ticket whose blocker is not ready yet is still listed. A ticket with any open gate other than the merge gate is skipped |
| `POST /api/jay/merge` | Jay **and** Developer Unlock. `{project, items: [{key, head}]}` (required: the pairs the confirm box listed) → `{ok, coordinator, merging[], skipped[], errors[{key, error}]}`. A pair whose head or readiness changed since the box was shown is skipped, never approved. Only if something is mergeable and the coordinator is identified and idle: sends `daemon.MERGE_TEMPLATE` (merge exactly these PRs at these heads, one at a time, in order; skip any whose head changed, CI is not green or GitHub wants the branch updated — never rebase or push; wait for CI on main; stop if main goes red; then verify) and then records Jay's merge approval for each exact head (`merge:<sha>`) whose review still covers it; one that moved during the send comes back in `errors` and does not undo the others. Refused for a paused project. ccd merges nothing |
| `POST /api/jay/go-live` | Jay **and** Developer Unlock. `{project, keys[]}` → `{ok, coordinator, approved[], skipped[{key, reason}], errors[{key, error}]}`. `keys` are the tickets the confirm box listed (required; 400 otherwise): only those whose live-deploy gate is still open are approved, the rest come back in `skipped`, gates opened since stay open. **Go Live prepares only.** Refused (409) while the project's night shift runs, within 30 min of the last Go Live, or while the last one is unfinished (a ticket it approved is not recorded deployed yet; at most 12 h), and when the coordinator is not identified or not idle. Then it sends `daemon.GO_LIVE_TEMPLATE` (the coordinator PREPARES: runbook steps, migrations, checks, rollback plan, saved to `~/command-center/deploys/<project>/<date>-plan.md`, then waits), and approves each open live-deploy gate (`confirm deploy`). A ticket that cannot be approved (its gate moved) is returned in `errors`; the others still go through, so there is never a 409 after the message was sent. Approvals are marked `approvedBy: "jay:go-live"`. Jay confirms the deploy himself in the coordinator's pane; the message orders no deploy, but the approval it records is a full live-deploy approval (any agent may then record `deployed --env live`), so that wait rests on the message text. ccd runs no deploy itself |
| `GET /api/tasks/{key}/record` | `{key, taskMd, workflowMd, dir}` — the readable record, also written to `~/command-center/task-records/<project>/<KEY>/{task.md, workflow.md, files/}` (never a product repo) |

**Waiting for Jay is per task** (`registry` pipeline `jay_first`, default on): `start` is refused (409) while the
ticket — or an open ticket it is blocked by — has an open question for Jay, a plan waiting on his approval or a
blocker only he can clear (`Pipeline.held`). Every other ticket goes ahead. A blocking ticket flagged needs:legal (or
type LEGAL) never holds; sign-offs on finished work (merge acceptance, UI review, live deploy) do not either.
`Pipeline.held` follows only direct `blocks` relations, one level: for A blocks B blocks C, C is held by an open item
on B but not by one on A. That matches the documented intent; it is not transitive.
Implementation lanes: at most 2 per project (`max_lanes` in the registry pipeline overrides).

**Paused projects** (registry `paused`, e.g. GauzeMate while Jay adds designs): no night shift, task check, dispatch
or Go Live (409), no pipeline step recorded by an agent and no ticket created by an agent; Jay still can. `GET
/api/tasks` carries `paused: {key: reason}` and `pipeline_cli tasks <project>` prints `PAUSED: …` instead of
the list. **Careful projects** (registry `night: careful`, SamVision): the night-shift text also carries
`skills/night-shift/careful.md` — research before any change, only LOW-risk implementation at night, one at a
time, risky areas stop at a plan. `GET /api/night-shift` reports `paused` and `mode` per project.

New pipeline steps on `POST /api/tasks/{key}/work/{op}` (agents: `python -m ccd.pipeline_cli <op>`):

| op | body | effect |
|---|---|---|
| `ask` | `{questions: [text \| {text, kind?, options?}]}` (1–10) | one batch of questions for Jay; the ticket reads **Needs Jay**; the task session keeps waiting |
| `stale` | `{reason}` | the task check: one question for Jay, `purpose: "stale"`, options **Cancel it / Keep it** (one open per ticket). Jay's "Cancel it" on `/answers` cancels the ticket (with a note, ending its sessions); "Keep it" keeps it. Nothing is typed into any Claude |
| `replan` | `{reason}` | back to Planning (RESEARCHING, plan `proposed`); approval and merge authorisation dropped; Jay accepts before the merge (`owner:accept`) |
| `rework` | `{reason}` | back to Implementation (IN_PROGRESS) from review, ready-to-merge, verifying or blocked; respects the lane limit; ccd records the ticket's open PRs (ref, head) in the rework event; the ticket returns to IN_REVIEW only when its GitHub poll sees a PR or head that is neither the reviewed head nor one of those recorded PRs (a replacement PR, or a new head on a known one) |
| `evidence` | `{kind: screenshot\|image\|link\|file\|test\|pr\|ci\|deploy\|note, ref, note?, stage?}` | append-only evidence |
| `writer` | `{owner: claude\|codex\|jay\|none, checkpoint?}` | one writer per worktree; taking it from another writer needs a checkpoint `{reason, branch, worktree, commit, dirty, changed[], tests, decisions, blocker, remaining}`; a handover to Claude sends the task session one fixed sentence: read the checkpoint with `pipeline_cli work <KEY>` |
| `deploy-request` | `{env: live\|preview\|dev, what, verification}` | after the merge (VERIFYING), before `verify pass` (which closes a ticket that owes no deploy). `live` opens the deploy gate — **Ready for live deployment** — and waits for Jay; preview/dev follow automation; a pending live request cannot be replaced by a preview one |
| `deployed` | `{env, result: pass\|fail, evidence}` | records the deployment; `live` is refused (409) until Jay approved it; pass + verified → DONE; fail → BLOCKED, and the next try needs a fresh request (and approval). Jay's **Approve live deploy** on a `needs:deploy` gate is an approval, never a close: the ticket waits for `deployed`. It is a real live-deploy approval, marked `approvedBy: "jay:gate"` (`confirm deploy` from the ticket gate), and the message typed into the task session (`daemon.GATE_DEPLOY_TEMPLATE`) asks Claude to prepare the deploy and wait for Jay to confirm in the pane; that wait rests on the message text only |
| `block` | `{reason, what?, why?, action?, impact?, technical?}` | as before, plus the manager explanation the UI shows first |

Review: an `APPROVE` from `agent:implementer`, or with the implementer's session or the task session's name (`sv-071`), is refused (409); every `APPROVE` must name its (fresh) reviewer session, and `start` records the implementer's session (default: the task session, `sv-071`). `rework` and `replan` drop any verification, live-deploy approval and UI/deploy acceptance, and close open UI/deploy gates.
Merge policy: `registry.PIPELINE_DEFAULTS.merge = "owner"` (the only other value is `"low-risk"`; the old `"auto"` is read as `owner`). Under `owner` a merge gate opens when a ticket is approved at its PR's head and Jay merges. Only `commandcenter` is `low-risk`: when `config.json` `auto_merge` is true, no `~/command-center/state/auto-merge.stop` exists and `ccd/merge_policy.py` accepts the PR (docs and tests only, at most 10 files and 300 lines, reviewed at the exact head), ccd itself runs `gh pr merge N --repo R --merge --match-head-commit <head>` and no gate opens. Otherwise (or if the merge fails) a merge gate opens with the reason and ccd does not retry that head. Agents never merge. No API route starts an auto-merge; there is no UI toggle.

Auto-merge events (ticket timeline, actor `system:auto-merge`; each also an `/api/activity` `task.pipeline` event, severity `action`): `pipeline.auto_merged` (`data.head`, `data.pr`, `data.ci` = `none` when the PR has no CI checks, `green`), `pipeline.auto_merge_held` and `pipeline.auto_merge_failed` (`data.head`, `data.reason`, followed by `pipeline.gate_opened`). `pipeline.ready_to_merge` says "with no CI checks" instead of "with green checks" when the PR has no checks (`data.ci`). Security events in the activity log: `merge.policy` (once at startup, `data.status` enabled/disabled) and `merge.auto`.

Terminal names (`WS /api/pty/{name}`, DEVELOPER): `repo|claude|codex:<PREFIX>` (Project Console), `repo|claude|codex:<KEY>` (Task Room: the shells and Codex in the ticket's known worktree, Claude = the task session `sv-071`), `server`. Every Command Center window attaches to the same session by name; closing a window only detaches. When a ticket closes, its `*:<KEY>` terminals close and an idle task session gets `/exit`.
