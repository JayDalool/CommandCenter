import { useSyncExternalStore } from "react";

export interface Route { screen: string; id: string | null; params: URLSearchParams; hash: string }

export const PAGES = ["office", "messages", "decisions", "teams", "topology", "engineering", "revenue", "more", "agents", "onboard", "newproject", "design"] as const;
export type Page = (typeof PAGES)[number];
const OTHER = ["task", "pop"];

export function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  const [path, query = ""] = h.split("?");
  const [screen, ...rest] = path.split("/").filter(Boolean);
  const known = (PAGES as readonly string[]).includes(screen) || OTHER.includes(screen);
  return { screen: known ? screen : "office", id: rest.length ? decodeURIComponent(rest.join("/")) : null,
    params: new URLSearchParams(query), hash: known ? `#/${h}` : "#/office" };
}

export function href(screen: string, id?: string | null): string {
  return `#/${screen}${id ? `/${encodeURIComponent(id)}` : ""}`;
}

/** A main-window route a pop-out may ask for: "#/<page>" or "#/<page>/<id>", nothing else. */
export const NAV_SHAPE = /^#\/(?!pop\/)[a-z]{2,20}(\/[A-Za-z0-9_-]{1,64})?$/;
const navChannel: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("hq-windows") : null;

/**
 * Go to a page. In the main window this is a normal hash change. In a pop-out window it asks the main
 * window to go there instead, so the pop-out keeps showing its own view (the window manager handles it).
 */
export function go(screen: string, id?: string | null) {
  const next = href(screen, id);
  if (location.hash.startsWith("#/pop/")) {
    if (!NAV_SHAPE.test(next)) return;
    try { navChannel?.postMessage({ t: "nav", id: next }); } catch { /* closed */ }
    try { window.opener?.focus(); } catch { /* not allowed */ }
    return;
  }
  if (location.hash !== next) location.hash = next;
}

let cached: { hash: string; route: Route } | null = null;
function snapshot(): Route {
  if (!cached || cached.hash !== location.hash) cached = { hash: location.hash, route: parse(location.hash) };
  return cached.route;
}
function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}
export function useRoute(): Route { return useSyncExternalStore(subscribe, snapshot, snapshot); }
