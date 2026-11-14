// Developer Unlock. The developer token is typed once, sent once to /api/developer/unlock, and
// forgotten; ccd answers with a session id. That id (never the token) is what this module keeps, and
// hands to the other Command Center windows Jay opens (pop-out terminals, rooms, a second Workspace
// window) over a same-origin BroadcastChannel. Never a URL, never the page.
//
// Where the id is kept depends on what Jay chose in the dialog:
//   - plain: this tab's sessionStorage, so a reload does not ask again and closing the browser ends
//     it. ccd ends it after 2 h idle or 8 h (security.DeveloperGate).
//   - "Remember this device": localStorage, so the browser stays unlocked across restarts for the
//     30 days ccd keeps the session. ccd saves only a hash of the id, lists the device in Settings,
//     and asks for the token again (403 `reenter`) before a terminal or a file write once 8 h have
//     passed since it was last typed.
// It still ends on LOCK (in any window; every window locks), on Lock all devices (from any device),
// and when ccd no longer knows it.
import { Store } from "../lib/store";

export interface DevState {
  active: boolean; expiresAt: number | null; error: string | null;
  /** This browser is a remembered device: the session outlives the browser session. */
  remembered?: boolean;
}
export const developer = new Store<DevState>({ active: false, expiresAt: null, error: null, remembered: false });
const KEY = "ccd.dev";
let session: string | null = null;

type Msg = { t: "dev"; id: string | null; expiresIn: number | null; remembered?: boolean } | { t: "dev?" };
const channel: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("cc-dev") : null;

/** One copy only: a remembered id in localStorage, a plain one in sessionStorage. Clearing removes both, and the
 *  newest unlock replaces whatever this browser held. */
function store(id: string | null, expiresAt: number | null, remembered: boolean) {
  const put = (where: () => Storage, on: boolean) => {
    try {
      if (id && on) where().setItem(KEY, JSON.stringify({ id, expiresAt, ...(remembered ? { remembered: true } : {}) }));
      else where().removeItem(KEY);
    } catch { /* private mode or storage refused: this tab's memory only */ }
  };
  put(() => sessionStorage, !remembered);
  put(() => localStorage, remembered);
}

function apply(id: string | null, expiresIn: number | null, remembered = false) {
  session = id;
  const expiresAt = id && expiresIn ? Date.now() / 1000 + expiresIn : null;
  store(id, expiresAt, !!id && remembered);
  developer.set({ active: !!id, expiresAt, error: null, remembered: !!id && remembered });
}

export function devSession(): string | null { return session; }

/** Set (or clear) the session here and in every other Command Center window. */
export function setDevSession(id: string | null, expiresIn: number | null = null, remembered = false) {
  apply(id, expiresIn, remembered);
  try { channel?.postMessage({ t: "dev", id, expiresIn, remembered: !!id && remembered } satisfies Msg); } catch { /* closed */ }
}

/** A session ccd no longer knows, found by this window. Only this window's own id goes: a tab restored with an old
 *  plain id must not take the browser's remembered one with it (that session would live on at ccd with no browser
 *  holding it). The remembered one, when it is a different id, is then what this window uses; ccd refuses it on the
 *  next call if it is dead too, and it is dropped the same way. */
function drop() {
  const was = session;
  const kept = stored(() => localStorage);
  session = null;
  try { sessionStorage.removeItem(KEY); } catch { /* storage refused */ }
  if (!kept || kept.id === was) { try { localStorage.removeItem(KEY); } catch { /* storage refused */ } }
  developer.set({ active: false, expiresAt: null, error: null, remembered: false });
  if (kept && kept.id !== was && kept.remembered) apply(kept.id, kept.expiresAt ? kept.expiresAt - Date.now() / 1000 : null, true);
}

/** Called when ccd answers 403 "Developer Unlock required": the session is gone (here only — the
 *  other windows find out on their own next call). */
export function devExpired() {
  if (session) drop();
}

