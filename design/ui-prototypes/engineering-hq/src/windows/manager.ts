// WINDOW MANAGER — pop out ANY view into its own OS window, with exactly one owner at a time.
//
// Ownership is a small shared record per view id (lib/shared.ts: BroadcastChannel + localStorage,
// same origin only, non-sensitive). A view with no record lives in the main window. A popped view
// is rendered ONLY by the window that owns it; every other window shows a shaded placeholder.
//
// Liveness of a pop-out window:
//   - Web Locks (preferred): the pop-out holds the lock `hq-view:<id>` for its whole life. The browser
//     releases it when the window closes, reloads or crashes, so no timer can be throttled into a
//     false "lost" while the window is minimised on another monitor.
//   - Heartbeat (fallback, browsers or tests without Web Locks): a beat every BEAT_MS.
// A closing window (OS X, reload) marks itself "closing"; if it does not re-claim within GRACE_MS
// the view returns to the main window. Closing a window NEVER ends a session, task or agent — in
// the real app a pop-out only attaches to existing sessions by name (web/app/src/workspace/rooms.ts).
import { SharedStore, WIN_ID, isRecord } from "../lib/shared";
import { Store } from "../lib/store";
import { ID_SHAPE, viewById, type ViewDef } from "./views";
import { NAV_SHAPE } from "../lib/router";

export const BEAT_MS = 1500;
export const STALE_MS = 6000;
export const GRACE_MS = 2500;
export const PENDING_MS = 8000;

export interface Own { state: "popped" | "closing"; win: string | null; beat: number; since: number }
type Owners = Record<string, Own>;

function isOwners(v: unknown): v is Owners {
  if (!isRecord(v)) return false;
  return Object.entries(v).every(([k, o]) => ID_SHAPE.test(k) && isRecord(o) && (o.state === "popped" || o.state === "closing")
    && (o.win === null || typeof o.win === "string") && typeof o.beat === "number" && typeof o.since === "number");
}
export const owners = new SharedStore<Owners>("owners", {}, isOwners);

type Ctl = { t: "focus"; id: string } | { t: "return"; id: string } | { t: "nav"; id: string };
const ctl: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("hq-windows") : null;
const isCtl = (d: unknown): d is Ctl => isRecord(d) && typeof d.id === "string"
  && (((d.t === "focus" || d.t === "return") && ID_SHAPE.test(d.id)) || (d.t === "nav" && NAV_SHAPE.test(d.id)));


export interface Notice { id: number; text: string; tone: "ok" | "warn" | "bad"; action?: { label: string; run: () => void } }
export const notices = new Store<Notice[]>([]);
let nid = 0;
export function notify(text: string, tone: Notice["tone"] = "ok", action?: Notice["action"]) {
  const n = { id: ++nid, text, tone, action };
  notices.set((l) => [...l.slice(-3), n]);
  setTimeout(() => notices.set((l) => l.filter((x) => x.id !== n.id)), action ? 9000 : 4500);
}

const handles = new Map<string, Window>();
const locks = (): LockManager | null => (typeof navigator !== "undefined" && (navigator as Navigator & { locks?: LockManager }).locks) || null;
const lockName = (id: string) => `hq-view:${id}`;
export const windowName = (id: string) => `hq-${id.replace(/[^A-Za-z0-9_-]/g, "_")}`;

const SIZE: Record<ViewDef["kind"], [number, number]> = { page: [1440, 900], dm: [980, 820], task: [1200, 800], term: [960, 600], panel: [520, 860] };

export type PopResult = "opened" | "focused" | "blocked" | "invalid";

