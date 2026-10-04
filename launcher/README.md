# CommandCenter.exe (Windows launcher)

Double-click to open Command Center on Windows. It replaces running
`scripts/windows/CommandCenter.ps1` by hand.

## What it does

1. Checks `http://127.0.0.1:7777/api/health`. If Command Center already answers
   (an existing tunnel), it just opens the window and exits.
2. If port 7777 is held by something else, it says so and stops.
3. Otherwise it starts a hidden
   `ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -L 7777:127.0.0.1:7777 -- jay-server`
   using Windows' own OpenSSH (`C:\Windows\System32\OpenSSH\ssh.exe`, else `ssh.exe` on PATH),
   and waits up to 20 s for ccd to answer through it.
4. Opens Edge (else Chrome) as an app window with its own profile in
   `%LOCALAPPDATA%\CommandCenter\Browser`. Without Edge or Chrome it uses the default
   browser and shows a "Click OK to stop the tunnel" box instead.
5. When that window closes, it stops the ssh it started. If ssh drops while the window
   is open, it reconnects (2 s, 5 s, 10 s, 20 s, then 30 s; gives up after 8 tries).

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
| Window closes but tunnel stays | Edge may be set to keep running in the background; turn off "Continue running background extensions and apps" in that profile. |

## Build

`scripts/build-launcher.sh` (Linux): vet, test, cross-compile, checks the result is a
GUI-subsystem PE with no credential strings, writes `CommandCenter.exe`, its `.sha256`
and `launcher.json` (version, sha256, commit, build time, size) into
`~/.local/share/command-center/launcher/`.

## Honest status

Built and unit-tested on Linux only. The Windows-only parts (Job Object, hidden ssh,
MessageBox, registry lookup, Edge process lifetime) are proven only by the Windows CI job
(`.github/workflows/launcher.yml`) and by the first real run on Jay's PC.
