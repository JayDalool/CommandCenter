# Remote access over Tailscale

Open CommandCenter from your phone or another computer through your own tailnet. ccd keeps listening on
`127.0.0.1:7777` only; Tailscale Serve on jay-server forwards a private `https://…ts.net` address to it. Nothing is
reachable from the public internet. Background and the controls: `docs/SECURITY.md`, "Remote access over Tailscale".

You run every step yourself. None of it is done by an agent.

## Before you start

- Tailscale installed and signed in on jay-server and on each device you will use, with the same account.
- In the Tailscale admin console, under DNS: **MagicDNS** on and **HTTPS Certificates** enabled. Serve needs both for
  an `https://…ts.net` address.
- In the admin console, check who can reach jay-server. "Only my tailnet" is true only if the access rules say so:
  - **Access controls** (ACLs or grants): only your own devices (your user) may reach jay-server on `tcp:443`. The
    default "allow all" policy also lets any other member of the tailnet in. Today you are the only member; keep it
    that way, or narrow the rule before adding anyone.
  - **Machines › jay-server › Share**: jay-server is not shared with any other tailnet (node sharing).
  This matters because the sign-in page and its one-time code endpoint answer anyone who can reach the address; the
  ccd token and Developer Unlock are still needed for everything else.

## Steps

1. On jay-server, start Serve for ccd's port:

   ```sh
   tailscale serve --bg 7777
   ```

   Use plain `serve` exactly as above: HTTPS in front, HTTP to ccd. **Never `tailscale funnel`**: Funnel publishes the
   address to the internet. Also never `--tcp` or `--tls-terminated-tcp`: in those modes Tailscale passes raw
   connections through and adds no headers, so ccd's Funnel check (it looks for the `Tailscale-Funnel-Request` header
   that Tailscale's HTTP proxy adds) cannot work. Do not rely on that check either way.

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
   tailscale funnel status
   curl -s https://jay-server.tail1a2b3.ts.net/api/health
   ```

   `serve status` should show `https://…ts.net` proxying to `http://127.0.0.1:7777`, and nothing else for port 443.
   `funnel status` should show no Funnel at all (nothing "available on the internet"). The `curl` should print ccd's
   health report (JSON starting with `{"ok":`), not `bad Host header`.

6. On the phone, open the address in the browser and sign in with the ccd token, the same way as on the desktop. Check
   that the page shows live updates (the dashboard changes without a reload) and, if you use it there, that a terminal
   opens: both run over `wss://` to the same address. That
   origin keeps its own sign-in, separate from `http://localhost:7777`. Bring the token over yourself; never paste it
   into a chat, a doc or Slack. Developer Unlock works the same as on the desktop.

7. Optional: to make Slack and ntfy links open this address instead of `localhost`, set `notify.slack.link_base` in
   `config.json` to the same URL and restart ccd.

## Undo

Switch off only this address:

```sh
tailscale serve --https=443 off
```

(`tailscale serve reset` also works, but it removes every Serve and Funnel setting on jay-server, including any you
add later for something else.) Then remove `remote_origins` from `config.json` and run
`systemctl --user restart ccd`. After that, only
`http://127.0.0.1:7777` (through the SSH tunnel) works again, as before.

## If it does not load

| What you see | Cause |
|---|---|
| `{"ok": false, "error": "bad Host header"}` | The address is not in `remote_origins`, or is not written exactly as Serve shows it. Also check that ccd was restarted. |
| `cross-origin request refused` | The page was opened from a different address than the one listed. |
| `not served to the public internet` | The request came through Funnel. Run `tailscale funnel --https=443 off`, then check `tailscale funnel status`. |
| The page loads but never updates live | The browser refused the `wss://` connection. Tell an agent: it is the page's CSP (`connect-src`) or the Serve mode. |
| The browser cannot connect at all | Tailscale is off on this device, or HTTPS certificates are not enabled for the tailnet. |
