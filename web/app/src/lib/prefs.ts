import { Store, useSelector } from "./store";

export interface Prefs {
  theme: "dark" | "light" | "system";
  density: "comfortable" | "compact";
  sshHost: string;
  consoleOpen: boolean;
  consoleAgent: string | null;
  consoleTab: "claude" | "repo" | "server";
  consoleProject: string | null;
  consoleFull: boolean;
  consoleFollow: boolean;
  lastProject: string | null;
  // Workspace layout (this browser only)
  wsExplorerW: number; wsExplorerOpen: boolean; wsTermH: number; wsTermOpen: boolean;
  wsMax: "none" | "main" | "term";
  /** Which mode the one Workspace sidebar shows. wsExplorerOpen is whether the sidebar itself is open. */
  wsSide: "explorer" | "scm" | "search";
}
const KEY = "cc.prefs";
const DEFAULTS: Prefs = { theme: "dark", density: "comfortable", sshHost: "jay-server", consoleOpen: false,
  consoleAgent: null, consoleTab: "claude", consoleProject: null, consoleFull: false, consoleFollow: true,
  lastProject: null, wsExplorerW: 260, wsExplorerOpen: true, wsTermH: 300, wsTermOpen: true, wsMax: "none",
  wsSide: "explorer" };

const SIDES = ["explorer", "scm", "search"];

/** Stored prefs -> Prefs. The old `wsMain` (center view) is dropped; its scm/search values become the sidebar mode. */
export function parsePrefs(raw: string | null): Prefs {
  try {
    const o = JSON.parse(raw ?? "{}") as Record<string, unknown>;
    const old = o.wsMain;
    delete o.wsMain;
    const p = { ...DEFAULTS, ...o } as Prefs;
    if (!SIDES.includes(String(o.wsSide))) p.wsSide = old === "scm" || old === "search" ? old : "explorer";
    return p;
  } catch { return { ...DEFAULTS }; }
}
function load(): Prefs { try { return parsePrefs(localStorage.getItem(KEY)); } catch { return { ...DEFAULTS }; } }

export const prefs = new Store<Prefs>(load());
prefs.subscribe(() => {
  const p = prefs.get();
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* per-viewer convenience only */ }
  apply(p);
});

export function apply(p: Prefs = prefs.get()) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = p.theme;
  document.documentElement.dataset.density = p.density;
}

export const usePrefs = <S,>(sel: (p: Prefs) => S) => useSelector(prefs, sel);

// Each ccd has its own token file, and one will not authenticate against the
// other. The live daemon on 7777 reads ~/.config/command-center/ccd.token; the
// dev preview (scripts/dev-ccd.py on 7788, reached directly or through the Vite
// proxy on 5173) reads ~/command-center/dev/ccd.token. The Connect screen must
// name the file belonging to the ccd that served this page, or Jay pastes a
// valid token that the other ccd correctly refuses.
export const LIVE_PORT = "7777";
export const LIVE_TOKEN_FILE = ".config/command-center/ccd.token";
export const DEV_TOKEN_FILE = "command-center/dev/ccd.token";
const DEV_PORTS = new Set(["7788", "7789", "5173"]);

/** The port this page is served on, which is the port of the ccd behind it. */
export function servedPort(): string {
  const p = typeof location === "undefined" ? "" : location.port;
  return p || LIVE_PORT;
}

export function tokenFile(port: string = servedPort()): string {
  return DEV_PORTS.has(port) ? DEV_TOKEN_FILE : LIVE_TOKEN_FILE;
}

/** Commands Jay can paste into a Windows terminal. Host alias is his SSH config name. */
export const commands = {
  tunnel: (h: string, port: string = servedPort()) => `ssh -N -L ${port}:127.0.0.1:${port} ${h}`,
  attach: (h: string) => `ssh -t ${h} herdr`,
  attachAgent: (h: string, agent: string) => `ssh -t ${h} herdr agent attach ${agent}`,
  repoShell: (h: string, path: string) => `ssh -t ${h} "cd ${path} && exec \\$SHELL -l"`,
  serverShell: (h: string) => `ssh -t ${h}`,
  token: (h: string, port: string = servedPort()) => `ssh ${h} cat ${tokenFile(port)} | clip`,
};
