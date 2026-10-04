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

## Addendum 2026-10-04 — the browser Claude terminal is a real attach too

Jay found the browser repo/server shells real-time and the Claude mirror not.
The browser Claude tab now opens a ccd PTY session `claude:<PREFIX>` whose
fixed command is `scripts/cc-terminal claude <PREFIX>` — the SAME helper and
coordinator lookup the native terminal uses — so the browser gets herdr's
direct attach stream (`herdr agent attach <pane>`). It is not a Claude process.
The snapshot mirror stays only as a fallback toggle.

Verified against herdr 0.9.3 in an isolated lab session before building:

| Question | Finding |
|---|---|
| attaches to the existing pane? | yes: "streams the current rendered terminal state, then live ANSI frames; input goes straight to that terminal" |
| attach client killed (SIGKILL) or hung up (SIGHUP)? | the pane and its process keep running; re-attach works |
| several clients? | one writable attach client per terminal; a second is refused ("already has an attached client; retry with --takeover"). ccd never uses --takeover |
| resize? | the split layout never changes; while attached, the attach client owns the terminal size; detaching restores it |
| detach keys | Ctrl+B then q (Ctrl+B Ctrl+B sends a literal Ctrl+B) |

So: closing the browser detaches the view (the attach client lives on in its
PTY session, as shells do); CLOSE CLAUDE TERMINAL ends only the attach client;
the native terminal and the browser cannot both type into the same Claude — the
second one is refused with herdr's message. Same gates as the shells: ccd token
+ Developer Unlock + Host + Origin + a registered prefix + exactly one
coordinator.
