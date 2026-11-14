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
| DNS rebinding from a web page | `Host` must be `127.0.0.1:7777` / `localhost:7777`, or a tailnet address Jay names (below) |
| cross-site request from a web page (CSRF) | `Origin`, when present, must be the same origin; actions require `application/json`, which forces a CORS preflight ccd never approves; no CORS headers are ever sent |
| cross-site WebSocket hijacking | same Host/Origin/token checks on the upgrade |
| typing escape sequences into a pane | answers and notes must be printable, one line; control characters refused |

The token is never logged (uvicorn's access log is disabled because a WS token
can be a query string) and never returned by the API. The legacy board reads
the file directly; the Windows client will fetch it over the SSH connection
that carries the tunnel.

## Remote access over Tailscale (Jay, 2026-11-12)

D-006 kept ccd off the public internet and left remote access to a later, separately approved design. Jay chose
Tailscale Serve for it (HQ launch plan, question B1); a public tunnel such as Cloudflare is a separate decision.

- ccd still listens on `127.0.0.1` only. `tailscale serve` on jay-server forwards
  `https://<machine>.<tailnet>.ts.net` to it, and only devices signed in to Jay's tailnet can reach that name.
- `config.json` `"remote_origins"` lists those addresses exactly (`https://`, a `*.ts.net` name, no port, no path).
  Each adds one allowed `Host` and one allowed `Origin`; anything else in the list is refused and logged, never
  widened. With the list absent, nothing changes.
- A request carrying `Tailscale-Funnel-Request` (Tailscale's HTTP proxy adds it to traffic that arrives through
  Funnel, its public mode) is refused on every address, `/api/health` included. It is a backstop, not the control: in
  raw TCP modes (`--tcp`, `--tls-terminated-tcp`) no header is added, so the runbook allows plain HTTP Serve only and
  checks `tailscale funnel status`.
- "Only Jay's devices" depends on the tailnet's access rules and on jay-server not being shared to another tailnet;
  the runbook checks both before setup. The sign-in redeem endpoint (no ccd token, a 256-bit one-time code) is the
  only thing reachable without the token.
- The page's CSP names each tailnet origin's `wss://` address in `connect-src`, so live updates and terminals do not
  depend on a browser matching `'self'` to `wss:`.
- Not done, on purpose: requiring Tailscale's identity header (`Tailscale-User-Login`) for the remote Host. Anything
  that can reach ccd without Serve is already on jay-server's loopback, where it could send that header itself.
- The token, Developer Unlock, the JSON-only rule and every other check are unchanged. A phone or laptop on the tailnet
  still needs the ccd token, and Developer Unlock for anything that writes.

Setup and undo: `docs/runbooks/remote-access-tailscale.md`.

## What leaves ccd

Rendered state only: project keys, names, repo slugs and paths; agent pane
ids, canonical names, roles, states and working directories; PR/issue numbers,
titles, CI marks; checkbox counts and lines from `docs/jay/*.md`; host numbers.

**`/api/health` needs no token** and, since the launcher's tray notice (CC-023), carries `gates: {open, last}`:
two integers, the number of open owner gates and the id of the newest gate/blocked event. So another local
user or process can see how many items wait for Jay and roughly when the pipeline last needed him (the
activity rhythm). It reveals no ticket key, title, reason or project. The alternative was to give the
launcher a token, which `launcher/binary_test.go` forbids on purpose.

**`GET /api/night-shift` (token-gated) serves agent-written text**: the newest morning report of each project, up
to 64 KB (`nightshift.REPORT_MAX`), read as bytes from `~/command-center/night-shift/<project>/` (a plain `.md`
file, no symlink, project key matched against `^[a-z][a-z0-9_-]{0,31}$`). The coordinator Claude writes it, so
it can quote anything the coordinator saw: the page shows it as text, and the instructions tell it to copy no
licensed data, records or secrets into a report. It leaves ccd only to a client holding the ccd token, like the
rest of the API, and is never stored in SQLite or the log.

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