function stored(s: () => Storage): { id: string; expiresAt: number | null; remembered: boolean } | null {
  try {
    const raw = s().getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as { id?: unknown; expiresAt?: unknown; remembered?: unknown };
    if (typeof v.id !== "string" || !v.id) return null;
    const expiresAt = typeof v.expiresAt === "number" ? v.expiresAt : null;
    if (expiresAt && expiresAt <= Date.now() / 1000) return null;
    return { id: v.id, expiresAt, remembered: v.remembered === true };
  } catch { return null; }
}

/** On start: this browser's remembered session, else this tab's stored one, else ask the other open windows for
 *  theirs. The remembered one comes first: a tab can only hold a plain id beside it when the tab was restored
 *  from before the device was remembered, and that older id must not replace the newer choice (taking it would
 *  also erase the remembered id from this browser while ccd keeps its session). A remembered id may have ended
 *  since (Lock all devices, 30 days): the caller checks it with ccd (`checkRemembered`). */
export function restoreDevSession(): Promise<void> {
  const device = stored(() => localStorage);
  const kept = device?.remembered ? device : stored(() => sessionStorage);
  if (kept) {
    apply(kept.id, kept.expiresAt ? kept.expiresAt - Date.now() / 1000 : null, kept === device);
    return Promise.resolve();
  }
  try { localStorage.removeItem(KEY); } catch { /* storage refused */ }   // an expired or unreadable one does not linger
  if (!channel) return Promise.resolve();
  return new Promise((resolve) => {
    // Answered or not, the listener goes: an unanswered start must not leave one behind.
    const stop = () => { clearTimeout(done); channel.removeEventListener("message", once); resolve(); };
    const done = setTimeout(stop, 250);
    const once = (e: MessageEvent<Msg>) => { if (e.data?.t === "dev" && e.data.id) stop(); };
    channel.addEventListener("message", once);
    try { channel.postMessage({ t: "dev?" } satisfies Msg); } catch { stop(); }
  });
}

/** A remembered session read back from localStorage is only a claim until ccd confirms it. `status` is
 *  GET /api/developer sent with this session: not active means it ended elsewhere, so this browser locks. Any
 *  other failure (ccd unreachable) leaves it: the next write finds out. */
export async function checkRemembered(status: () => Promise<{ active: boolean; expiresIn: number | null; remembered?: boolean }>) {
  const id = session;
  if (!id || !developer.get().remembered) return;
  try {
    const r = await status();
    if (session !== id) return;                       // locked or replaced while ccd answered
    // Here only, as devExpired: another window may hold a newer session, and finds out about this one by itself.
    if (!r.active) drop();
    else apply(id, r.expiresIn, r.remembered !== false);
  } catch { /* ccd unreachable: keep what we have */ }
}

// ccd asked for the token again (403 `reenter`, or a terminal closed with 4412). The dialog lives in the UI; it
// registers itself here so the request layer can ask without importing it.
let asker: (() => Promise<boolean>) | null = null;
let asking: Promise<boolean> | null = null;
export function setReenterAsker(fn: (() => Promise<boolean>) | null) { asker = fn; }
/** Ask Jay for the token again. Resolves true once ccd has taken it; false when he cancels or no dialog is mounted.
 *  Several requests refused at once share one dialog. */
export function askReenter(): Promise<boolean> {
  if (!asker) return Promise.resolve(false);
  return asking ??= asker().finally(() => { asking = null; });
}

channel?.addEventListener("message", (e: MessageEvent<Msg>) => {
  const m = e.data;
  if (!m) return;
  if (m.t === "dev?") {
    if (session) {
      const d = developer.get();
      const left = d.expiresAt ? d.expiresAt - Date.now() / 1000 : null;
      channel.postMessage({ t: "dev", id: session, expiresIn: left, remembered: !!d.remembered } satisfies Msg);
    }
  } else if (m.t === "dev") {
    if (m.id !== session || !!m.remembered !== !!developer.get().remembered) apply(m.id, m.expiresIn, m.remembered === true);
  }
});
