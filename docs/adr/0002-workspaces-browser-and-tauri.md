# 0002 — Workspaces: browser mode now, an embedded terminal only in Tauri

Date: 2026-10-03 · Status: accepted

## Context

Jay wants the herdr CLI experience inside Command Center. A browser page cannot
open an SSH session, and herdr's pane I/O would have to be proxied through ccd
to reach one — which turns ccd into a remote shell server on a host that also
has a second login user.

## Decision

Browser mode shows herdr's real layout (workspaces → tabs → pane rectangles from
`session.snapshot`), focuses agents/workspaces/tabs through herdr's own API,
reads redacted tails on demand (labelled READ-ONLY), lets Jay answer a blocked
agent with one line (the existing guarded action), and gives the exact command
for the real terminal: `ssh -t jay-server herdr agent attach <name>`.

The future Tauri app adds `openTerminal()` behind the same `WorkspaceTransport`
interface by running that ssh command in a local PTY. ccd never carries the
interactive byte stream.

## Alternatives considered

- **xterm.js in the browser over a ccd WebSocket PTY.** Rejected: ccd would
  become a shell server; any token holder could type anything into any pane.
- **A fake terminal (scrolling text box).** Rejected: misleading.
- **`ssh://` links.** Rejected: not registered on Windows by default, and still
  not in-app.

## Consequences

ccd gains only `workspace.focus` and `tab.focus` in its herdr allowlist. Layout
changes (split, close, new pane) stay in herdr. The browser UI is honest about
what is interactive.