**One GitHub write, off by default (CC-025, ADR 0007).** ccd can run `gh pr merge` for a reviewed, low-risk
Command Center PR. It needs all of: `auto_merge: true` in `config.json` (default `false`), registry merge policy
`low-risk` (only `commandcenter`), and no file `~/command-center/state/auto-merge.stop` (the kill switch, checked
immediately before every merge; `touch` it to stop at once, delete it to resume). `ccd/merge_policy.py` decides:
only added or modified `server/tests/**/*.py`, `web/app/tests/**/*.ts(x)`, `docs/**/*.md` and `README.md` files, at most
10 files and 300 lines, never `server/ccd/**`, `scripts/**`, `launcher/**`, `.github/**`, `web/app/src/**`,
lockfiles, manifests, `plans/**`, `docs/SECURITY.md`, `docs/adr/**`, any dot-folder or dot-file at any depth (`.claude/`, `.mcp.json`, `.codex/`), `__pycache__`, or `AGENTS.md`, `AGENTS.override.md`, `AGENT.md`, `CLAUDE.md`, `CLAUDE.local.md`, `GEMINI.md`, `SKILL.md` anywhere.
The command is `gh pr merge N --repo <registry repo> --merge --match-head-commit <reviewed head>`: never `--admin`,
`--auto`, `--squash` or `--delete-branch`, and GitHub refuses it if the head changed. ccd uses the `gh` login of the
user it runs as; no token is read, stored or logged by ccd. Everything else (and any failure) opens a merge gate for
Jay. Audit: security events `merge.policy` (state at startup) and `merge.auto` (each merge, hold or failure), ticket
events `pipeline.auto_merged / auto_merge_held / auto_merge_failed` (actor `system:auto-merge`). Agents never merge.

How strong that is, plainly: agents run as the same user as Jay, so they can write `config.json` and the state
folder, and their `gh` is logged in as Jay. "Agents never merge" and "Jay switches it on" are written rules plus
review, not technical blocks; ccd reads `auto_merge` only at start, so a config edit does nothing until ccd is
restarted. The reviewer's "fresh review" is self-reported: ccd checks the recorded APPROVE, its session name and
the exact head, not who really read the diff. Details and the missing separation (a second GitHub identity or
branch protection): ADR 0007.


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
filed under Jay; it is not authentication. Since PR 7 every write is also
recorded with how far its actor is proven (below), but nothing is refused yet.

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
gets a random session id. The token itself is never stored. **Once per app
session (control room, spec §27):** the session id is kept in the tab's
`sessionStorage` (so a reload does not ask again) and handed to Command Center's
own other windows — pop-out terminals and rooms, a second Workspace window — over
a same-origin `BroadcastChannel`; never a URL or the page. A plain unlock ends on
LOCK (in any window: every window locks), when the browser session ends, 2 h idle
or 8 h total. Five wrong developer tokens at unlock and handoff in five minutes
lock both for five minutes; both need the ccd token. Write routes answer 403 to
the ccd token alone. The ccd token reaches a pop-out window the same way when the
browser does not copy `sessionStorage` into it.

**Developer Unlock that lasts (contract §6, Jay 2026-11-14).** Unlock asked too often, so:

- **It survives a ccd restart.** Sessions are saved to `~/command-center/data/developer-sessions.json` (0600, written
  atomically). For each session the file holds an HMAC-SHA256 of its id keyed with the developer token, its kind,
  three times (made, last used, last proved) and a device label. **Never the session id, never the developer token.**
  The file also carries an HMAC of a fixed string under the same key, so a file written under another
  `developer.token` is ignored whole: changing `developer.token` ends every session. Consequences: reading the file
  gives no session (it holds no id, and the HMAC cannot be reversed); writing an entry into it without the token
  matches no id; the limits come from the kind in code, never from the file; and each row carries an HMAC over its
  kind, times, id and label, so an edited row (say, a plain session turned into a remembered one) is dropped. A time
  in the future is dropped too, and if the server clock goes backwards the sessions it would stretch end. A file another user can read or that
  another uid owns is ignored and replaced on the next save. "Last used" reaches the disk at most once a minute;
  unlock, lock, lock-all and expiry are written at once. If the file cannot be written, sessions keep working from
  memory and simply do not survive the next restart. Wrong-token counts stay in memory (a restart clears them;
  only jay can restart ccd).
