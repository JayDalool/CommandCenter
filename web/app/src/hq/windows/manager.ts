// HQ's pop-out windows (roadmap P2.1 and P2.3, the part HQ pages need): an HQ page in its own window that Jay drags to
// another monitor, or opens straight onto one. CommandCenter.exe shows the UI as an Edge or Chrome app window
// (launcher/browser.go, --app=), so a pop-out is a real window of its own.
//
// Rules (roadmap, "Pop-outs"; ADR-style, kept here so a change to them is a change to this file):
// - A pop-out's address is #/pop/<view> and nothing else: no id, no parameters, checked by POP_HASH.
// - One owner per view: a popped view is shown in its window only; the main window shows where it went instead.
// - Windows talk over one same-origin BroadcastChannel ("cc-windows"). Every message is shape-checked (isWinMsg) and
//   carries no secret; the token still reaches a pop-out over the existing cc-token channel (api/auth.ts).
// - Closing a window only closes it. Nothing here starts or stops a session.
// - Which monitor: Edge and Chrome place a window on another screen only once Jay allows "Manage windows on all your
//   displays" (the Window Management API). Without it the window opens beside this one and Jay drags it.
import { Store } from "../../lib/store";
import { isPopView, popHash, type PopView } from "./address";

export * from "./address";
const winName = (v: PopView) => `cc-hq-${v}`;

/** Where a window is, in screen pixels (window.screenX/Y, outerWidth/Height). */
export interface Place { x: number; y: number; w: number; h: number }

export type WinMsg =
  | { t: "here"; view: PopView; place: Place }   // a pop-out is open (sent every HEARTBEAT_MS and on "who")
  | { t: "gone"; view: PopView }                 // a pop-out closed
  | { t: "who" }                                 // a window (re)loaded and asks which pop-outs are open
  | { t: "focus"; view: PopView }                // bring that pop-out forward
  | { t: "return"; view: PopView };              // the main window takes the view back: the pop-out closes

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && Math.abs(n) < 100_000;
const exact = (o: object, keys: string[]) => Object.keys(o).length === keys.length && keys.every((k) => k in o);
export function isPlace(p: unknown): p is Place {
  return !!p && typeof p === "object" && exact(p, ["x", "y", "w", "h"])
    && finite((p as Place).x) && finite((p as Place).y) && finite((p as Place).w) && finite((p as Place).h);
}
/** The only messages a window acts on: anything else on the channel is ignored. */
export function isWinMsg(m: unknown): m is WinMsg {
  if (!m || typeof m !== "object") return false;
  const o = m as Record<string, unknown>;
  switch (o.t) {
    case "who": return exact(o, ["t"]);
    case "gone": case "focus": case "return": return exact(o, ["t", "view"]) && isPopView(o.view);
    case "here": return exact(o, ["t", "view", "place"]) && isPopView(o.view) && isPlace(o.place);
    default: return false;
  }
}

export const HEARTBEAT_MS = 2000;
/** A pop-out not heard from for this long is taken as closed (it crashed, or its "gone" was lost). */
export const STALE_MS = 3 * HEARTBEAT_MS + 500;

/** The pop-outs this window knows are open, each with where it last said it was. */
export const popped = new Store<Partial<Record<PopView, { at: number; place: Place }>>>({});

const channel: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("cc-windows") : null;
const handlers = new Set<(m: WinMsg) => void>();
export function send(m: WinMsg) { try { channel?.postMessage(m); } catch { /* channel closed */ } }
export function onMessage(h: (m: WinMsg) => void) { handlers.add(h); return () => { handlers.delete(h); }; }

/** Take one message: track pop-outs, then hand it on. Exported for tests (a BroadcastChannel never hears itself). */
export function receive(data: unknown, now = Date.now()) {
  if (!isWinMsg(data)) return;
  if (data.t === "here") popped.set((p) => ({ ...p, [data.view]: { at: now, place: data.place } }));
  else if (data.t === "gone") popped.set((p) => { const n = { ...p }; delete n[data.view]; return n; });
  handlers.forEach((h) => h(data));
}
channel?.addEventListener("message", (e: MessageEvent) => receive(e.data));

/** Forget pop-outs that stopped saying they are open. */
export function sweep(now = Date.now()) {
  const p = popped.get();
  const keep = Object.entries(p).filter(([, v]) => v && now - v.at <= STALE_MS);
  if (keep.length !== Object.keys(p).length) popped.set(Object.fromEntries(keep));
}

// ---------- remembered places ----------

