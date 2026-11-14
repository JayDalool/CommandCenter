// DEVELOPER MODE: LOCKED / ACTIVE. Writing files, uploading and removing
// attachments need it; browsing never does. The developer token is typed into
// a password field, sent once, and dropped from memory as soon as ccd answers.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { developer, setDevSession } from "../api/developer";
import { Dialog } from "./Dialog";

export function useDevActive() { return useSelector(developer, (d) => d.active); }

// What the open dialog is for, kept here because the dialog is mounted once, by the shell (Shell.tsx), and opened
// from anywhere with an event. `then` is what Jay was in the middle of: it runs once he has unlocked, so he does not
// press the same button twice. Everything waiting is dropped when he cancels.
interface Ask { reenter?: boolean; then?: () => void; cancel?: () => void }
let waiting: Ask[] = [];
const reentering = () => waiting.some((a) => a.reenter);
const carrying = () => waiting.some((a) => a.then && !a.reenter);
function ask(a: Ask) { waiting.push(a); window.dispatchEvent(new Event("cc:dev-unlock")); }
function settle(ok: boolean) {
  const all = waiting;
  waiting = [];
  for (const a of all) (ok ? a.then : a.cancel)?.();
}

export function unlockDialogOpen() { ask({}); }
/** The dialog went away without an answer (its shell unmounted): nothing may wait on it for ever. */
export function unlockDialogGone() { settle(false); }

/** For an action that needs Developer Mode: true when it is active. Otherwise the unlock dialog opens and, once Jay
 *  has unlocked, `again` runs: the same action, without a second press. Reads the store, not a hook's value, so the
 *  action passes this check when it is run again from the dialog. */
export function devOr(again: () => void): boolean {
  if (developer.get().active) return true;
  ask({ then: again });
  return false;
}

/** ccd wants the token typed again on a remembered device (403 `reenter`, a terminal closed with 4412). Resolves
 *  true once it has been, false when Jay cancels. The shell hands this to the request layer while it is mounted. */
export function reenterDialog(): Promise<boolean> {
  return new Promise((resolve) => ask({ reenter: true, then: () => resolve(true), cancel: () => resolve(false) }));
}

/** Lock Developer Mode in this app session. The session ends here even when ccd cannot be reached. */
export async function lockDevMode() {
  try { await app.api.lock(); } catch { /* the session ends locally regardless */ }
  setDevSession(null); app.toast("Developer Mode locked");
}

const REMEMBER = "ccd.dev.remember";   // the box's last answer in this browser: "1" or absent. Not a secret.
const lastRemember = () => { try { return localStorage.getItem(REMEMBER) === "1"; } catch { return false; } };
const keepRemember = (on: boolean) => { try { if (on) localStorage.setItem(REMEMBER, "1"); else localStorage.removeItem(REMEMBER); } catch { /* storage refused */ } };

