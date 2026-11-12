// The HQ frame over today's screens (roadmap P1.1). Each sidebar item opens a Classic screen at its Classic address
// and keeps that screen's digit key (components/Shell.tsx, NAV), so links, bookmarks and shortcuts all still work.
// The HQ pages replace these screens one at a time; until then the names are HQ's and the screens are Classic's.
import type { Route } from "../../lib/router";
import { TITLES } from "../../components/Shell";

export interface HqNavItem { id: string; label: string; icon: string; key: string }

export const HQ_NAV: HqNavItem[] = [
  { id: "dashboard", label: "My Office", icon: "home", key: "1" },
  { id: "needs", label: "Decisions", icon: "shield", key: "0" },
  { id: "tasks", label: "Engineering", icon: "wrench", key: "3" },
  { id: "workspace", label: "Workspace", icon: "terminal", key: "2" },
  { id: "activity", label: "Activity", icon: "pulse", key: "4" },
  { id: "files", label: "Files", icon: "folder", key: "5" },
];
export const HQ_NAV_LOW: HqNavItem[] = [{ id: "settings", label: "Settings & more", icon: "gear", key: "6" }];

/** HQ's name for a screen, where it has one; every other screen keeps its Classic title. */
const HQ_TITLES: Record<string, string> = { dashboard: "My Office", overview: "My Office", needs: "Decisions",
  tasks: "Engineering", workspace: "Workspace", activity: "Activity", files: "Files", console: "Files", settings: "Settings" };

const ALIAS: Record<string, string> = { overview: "dashboard", console: "files" };

/** The sidebar item a screen belongs to: the aliases go to their screen, Alerts lives under Activity. */
export function sectionOf(screen: string): string {
  return ALIAS[screen] ?? (screen === "alerts" ? "activity" : screen);
}

/** The top bar's and the tab's title, as Classic's top bar works it out: a task shows its key, a project its name. */
export function hqTitle(screen: string, id: string | null, projectName: string | null = null): string {
  if (screen === "projects" && projectName) return projectName;
  if (screen === "tasks" && id) return id;
  return HQ_TITLES[screen] ?? TITLES[screen] ?? "My Office";
}

/** One tab per screen (and per task or project): Settings' sections and other query parameters share their tab. */
export function viewKey(route: Pick<Route, "screen" | "id">): string {
  const s = ALIAS[route.screen] ?? route.screen;
  return route.id ? `${s}/${route.id}` : s;
}