- **"Remember this device"** (`remember: true` at unlock): 30 days, no idle limit. The browser is to keep that
  session id in `localStorage` (the unlock-dialog checkbox, the Settings device list and the re-entry prompt are the
  web side's part of contract §6 and land after this server change) instead of `sessionStorage` so it outlives the tab; anything running in Command Center's own
  origin could read either, so the defences against script injection (CSP, no third-party script, sanitised
  rendering) are what protect it, as they protect the ccd token beside it. Plain and SSH sessions keep their limits
  above.
- **The terminal and file writes keep short limits.** A remembered session older than 8 hours since the token was
  last typed can still approve and answer, but the live terminal (`WS /api/pty/*`), typing a free-text prompt into a Claude pane
  (`/api/action/prompt`, which can make that agent run anything) and every file write
  (`/api/files/save|upload|mkdir|rename|duplicate|remove`, `/api/scm/*`) refuse it: 403 `{reenter: true}`, and an
  open terminal closes with code 4412. Typing the token again (`POST /api/developer/unlock` with the same
  `X-CCD-Developer`) re-proves that session in place for another 8 hours. Plain sessions (8 h) and SSH sign-in
  (12 h, proved by Jay's SSH key) are unaffected. So a stolen remembered id can do what Jay's clicks do for up to a
  month, but cannot open a shell, prompt an agent or change code past one working day, and Jay can end it at once with:
- **Lock all devices** (`POST /api/developer/lock-all`, Settings): every session on every device ends, with every
  unredeemed sign-in code, in memory and on disk. It needs a live Developer session, so the ccd token alone (which
  processes running as jay can read) cannot lock Jay out. Settings lists the devices holding a session
  (`GET /api/developer/devices`: label, kind, created, last used, expiry; never an id). LOCK ends just this one.

What the file does not defend against: a process running as jay can put back an older copy of it, which would
bring back sessions that Lock all ended. Such a process can also read `developer.token` itself, so the file adds no
new power; the unlock defends against clicks that do not come from Jay, not against code already running as jay
with the token in reach.

Why the unlock stays at all: on this server the ccd token is readable by every process running as jay, agents
included. Developer Unlock is the one proof that a click came from Jay at a screen and not from an agent approving
its own work, so it is made to last, not removed.

**SSH sign-in (control room).** Typing two tokens was the friction; an SSH key login is the stronger
proof and CommandCenter.exe already makes one for its tunnel. Over it the launcher runs the fixed helper
`scripts/cc-session`, which — as jay, the only user who can read `developer.token` — calls
`POST /api/developer/handoff` (ccd token + developer token). ccd mints a Developer session that lasts the
working day (12 h, no shorter idle limit) and a **one-time code, valid 120 s**. The launcher opens
`#/?signin=<code>` (a URL fragment: never sent to any server); the page strips it at once and trades it at
`POST /api/developer/redeem` — the one `/api` route that takes no ccd token, still behind the Host and
Origin checks, JSON-only — for the ccd token and the session. Wrong or reused codes are refused and not counted: a code is 256 random
bits, good once for 120 s, and counting tokenless guesses would let any local user lock Jay out. ccd logs that a code was issued, never the code.
A page cannot mint a code: minting needs both tokens, which only a process running as jay can read.
`commandcenter://unlock` (any web page can open it) can only make the launcher open Command Center's own
address with a fresh code, which only Command Center's own origin can read.

**What reaches a Claude pane.** Typing into Claude stays a Developer action:
`POST /api/action/prompt` (DEVELOPER), the terminals (DEVELOPER), and Jay's
answers to Claude's questions — `POST /api/tasks/{key}/answers` needs `jay`
**and** Developer Unlock, and only ever goes to the ticket's EXISTING task
session (named after the key, e.g. `sv-071`, via herdr `agent.prompt` on an
idle pane); nothing is started when none runs. A pipeline step Jay takes
(rework, re-plan, approve a plan or a live deploy) tells that session what he
decided only when Developer Unlock is active. The one agent-initiated delivery
is a worktree handover WITH a checkpoint (`writer` step, spec §20): one fixed
sentence telling the task session to read the checkpoint with
`pipeline_cli work <KEY>` — the checkpoint's free text is never typed into
Claude. A task session is only ever a live Claude whose herdr name or label is
the key (never a terminal title), and never a pane that resolves as a
coordinator. When a ticket closes through a pipeline step, or by Jay with
Developer Unlock, its task terminals close and its task session is asked to
`/exit` once it is idle (checked for up to 10 minutes; a still-busy one is left
running and reported). A close by a plain edit with the ccd token alone stops
nothing: it records that the sessions were left running.

**Worktree removal (CC-024).** ccd deletes a directory on its own in exactly one
case: a DONE ticket's recorded worktree, at the end of ccd's git poll, and only when
every check holds (`ccd/worktree_cleanup.py`): the path is strictly inside
`/srv/server/worktrees/` or `<project root>/.claude/worktrees/` with no symlink
below those folders; git lists it as a linked worktree of the ticket's repo
(not the main checkout, not locked) with the ticket's own branch checked out (so
Claude Code's `agent-*` worktrees never match); `git status` is empty; no commit is
missing from the remotes ccd last saw (it never fetches, so a stale ref only keeps
more); no other worktree is nested inside it; one walk of the whole tree (symlinks not
followed, at most 200,000 folders, about 0.1 s for a 60,000-entry tree) finds no entry named
`.git` (folder, gitfile or symlink, in any tracked, untracked or ignored folder, however
empty its parent) and no folder shaped like a bare repository: git shows nothing inside
those and `worktree remove` would delete them; no tracked file is hidden from
`git status` (skip-worktree, assume-unchanged); no merge, rebase, cherry-pick, revert or
bisect is in progress; no commit is held only by the worktree's own HEAD reflog or
`refs/worktree/*` (both are deleted with it; commits that a branch reflog also names,
such as an amend or reset on the branch, do not count); every quick check is repeated
right before the removal, after the walk; herdr is connected and no pane and no process
has its working directory
inside it. The only command is `git -C <repo> worktree remove <path>`: no
`--force`, no `rm`, the branch is never deleted. Ignored files (node_modules, .venv,
local copies of secrets) go with the directory; the branch and its pushed commits
stay, so `git worktree add <path> <branch>` brings the work back. Any failed check
keeps the worktree and records `pipeline.worktree_kept` once per reason. No route,
no browser input and no agent can start it or name a path; the path is the one a
pipeline `start` recorded. Kill switch: `"worktree_cleanup": false` in config.json.

*Known limits of the removal.* (1) After a removal, a commit dropped by an amend or reset on
the branch survives only in the branch's reflog, until that reflog expires or the branch is
deleted; it is not on any remote. (2) A commit held only by a `refs/worktree/*` ref's reflog
(a contrived setup; the ref itself is checked) is not seen. (3) A squash or fixup rebase leaves
interim commits only in HEAD's reflog, so that worktree is kept: the safe direction. (4) The
herdr pane list is read once before the checks; a pane opened afterwards is caught only
through the `/proc` working-directory check. (5) Processes of other users cannot be read.
(6) Ignored files with real content (local databases, secret copies) go with the directory:
Jay's decision.

The night shift adds fixed messages to the **coordinator's** pane, all through herdr `agent.prompt` and never
into a pane that waits on a prompt (ADR 0006). Jay's presses need `jay` **and** Developer Unlock: Night shift
(the `/night-shift` rules), End night shift (one stop-safely sentence, no Esc) and Go Live (a message to PREPARE a
deploy, which authorizes no deploy: Jay confirms it himself in that pane). The one automatic sender is the
**supervisor** (`nightshift.py`, `Daemon.night_loop`): while a night shift Jay started runs, it types one fixed
reminder into an idle coordinator, at most every 10 minutes, counted only once delivered. herdr "idle" only
means ready for input, and `agent.prompt` pastes and presses Enter, so before each reminder ccd reads the pane's
text (not stored or logged) and skips the reminder, uncounted, unless Claude's prompt line is plainly empty or
shows its placeholder; a screen it cannot parse is skipped. This is a best-effort check on screen text: a draft
it misreads, or typed between the read and the paste, can still be submitted. The hard limits bound that risk:
it stops after 6 reminders in a shift, after the morning cutoff (07:00 local by default), when the report says
complete, or after 3 reminders with no ticket or report change. The reminder text is a constant; no report or
ticket text is ever typed. (Go Live, End night shift and the other buttons are Jay's own presses and do not
make this check.)

**What a Go Live approval is.** A live-deploy gate that Go Live confirms is a full approval in the pipeline:
afterwards any agent may record `deployed --env live` for that ticket. That the deploy waits for Jay's
confirmation in the coordinator's pane is enforced only by the message text, not by ccd. The record is marked
(`approvedBy: "jay:go-live"`, event "approved for a prepared deploy (Jay confirms in the pane)") and Go Live
approves only the tickets listed in the confirm box that are still open. The per-ticket **Approve live deploy**
button (and WorkPanel's) is the same: a real live-deploy approval, marked `approvedBy: "jay:gate"` with the same event
text, and the message typed into the task session (`daemon.GATE_DEPLOY_TEMPLATE`) asks Claude to PREPARE the deploy and
wait for Jay to confirm in the pane. That wait rests on the message text only; `deployed` checks just `approvedAt`.

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
is present and the same. Names are `repo:<PREFIX>` (cwd = the registry root),
`codex:<PREFIX>` (Codex if installed, else a shell saying so; same cwd),
`repo:<KEY>` / `codex:<KEY>` (a Task Room: cwd = that ticket's recorded worktree
only when it is a known git worktree of the project or inside its root, else the
root), `claude:<PREFIX>` / `claude:<KEY>` (the herdr attach client for the
existing coordinator / task session) or `server` (cwd = `$HOME`). Names are
matched against fixed patterns; nothing from the browser becomes a path. Each is one
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


## v2 Phase 1: policy files (D-007, D-008)

`policy/` holds the Project Operating Profiles and Jay's decisions. They grant nothing yet: `[target]` is read by
the shadow-mode engine only, and `[enforced]` must equal the registry. Who may change them: Jay. Controls today are
review plus visibility, not a technical block (agents still run as the same user): `policy/**` can never
auto-merge (merge_policy DENY), each load records every file's SHA-256 and a combined fingerprint as the
security event `policy.loaded`, and a broken, missing or drifting file raises the `policy:problems` alert. A
profile that fails validation is unusable (`Policy.profile()` returns None) and the engine will treat it as the
most restrictive policy. `GET /api/profiles` is token-gated and read-only; there is no write route.

## Worker node tokens (v2 Phase 1)

A worker node (e.g. the laptop) enrols with ccd's bearer token and receives its own node token once; ccd stores only
the token's SHA-256 and compares in constant time. A node is unusable until Jay approves it (Jay AND Developer
Unlock); a revoked node's token never works again and its name is never reused. The node token proves which node is
calling `POST /api/workers/heartbeat`; on its own it grants nothing else yet (but see below). Jobs and per-job tokens come in Phase 2.

**What a node really holds today.** Enrol and heartbeat both also need ccd's bearer token (every `/api` route
does), so an enrolled machine keeps ccd's token as well as its node token. ccd's token reads and steers everything
short of Developer Unlock and can claim any `X-CCD-Actor`, so only enrol machines that already hold it (Jay's own
laptop). Per-actor tokens (PR 7) and a heartbeat that needs only the node token are the fix.

**Approving the right machine.** Each node has a fingerprint (`abcd-ef01`, the start of its token's SHA-256). The
enrol response returns it for the node to print; Settings → Workers shows it with who enrolled the node and when.
Approve only when the two match: that check is the real guard. Enrol refuses an `agent:*` actor, but
`X-CCD-Actor` is self-asserted until PR 7, so that only stops an agent that names itself honestly. At most 10 nodes
can wait for approval. Anyone holding ccd's token can enrol a name first and so use it up for good (revoking is
final); that is within the boundary above, where ccd's token is already full power.

## Onboarding groundwork (D-024 proposed; off by default)

Jay (2026-10-23) allowed policy-independent groundwork behind a disabled flag and nothing more: no permission
granted, no agent started, no proposed policy enforced. `ccd/onboarding.py` and tasks.db v10 hold it.

- **Off unless `config.json` says `"onboarding_groundwork": true`** (the literal `true`, read at start). Off, every
  `/api/onboarding` route answers 404 before looking at anything else, nothing goes to the activity log, and the
  only difference from before is migration 10's empty tables (a refused write is still an audit row, like any write).
- **Records, not power.** An agent record is `registered` or `retired`; the schema has no active state, no grant
  table and no credential column. Registering issues no actor token and starts no session. Requested permissions are
  stored for review and checked against each permission's hard ceiling (`repo.merge`, `data.prod`, `infra.*`,
  `prod.browser_write` can never be more than `deny`); nothing reads them to allow anything.
