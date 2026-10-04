import { useSyncExternalStore } from "react";

export interface Route { screen: string; id: string | null; params: URLSearchParams }

export const SCREENS = ["overview", "projects", "tasks", "development", "console", "agents", "server",
  "activity", "alerts", "settings", "prs", "workspaces", "workspace"] as const;
export type Screen = (typeof SCREENS)[number];

export function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  const [path, query = ""] = h.split("?");
  const [screen, ...rest] = path.split("/").filter(Boolean);
  return {
    screen: (SCREENS as readonly string[]).includes(screen) ? screen : "overview",
    id: rest.length ? decodeURIComponent(rest.join("/")) : null,
    params: new URLSearchParams(query),
  };
}

export function href(screen: string, id?: string | null, params?: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([k, v]) => v && q.set(k, v));
  const qs = q.toString();
  return `#/${screen}${id ? `/${encodeURIComponent(id)}` : ""}${qs ? `?${qs}` : ""}`;
}

export function go(screen: string, id?: string | null, params?: Record<string, string | undefined>) {
  const next = href(screen, id, params);
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
export function useRoute(): Route { return useSyncExternalStore(subscribe, snapshot); }
