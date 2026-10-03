# Security model (ccd, P2)

## Exposure

- Binds `127.0.0.1:7777`. The host is a constant in `ccd/config.py`; there is
  no flag or environment variable to change it, and `__main__` refuses to run
  if it is edited to anything else. Verified live: every other interface
  (LAN, Tailscale, Docker bridges) refuses port 7777.
- No Cloudflare, no Funnel, no Tailscale Serve, no nginx vhost.
- The herdr socket is used only by ccd, as the same user, over its unix path.
  It is never bridged to TCP.

## Who may call it — and a deliberate deviation from the V2 plan

The plan (§13.4) said "authentication = SSH, no bearer token". That assumed
only SSH users can reach loopback. On this server that is not true: a second
login user, `minecraft-ai` (uid 1001), can open `127.0.0.1:7777` like anyone
else, and a web page in Jay's browser can aim requests at a tunnelled port.
So ccd adds, at no cost to Jay:

| Threat | Control |
|---|---|
| another local user, or a stray local process | per-install token, `~/.config/command-center/ccd.token`, 0600, required on everything but `/api/health` |
| DNS rebinding from a web page | `Host` must be `127.0.0.1:7777` / `localhost:7777` |
| cross-site request from a web page (CSRF) | `Origin`, when present, must be the same origin; actions require `application/json`, which forces a CORS preflight ccd never approves; no CORS headers are ever sent |
| cross-site WebSocket hijacking | same Host/Origin/token checks on the upgrade |
| typing escape sequences into a pane | answers and notes must be printable, one line; control characters refused |

The token is never logged (uvicorn's access log is disabled because a WS token
can be a query string) and never returned by the API. The legacy board reads
the file directly; the Windows client will fetch it over the SSH connection
that carries the tunnel.

## What leaves ccd

Rendered state only: project keys, names, repo slugs and paths; agent pane
ids, canonical names, roles, states and working directories; PR/issue numbers,
titles, CI marks; checkbox counts and lines from `docs/jay/*.md`; host numbers.

Never: the GitHub token, Claude credentials, the ntfy URL or any other config
value outside `PUBLIC_PROJECT_FIELDS`, `.env` contents, transcripts, and
**terminal titles** (Claude titles its terminal after the conversation, which
can quote anything).

Pane tails (`/api/agents/{id}/tail`) are the one path to raw output. They are
token-gated, on demand, bounded to 200 lines, passed through a credential
redactor, and never written to SQLite or the log. A redactor cannot recognise
licensed property data, which is why tails are opt-in and never persisted.

## What is stored (`~/command-center/state/ccd.db`)

Event kind, time, project key, pane id, PR/issue number and title-derived text,
from/to states, and a short whitelist of data keys (`store.EVENT_DATA_KEYS`).
Last-good GitHub responses (issue/PR metadata) and host numbers in `kv`.
Alert ids and acknowledgements. **Not stored:** pane output, blocked-agent
question text (shown live only), answer text (only its length), secrets.
Retention: 30 days, pruned daily; capped at 200,000 events.

## Actions

Allowed: answer a blocked agent, focus an agent, acknowledge an alert, dispatch
a task to an idle coordinator under the dispatch skill's rules. Every action is
audited before it runs. herdr methods outside an explicit allowlist
(`herdr.ALLOWED_METHODS`) are refused before they reach the socket — ccd cannot
close, split, start or move anything even by mistake.