- **Who writes.** Every write needs Jay AND Developer Unlock (daemon), any non-`jay` actor is refused (module), and
  the schema CHECKs `created_by`, `retired_by` and every event's actor to be `jay`. Because `X-CCD-Actor` is still
  self-asserted, Developer Unlock is the real check, as for WorkerNode approval.
- **No secrets.** A draft whose keys or values look like a token, key, password or credential URL is refused whole:
  nothing is stored, not even a scrubbed copy, and the error names only where it was found.
- **History.** Registrations, configuration versions, drafts and events are never deleted (triggers); a retired ID
  is never reused; a closed draft is final; each record lands with its event in one transaction; each HTTP write is
  also in the audit trail (body hash and keys only).
- **Budgets in shadow.** `GET /api/onboarding/budgets` reports where a D-033 hold would apply. It stops nothing.
  Missing data never makes spend look smaller: a reply with no known price counts at the highest listed price,
  usage tied to no project counts toward the company budget, and with no fresh meter reading for 15 minutes spend
  is Unknown and a scope at 80 % of its limit or more would hold. Each gap is named in `dataAlerts`.
- **Migration 10 and its way back.** v10 only adds four empty tables. `python -m ccd.migration_safety drill` proves
  on a copy that existing rows, indexes, triggers and the audit chain are unchanged, that an older ccd refuses the
  file, and that the rollback and the backup both return a file an older ccd opens. The rollback (ccd stopped) takes
  a backup first and refuses, changing nothing, while any onboarding table holds a row, so history is never
  dropped; after that point the way back is rolling forward, or the backup taken before the upgrade
  (`docs/runbooks/tasks-db-v10-rollback.md`). A drill report made with `--redact` names no path, host or user and
  never holds row contents; `--clean` deletes the copies of the data after the run.

