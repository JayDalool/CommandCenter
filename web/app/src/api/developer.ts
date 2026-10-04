// Developer Unlock. The developer token is typed once, sent once to
// /api/developer/unlock, and forgotten; ccd answers with a session id that
// lives ONLY in this module's memory. Never localStorage, never sessionStorage,
// never a URL, never the page. A reload, a ccd restart or LOCK ends it.
import { Store } from "../lib/store";

export interface DevState { active: boolean; expiresAt: number | null; error: string | null }
export const developer = new Store<DevState>({ active: false, expiresAt: null, error: null });
let session: string | null = null;

export function devSession(): string | null { return session; }

export function setDevSession(id: string | null, expiresIn: number | null = null) {
  session = id;
  developer.set({ active: !!id, expiresAt: id && expiresIn ? Date.now() / 1000 + expiresIn : null, error: null });
}

/** Called when ccd answers 403 "Developer Unlock required": the session is gone. */
export function devExpired() {
  if (session) setDevSession(null);
}
