// Every page and its important states (modals, menus, popovers, wizards), shared by the gallery capture
// (e2e/gallery.mjs) and the QA sweep (e2e/qa.mjs). A state = a route plus an optional set-up that opens something.

export const VIEWPORTS = [
  { id: "1920", label: "Desktop 1920×1080", width: 1920, height: 1080, scale: 1 },
  { id: "1366", label: "Laptop 1366×768", width: 1366, height: 768, scale: 1 },
  { id: "1280", label: "Small laptop 1280×720", width: 1280, height: 720, scale: 1 },
  { id: "phone", label: "Phone 390×844", width: 390, height: 844, scale: 2 },
];

export const wait = (p, ms = 250) => p.waitForTimeout(ms);
export const next = (p) => p.getByRole("button", { name: /^Next:/ }).click();
export const click = (p, sel) => p.locator(sel).first().click();

// Wizard walks share these steps; `upTo` stops after that many Next presses.
export async function agentWizard(p, upTo) {
  await p.getByRole("button", { name: "New Agent" }).first().click(); await wait(p);
  if (upTo === 0) return;
  await p.getByRole("button", { name: "Implementation Agent template" }).click();
  const steps = [
    async () => { await p.getByLabel("Display name").fill("Mira"); },
    async () => {}, async () => {}, async () => {},
    async () => { await p.getByRole("button", { name: /How effective access/ }).click(); },
    async () => { await p.getByRole("button", { name: /^Repository/ }).click(); await p.getByRole("button", { name: /^Production/ }).click(); },
    async () => {}, async () => {}, async () => {},
  ];
  for (let i = 0; i < upTo; i++) { await next(p); await wait(p, 120); await steps[i](); }
}
export async function projectWizard(p, upTo) {
  await p.getByRole("button", { name: "New Project" }).first().click(); await wait(p);
  await p.getByLabel("Project name").fill("Listing Scraper");
  const steps = [
    async () => { await p.getByLabel(/Repository \(owner/).fill("JayDalool/listing-scraper"); },
    async () => {}, async () => {},
    async () => { await p.getByLabel("Project lead").selectOption("claude"); },
    async () => {}, async () => {},
    async () => { await p.getByRole("button", { name: /Advanced rules/ }).click(); },
    async () => {},
  ];
  for (let i = 0; i < upTo; i++) { await next(p); await wait(p, 120); await steps[i](); }
}

// group, id, title, note, route, phone (also capture on a phone), full (also capture the whole scroll length at 1920), run (set-up)
export const S = [];
// `only` limits a state to some viewports (e.g. ["phone"] for the phone tab bar and More sheet).
const add = (group, id, title, route, o = {}) => S.push({ group, id, title, route, note: o.note ?? "", phone: o.phone ?? false, full: o.full ?? false, run: o.run, query: o.query, only: o.only });

// My Office
add("My Office", "office", "My Office (executive dashboard)", "office", { phone: true, full: true, note: "Agents, Needs You, updates from Project Leads, system health." });
add("My Office", "office-outage", "Status feed outage", "settings/demo", { note: "Honest state: agents show Unknown or Stale, never Working.",
  run: async (p) => { await p.getByLabel("Simulate a status-feed outage").check(); await p.evaluate(() => { location.hash = "#/office"; }); await wait(p, 700); } });
// Shell
add("Shell and navigation", "shell-search", "Search (Ctrl+K)", "office", { phone: true, run: async (p) => { await p.locator(".search").click(); await p.keyboard.type("sv"); await wait(p); } });
add("Shell and navigation", "shell-notifications", "Notifications", "office", { run: async (p) => { await click(p, 'button[aria-label="Notifications (demo)"]'); await wait(p, 350); } });
add("Shell and navigation", "shell-jay-menu", "Jay's menu", "office", { run: async (p) => { await click(p, "button.me"); await wait(p, 350); } });
add("Shell and navigation", "shell-tab-menu", "Tab context menu", "messages/sv-lead", { note: "Right-click any tab: pop out, close, close others.",
  run: async (p) => { await p.evaluate(() => { location.hash = "#/office"; }); await wait(p, 400); await p.locator('[data-testid="tab-page:messages"]').click({ button: "right" }); await wait(p, 350); } });
add("Shell and navigation", "phone-tabbar", "Phone: bottom tab bar", "messages/sv-lead", { only: ["phone"], note: "Office, Messages, Decisions, Approvals and More. The desktop keeps the sidebar." });
add("Shell and navigation", "phone-more", "Phone: More sheet", "office", { only: ["phone"], note: "Every other page, grouped like a phone settings list.",
  run: async (p) => { await click(p, '.tabbar button[aria-haspopup="dialog"]'); await wait(p, 450); } });
add("Shell and navigation", "shell-loading", "Loading skeletons", "office", { query: "?nofeed&slow", note: "Shown only when something loads; simulated here.",
  run: async (p) => { await p.evaluate(() => { location.hash = "#/teams/samvision"; }); await wait(p, 150); } });
// Messages
add("Messages", "messages-lead", "Private conversation with a Project Lead", "messages/sv-lead", { phone: true, note: "With the current task context beside it." });
add("Messages", "messages-agent", "Conversation with an agent", "messages/nova");
add("Messages", "messages-team", "Team channel", "messages/team-samvision");
add("Messages", "messages-slack", "Slack (not connected)", "messages/slack");
add("Messages", "messages-new", "New Message: choose who to write to", "messages/sv-lead", { run: async (p) => { await p.getByRole("button", { name: /New Message/ }).click(); await wait(p, 350); } });
add("Messages", "messages-attach", "Attach menu", "messages/sv-lead", { run: async (p) => { await click(p, 'button[aria-label="Attach (demo)"]'); await wait(p, 350); } });
// Decisions
add("Decisions", "decisions", "Needs My Attention (queue)", "decisions", { phone: true, full: true, note: "Decisions, questions, reviews and approvals waiting for Jay. Each opens where it is answered." });
add("Decisions", "decisions-approvals", "Needs My Attention: approvals only", "decisions", { run: async (p) => { await p.getByRole("tab", { name: "Approvals" }).click(); await wait(p, 300); } });
add("Decisions", "decisions-room", "Decision room: SV-025", "decisions/sv-025", { phone: true, full: true });
add("Decisions", "decisions-findings", "Decision room: UI findings evidence", "decisions/sv-025", { run: async (p) => { await p.getByRole("tab", { name: "UI Findings" }).click(); await wait(p, 300); } });
add("Decisions", "decisions-technical", "Decision room: technical tab", "decisions/sv-025", { run: async (p) => { await p.getByRole("tab", { name: "Technical" }).click(); await wait(p, 300); } });
add("Decisions", "decisions-confirm", "Record a decision", "decisions/sv-025", { run: async (p) => {
  await p.locator('[aria-label="Options"] button').first().click(); await wait(p, 150);
  await p.getByRole("button", { name: "Record decision" }).first().click(); await wait(p, 350); } });
// Teams
add("Teams", "teams-samvision", "SamVision team hierarchy", "teams/samvision", { phone: true, full: true });
add("Teams", "teams-commandcenter", "CommandCenter team", "teams/commandcenter");
add("Teams", "teams-gauzemate", "Paused project: no active Project Lead", "teams/gauzemate");
add("Teams", "teams-agent-drawer", "Agent details drawer", "teams/samvision", { run: async (p) => { await p.getByRole("button", { name: /^Atlas, / }).first().click(); await wait(p, 400); } });
// Agents
add("Agents", "agents", "Agent directory", "agents", { phone: true, full: true });
add("Agents", "agents-inspector", "Agent Inspector", "agents", { run: async (p) => { await p.getByRole("button", { name: /^Nova, / }).first().click(); await wait(p, 400); } });
add("Agents", "agents-menu", "Agent context menu", "agents", { run: async (p) => { await p.getByRole("button", { name: /^Nova, / }).first().click({ button: "right" }); await wait(p, 350); } });
add("Agents", "agents-pause", "Pause an agent", "agents", { run: async (p) => { await p.getByRole("button", { name: /^Nova, / }).first().click(); await wait(p, 300); await p.locator("button.mg", { hasText: "Pause" }).first().click(); await wait(p, 350); } });
add("Agents", "agents-offboard", "Offboard an agent", "agents", { run: async (p) => { await p.getByRole("button", { name: /^Nova, / }).first().click(); await wait(p, 300); await p.locator("button.mg", { hasText: "Offboard" }).first().click(); await wait(p, 350); } });
add("Agents", "agents-reassign", "Reassign an agent", "agents", { run: async (p) => { await p.getByRole("button", { name: /^Nova, / }).first().click(); await wait(p, 300); await p.locator("button.mg", { hasText: "Reassign" }).first().click(); await wait(p, 350); } });
add("Agents", "agents-edit", "Change an agent's model (edit in the wizard)", "agents", { run: async (p) => { await p.getByRole("button", { name: /^Nova, / }).first().click(); await wait(p, 300); await p.locator("button.mg", { hasText: "Change model" }).first().click(); await wait(p, 450); } });
// Topology
add("Operations Topology", "topology", "Operations Topology", "topology", { phone: true });
add("Operations Topology", "topology-fullscreen", "Full-screen topology", "topology", { run: async (p) => { await click(p, 'button[aria-label="Full screen graph"]'); await wait(p, 500); } });
add("Operations Topology", "topology-stage", "Stage selected, with its inspector", "topology", { run: async (p) => { await click(p, '[data-node="s:build"]'); await wait(p, 400); } });
add("Operations Topology", "topology-project", "Project selected", "topology", { run: async (p) => { await click(p, '[data-node="p:samvision"]'); await wait(p, 400); } });
add("Operations Topology", "topology-table", "Table view", "topology", { run: async (p) => { await p.getByRole("tab", { name: "Table" }).click(); await wait(p, 350); } });
add("Operations Topology", "topology-timeline", "Timeline view", "topology", { run: async (p) => { await p.getByRole("tab", { name: "Timeline" }).click(); await wait(p, 350); } });
// Engineering
add("Engineering", "engineering", "Engineering Workbench", "engineering", { phone: true, full: true });
add("Engineering", "engineering-plan", "Task detail: plan tab", "engineering", { run: async (p) => { await p.locator('aside[aria-label="Task detail"] [role="tab"]', { hasText: "Plan" }).click(); await wait(p); } });
add("Engineering", "engineering-checks", "Task detail: checks tab", "engineering", { run: async (p) => { await p.locator('aside[aria-label="Task detail"] [role="tab"]', { hasText: "Checks" }).click(); await wait(p); } });
add("Engineering", "engineering-activity", "Task detail: activity tab", "engineering", { run: async (p) => { await p.locator('aside[aria-label="Task detail"] [role="tab"]', { hasText: "Activity" }).click(); await wait(p); } });
add("Engineering", "engineering-select", "Workbench: rows selected", "engineering", { run: async (p) => { await p.getByLabel("Select SV-025").check(); await p.getByLabel("Select CC-061").check(); await wait(p, 300); } });
add("Engineering", "engineering-filter", "Workbench: filtered to staging", "engineering", { run: async (p) => { await p.getByLabel("Environment").selectOption("Staging"); await wait(p, 300); } });
add("Engineering", "task-room", "Task Room SV-025", "task/SV-025", { phone: true });
// Revenue
add("Revenue", "revenue", "Revenue (not connected)", "revenue", { phone: true, note: "The default: no provider is connected." });
add("Revenue", "revenue-demo", "Revenue with the fictional demo", "revenue", { full: true, run: async (p) => { await p.getByLabel("Fictional demo").check(); await wait(p, 400); } });
// Budgets
add("Budgets and usage", "budgets", "Budgets: agent over its limit", "budgets", { phone: true, full: true });
for (const [id, label] of [["normal", "Normal"], ["project", "Project over limit"], ["company", "Company over limit"]])
  add("Budgets and usage", `budgets-${id}`, `Budgets: ${label.toLowerCase()}`, "budgets", { run: async (p) => { await p.getByRole("radio", { name: label }).click(); await wait(p, 300); } });
add("Budgets and usage", "budgets-override", "Request a temporary override", "budgets", { run: async (p) => { await p.getByRole("button", { name: /Request override/ }).first().click(); await wait(p, 350); } });
// Approvals
add("Approvals", "approvals", "Approvals: queue, approval screen, Slack preview", "approvals", { phone: true, full: true });
add("Approvals", "approvals-high", "High-risk request (Developer Unlock and typed ID)", "approvals/r-b41e07", { phone: true });
add("Approvals", "approvals-expired", "Expired request", "approvals/r-0e93cc");
// New Agent
const AGENT_STEPS = ["Template", "Identity", "Intelligence", "Organisation", "Skills and tools", "Repositories and machines", "Permissions", "Instructions", "Budget", "Review and activate"];
AGENT_STEPS.forEach((t, i) => add("New Agent onboarding", `agent-${String(i).padStart(2, "0")}`, `New Agent ${i + 1}/10: ${t}`, "agents", { phone: i === 0 || i === 6 || i === 9, run: (p) => agentWizard(p, i) }));
add("New Agent onboarding", "agent-approve", "New Agent: final approval", "agents", { run: async (p) => { await agentWizard(p, 9); await p.getByRole("button", { name: "Approve & Add Agent" }).click(); await wait(p, 350); } });
// New Project
const PROJECT_STEPS = ["Identity", "Repository", "Environments", "Workers", "Team", "Operating profile", "Budget", "Deploy rules", "Review"];
PROJECT_STEPS.forEach((t, i) => add("New Project onboarding", `project-${String(i).padStart(2, "0")}`, `New Project ${i + 1}/9: ${t}`, "teams/samvision", { phone: i === 0 || i === 8, run: (p) => projectWizard(p, i) }));
add("New Project onboarding", "project-approve", "New Project: final approval", "teams/samvision", { run: async (p) => { await projectWizard(p, 8); await p.getByRole("button", { name: "Approve Mock Project" }).click(); await wait(p, 350); } });
// Settings
for (const [id, t] of [["general", "General"], ["appearance", "Appearance"], ["notifications", "Notifications"], ["windows", "Windows & monitors"], ["security", "Security"], ["connections", "Connections"],
  ["projects", "Operating profiles"], ["workers", "Workers"], ["demo", "Demo controls"], ["more", "Other destinations"], ["help", "Help & shortcuts"]])
  add("Settings", `settings-${id}`, `Settings: ${t}`, `settings/${id}`, { phone: id === "appearance" || id === "security" });
add("Settings", "settings-list", "Phone: Settings opens as a list", "settings", { only: ["phone"], note: "Each section opens on its own screen with a back link." });
// Design system
add("Design system", "design", "Design system", "design", { phone: true, full: true });
add("Design system", "design-menu", "Menu", "design", { run: async (p) => { await p.getByRole("button", { name: /^Actions/ }).click(); await wait(p, 350); } });
add("Design system", "design-dialog", "Dialog", "design", { run: async (p) => { await p.getByRole("button", { name: "Open dialog" }).click(); await wait(p, 400); } });
add("Design system", "design-popover", "Popover", "design", { run: async (p) => { await p.getByRole("button", { name: "Popover" }).click(); await wait(p, 350); } });

// Light theme: the optional variant (dark stays the default). Same layouts, opened with ?theme=light.
export const LIGHT = "?nofeed&theme=light";
const light = (id, title, route, o = {}) => add("Light theme (optional)", `light-${id}`, `Light: ${title}`, route, { query: LIGHT, ...o });
light("office", "My Office", "office", { phone: true, note: "Optional variant. Dark navy and purple stays the default." });
light("messages", "Project Lead conversation", "messages/sv-lead", { phone: true });
light("decisions", "Needs My Attention", "decisions");
light("decision-room", "Decision room", "decisions/sv-025");
light("teams", "SamVision team", "teams/samvision");
light("agents", "Agent directory", "agents");
light("topology", "Operations Topology", "topology");
light("engineering", "Engineering Workbench", "engineering");
light("task-room", "Task Room (terminal stays dark)", "task/SV-025");
light("budgets", "Budgets", "budgets");
light("approvals", "High-risk approval", "approvals/r-b41e07", { phone: true });
light("onboarding", "New Agent onboarding", "agents", { run: (p) => agentWizard(p, 0) });
light("settings", "Settings: Appearance", "settings/appearance", { phone: true });
light("design", "Design system", "design");
light("more", "Phone: More sheet", "office", { only: ["phone"], run: async (p) => { await click(p, '.tabbar button[aria-haspopup="dialog"]'); await wait(p, 450); } });

// Pop-out windows at their own sizes (same sizes as src/windows/manager.ts SIZE).
export const POPS = [
  ["pop-page-topology", "Topology in its own window", "page:topology", 1440, 900],
  ["pop-page-budgets", "Budgets in its own window", "page:budgets", 1440, 900],
  ["pop-dm", "Project Lead conversation in its own window", "dm:sv-lead", 980, 820],
  ["pop-task", "Task Room in its own window", "task:SV-025", 1200, 800],
  ["pop-term", "Terminal pane in its own window", "term:SV-025", 960, 600],
  ["pop-agent", "Agent Inspector in its own window", "panel:agent", 520, 860],
  ["pop-inspector", "Topology Inspector in its own window", "panel:topology-inspector", 520, 860],
  ["pop-context", "Current task context in its own window", "panel:task-context", 520, 860],
];
