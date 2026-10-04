# 0004 — Console: herdr mirrors Claude, a scoped PTY service owns the shells

Date: 2026-10-03 · Status: accepted — phases 1–3 implemented (phase 3 authorized by Jay 2026-10-03, CC-002)

Supersedes the "rejected" list of [ADR 0002](0002-workspaces-browser-and-tauri.md):
Jay has decided Command Center should become his main interface into jay-server,
so a real browser terminal is now in scope. What 0002 got right stands — ccd
must not become a general shell server by accident — and shapes the design below.

## Context

Jay wants one CONSOLE area with three modes: the project's real Claude
coordinator, a shell rooted in the project's repository, and a general shell on
jay-server. Terminals must survive a browser reload, must never duplicate a
Claude session, and must never be reachable from outside the SSH tunnel.

## What herdr can actually do (0.9.3, protocol 22, read from `herdr api schema`)

herdr owns every pane and exposes, per pane:

| need | herdr gives | good enough for |
|---|---|---|
| see output | `pane.read` / `agent.read` — `source: visible\|recent\|recent_unwrapped`, `format: text\|ansi`, plus a `revision` | a faithful **mirror** of a pane's screen |
| know it changed | event `pane_output_changed {pane_id, workspace_id, revision}` | refreshing that mirror within ~a second, with no polling |
| type | `pane.send_text`, `pane.send_keys`, `pane.send_input`, `agent.prompt` | real keyboard input into an existing pane |
| context | `pane.process_info` (shell pid, tty, foreground argv, cwd), `PaneInfo.cwd/foreground_cwd/agent_session` | the header Jay asked for |
| create / destroy | `pane.split {cwd, env}`, `tab.create`, `workspace.create`, `pane.close` | panes, but inside Jay's own layout |
| geometry | `pane.resize {direction, amount}` — a split-ratio nudge | **not** a cols×rows PTY resize |

Two gaps decide the architecture:

1. **There is no output byte stream.** `pane_output_changed` carries a revision
   number, not bytes; the client must then `pane.read`. That is a screen mirror,
   not a PTY: fine for watching and typing, wrong for anything that depends on
   exact byte timing.
2. **There is no browser-side geometry.** A herdr pane's size is set by Jay's
   TUI layout. A browser terminal cannot tell it "I am 140×40", so `vim`, `less`
   and `htop` would render at the pane's size, not the window's.

A third point is a rule, not a gap: ccd must not create, close, split or move
panes (README, ADR 0002). Making the repo shell a `pane.split` would put
Command Center's shells into Jay's live herdr layout and break that rule.

## Decision

Three modes, two different mechanisms, named honestly in the UI.

**CLAUDE tab — a mirror of the herdr pane. herdr keeps owning it.**
ccd reads the coordinator pane (`format: ansi`, `source: visible`) and refreshes
on `pane_output_changed`. Input goes through herdr's own `pane.send_text` /
`pane.send_keys`. Opening the browser never starts a Claude session; reconnecting
reattaches to the same pane, because the pane is herdr's and ccd only looks at
it. Closing Chrome cannot kill Claude — there is nothing of Claude's to close.
Lifetime: exactly the herdr pane's lifetime.

**REPO SHELL and SERVER SHELL — a scoped PTY service inside ccd.**
herdr cannot supply these cleanly: it would mean ccd creating and closing panes
in Jay's layout, with no cols×rows control. So ccd gets its own small PTY
manager with named, long-lived sessions (`repo:<project>`, `server`), each a
login shell, owned by ccd and not by the browser tab. A reload reattaches by
name and replays a bounded scrollback buffer; an explicit CLOSE SESSION is the
only thing that ends one.

**Transport**: the existing authenticated WebSocket boundary — same origin,
`127.0.0.1` only, token as a subprotocol (never in a URL or a log), Host and
Origin checks, the same `Guard` as every other route. Rendering: xterm.js,
bundled by Vite and served from ccd (the CSP stays `script-src 'self'`; no CDN).

**Not built, deliberately**: no new listener, no port, no herdr socket bridge,
no second user, no allowlist of commands Jay may type in his own shell.

## Phases

| phase | what | risk |
|---|---|---|
| 1 | Console IA: page, three tabs, project/ticket context, header, full-screen, Quick Console becomes a launcher | UI only |
| 2 | Claude tab mirror on the existing read-only, redacted `/api/agents/{id}/tail`; refresh while visible | read-only, existing route |
| 3 | PTY service + `WS /api/pty/{session}` + xterm.js + input into the Claude pane | **new capability — needs Jay, and a fresh security review** |

Phase 3 is where ccd gains the ability to run commands. It is implemented
(server/ccd/pty.py, `WS /api/pty/{name}`), with one change from the design
below: opening, attaching to or closing a terminal needs **Developer Unlock**
on top of the ccd token, so a leaked ccd token alone still cannot run anything.
Claude input is herdr's `agent.prompt` (idle agents) and `pane.send_keys`
limited to esc and Enter, also behind Developer Unlock. Terminals end when ccd
stops (they are ccd's children); Claude panes, being herdr's, never do.

## Phase 3 design, for that review

- `server/ccd/pty.py`: one process group per named session, `openpty`, `setsid`,
  `TIOCSWINSZ` on resize. Sessions live in a dict owned by the daemon; nothing
  about them is written to SQLite.
- Session names are fixed and derived, never client-supplied paths:
  `repo:<project key>` → `cwd` = that project's configured `path`;
  `server` → `cwd` = `$HOME`. A project key that is not in the config is refused.
- One WebSocket per view; several views of one session share its output and all
  may type (it is one shell, as a `tmux` attach is).
- Backpressure: a ring buffer per session (e.g. 256 KiB) and a per-socket send
  queue; a slow client is dropped with `output_lost`, never allowed to stall the
  PTY. Output is rate-limited, not unbounded.
- Idle: a session with no attached client keeps running (that is the point) but
  is capped in number (one per project plus one server shell) and reported in
  `/api/health`.
- Audit: `pty.session.opened` / `pty.session.closed` / `pty.attached` events in
  the event log, with session name and client count. **Never the keystrokes, the
  command lines or the output** — those can contain secrets, and ccd already
  promises not to store pane output.
- `SIGHUP` + `SIGKILL` after a grace period on CLOSE SESSION; on ccd shutdown
  sessions are left running only if they are re-parented, otherwise they end
  with ccd (and Claude, being herdr's, is unaffected either way).

## Consequences

- The Claude tab is a mirror, not a PTY: full-screen TUIs inside a Claude pane
  render at herdr's pane size. Acceptable — Claude is a line-oriented log.
- Phase 3 makes any holder of the ccd token able to run commands as `jay`. That
  is already true of an SSH session as `jay`, and the tunnel is the same
  boundary, but it raises the cost of a leaked token from "read metadata" to
  "run anything". The token file stays `0600`, the listener stays loopback, and
  this is the reason phase 3 waits for Jay rather than shipping with phase 1.

## Alternatives considered

- **Repo shells as herdr panes** (`pane.split {cwd}`): rejected — ccd would
  create and close panes in Jay's layout, against the standing rule, and still
  with no cols×rows control.
- **Proxying the herdr socket to the browser**: rejected — it would expose every
  herdr method, including `pane.close` and `server.stop`, to anything holding
  the token.
- **`ttyd` / `gotty` beside ccd**: rejected — a second listener and a second
  auth model to get wrong; the point is one authenticated boundary.
- **Keep the read-only tail forever**: rejected by Jay's decision; it cannot be
  his main interface to the server.
