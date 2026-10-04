// First run: paste the ccd token. It goes to sessionStorage (or, if remembered,
// localStorage) for this origin only — never the URL, never the page source.
import { useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { usePrefs, commands, servedPort, tokenFile, LIVE_PORT } from "../lib/prefs";
import { TOKEN_SHAPE } from "../api/auth";
import { Command } from "../components/ui";

export function Connect() {
  const err = useSelector(app.store, (d) => d.authError);
  const checking = useSelector(app.store, (d) => d.auth === "checking");
  const host = usePrefs((p) => p.sshHost);
  const [token, setToken] = useState("");
  const port = servedPort();
  const [remember, setRemember] = useState(false);
  const ok = TOKEN_SHAPE.test(token.trim());
  return <div className="connect"><main className="connect-card" aria-labelledby="connect-title">
    <div className="dialog-head"><span className="brand-mark" aria-hidden><i /><i /><i /><i /></span>
      <h1 id="connect-title" className="brand-name">Command Center</h1><span className="brand-host" style={{ marginLeft: "auto" }}>{host} · 127.0.0.1:{port}{port !== LIVE_PORT && " · preview"}</span></div>
    <form className="dialog-body" onSubmit={(e) => { e.preventDefault(); if (ok) void app.login(token, remember); }}>
      <ol className="connect-steps">
        <li><span className="mono muted">1</span><span>Tunnel from Windows (keep it open):<Command cmd={commands.tunnel(host, port)} /></span></li>
        <li><span className="mono muted">2</span><span>Copy <span className="mono">~/{tokenFile(port)}</span> — this ccd's own token:<Command cmd={commands.token(host, port)} /></span></li>
        <li><span className="mono muted">3</span><span>Paste it here.</span></li>
      </ol>
      <input className="input mono" type="password" autoComplete="off" spellCheck={false} value={token} autoFocus
        onChange={(e) => setToken(e.target.value)} placeholder="ccd token" aria-label="ccd token" aria-invalid={!!token && !ok} />
      <label className="row muted"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        Remember on this browser (otherwise this tab only)</label>
      {err && <div className="bad-t" role="alert">{err}</div>}
      <div className="row"><button type="submit" className="btn is-primary" disabled={!ok || checking}>{checking ? "Checking…" : "Connect"}</button>
        <span className="muted mono-xs">The token never goes in a URL and is never logged.</span></div>
    </form>
  </main></div>;
}
