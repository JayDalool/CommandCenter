# Architecture (P2)

```
            jay-server
 ┌───────────────────────────────────────────────────────────────┐
 │ herdr server ── owns every pane ── Claude coordinators, lanes │
 │      │ ~/.config/herdr/herdr.sock (unix, same user)           │
 │      ▼                                                        │
 │ ccd (systemd --user, own cgroup)                              │
 │   herdr.py   session.snapshot  bootstrap, every reconnect,    │
 │                                 every 30 s reconcile          │
 │              events.subscribe  push: agent status, structure  │
 │   sources.py gh api graphql   1 call / repo / 120 s           │
 │              git              unpushed + worktrees / 300 s    │
 │              /proc, docker ps host / 120 s; journalctl / 10 m │
 │   model.py   derive()         the legacy board logic, lifted  │
 │   daemon.py  diff → events → SQLite (seq) → WS subscribers    │
 │   api.py     127.0.0.1:7777   REST + WS, guarded              │
 │      ▲                                                        │
 │ legacy board (Textual, cron ping) ── reads /api/state,        │
 │                                      local build if ccd down  │
 └──────┼────────────────────────────────────────────────────────┘
        └── later: ssh -L 7777:127.0.0.1:7777 ← Windows browser (P4)
```

## herdr protocol notes (0.9.3, protocol 22, verified live)

- newline-delimited JSON over the unix socket; one response line per request
- `events.subscribe` holds its connection: `subscription_started`, then one
  line per event
- event names come in two spellings on one connection: structural events as
  `pane_created`, filtered subscription events as `pane.agent_status_changed`.
  ccd normalises both (a live bug found during the P2 canary)
- `pane.agent_status_changed` must name a `pane_id`, so the subscription is
  reopened whenever the set of agents changes
- events carry **no sequence number**: a dropped connection can lose events
  silently. ccd therefore resyncs from `session.snapshot` on every reconnect
  and every `reconcile_seconds`, and only trusts events for timeliness
- a protocol other than 22 → events ignored, snapshot polling only, warning in
  `/api/health`

## Source failure behaviour

| Source down | ccd |
|---|---|
| herdr | agents kept, state `unknown`, `herdr_error` set, alert raised, GitHub data still served; reconnect with backoff 1 → 30 s |
| GitHub | last-good data kept (also across restarts, from SQLite), per-project error + "as of" time; no false `pr.closed` events |
| git / host | last value kept, error in `sources` |
| ccd itself | clients reconnect with `?since=`; agents unaffected; legacy board builds locally |
