// Developer Unlock. The developer token is typed once, sent once to /api/developer/unlock, and
// forgotten; ccd answers with a session id. That id (never the token) is kept for the current app
// session: in this tab's sessionStorage — so a reload or a navigation does not ask again — and handed
// to the other Command Center windows Jay opens (pop-out terminals, rooms, a second Workspace window)
// over a same-origin BroadcastChannel. Never localStorage, never a URL, never the page.
//
// It still ends: on LOCK (in any window — every window locks), when the tab or browser closes, on a
// ccd restart, and on ccd's own idle / maximum lifetime (security.DeveloperGate: 2 h idle, 8 h max).
import { Store } from "../lib/store";

export interface DevState { active: boolean; expiresAt: number | null; error: string | null }
export const developer = new Store<DevState>({ active: false, expiresAt: null, error: null });
const KEY = "ccd.dev";
let session: string | null = null;

type Msg = { t: "dev"; id: string | null; expiresIn: number | null } | { t: "dev?" };
const channel: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("cc-dev") : null;

function store(id: string | null, expiresAt: number | null) {
  try {
    if (id) sessionStorage.setItem(KEY, JSON.stringify({ id, expiresAt }));
    else sessionStorage.removeItem(KEY);
  } catch { /* private mode: this tab's memory only */ }
}

function apply(id: string | null, expiresIn: number | null) {
  session = id;
  const expiresAt = id && expiresIn ? Date.now() / 1000 + expiresIn : null;
  store(id, expiresAt);
  developer.set({ active: !!id, expiresAt, error: null });
}

export function devSession(): string | null { return session; }

/** Set (or clear) the session here and in every other Command Center window. */
export function setDevSession(id: string | null, expiresIn: number | null = null) {
  apply(id, expiresIn);
  try { channel?.postMessage({ t: "dev", id, expiresIn } satisfies Msg); } catch { /* closed */ }
}

/** Called when ccd answers 403 "Developer Unlock required": the session is gone (here only — the
 *  other windows find out on their own next call). */
export function devExpired() {
  if (session) apply(null, null);
}

/** On start: this tab's stored session, else ask the other open windows for theirs. */
export function restoreDevSession(): Promise<void> {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      const { id, expiresAt } = JSON.parse(raw) as { id: string; expiresAt: number | null };
      if (id && (!expiresAt || expiresAt > Date.now() / 1000)) {
        apply(id, expiresAt ? expiresAt - Date.now() / 1000 : null);
        return Promise.resolve();
      }
    }
  } catch { /* nothing stored */ }
  if (!channel) return Promise.resolve();
  return new Promise((resolve) => {
    const done = setTimeout(resolve, 250);
    const once = (e: MessageEvent<Msg>) => {
      if (e.data?.t === "dev" && e.data.id) { clearTimeout(done); channel.removeEventListener("message", once); resolve(); }
    };
    channel.addEventListener("message", once);
    try { channel.postMessage({ t: "dev?" } satisfies Msg); } catch { resolve(); }
  });
}

channel?.addEventListener("message", (e: MessageEvent<Msg>) => {
  const m = e.data;
  if (!m) return;
  if (m.t === "dev?") {
    if (session) {
      const left = developer.get().expiresAt ? developer.get().expiresAt! - Date.now() / 1000 : null;
      channel.postMessage({ t: "dev", id: session, expiresIn: left } satisfies Msg);
    }
  } else if (m.t === "dev") {
    if (m.id !== session) apply(m.id, m.expiresIn);
  }
});