const PLACES = "cc.hq.windows";
export function savedPlace(v: PopView): Place | null {
  try { const all: unknown = JSON.parse(localStorage.getItem(PLACES) ?? "{}"); const p = (all as Record<string, unknown>)?.[v];
    return isPlace(p) ? p : null; } catch { return null; }
}
export function savePlace(v: PopView, p: Place) {
  if (!isPlace(p) || p.w < 200 || p.h < 150) return;
  try {
    const all = JSON.parse(localStorage.getItem(PLACES) ?? "{}") as Record<string, unknown>;
    localStorage.setItem(PLACES, JSON.stringify({ ...(all && typeof all === "object" ? all : {}), [v]: p }));
  } catch { /* storage off: the next pop-out opens at the default place */ }
}
export const herePlace = (): Place => ({ x: window.screenX, y: window.screenY, w: window.outerWidth, h: window.outerHeight });

// ---------- monitors (Window Management API, Edge and Chrome) ----------

export interface ScreenInfo { label: string; left: number; top: number; width: number; height: number; primary: boolean; current: boolean }
interface DetailedScreen { label?: string; availLeft: number; availTop: number; availWidth: number; availHeight: number; isPrimary?: boolean }
interface ScreenDetails { screens: DetailedScreen[]; currentScreen: DetailedScreen }
type WithScreens = Window & { getScreenDetails?: () => Promise<ScreenDetails> };

/** This browser can place a window on a chosen monitor (after Jay allows it once). */
export const canPickScreen = () => typeof (window as WithScreens).getScreenDetails === "function";

/** Has Jay already allowed it? "prompt" means asking will show the browser's question. */
export async function screenPermission(): Promise<"granted" | "denied" | "prompt" | "unsupported"> {
  if (!canPickScreen()) return "unsupported";
  try { return (await navigator.permissions.query({ name: "window-management" as PermissionName })).state; }
  catch { return "prompt"; }
}

/** The monitors, current one first. Asks the browser's permission the first time; null if refused or unsupported. */
export async function listScreens(): Promise<ScreenInfo[] | null> {
  const get = (window as WithScreens).getScreenDetails;
  if (!get) return null;
  try {
    const d = await get.call(window);
    return d.screens.map((s, i) => ({ label: s.label || `Screen ${i + 1}`, left: s.availLeft, top: s.availTop, width: s.availWidth,
      height: s.availHeight, primary: !!s.isPrimary, current: s === d.currentScreen }))
      .sort((a, b) => Number(b.current) - Number(a.current));
  } catch { return null; }
}

/** Where a new pop-out goes on `s`: most of the screen, inset from its edges. */
export function placeOn(s: Pick<ScreenInfo, "left" | "top" | "width" | "height">): Place {
  const w = Math.round(Math.min(1400, s.width * 0.9)), h = Math.round(Math.min(1000, s.height * 0.9));
  return { x: Math.round(s.left + (s.width - w) / 2), y: Math.round(s.top + (s.height - h) / 2), w, h };
}

// ---------- the main window's side ----------

const opened = new Map<PopView, Window>();
/** Forget every window this one opened or heard of. For tests. */
export function resetWindows() { opened.clear(); popped.set({}); }

export function features(p: Place | null): string {
  if (!p) return "popup=yes,width=1280,height=860";
  return `popup=yes,left=${Math.round(p.x)},top=${Math.round(p.y)},width=${Math.round(p.w)},height=${Math.round(p.h)}`;
}

/** Open `v` in its own window: at `place`, else where it was last, else beside this window. One window per view: a
 *  second pop-out of the same view reuses its window. False when the browser blocked it. */
export function popOut(v: PopView, place?: Place | null): boolean {
  const w = window.open(`${location.pathname}${location.search}${popHash(v)}`, winName(v), features(place ?? savedPlace(v)));
  if (!w) return false;
  opened.set(v, w);
  // Shown as popped at once; its own "here" follows within a heartbeat, or the sweep clears it if it never loads.
  popped.set((p) => ({ ...p, [v]: { at: Date.now(), place: place ?? savedPlace(v) ?? herePlace() } }));
  return true;
}

/** Bring `v`'s window forward. Returns where it is when this window cannot raise it (opened before a reload). */
export function focusView(v: PopView): "focused" | "asked" {
  const w = opened.get(v);
  if (w && !w.closed) { w.focus(); return "focused"; }
  send({ t: "focus", view: v });
  return "asked";
}

/** Take `v` back into this window: its pop-out closes itself. */
export function returnView(v: PopView) {
  send({ t: "return", view: v });
  const w = opened.get(v);
  if (w && !w.closed) w.close();
  opened.delete(v);
  popped.set((p) => { const n = { ...p }; delete n[v]; return n; });
}

/** In words, where a pop-out is relative to this window: Jay may not see it if it is on another monitor. */
export function whereIs(p: Place, here: Place = herePlace(), screenW = window.screen.width): string {
  const cx = p.x + p.w / 2, hx = here.x + here.w / 2;
  if (Math.abs(cx - hx) < screenW / 2) return "on this screen";
  return cx > hx ? "on the screen to the right" : "on the screen to the left";
}
