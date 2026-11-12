// The tab strip's open views, for this window only (sessionStorage): a reload keeps them, another window has its own.
// A tab remembers the last address it showed, so a Settings section or a filter comes back as it was left.
import { Store } from "../../lib/store";

export interface HqTab { key: string; hash: string }

const KEY = "cc.hq.tabs";
/** Enough for a working session. Opening one more closes the oldest tab that is not the current one. */
export const MAX_TABS = 10;

export function parseTabs(raw: string | null): HqTab[] {
  try {
    const v: unknown = JSON.parse(raw ?? "[]");
    if (!Array.isArray(v)) return [];
    return v.filter((t): t is HqTab => !!t && typeof t === "object" && typeof (t as HqTab).key === "string"
      && typeof (t as HqTab).hash === "string" && (t as HqTab).hash.startsWith("#/")).slice(0, MAX_TABS);
  } catch { return []; }
}

function load(): HqTab[] { try { return parseTabs(sessionStorage.getItem(KEY)); } catch { return []; } }

export const tabs = new Store<HqTab[]>(load());
tabs.subscribe(() => { try { sessionStorage.setItem(KEY, JSON.stringify(tabs.get())); } catch { /* this window only */ } });

/** The view at `key` now shows `hash`: add its tab at the end, or update the address its tab returns to. */
export function visit(list: HqTab[], key: string, hash: string): HqTab[] {
  const at = list.findIndex((t) => t.key === key);
  if (at >= 0) return list[at].hash === hash ? list : list.map((t, i) => (i === at ? { key, hash } : t));
  const next = [...list, { key, hash }];
  return next.length > MAX_TABS ? next.slice(next.length - MAX_TABS) : next;
}

/** Close `key`. When it was the current tab, also say where to go: the tab to its right, else the one to its left. */
export function close(list: HqTab[], key: string, current: string): { list: HqTab[]; go: string | null } {
  const at = list.findIndex((t) => t.key === key);
  if (at < 0) return { list, go: null };
  const next = list.filter((t) => t.key !== key);
  if (key !== current) return { list: next, go: null };
  return { list: next, go: (next[at] ?? next[at - 1])?.hash ?? "#/dashboard" };
}