/** Pop a view out. MUST be called from a user gesture (click / key) so the browser allows the window. */
export function popOut(id: string, open: typeof window.open = window.open.bind(window)): PopResult {
  const def = viewById(id);
  if (!def) return "invalid";
  const have = owners.get()[id];
  if (have) { focusWindow(id); return "focused"; }      // already out: never a second owner
  const now = Date.now();
  owners.set((o) => ({ ...o, [id]: { state: "popped", win: null, beat: now, since: now } }));
  const [w, h] = SIZE[def.kind];
  const url = `${location.pathname}${location.search}#/pop/${encodeURIComponent(id)}`;
  const win = open(url, windowName(id), `popup=yes,width=${w},height=${h}`);
  if (!win) {
    owners.set((o) => { const n = { ...o }; delete n[id]; return n; });
    const framed = (() => { try { return window.top !== window.self; } catch { return true; } })();
    notify(framed
      ? `This copy is running inside a page that does not allow new windows, so “${def.title}” cannot pop out here. To try pop-outs on your monitors, run the prototype locally (npm run review) and open it in its own browser tab.`
      : `Your browser blocked the pop-out window for “${def.title}”. Allow pop-ups for this site (address bar → pop-up icon), then try again.`, "bad");
    return "blocked";
  }
  handles.set(id, win);
  return "opened";
}

/** Bring a popped view's window forward. Browsers may refuse; the caller offers Return here then. */
export function focusWindow(id: string): boolean {
  const h = handles.get(id);
  try { ctl?.postMessage({ t: "focus", id } satisfies Ctl); } catch { /* closed */ }
  if (h && !h.closed) { try { h.focus(); return true; } catch { /* cross-window focus denied */ } }
  return false;
}

/** Take the view back into this window. The pop-out sees it lost ownership and closes itself. */
export function returnHere(id: string) {
  owners.set((o) => { if (!o[id]) return o; const n = { ...o }; delete n[id]; return n; });
  try { ctl?.postMessage({ t: "return", id } satisfies Ctl); } catch { /* closed */ }
  const h = handles.get(id);
  handles.delete(id);
  try { if (h && !h.closed) h.close(); } catch { /* not ours to close */ }
}

// ---------------- pop-out side ----------------

/** Called once by the window that renders `#/pop/<id>`. Returns a stop function. */
export function claimAsPopout(id: string, onLost: () => void): () => void {
  const flag = `hq.claimed.${id}`;
  let mine = true;
  const was = (() => { try { return sessionStorage.getItem(flag); } catch { return null; } })();
  const cur = owners.get()[id];
  // A reload of a window whose view was returned meanwhile must not steal it back. A fresh pop-out
  // from the main window (a pending record, win = null) always wins, even in a reused named window.
  if (was === "returned" && !(cur && cur.win === null)) { mine = false; onLost(); return () => {}; }
  try { sessionStorage.setItem(flag, "1"); } catch { /* ignore */ }
  const claim = () => owners.set((o) => ({ ...o, [id]: { state: "popped", win: WIN_ID, beat: Date.now(), since: o[id]?.since ?? Date.now() } }));
  claim();   // synchronously, so no other window's change can read the view as unowned in between
  let release: (() => void) | null = null;
  const lm = locks();
  if (lm) void lm.request(lockName(id), () => new Promise<void>((res) => { if (!mine) res(); else release = res; })).catch(() => {});
  const beat = setInterval(() => {
    const o = owners.get()[id];
    if (o && o.win === WIN_ID) owners.set((all) => ({ ...all, [id]: { ...o, beat: Date.now(), state: "popped" } }));
  }, BEAT_MS);
  const unsub = owners.subscribe(() => {
    const o = owners.get()[id];
    if (mine && (!o || (o.win !== null && o.win !== WIN_ID))) { mine = false; try { sessionStorage.setItem(flag, "returned"); } catch { /* ignore */ } onLost(); }
  });
  const onCtl = (e: MessageEvent) => { if (isCtl(e.data) && e.data.id === id && e.data.t === "focus") { try { window.focus(); } catch { /* ignore */ } } };
  ctl?.addEventListener("message", onCtl);
  // OS close button or reload: mark closing. Nothing else happens — no session, task or agent stops.
  const onHide = () => {
    const o = owners.get()[id];
    if (mine && o?.win === WIN_ID) owners.set((all) => ({ ...all, [id]: { ...o, state: "closing", beat: Date.now() } }));
  };
  window.addEventListener("pagehide", onHide);
  return () => {
    mine = false; clearInterval(beat); unsub(); ctl?.removeEventListener("message", onCtl);
    window.removeEventListener("pagehide", onHide); (release as (() => void) | null)?.();
  };
}

