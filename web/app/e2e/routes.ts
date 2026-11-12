// The routes the suite opens, in Classic and in the HQ preview, as the address bar shows them after "#/".

/** Every screen and Settings tab, plus a task detail and the two pop-out windows, with what each must show. The router
 *  sends an unknown screen to the Dashboard, so this is what stops a renamed or broken route from passing as one. */
export const SHOWS: Record<string, string> = {
  dashboard: "Dashboard", overview: "Dashboard", needs: "Needs You", workspace: "Workspace", tasks: "Task Manager",
  "tasks/SV-056": "SV-056", activity: "Activity / Logs", files: "Files", console: "Files",
  projects: "Projects", development: "Development", agents: "Agents", server: "Server", alerts: "Alerts",
  prs: "Pull requests", workspaces: "herdr layout",
  settings: "Settings › General", "settings?tab=desktop": "Settings › Desktop app",
  "settings?tab=developer": "Settings › Developer mode", "settings?tab=connection": "Settings › Connection",
  "settings?tab=policies": "Settings › Policies", "settings?tab=decisions": "Settings › Decisions",
  "settings?tab=workers": "Settings › Workers", "settings?tab=audit": "Settings › Audit",
  "settings?tab=usage": "Settings › Usage", "settings?tab=import": "Settings › Task migration preview",
  "settings?tab=diagnostics": "Settings › Diagnostics",
  room: "pop-out", pane: "pop-out",
};

/** What the HQ preview's top bar names differently: its sidebar's names for the same screens (hq/frame/nav.ts). */
export const SHOWS_HQ: Record<string, string> = { ...SHOWS, dashboard: "My Office", overview: "My Office", needs: "Decisions",
  tasks: "Engineering", activity: "Activity" };

/** Each must load clean. */
export const LOAD = Object.keys(SHOWS);

/** Aliases: the same screen as another route, so parity does not screenshot them twice. */
const ALIASES = ["overview", "console"];

/** The screens whose pixels must not change unless a PR means to change Classic: every route but the aliases. */
export const PARITY = LOAD.filter((r) => !ALIASES.includes(r));

/** Pop-out windows: no navigation, no top bar. */
export const isBare = (route: string) => SHOWS[route] === "pop-out";

/** A file-name-safe name for a route: "settings?tab=audit" -> "settings-tab-audit". */
export const slug = (route: string) => route.replace(/[^A-Za-z0-9]+/g, "-").replace(/-$/, "");

/** What this branch adds to Classic on purpose, by route, as CSS selectors. Parity hides exactly these (display: none)
 *  and the rest of the screen must still match the base branch pixel for pixel; each must be on the page, so a stale
 *  entry fails. Anything listed here is not compared, so keep it to new elements and say why in the PR. Once the
 *  branch merges, its base has them too: the next branch starts this list empty. */
export const ADDED: Record<string, string[]> = {};

