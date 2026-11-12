# Remote access over Tailscale

Open CommandCenter from your phone or another computer through your own tailnet. ccd keeps listening on
`127.0.0.1:7777` only; Tailscale Serve on jay-server forwards a private `https://…ts.net` address to it. Nothing is
reachable from the public internet. Background and the controls: `docs/SECURITY.md`, "Remote access over Tailscale".

You run every step yourself. None of it is done by an agent.

## Before you start

- Tailscale installed and signed in on jay-server and on each device you will use, with the same account.
- In the Tailscale admin console, under DNS: **MagicDNS** on and **HTTPS Certificates** enabled. Serve needs both for
  an `https://…ts.net` address.

## Steps

1. On jay-server, start Serve for ccd's port:

   ```sh
   tailscale serve --bg 7777
   ```

   Use `serve`. **Never `tailscale funnel`**: Funnel publishes the address to the internet. ccd refuses requests that
   arrive through Funnel anyway, but do not rely on that.

2. Read the address it prints, or run:

   ```sh
   tailscale serve status
   ```

   It looks like `https://jay-server.tail1a2b3.ts.net`.

3. Add that address to `~/command-center/board/config.json`. Use the exact text: `https://`, no slash at the end, no
   port.

   ```json
   "remote_origins": ["https://jay-server.tail1a2b3.ts.net"]
   ```

4. Restart ccd:

   ```sh
   systemctl --user restart ccd
   ```

5. Check it. If something is wrong in the list, ccd writes a warning line in its log
   (`~/command-center/state/ccd.log`) saying "remote_origins entries refused".

   ```sh
   tailscale serve status
   curl -s https://jay-server.tail1a2b3.ts.net/api/health
   ```

   The first should show `https://…ts.net` proxying to `http://127.0.0.1:7777`. The second should print ccd's health
   report (JSON starting with `{"ok":`), not `bad Host header`.

6. On the phone, open the address in the browser and sign in with the ccd token, the same way as on the desktop. That
   origin keeps its own sign-in, separate from `http://localhost:7777`. Bring the token over yourself; never paste it
   into a chat, a doc or Slack. Developer Unlock works the same as on the desktop.

7. Optional: to make Slack and ntfy links open this address instead of `localhost`, set `notify.slack.link_base` in
   `config.json` to the same URL and restart ccd.

## Undo

```sh
tailscale serve reset
```

Then remove `remote_origins` from `config.json` and run `systemctl --user restart ccd`. After that, only
`http://127.0.0.1:7777` (through the SSH tunnel) works again, as before.

## If it does not load

| What you see | Cause |
|---|---|
| `{"ok": false, "error": "bad Host header"}` | The address is not in `remote_origins`, or is not written exactly as Serve shows it. Also check that ccd was restarted. |
| `cross-origin request refused` | The page was opened from a different address than the one listed. |
| `not served to the public internet` | The request came through Funnel. Run `tailscale funnel reset`. |
| The browser cannot connect at all | Tailscale is off on this device, or HTTPS certificates are not enabled for the tailnet. |
