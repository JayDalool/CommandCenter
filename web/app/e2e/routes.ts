// The Classic routes the suite opens, as the address bar shows them after "#/".

/** Every screen and Settings tab, plus a task detail and the two pop-out windows. Each must load clean. */
export const LOAD = [
  "dashboard", "overview", "needs", "workspace", "tasks", "tasks/SV-056", "activity", "files", "console",
  "projects", "development", "agents", "server", "alerts", "prs", "workspaces",
  "settings", "settings?tab=desktop", "settings?tab=developer", "settings?tab=connection", "settings?tab=policies",
  "settings?tab=decisions", "settings?tab=workers", "settings?tab=audit", "settings?tab=usage", "settings?tab=import",
  "settings?tab=diagnostics",
  "room", "pane",
];

/** The screens whose pixels must not change unless a PR means to change Classic. Aliases are left out. */
export const PARITY = [
  "dashboard", "needs", "workspace", "tasks", "tasks/SV-056", "activity", "files",
  "projects", "development", "agents", "server", "alerts", "prs", "workspaces",
  "settings", "settings?tab=policies", "settings?tab=audit",
];

/** A file-name-safe name for a route: "settings?tab=audit" -> "settings-tab-audit". */
export const slug = (route: string) => route.replace(/[^A-Za-z0-9]+/g, "-").replace(/-$/, "");
