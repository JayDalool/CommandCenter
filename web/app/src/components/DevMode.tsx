// DEVELOPER MODE: LOCKED / ACTIVE. Writing files, uploading and removing
// attachments need it; browsing never does. The developer token is typed into
// a password field, sent once, and dropped from memory as soon as ccd answers.
import { useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { developer, setDevSession } from "../api/developer";
import { Dialog } from "./Dialog";

export function useDevActive() { return useSelector(developer, (d) => d.active); }

export function unlockDialogOpen() { window.dispatchEvent(new Event("cc:dev-unlock")); }

export function UnlockDialog({ onClose }: { onClose: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    try {
      const r = await app.api.unlock(value.trim());
      setDevSession(r.session, r.expiresIn);
      setValue("");
      app.toast("Developer Mode active");
      onClose();
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return <Dialog title="Developer Unlock" onClose={onClose}>
    <div className="stack" style={{ gap: 8, marginBottom: 14 }}>
      <a className="btn is-primary" href="commandcenter://unlock" onClick={() => setTimeout(onClose, 300)}>Sign in with SSH (CommandCenter.exe)</a>
      <p className="mono-xs muted">Uses your SSH key login: a signed-in window opens and every Command Center window unlocks for the
        day. No launcher here? On the server run <span className="mono">scripts/cc-session --url</span> and open the link it prints.</p>
    </div>
    <form onSubmit={submit} className="stack" style={{ gap: 10 }} autoComplete="off">
      <p className="text2">Terminals, Claude, answers, uploads and file changes need the developer token — once per
        app session. It is different from the ccd token and is never stored; Command Center keeps only a session id
        for this browser session and shares it with its own windows. Closing the browser, a ccd restart, 2 hours
        idle or Lock ends it.</p>
      <p className="mono-xs muted">ssh jay-server cat ~/.config/command-center/developer.token</p>
      <input className="input mono" type="password" value={value} onChange={(e) => setValue(e.target.value)}
        aria-label="Developer token" placeholder="developer token" data-autofocus autoComplete="off" spellCheck={false} />
      {err && <div className="bad-t" role="alert">{err}</div>}
      <div className="row"><button type="submit" className="btn is-jay" disabled={busy || !value.trim()}>Unlock</button>
        <button type="button" className="btn is-quiet" onClick={onClose}>Cancel</button></div>
    </form>
  </Dialog>;
}

/** The one small indicator (spec §27): "Developer ●" when active, a click locks; "Developer ○" unlocks. */
export function DevDot() {
  const active = useDevActive();
  return <button type="button" className={`dev-dot${active ? " is-on" : ""}`}
    title={active ? "Developer Mode active for this app session — click to lock" : "Developer Mode locked — click to unlock"}
    aria-label={active ? "Developer Mode active. Lock" : "Developer Mode locked. Unlock"}
    onClick={async () => {
      if (!active) { unlockDialogOpen(); return; }
      try { await app.api.lock(); } catch { /* the session ends locally regardless */ }
      setDevSession(null); app.toast("Developer Mode locked");
    }}>Developer <i aria-hidden>{active ? "●" : "○"}</i></button>;
}

export function DevBadge() {
  const active = useDevActive();
  return active
    ? <span className="row" style={{ gap: 6 }}>
      <span className="ro-tag is-live" title="Writes to project files are allowed in this tab">DEVELOPER MODE: ACTIVE</span>
      <button type="button" className="btn is-quiet is-sm" onClick={async () => {
        try { await app.api.lock(); } catch { /* the session ends locally regardless */ }
        setDevSession(null); app.toast("Developer Mode locked");
      }}>Lock</button></span>
    : <span className="row" style={{ gap: 6 }}>
      <span className="ro-tag is-off" title="Browsing works; saving and uploading need Developer Unlock">DEVELOPER MODE: LOCKED</span>
      <button type="button" className="btn is-sm" onClick={unlockDialogOpen}>Unlock</button></span>;
}
