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


## Workspace, files and Developer Unlock (go-live)

Two credentials, two powers:

| Credential | Where | Allows |
|---|---|---|
| ccd token | `~/.config/command-center/ccd.token` (0600) | everything that reads, plus ticket metadata and the guarded herdr actions |
| developer token | `~/.config/command-center/developer.token` (0600, created on first start, must differ from the ccd token) | **also** saving and uploading repository files, adding and removing attachments |

The browser sends the developer token once to `POST /api/developer/unlock` and
gets a random session id that lives only in ccd's memory and the tab's memory
(never localStorage, sessionStorage, a URL or the page). Sessions end on LOCK,
2 h idle, 8 h total, or a ccd restart. Five wrong tokens in five minutes lock
unlocking for five minutes. Write routes answer 403 to the ccd token alone.

**Roots.** The explorer, editor and uploads reach only a registered project's
`root` in `ccd/registry.py`. The browser sends a project key and a relative
path, never a root. Every path is refused if it holds NUL, control characters,
a backslash, an absolute path, `..`, or a percent-encoded `.`/`..`/separator;
symlinks are resolved and anything whose real path leaves the root is refused.
`.git` is hidden and unwritable at any depth.

**Protected files** (listed with a lock, never read, downloaded, saved or
uploaded; checked on the requested path and again on the resolved path;
case-insensitive). The exact lists live in `ccd/files.py`:

- directories `.git .ssh .gnupg .aws .azure .kube .docker .password-store`
- dotenv files and every variant of them, except the `.example`, `.sample`,
  `.template` and `.dist` variants
- private-key names (`id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`), netrc,
  npmrc, pypirc, git-credentials, pgpass, htpasswd, `credentials`,
  `credentials.json`, `token`, `token.txt`, `secrets.{json,yaml,yml,toml}`
- extensions `.pem .key .p12 .pfx .jks .keystore .kdbx .gpg .asc .token`

**Writes.** Saves are atomic (temp file in the same folder, fsync, rename), keep
the file's mode, refuse symlinks and non-UTF-8/NUL files, and refuse if the
file's SHA-256 changed since it was opened (409). Uploads are raw
`application/octet-stream` (still a CORS-preflighted type), capped at
`upload_max_mb` (default 50), and never overwrite silently: the default fails
on a clash, `rename` and the default place the file with a hard link that
cannot clobber, and `replace` must be chosen explicitly.

**Attachments** live in `~/.local/share/command-center/attachments/` (0700),
named by a random 128-bit id; the original name is display metadata in
`~/command-center/data/attachments.db`. They never enter a repository. Downloads
are always `application/octet-stream`, `Content-Disposition: attachment`,
`CSP: default-src 'none'; sandbox`, so HTML/SVG are saved, never rendered.
The ticket audit trail records `attachment_added` / `attachment_removed` with
name and size only, never contents.

**Terminals (ADR 0004 phase 3).** `WS /api/pty/{name}` needs the ccd token
(subprotocol `ccd-token.<t>`), a Developer Unlock session (subprotocol
`ccd-dev.<id>`), a Host of `127.0.0.1:7777`/`localhost:7777` and an Origin that
is present and the same. Names are `repo:<PREFIX>` (cwd = the registry root) or
`server` (cwd = `$HOME`); nothing from the browser becomes a path. Each is one
login shell as jay in its own process group, started with a reduced
environment (PATH, LANG, LC_ALL, TZ, HOME, USER, SHELL, TERM) and with every
inherited descriptor above 2 closed, so no ccd socket, database or other
terminal leaks in. Output is a 256 KiB ring plus bounded per-viewer queues; a
viewer that falls behind is dropped, never the shell. A browser leaving only
detaches; CLOSE SESSION signals that one process group (HUP, then KILL), an
unattached shell ends after 12 h, and all end when ccd stops. Each shell runs
in its own transient systemd user scope (`cc-pty-<name>-<id>`), outside ccd's
cgroup, so a build in a terminal neither shares ccd's 256 MB MemoryMax nor can
get ccd OOM-killed. ccd's unit sets `NoNewPrivileges=yes`, which the shells
inherit: `sudo` cannot work in a Command Center terminal — by design, there is
no privilege escalation from the browser. Use an SSH session for sudo. Locking Developer
Mode closes open terminal views within seconds. The audit trail records
created / attached / detached / closed / expired with the session name and
viewer count — never input, output or commands.

**PTY session lifecycle.** Every way a session ends also stops that session's
own `cc-pty-*` systemd scope (never any other unit), so background and `nohup`
jobs started in a terminal do not outlive it.

| Event | Process | Scope |
| --- | --- | --- |
| Shell exits by itself (`exit`, Ctrl+D) | already gone | stopped at once |
| Browser disconnects / DETACH | keeps running | untouched |
| CLOSE SESSION | HUP to its group, KILL after 2 s | stopped |
| Idle expiry (unattached 12 h) | same as CLOSE SESSION | stopped |
| ccd stops | every session closed as CLOSE SESSION | stopped |
| `claude:` attach, nobody viewing for 60 s (counted from the last detach) | attach client closed; Claude and its herdr pane live on | stopped |
| Open while that session is closing | waits for it to end, then starts a fresh one | old one stopped |

**Source control** (`/api/scm/*`) runs plain git in a registered root with no
pager, prompt or editor and a timeout. Paths are single files (a folder is
refused, so a folder pathspec cannot reach protected files), passed after `--`
as `:(literal)` pathspecs. Stage all stages only the non-protected paths that
status lists — never `git add -A`. A commit needs the exact staged file list
the browser showed. There is no push, pull, fetch, reset, rebase, force or
hook bypass; repository hooks run as they would in a shell.

**Search** runs ripgrep when installed; otherwise a Python fallback does
fixed-string search only (a user regex is never run in-process, where
backtracking could stall ccd), bounded per file, per line, in hits and time.

**Writes are descriptor-relative.** After validation, every write walks the
resolved path from the root with `O_NOFOLLOW|O_DIRECTORY` and acts on the final
name through that directory descriptor, so a folder swapped for a symlink after
the check cannot redirect it (closes the L1 finding). New names are placed with
`link()`, which cannot clobber. Rename and folder delete check-then-act under
ccd's write lock: atomic against other ccd requests, not against an agent
editing the same tree at that instant.