## Messages (Jay's answers C1-C8, 2026-11-12)

Jay talks to the CTO and each project lead in HQ's Messages (docs/API.md, Messages).

- **Nothing Jay writes is typed into a terminal** (C2 b). The lead gets one fixed nudge through herdr's `agent.prompt`,
  only while idle and only when its input line reads as empty (the night-shift check), so a half-typed draft is never
  submitted. The nudge names the conversation and the two commands; the lead reads the words with `cc-inbox`.
  The nudge's wording is neutral: it says a message is waiting and that the lead's usual rules, gates and approvals
  apply to anything it asks. A message is never an approval.
- **Who.** No Developer Unlock (C3). Jay's side is the ordinary ccd token with no `X-CCD-Actor`; an agent writes only as
  its own conversation's lead (`agent:lead-<conv>`, `agent:cto` for `cto`): it reads only through that conversation's
  inbox and only that conversation's files, cannot list conversations or read history, cannot mark Jay's side read
  and cannot start a lead. Any other agent actor is refused. Jay's side is limited to 30 messages a minute per
  conversation. As everywhere else, `X-CCD-Actor` is self-asserted: anything holding the token could write as Jay or
  as any lead. The binding stops one lead wandering into another's conversation by mistake; it is not a boundary
  against a hostile process, which waits for Phase 2 identity like every other route.