export function UnlockDialog({ onClose }: { onClose: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Asked for again on a remembered device: the session is still there, only the token is too old for a terminal
  // or a file write. Decided when the dialog opens.
  const [reenter] = useState(reentering);
  // Something Jay pressed is waiting on this dialog and runs as soon as it is unlocked: the button says so.
  const [carry] = useState(carrying);
  // This ccd's own developer.token (a preview has its own; the live one would be refused here), and whether it can
  // remember a device at all: an older ccd cannot, and the box is not offered.
  const [file, setFile] = useState("~/.config/command-center/developer.token");
  const [canRemember, setCanRemember] = useState(false);
  const [remember, setRemember] = useState(lastRemember);
  useEffect(() => {
    app.api.developerStatus().then((r) => { if (r.tokenFile) setFile(r.tokenFile); setCanRemember(typeof r.remembered === "boolean"); })
      .catch(() => undefined);
  }, []);
  const close = (ok: boolean) => { onClose(); settle(ok); };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    try {
      // Typed again on a remembered device (ccd asks only those): ccd re-proves the session this request carries.
      // It must stay remembered: sent without `remember`, ccd would turn it into a plain 8-hour session.
      const keep = reenter || (canRemember && remember);
      const r = await app.api.unlock(value.trim(), keep);
      setDevSession(r.session, r.expiresIn, r.remembered === true);
      if (!reenter && canRemember) keepRemember(remember);
      setValue("");
      app.toast(reenter ? "Developer token accepted" : r.remembered ? "Developer Mode active, this device remembered for 30 days" : "Developer Mode active");
      close(true);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return <Dialog title="Developer Unlock" onClose={() => close(false)}>
    {!reenter && <div className="stack" style={{ gap: 8, marginBottom: 14 }}>
      <a className="btn is-primary" href="commandcenter://unlock" onClick={() => setTimeout(() => close(false), 300)}>Sign in with SSH (CommandCenter.exe)</a>
      <p className="mono-xs muted">Uses your SSH key login: a signed-in window opens and every Command Center window unlocks for the
        day. No launcher here? On the server run <span className="mono">scripts/cc-session --url</span> and open the link it prints.</p>
    </div>}
    <form onSubmit={submit} className="stack" style={{ gap: 10 }} autoComplete="off">
      {reenter
        ? <p className="text2">This device is remembered, and it has been more than 8 hours since the developer token was typed
          here. Terminals and file changes need it again. Approvals and answers stay unlocked.</p>
        : <p className="text2">Terminals, Claude, answers, uploads and file changes need the developer token. It is different
          from the ccd token and is never stored; Command Center keeps only a session id and shares it with its own
          windows. {canRemember ? "Unless this device is remembered, it" : "It"} lasts 8 hours and ends when the browser closes,
          after 2 hours idle, or on Lock.</p>}
      <p className="mono-xs muted">ssh jay-server cat {file.replace(/^~\//, "")}</p>
      <input className="input mono" type="password" value={value} onChange={(e) => setValue(e.target.value)}
        aria-label="Developer token" placeholder="developer token" data-autofocus autoComplete="off" spellCheck={false} />
      {!reenter && canRemember && <label className="row" style={{ gap: 8, alignItems: "flex-start" }}>
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <span className="text2">Remember this device for 30 days
          <span className="mono-xs muted" style={{ display: "block" }}>It stays unlocked when the browser closes and when ccd
            restarts. Terminals and file changes ask for the token again after 8 hours. Lock, or Lock all devices in
            Settings, ends it.</span></span></label>}
      {err && <div className="bad-t" role="alert">{err}</div>}
      {carry && <p className="mono-xs muted">What you just asked for carries on as soon as this is unlocked. Cancel drops it.</p>}
      <div className="row"><button type="submit" className="btn is-jay" disabled={busy || !value.trim()}>{carry ? "Unlock and continue" : "Unlock"}</button>
        <button type="button" className="btn is-quiet" onClick={() => close(false)}>Cancel</button></div>
    </form>
  </Dialog>;
}

/** The one small indicator (spec §27): "Developer ●" when active, a click locks; "Developer ○" unlocks. HQ on a phone
 * shows the short label ("Dev ●"); everywhere else the short one is hidden (control.css). */
export function DevDot() {
  const active = useDevActive();
  return <button type="button" className={`dev-dot${active ? " is-on" : ""}`}
    title={active ? "Developer Mode active for this app session — click to lock" : "Developer Mode locked — click to unlock"}
    aria-label={active ? "Developer Mode active. Lock" : "Developer Mode locked. Unlock"}
    onClick={async () => {
      if (!active) { unlockDialogOpen(); return; }
      try { await app.api.lock(); } catch { /* the session ends locally regardless */ }
      setDevSession(null); app.toast("Developer Mode locked");
    }}><span className="dev-dot-l">Developer</span><span className="dev-dot-s">Dev</span><i aria-hidden>{active ? "●" : "○"}</i></button>;
}

export function DevBadge() {
  const active = useDevActive();
  return active
    ? <span className="row" style={{ gap: 6 }}>
      <span className="ro-tag is-live" title="Writes to project files are allowed in this tab">DEVELOPER MODE: ACTIVE</span>
      <button type="button" className="btn is-quiet is-sm" onClick={() => void lockDevMode()}>Lock</button></span>
    : <span className="row" style={{ gap: 6 }}>
      <span className="ro-tag is-off" title="Browsing works; saving and uploading need Developer Unlock">DEVELOPER MODE: LOCKED</span>
      <button type="button" className="btn is-sm" onClick={unlockDialogOpen}>Unlock</button></span>;
}
