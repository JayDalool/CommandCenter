# 0003 — The UI is served by ccd, and the token lives in the browser tab

Date: 2026-10-03 · Status: accepted for browser phase

## Context

ccd requires a per-install token and checks Host and Origin. A UI on another
origin (a Vite server) would be refused, and a proxy that injects the token
would authenticate anything that reaches the proxy port — including the second
local user.

## Decision

ccd serves the built UI from the same origin (`/` → `web/app/dist`, strict CSP,
no inline scripts). Jay pastes the token once; it is kept in memory and
`sessionStorage` (this tab), or `localStorage` if he ticks "remember". REST sends
it as `X-CCD-Token`; the WebSocket offers it as a subprotocol
(`ccd-token.<token>` next to `ccd.v1`), so it never appears in a URL, history or
a path log. ccd's Host/Origin/token/JSON checks are unchanged.

## One token per ccd

Each ccd has its own token file, and one will not authenticate against the
other: the live daemon on 7777 reads `~/.config/command-center/ccd.token`, the
dev preview (`scripts/dev-ccd.py`, port 7788, also reached through the Vite
proxy on 5173) reads `~/command-center/dev/ccd.token`. The Connect screen
derives both the tunnel port and the token file from the origin it was served
from, so the instructions always name the ccd behind the page. Offering the
wrong file is the one way to see "ccd refused that token." from a client whose
headers are correct.

## Alternatives considered

- **Token in the URL / query string.** Rejected (history, logs).
- **Cookie session minted from the token.** Deferred: adds a session store and
  CSRF surface for little gain while there is one user and one tab.
- **Proxy that injects the token.** Rejected (authenticates the proxy port).

## Windows launcher (later)

One shortcut: start `ssh -N -L 7777:127.0.0.1:7777 jay-server` (auto-reconnect),
fetch the token over the same SSH connection, and hand it to the app — in Tauri
through IPC, never a URL. Until then: tunnel, `ssh jay-server cat
.config/command-center/ccd.token | clip`, paste.