- **Storage.** `DATA_DIR/chat.db` (created `0600`) and `SHARE_DIR/chat-files/` (`0700`), apart from `ccd.db` and
  `tasks.db`, never in a repository. This is the one store that holds conversation text, because Jay asked to keep all
  history (C4). Text that looks like a token, key, password or credential URL is refused whole (`onboarding.SECRET_RE`).
  Text may not hold control or format characters (C0, C1, bidi overrides, zero-width) other than newline and tab.
  Events and the audit trail record which conversation and message, never the text.
- **Files** (C6). The type comes from the first bytes (PNG, JPEG, GIF, WebP, `%PDF-`), and a text file must also be
  named `.md`, `.markdown` or `.txt` and decode as UTF-8 with no control characters (so no terminal escape codes
  reach a lead's `cat`) and nothing that looks like a secret; SVG, HTML and everything else are refused before
  anything is kept. The stored name always ends in an extension of the detected type (`run.bat` → `run.bat.png`), so
  a file saved by `cc-inbox` or a browser never opens as something else. At most 20 unsent files per conversation
  and side; blobs left without a row by a crash are swept when ccd starts. `cc-inbox` saves only into a real
  `0700` folder of its own account (never through a symlink), and `cc-reply` checks a file's size before reading it. Names are display text only (the generated id is the path; no `/`, control or bidi
  characters). Downloads are `application/octet-stream` + `attachment` + `Content-Security-Policy: sandbox`. HQ shows
  an image by fetching its bytes and making a `blob:` of the stored image type; the UI's CSP gains `img-src blob:`
  for that, and nothing else. Markdown is shown as plain text, never rendered as HTML.
- **Starting a lead** (C7) is the one place ccd starts a Claude. Only Jay, only from Messages, only while
  `chat_start_leads` is true, never for a paused project, and never when an unidentified Claude already sits in the
  lead's folder. A budget at its hold refuses the start until Jay confirms it; the confirmation is recorded. It runs
  herdr's own CLI: `workspace create --no-focus` (a new workspace at the lead's folder) and `agent start <name>
  --kind claude` in its root pane. It splits, moves, closes and stops nothing; a failed start leaves the workspace
  for Jay to see.

## Audit trail, actor identity and metering (v2 Phase 1, PR 7)

**Audit trail** (`ccd/audit.py`, tasks.db v9 `audit_events`). One row for every write (`POST/PATCH/PUT/DELETE`)
that got past the token check, and for each pipeline event ccd itself produced (`system:ccd`). A row keeps: time,
claimed actor, how it is proven (`developer` = a live Developer Unlock session and the claim is `jay`; `token` = an
actor token, verified only when it names the claimed actor; `none`; `system`), method, path, response status,
project and ticket when the path or body names them, the policy fingerprint, the SHA-256 of the JSON body and its
top-level key names. **Never the body itself**, and for the Developer Unlock routes not even its hash (their body
is the developer secret). Requests without ccd's token are not recorded, so the table cannot be flooded from
outside; a failed sign-in-code redeem is not recorded either. Triggers refuse UPDATE and DELETE; each row also
carries `sha = sha256(prev_sha + row)`, so editing or removing any row but the newest breaks the chain. Settings → Audit checks rows added since
the last good check on every look, and the whole chain on request (`GET /api/audit?full=1`).
Recording happens after the response and never changes it; a failure to record is logged.

