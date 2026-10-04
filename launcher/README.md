# CommandCenter.exe (Windows launcher)

Double-click to open Command Center on Windows. It replaces running
`scripts/windows/CommandCenter.ps1` by hand.

## What it does (v0.2.0)

1. If another CommandCenter.exe is already running (per-user mutex
   `Local\CommandCenterLauncher-7777`), it starts no second tunnel: it waits up to
   25 s for Command Center to answer, opens one more window, and exits.
2. Checks `http://127.0.0.1:7777/api/health`. If Command Center already answers
   (an existing tunnel), it just opens the window and exits.
3. If port 7777 is held by something else, it says so and stops.
4. Otherwise it starts a hidden
   `ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -L 7777:127.0.0.1:7777 -- jay-server`
   using Windows' own OpenSSH (`C:\Windows\System32\OpenSSH\ssh.exe`, else `ssh.exe` on PATH),
   and waits up to 20 s for ccd to answer through it.
5. Opens Edge (else Chrome) as an app window with its own profile in
   `%LOCALAPPDATA%\CommandCenter\Browser`. When that window closes, it stops the ssh it
   started and exits.
6. Without Edge or Chrome (or when Edge hands the window to an Edge that was already
   running, so the launcher cannot see it close), it opens the default browser and shows
   a tray icon instead: right- or left-click for **Open Command Center**, **Reconnect**
   (restarts only its own ssh, at once) and **Quit** (stops its ssh and exits). If no
   tray icon can be shown, it falls back to a "Click OK to stop the tunnel" box.
7. If ssh drops while the window is open, it reconnects (2 s, 5 s, 10 s, 20 s, then
   30 s; gives up after 8 tries and says why).

The ssh runs inside a Windows Job Object set to kill on close, so it also dies if the
launcher crashes. Other ssh sessions and tunnels are never touched.

## What it never does

- It contains no token, key or password, and reads none. The ccd token is still pasted
  once into the page (the page remembers it if you tick "remember").
- It does not change SSH config, the registry, or firewall settings.
- The optional log `%LOCALAPPDATA%\CommandCenter\launcher.log` (max 256 KB, one old copy)
  holds only events: start, reuse, ssh exit with ssh's last error line, browser path.

## One-time setup

Your Windows account must already reach the server with `ssh jay-server` and key login,
without any prompt (as you use today). Test in a terminal: `ssh jay-server exit`.
Host-key or passphrase prompts cannot be shown by the launcher; it reports them as a
connection error instead.

Optional settings, `%LOCALAPPDATA%\CommandCenter\launcher.json`:

```json
{"host": "jay-server", "localPort": 7777, "remotePort": 7777}
```

`host` must be a plain alias or name (letters, digits, `.`, `_`, `-`). The two ports must
be equal: ccd only accepts requests addressed to its own port.

## Troubleshooting

| Message | Do this |
|---|---|
| Could not connect to jay-server / ssh said ... | Run `ssh jay-server exit` in a terminal and fix what it says. |
| Port 7777 is in use by another program | Close that program (`netstat -ano \| findstr :7777` shows its PID). |
| Command Center did not answer within 20 seconds | ccd is down on the server: `systemctl --user status ccd`. |
| OpenSSH client was not found | Settings > System > Optional features > add "OpenSSH Client". |
| Double-click only opens another window | Expected: one launcher already runs the tunnel. Quit it from its tray icon to stop it. |
| Window closes but tunnel stays | Edge may be set to keep running in the background; turn off "Continue running background extensions and apps" in that profile. |

## Build

`scripts/build-launcher.sh` (Linux): vet, test, cross-compile, checks the result is a
GUI-subsystem PE with no credential strings, writes `CommandCenter.exe`, its `.sha256`
and `launcher.json` (version, sha256, commit, build time, size) into
`~/.local/share/command-center/launcher/`.

## Honest status

Built and unit-tested on Linux only. `run_test.go` drives every launcher path against a
fake Windows (reuse, foreign port, no ssh, connect error, health timeout, reconnect,
window close, Edge/Chrome/default order, tray Open/Reconnect/Quit, tray-less fallback,
give-up, second launch) and checks that every ssh it started is dead afterwards and no
other process is touched. The Windows-only parts (Job Object, hidden ssh, MessageBox,
mutex, tray icon and its menu, registry lookup, Edge process lifetime) are proven only
by the Windows CI job (`.github/workflows/launcher.yml`: struct layouts, job kills its
child, mutex, tray comes up and goes away) and by the first real run on Jay's PC. CI
cannot click the tray menu; that needs a person.
