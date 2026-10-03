import { Store, useSelector } from "./store";

export interface Prefs {
  theme: "dark" | "light" | "system";
  density: "comfortable" | "compact";
  sshHost: string;
  consoleOpen: boolean;
  consoleAgent: string | null;
  lastProject: string | null;
}
const KEY = "cc.prefs";
const DEFAULTS: Prefs = { theme: "dark", density: "comfortable", sshHost: "jay-server", consoleOpen: false,
  consoleAgent: null, lastProject: null };

function load(): Prefs {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") }; } catch { return { ...DEFAULTS }; }
}

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

/** Commands Jay can paste into a Windows terminal. Host alias is his SSH config name. */
export const commands = {
  tunnel: (h: string) => `ssh -N -L 7777:127.0.0.1:7777 ${h}`,
  attach: (h: string) => `ssh -t ${h} herdr`,
  attachAgent: (h: string, agent: string) => `ssh -t ${h} herdr agent attach ${agent}`,
  token: (h: string) => `ssh ${h} cat .config/command-center/ccd.token | clip`,
};
