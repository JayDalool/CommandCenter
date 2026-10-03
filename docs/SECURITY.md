# Security model (ccd, P2 + P4B)

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


## P4B additions

**Served UI.** `GET /` and `/assets/*` serve `web/app/dist` without a token
(public code, no data), with `Content-Security-Policy: default-src 'self';
script-src 'self'; connect-src 'self' ws://127.0.0.1:<port> …; frame-ancestors
'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. Non-GET to a UI
path is 405. Host checks still apply. Every `/api/*` path except health still
needs the token.

**Token in the browser.** Pasted once; held in memory and `sessionStorage`
(or `localStorage` if "remember" is ticked) for the 127.0.0.1:7777 origin only.
Sent as a header for REST and as a WebSocket subprotocol — never a URL. The
same-origin policy keeps other sites from reading it; the CSP blocks injected
scripts.

**tasks.db** (`~/command-center/data/`, 0700 dir): Jay's ticket titles,
descriptions, notes and the audit trail. Product data: never pruned, not
secrets. Do not paste credentials or licensed property data into tickets; there
is no redactor on ticket text.

**Attribution limit.** Agents run as the same Unix user and can read the token,
so `X-CCD-Actor` is self-asserted: it keeps honest agents' writes from being
filed under Jay; it is not authentication. Per-agent tokens are the fix if that
ever matters.

**Read-only by design.** The import preview reads files and cached GitHub data
on its own read-only SQLite connection; there is no apply endpoint. herdr's
allowlist gained only `workspace.focus` and `tab.focus`.

**Host data.** Top processes expose pid, `comm` and RSS — never command lines.


## P4B revision: Development and Console

**`GET /api/development`** joins data ccd already has — tickets, the cached
GitHub poll and local branch names — and adds no new reach. The one new
subprocess is `git log --format=%S --branches --not <default>` per repo per
`git_seconds`, read-only, in the repos already configured. Branch names and
commit counts are metadata, not content: no diff, no commit message, no file
ever leaves ccd through this route.

**The Console's Claude tab** uses the existing `GET /api/agents/{id}/tail`:
redacted, capped at 200 lines, fetched on demand, never stored. It polls only
while the page is on screen and `document.visibilityState` is `visible`, so a
forgotten tab stops reading a pane. Typing into a blocked agent is the same
guarded one-line action as before.

**The Console's shells are not implemented.** An interactive PTY is the one
change that would turn a leaked ccd token from "read operational metadata" into
"run commands as jay", so it is designed in
[ADR 0004](adr/0004-console-and-real-terminals.md) and waits for Jay rather than
shipping quietly with the UI. When it is built it must keep every rule here:
loopback only, the SSH tunnel, the same `Guard` (Host, Origin, token as a
WebSocket subprotocol, never in a URL or a log), session names derived from the
config rather than client-supplied paths, bounded output buffers with a dropped
client rather than a stalled PTY, and audit rows for session open/close/attach
only — never keystrokes, command lines or output, which can contain secrets.

No new listener, no port, no herdr socket bridge, and no allowlist of commands
Jay may type in his own shell: the terminal is Jay's shell. UI buttons outside a
terminal stay under the existing safe-action rules.
