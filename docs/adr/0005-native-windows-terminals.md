# ADR 0005 — Native Windows Terminal for Claude, repo and server shells

Date: 2026-10-04 · Status: accepted (Jay's decision) · Tickets: CC-002, CC-005, CC-006

## Context

herdr 0.9.3 gives ccd snapshots of a pane, not a byte stream, so the browser's
Claude view can only ever be a mirror. Interactive work belongs in a real
terminal. Jay works from Windows over SSH to jay-server.

## Decision

The browser stays the place for tasks, files, editor, source control,
development and monitoring. Interactive terminals open as **native Windows
Terminal tabs over Jay's own SSH**. The browser PTY shells (ADR 0004 phase 3)
stay as an opt-in fallback.

## Flow

```
Workspace button
  └─ <a href="commandcenter://terminal/<claude|repo|server>?project=<PREFIX>">
       (only an ACTION and a registered-shaped PREFIX; no command, path, host or token)
Windows: HKCU\Software\Classes\commandcenter → "CommandCenter.exe" "%1"
  └─ CommandCenter.exe parses the URI strictly (allowlist), then itself builds:
       wt.exe -w CommandCenter new-tab --title "<Title>" -- ssh.exe -t <configured host> -- \
           /srv/server/repos/CommandCenter/scripts/cc-terminal <claude|repo> <PREFIX>
       (server: ssh.exe -t <configured host>, a normal login)
       fallback without Windows Terminal: a new PowerShell console running the same ssh
jay-server: scripts/cc-terminal resolves from server/ccd/registry.py
  repo   → cd <registered root> && exec <login shell> -l
  claude → the ONE live claude pane titled <project key> whose cwd is the root
           → exec herdr agent attach <pane>   (never start/resume a session)
           none / several → a clear message, nothing started
```

## Why a URI protocol, not a local listener

A tray IPC endpoint the browser could reach would be an HTTP listener on the PC
that any web page could also reach. A per-user `commandcenter:` protocol opens
no port, needs no admin, and the browser asks Jay before the first launch.

## Security

- The page can name only three actions and a prefix matching `^[A-Z][A-Z0-9]{1,5}$`.
  The launcher refuses anything else in the URI (host, port, userinfo, other
  paths, extra or repeated parameters, encodings, shell metacharacters).
- The launcher never takes a command, path, cwd, host or SSH option from the
  URI. The host comes from its own validated config.
- The server helper never takes a path or command from its arguments; it
  resolves the project from the registry and the coordinator from herdr.
- Any web page could trigger these links. The worst case is an unwanted
  terminal window to jay-server opening on Jay's PC: nothing runs beyond a
  login shell or an attach, and SSH auth is Jay's own. The new tab takes focus,
  so keys Jay is typing at that moment would go into it; for `claude`,
  cc-terminal discards anything typed before the attach. The browser's
  per-site "Open CommandCenter.exe?" prompt is the real gate: allow it only for
  http://127.0.0.1:7777.
- No credential is in the URI, the launcher or the helper.
