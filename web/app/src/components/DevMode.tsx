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
    <form onSubmit={submit} className="stack" style={{ gap: 10 }} autoComplete="off">
      <p className="text2">Saving files, uploading, and removing attachments need the developer token. It is
        different from the ccd token. Command Center keeps only a session in this tab's memory. A reload, a ccd
        restart, or LOCK ends it.</p>
      <p className="mono-xs muted">ssh jay-server cat ~/.config/command-center/developer.token</p>
      <input className="input mono" type="password" value={value} onChange={(e) => setValue(e.target.value)}
        aria-label="Developer token" placeholder="developer token" data-autofocus autoComplete="off" spellCheck={false} />
      {err && <div className="bad-t" role="alert">{err}</div>}
      <div className="row"><button type="submit" className="btn is-jay" disabled={busy || !value.trim()}>Unlock</button>
        <button type="button" className="btn is-quiet" onClick={onClose}>Cancel</button></div>
    </form>
  </Dialog>;
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