// ---------------- recovery (every window runs it; it is idempotent) ----------------

/** Decide which owner records are dead. Pure, so tests can drive it with any clock. */
export function deadOwners(o: Owners, now: number, held: Set<string> | null): string[] {
  return Object.entries(o).filter(([id, r]) => {
    const alive = held ? held.has(lockName(id)) : now - r.beat < STALE_MS;
    if (r.win === null) return now - r.since > PENDING_MS;            // the window never came up
    if (r.state === "closing") return now - r.beat > GRACE_MS && !(held && held.has(lockName(id)));
    return !alive && now - r.beat > (held ? GRACE_MS : STALE_MS);
  }).map(([id]) => id);
}

export async function sweep(now = Date.now()): Promise<string[]> {
  const lm = locks();
  let held: Set<string> | null = null;
  if (lm) { try { const q = await lm.query(); held = new Set((q.held ?? []).map((l) => l.name ?? "")); } catch { held = null; } }
  const dead = deadOwners(owners.get(), now, held);
  if (dead.length) owners.set((o) => { const n = { ...o }; dead.forEach((id) => delete n[id]); return n; });
  return dead;
}

let started = false;
/** Main-window duties: recovery sweep, and telling Jay when a view comes back. */
export function startMainWindowDuties(): () => void {
  if (started) return () => {};
  started = true;
  let prev = owners.get();
  const unsub = owners.subscribe(() => {
    const cur = owners.get();
    for (const id of Object.keys(prev)) {
      if (!cur[id] && prev[id].win !== null) { const d = viewById(id); if (d) notify(`“${d.title}” is back in this window.`); handles.delete(id); }
    }
    prev = cur;
  });
  const t = setInterval(() => { void sweep(); }, 1000);
  void sweep();
  const onCtl = (e: MessageEvent) => {
    if (!isCtl(e.data)) return;
    if (e.data.t === "return") handles.delete(e.data.id);
    if (e.data.t === "nav" && location.hash !== e.data.id) { location.hash = e.data.id; try { window.focus(); } catch { /* ignore */ } }
  };
  ctl?.addEventListener("message", onCtl);
  return () => { started = false; unsub(); clearInterval(t); ctl?.removeEventListener("message", onCtl); };
}

// ---------------- main-window presence (so a pop-out knows when the main window is gone) ----------------

type Presence = Record<string, number>;
const isPresence = (v: unknown): v is Presence => isRecord(v) && Object.values(v).every((x) => typeof x === "number");
export const mains = new SharedStore<Presence>("mains", {}, isPresence);

export function beatAsMain(): () => void {
  const lm = locks();
  let release: (() => void) | null = null;
  let stopped = false;
  if (lm) void lm.request(`hq-main:${WIN_ID}-${Math.random().toString(36).slice(2)}`, () => new Promise<void>((r) => { if (stopped) r(); else release = r; })).catch(() => {});
  const beat = () => mains.set((m) => {
    const now = Date.now();
    const n: Presence = { [WIN_ID]: now };
    for (const [k, v] of Object.entries(m)) if (k !== WIN_ID && now - v < STALE_MS * 3) n[k] = v;
    return n;
  });
  beat();
  const t = setInterval(beat, BEAT_MS * 2);
  const bye = () => mains.set((m) => { const n = { ...m }; delete n[WIN_ID]; return n; });
  window.addEventListener("pagehide", bye);
  return () => { stopped = true; clearInterval(t); window.removeEventListener("pagehide", bye); bye(); (release as (() => void) | null)?.(); };
}

export async function mainAlive(now = Date.now()): Promise<boolean> {
  const lm = locks();
  if (lm) { try { const q = await lm.query(); return (q.held ?? []).some((l) => (l.name ?? "").startsWith("hq-main:")); } catch { /* fall back */ } }
  return Object.values(mains.get()).some((b) => now - b < STALE_MS);
}