The Developer Unlock check used for recording is read-only (`DeveloperGate.peek`: it does not refresh the session's idle timer).

**Actor tokens** (`ccd/identity.py`, `actor_tokens`). Jay, with Developer Unlock, issues a token to one agent
(`agent:<name>`, never `jay`: Jay is proven by Developer Unlock). It is shown once (`cca_…`); ccd keeps its SHA-256,
an expiry (default 30 days, at most 365) and a fingerprint. Tokens are never deleted, and the only change allowed is
one revoke. An agent sends it as `X-CCD-Actor-Token` next to `X-CCD-Actor`. **Nothing requires it yet**: a write
without it, or with one naming a different actor, still happens and is recorded as unverified (a mismatch is flagged).
Settings → Audit shows what requiring it would refuse; turning that on is Phase 2 and needs Jay's decision. Limits:
an actor token lives wherever the agent keeps it, in the same Unix account as ccd's token, so it raises the bar for
honest mistakes and makes a false claim visible, not impossible; per-job tokens on separate workers (Phase 2) are
the stronger fix.

**Typed identity tokens and the shadow identity record** (Phase 2 shadow step 1, tasks.db v11; Jay 2026-10-25).
New tokens live in `identity_tokens` and are typed by prefix so a leaked one is recognisable: `cca_a_…` for an agent
(`agent:<name>`), `cca_s_…` for a service (`svc:<name>`); Jay may bind one to a single project. The same rules hold:
issued only by Jay with Developer Unlock, shown once, SHA-256 kept, expiry, never deleted, one revoke (triggers also refuse a replacing INSERT). Tokens from before v11 (`actor_tokens`) still verify and are
revoked by their negative id. From v11 every newly issued token is typed and stored here, whatever the flag below
says. `X-CCD-Actor` itself is unchanged (`jay` or `agent:<name>`): a service token holder sends no actor header, and
its write is recorded as the default actor with `via: token`, not verified, "service token; no actor header". With `config.json`
`"phase2_identity_shadow": true` (default **false**) every recorded write also gets an `identity_observations` row,
in the same transaction as its audit row and chained to it: the asserted actor (or none), the **resolved actor**
(`jay` only with Developer Unlock, a token's subject with a valid token, else `unknown`), and the reasons Phase 2
enforcement would refuse it (`missing_header`, `unverified`, `asserted_mismatch`, `jay_without_unlock`,
`project_mismatch`, judged on the project of the ticket the path names, in any case, or else, when the path names no
ticket, the body's `project`; a write that names neither is not checked). A service token with no actor header is judged by its own subject. **It refuses
nothing**: `enforced` is 0 and the table's CHECK refuses any other value, and a
shadow row that cannot be written is skipped without losing the audit row (`identityErrors` counts them). Enforcing
any of it is a separate decision for Jay.

**Worker node keys and signed heartbeats** (Phase 2 shadow step 2, tasks.db v12; Jay 2026-10-25; `ccd/nodekeys.py`).
With `config.json` `"phase2_node_shadow": true` (default **false**) a node may send an Ed25519 public key when it
enrols (`python -m ccd.nodekeys init --dir DIR` makes the pair; the private key is 0600 in a 0700 directory and never
leaves the node). ccd keeps the public key in `node_keys` with a 16-hex fingerprint, which enrol returns and
`GET /api/workers` lists. Settings → Workers does not show it yet, so **approving a node does not approve its key**:
every key stays `key_not_approved` until a later step adds a screen where Jay compares the fingerprint the node printed
and approves the key on purpose. Revoking a node revokes its key. Keys are never deleted or replaced, a node has at
most one live key (a second one is recorded as `node_has_key`), a key is never reused across nodes (`duplicate_key`),
and the database refuses a row added as `agent:*` (that name is the caller's own claim until Phase 2 enforces
identity, so this is a guard, not a proof). Each heartbeat
may carry `X-CCD-Node-Signature: v1 ts=… nonce=… sig=…` over `ccd-node-v1`, the method, path, node id, time, nonce
and the SHA-256 of the canonical JSON body. ccd checks it and appends a `node_observations` row (its own hash chain)
with the reasons Phase 2 would refuse it: `unsigned`, `malformed`, `no_key`, `key_not_approved`, `bad_signature`,
`stale_timestamp` (more than 60 s off), `replayed_nonce` (seen in the last 10 minutes; only a verified signature
records a nonce, so forgeries cannot burn one), `node_pending`, `node_revoked`, `bad_node_token`, `bad_key`,
`duplicate_key`, `node_has_key`. The canonical body is Python's `json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=True)` (non-ASCII text as `\uXXXX` escapes); a non-Python node must match it exactly. The signed path is the path ccd sees, so a proxy that
rewrites a path prefix would make every signature fail (none does today).
**It refuses nothing**: every heartbeat and enrolment answers exactly as before, `enforced` is 0 (CHECK), and a check
that fails is counted (`shadow.errors`), never raised. Not covered yet: the server node (ccd's own host heartbeats
in-process), capability claims beyond what Jay approved, job claims and key rotation; existing nodes must re-enrol to
get a key, under a new name (revoked names are never reused). Observations are kept for good, like the audit trail (about 200 bytes each; a retention rule comes with
enforcement). Verification uses PyCA `cryptography` (pinned in requirements.txt); if it is missing, ccd still starts and
logs a warning with the check off.

**Capability Broker, recorded only** (Phase 2 shadow step 3, tasks.db v13; Jay 2026-10-25; `ccd/broker.py`). With
`config.json` `"phase2_broker_shadow": true` (default **false**) ccd records, just before each action that exercises
authority, what the Phase 2 Broker would decide. The design's eight checks are each `ok`, `n/a`, `deny` or `unknown`,
and unknown counts as deny:
- `actor`: who the request proves to be (`identity.resolve`, as in the identity shadow); ccd acting on its own is
  `system:ccd`;
- `agent_grant` and `task_mode`: these do not exist yet, so they are `unknown` for every agent;
- `project`: the profile is present, valid and the project not paused;
- `node`: today every action runs on the server;
- `capability`: which kinds of actor may use the verb at all. Writes inside Jay's own checkout (`repo.write`, the
  Workspace's stage/unstage/discard/commit/branch, and `worktree.remove`) are denied for everyone, because Phase 2
  moves them to a mirror the Broker owns;
- `approval`: Jay's live Developer Unlock for his own actions, the Autonomy Engine's verdict "auto" for a merge ccd
  makes itself (`gh pr merge` in auto-merge), and the ticket's recorded deploy approval for `deploy.record`;
- `egress`: no recorded verb sends data out, so `n/a`.

Verbs and where they are recorded: `pr.merge` (auto-merge, and Jay's Merge for each PR the coordinator is asked to
merge), `go_live.approve`, `deploy.request` and `deploy.record` (pipeline steps), `pane.input` (answer, prompt and
key from the UI, Task nudges, dispatch, coordinator messages, night-shift nudges and end), `repo.write` and
`worktree.remove` (recorded after git removed it; the cleanup decides inside its own thread). Each row goes into
`broker_observations`, which has its own hash chain, `enforced` fixed at 0 by a CHECK, and append-only triggers.
A row is an attempt as the Broker would see it, not proof the action completed: a few are written before a check
that can still refuse the request (a pipeline step's own 400/403/409, or no idle coordinator for Merge and Go Live);
the audit trail and events say what happened. `GET /api/broker` shows the summary and the newest rows. **It refuses nothing**: every action runs exactly as before,
the record is written before the action and never raises (a failure is counted in `errors`), and with the switch off
nothing is recorded. The API caller's identity reaches the record through a context variable set by `BrokerContext`
in api.py, which reads only headers. Not covered yet: the terminal WebSocket, node job claims and writer claims (not
built), token issuance and revocation, merges an agent does with Jay's `gh` login outside ccd, and single-use approval
records bound to a PR head (the approval term uses today's gates instead). The record is kept for good, like the audit
trail.

**Metering** (`ccd/meter.py`, `usage_records`). Every 5 minutes ccd reads what is new in the agents' own session logs
on this machine (`~/.claude/projects/**/*.jsonl`, `~/.codex/sessions/**/*.jsonl`), off the event loop, at most 8 MB
a pass. From each line it keeps only the model, token counts, time, session id, working directory and branch (to tie
the use to a project and ticket); **message text is never stored**. A work step may also report its own `usage`
object; it is shown separately and never added to the totals (it is usually the same replies again). Costs are estimates at Anthropic list prices (a subscription is not billed per token; Codex is counted in
tokens only). Profile budgets (`target.budget`) are displayed against month-to-date use; nothing is stopped when one
is passed. Set `"meter": {"enabled": false}` in config to turn reading the logs off.
