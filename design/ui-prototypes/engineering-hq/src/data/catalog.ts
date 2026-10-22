// What an agent or a project can be configured with, the reusable templates, and the rules that combine
// them. DEMO: a design proposal. Nothing here is written to ccd, to policy files or to GitHub.
import type { IconName } from "./seed";

// ---------------------------------------------------------------- intelligence
export type Provider = "anthropic" | "openai";
export type Reasoning = "low" | "medium" | "high" | "max";
export const PROVIDERS: { id: Provider; label: string; models: string[] }[] = [
  { id: "anthropic", label: "Anthropic", models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] },
  { id: "openai", label: "OpenAI", models: ["gpt-5-codex"] },
];
export const providerOf = (model: string) => PROVIDERS.find((p) => p.models.includes(model))?.id;
/** Model class, so a template can recommend a tier without pinning a version. */
export const MODEL_TIER: Record<string, "frontier" | "balanced" | "fast"> = {
  "claude-opus-5-5": "frontier", "claude-sonnet-5-5": "balanced", "claude-haiku-5-5": "fast", "gpt-5-codex": "balanced",
};
/** $ per million input / output tokens, as ccd's usage meter prices them (server/ccd/meter.py). */
export const MODEL_PRICE: Record<string, [number, number]> = {
  "claude-opus-5-5": [4, 20], "claude-sonnet-5-5": [2, 10], "claude-haiku-5-5": [0.1, 0.5], "gpt-5-codex": [1.25, 10],
};
export const REASONING: { id: Reasoning; label: string; hint: string }[] = [
  { id: "low", label: "Low", hint: "Routine, well-specified changes" },
  { id: "medium", label: "Medium", hint: "Most implementation work" },
  { id: "high", label: "High", hint: "Planning, review, hard bugs" },
  { id: "max", label: "Max", hint: "Architecture and incident analysis" },
];

// ---------------------------------------------------------------- permissions
/** Allowed · Requires approval (Jay approves each use) · Denied. */
export type Grant = "allow" | "approval" | "deny";
export const GRANT_RANK: Record<Grant, number> = { deny: 0, approval: 1, allow: 2 };
export const GRANT_LABEL: Record<Grant, string> = { allow: "Allowed", approval: "Requires approval", deny: "Denied" };
export const minGrant = (...g: Grant[]): Grant => g.reduce((a, b) => (GRANT_RANK[b] < GRANT_RANK[a] ? b : a), "allow" as Grant);

export interface PermDef {
  id: string; label: string; group: string;
  /** The most an agent setting can ever reach. CommandCenter enforces this; no setting overrides it. */
  ceiling: Grant; boundary?: string;
  /** The worker capability it needs, if any. */
  needs?: string;
  /** Whether the task execution mode can restrict it (writes and actions; not plain reads). */
  acts?: boolean;
}
export const PERM_GROUPS = ["Repository", "Runtime", "Production", "Data", "Infrastructure"] as const;
export const PERMISSIONS: PermDef[] = [
  { id: "repo.read", label: "Read code", group: "Repository", ceiling: "allow", needs: "git" },
  { id: "repo.branch", label: "Create local branches", group: "Repository", ceiling: "allow", needs: "git", acts: true },
  { id: "repo.worktree", label: "Modify its worktree", group: "Repository", ceiling: "allow", needs: "git", acts: true },
  { id: "repo.commit", label: "Commit", group: "Repository", ceiling: "allow", needs: "git", acts: true },
  { id: "repo.push", label: "Push its own feature branches", group: "Repository", ceiling: "allow", needs: "git", acts: true },
  { id: "repo.pr", label: "Open pull requests", group: "Repository", ceiling: "allow", acts: true },
  { id: "repo.merge", label: "Merge pull requests", group: "Repository", ceiling: "deny", boundary: "Owner only. Jay merges every PR." },
  { id: "run.tests", label: "Execute tests", group: "Runtime", ceiling: "allow", needs: "tests", acts: true },
  { id: "run.dev", label: "Run a dev server", group: "Runtime", ceiling: "allow", needs: "dev_server", acts: true },
  { id: "run.terminal", label: "Use a terminal", group: "Runtime", ceiling: "allow", needs: "terminal", acts: true },
  { id: "run.browser", label: "Inspect with a browser", group: "Runtime", ceiling: "allow", needs: "browser", acts: true },
  { id: "run.ci", label: "Re-run CI jobs", group: "Runtime", ceiling: "approval", needs: "ci", acts: true, boundary: "CI re-runs are approved per run." },
  { id: "prod.observe", label: "Observe (status, logs)", group: "Production", ceiling: "allow" },
  { id: "prod.diagnose", label: "Run diagnostics", group: "Production", ceiling: "approval", acts: true, boundary: "Diagnostics on production are approved per run." },
  { id: "prod.restart", label: "Restart an approved service", group: "Production", ceiling: "approval", acts: true, boundary: "Restarts need Jay's approval." },
  { id: "prod.deploy", label: "Deploy", group: "Production", ceiling: "approval", acts: true, boundary: "Deploys go through the release gate and Jay." },
  { id: "prod.rollback", label: "Roll back", group: "Production", ceiling: "approval", acts: true, boundary: "Rollbacks need Jay's approval." },
  { id: "prod.browser_write", label: "Change production through a browser", group: "Production", ceiling: "deny", boundary: "Never. Agents may only observe production." },
  { id: "data.dev_read", label: "Read development database", group: "Data", ceiling: "allow", needs: "database" },
  { id: "data.dev_write", label: "Modify development database", group: "Data", ceiling: "approval", needs: "database", acts: true, boundary: "Development data changes are approved per change." },
  { id: "data.prod", label: "Production database access", group: "Data", ceiling: "deny", boundary: "Never available to agents." },
  { id: "infra.runners", label: "Manage runners", group: "Infrastructure", ceiling: "deny", boundary: "Infrastructure stays with Jay." },
  { id: "infra.dns", label: "Change DNS", group: "Infrastructure", ceiling: "deny", boundary: "Infrastructure stays with Jay." },
  { id: "infra.hosting", label: "Change hosting", group: "Infrastructure", ceiling: "deny", boundary: "Infrastructure stays with Jay." },
  { id: "infra.secrets", label: "Read or write secrets", group: "Infrastructure", ceiling: "deny", boundary: "Secrets stay in ccd. No agent and no browser sees them." },
  { id: "infra.provision", label: "Provision infrastructure", group: "Infrastructure", ceiling: "deny", boundary: "Never from an agent." },
];
export const perm = (id: string) => PERMISSIONS.find((p) => p.id === id)!;
export type Grants = Record<string, Grant>;
/** Template grants are clamped to each permission's ceiling. */
export function grants(allow: string[], approval: string[] = []): Grants {
  const g: Grants = {};
  for (const p of PERMISSIONS) g[p.id] = minGrant(allow.includes(p.id) ? "allow" : approval.includes(p.id) ? "approval" : "deny", p.ceiling);
  return g;
}

// ---------------------------------------------------------------- workers and task modes
export interface Worker { id: string; label: string; status: "online" | "unknown"; caps: string[]; agentNode: boolean; note: string }
export const WORKERS: Worker[] = [
  { id: "server", label: "jay-server", status: "online", caps: ["git", "tests", "dev_server", "terminal", "browser", "ci", "database"], agentNode: true,
    note: "Allowed agent execution node today (allowed_nodes = server)." },
  { id: "laptop", label: "jay-laptop-wsl", status: "unknown", caps: ["git", "tests", "terminal"], agentNode: false,
    note: "Not an agent execution node today. Using it needs Jay's approval and a policy change." },
];
export const worker = (id: string) => WORKERS.find((w) => w.id === id);
export const WORKER_CAP_LABEL: Record<string, string> = { git: "Git", tests: "Test runner", dev_server: "Dev server", terminal: "Terminal", browser: "Browser", ci: "CI access", database: "Dev database" };

export type TaskMode = "manual" | "assisted" | "autonomous";
export const TASK_MODES: { id: TaskMode; label: string; hint: string }[] = [
  { id: "manual", label: "Manual", hint: "Jay works; agents observe or help when asked." },
  { id: "assisted", label: "Assisted", hint: "Jay drives; agents actively assist." },
  { id: "autonomous", label: "Autonomous", hint: "CommandCenter drives within the project profile." },
];
/** What a task mode allows for actions (writes); reads are never restricted by mode. */
export const MODE_CAP: Record<TaskMode, Grant> = { manual: "approval", assisted: "allow", autonomous: "allow" };

/**
 * An agent may use a capability only where all four agree:
 *   agent grant ∩ project rule ∩ worker capability ∩ task execution mode.
 * The result can never be more permissive than any one of them.
 */
export function effective(permId: string, agentGrants: Grants, projectRules: Grants, workerIds: string[], mode: TaskMode) {
  const p = perm(permId);
  const a = minGrant(agentGrants[permId] ?? "deny", p.ceiling);
  const pr = projectRules[permId] ?? "allow";
  const w: Grant = !p.needs ? "allow" : workerIds.some((id) => worker(id)?.caps.includes(p.needs!)) ? "allow" : "deny";
  const m: Grant = p.acts ? MODE_CAP[mode] : "allow";
  return { agent: a, project: pr, worker: w, mode: m, result: minGrant(a, pr, w, m) };
}

// ---------------------------------------------------------------- tools and capabilities
/** Available = installed on a worker it may use. Authorised = what its grants allow. They are different things. */
export const TOOLS: { id: string; label: string; perm: string; cap?: string; locked?: string }[] = [
  { id: "code", label: "Code inspection", perm: "repo.read", cap: "git" },
  { id: "coding", label: "Coding (edit, commit)", perm: "repo.commit", cap: "git" },
  { id: "review", label: "Code review", perm: "repo.read", cap: "git" },
  { id: "testing", label: "Testing", perm: "run.tests", cap: "tests" },
  { id: "terminal", label: "Terminal", perm: "run.terminal", cap: "terminal" },
  { id: "browser", label: "Browser", perm: "run.browser", cap: "browser" },
  { id: "browser_prod", label: "Production write through browser", perm: "prod.browser_write", cap: "browser" },
  { id: "github", label: "GitHub (PRs, reviews)", perm: "repo.pr" },
  { id: "ci", label: "CI interaction", perm: "run.ci", cap: "ci" },
  { id: "deploy", label: "Deployment", perm: "prod.deploy" },
  { id: "database", label: "Database (development)", perm: "data.dev_read", cap: "database" },
  { id: "graphify", label: "Graphify", perm: "repo.read", locked: "Not approved yet. Install only after Jay approves it." },
];
export const SKILLS = [
  { id: "planning", label: "Requirements and planning" }, { id: "research", label: "Research synthesis" }, { id: "implementation", label: "Implementation with tests" },
  { id: "code-review", label: "Independent code review" }, { id: "security-review", label: "Security review" }, { id: "architecture", label: "Architecture review" },
  { id: "database", label: "Schema and migrations" }, { id: "ui-testing", label: "UI testing and screenshots" }, { id: "accessibility", label: "Accessibility audit" },
  { id: "ux-research", label: "Product and UX research" }, { id: "docs", label: "Documentation" }, { id: "release", label: "Release checklist" }, { id: "coordination", label: "Delegation and coordination" },
];
export const MCP_SERVERS: { id: string; label: string; hint: string; locked?: string }[] = [
  { id: "github", label: "GitHub", hint: "Scoped to its allowed repositories" },
  { id: "filesystem", label: "Filesystem", hint: "Its own worktree only" },
  { id: "playwright", label: "Playwright", hint: "Local and staging builds" },
  { id: "docs", label: "Project docs", hint: "Read-only" },
  { id: "slack", label: "Slack", hint: "", locked: "Off until Jay approves the Slack integration." },
  { id: "billing", label: "Billing", hint: "", locked: "Off until Jay approves the billing integration." },
];

// ---------------------------------------------------------------- instructions
export const HARD_NEVER = [
  "Change production without Jay's approval.",
  "Merge, deploy or change policy on its own.",
  "Review its own work.",
  "Read, copy or ask for secrets.",
  "Create or authorise other agents, or widen its own permissions.",
];
export interface Instructions {
  mission: string; responsibilities: string; operating: string; escalate: string; never: string;
  style: string; output: string; reviews: string; handoff: string;
}
export const INSTRUCTION_FIELDS: { id: keyof Instructions; label: string; hint: string; rows?: number }[] = [
  { id: "mission", label: "Mission", hint: "One sentence on why this agent exists." },
  { id: "responsibilities", label: "Responsibilities", hint: "What it owns.", rows: 3 },
  { id: "operating", label: "Operating instructions", hint: "How it works day to day.", rows: 3 },
  { id: "escalate", label: "Escalate to its lead or Jay when…", hint: "" , rows: 2 },
  { id: "never", label: "Never (in addition to the fixed rules)", hint: "", rows: 2 },
  { id: "style", label: "Communication style", hint: "" },
  { id: "output", label: "Expected output", hint: "" },
  { id: "reviews", label: "Review responsibilities", hint: "" },
  { id: "handoff", label: "Handoff rules", hint: "", rows: 2 },
];

// ---------------------------------------------------------------- budgets
export interface AgentBudget {
  tier: "frontier" | "balanced" | "fast"; dailyWarnUsd: number; weeklyWarnUsd: number; perTaskWarnUsd: number;
  maxParallel: number; escalation: "never" | "approval" | "allowed"; expensiveApprovalUsd: number;
}

// ---------------------------------------------------------------- agent templates
export interface AgentConfig {
  template: string; provider: Provider; model: string; fallback: string; reasoning: Reasoning; context: "standard" | "long";
  skills: string[]; mcp: string[]; repos: string[]; machines: string[]; grants: Grants;
  instructions: Instructions; budget: AgentBudget;
}
export interface AgentTemplate {
  id: string; title: string; spec: string; blurb: string; stage: string; glyph: IconName; color: string;
  reportsTo: "jay" | "lead"; lead?: boolean; core?: boolean;
  config: Omit<AgentConfig, "template" | "repos" | "machines">;
}
const BUD = (tier: AgentBudget["tier"], d: number, w: number, t: number, par = 1): AgentBudget =>
  ({ tier, dailyWarnUsd: d, weeklyWarnUsd: w, perTaskWarnUsd: t, maxParallel: par, escalation: "approval", expensiveApprovalUsd: 25 });
const INS = (mission: string, responsibilities: string, extra: Partial<Instructions> = {}): Instructions => ({
  mission, responsibilities,
  operating: "Work in its own worktree on jay-server. Keep the task ledger current. Small, reviewable steps.",
  escalate: "Requirements are unclear, a change touches production or personal data, or the budget warning fires.",
  never: "", style: "Short, plain updates. Lead with the result.", output: "A clear summary with evidence (tests, screenshots, links).",
  reviews: "Never reviews its own work.", handoff: "Hand off with a summary, open questions and links to evidence.", ...extra,
});
const READ = ["repo.read", "prod.observe"];
const BUILD = [...READ, "repo.branch", "repo.worktree", "repo.commit", "repo.push", "repo.pr", "run.tests", "run.dev", "run.terminal", "data.dev_read"];
export const AGENT_TEMPLATES: AgentTemplate[] = [
  { id: "lead", title: "Project Lead", glyph: "spark", color: "#ff7a45", lead: true, core: true, stage: "Coordinates", reportsTo: "jay",
    spec: "Turns Jay's requests into scoped tasks, delegates and keeps Jay informed", blurb: "Runs a project team.",
    config: { provider: "anthropic", model: "claude-opus-5-5", fallback: "claude-sonnet-5-5", reasoning: "high", context: "long", skills: ["planning", "coordination"], mcp: ["github", "docs"],
      grants: grants([...READ, "repo.pr"], ["prod.diagnose"]),
      instructions: INS("Deliver the project's goals through a well-run team.", "Write requirements and acceptance criteria, delegate each stage, keep Jay informed and bring decisions with evidence.",
        { reviews: "Checks that every stage has a different reviewer from its builder." }), budget: BUD("frontier", 20, 100, 15, 3) } },
  { id: "research", title: "Research / Planning Lead", glyph: "search", color: "#4f7bff", core: true, stage: "1. Plan", reportsTo: "lead",
    spec: "Requirements, research and implementation plans", blurb: "Compares options and writes the plan.",
    config: { provider: "anthropic", model: "claude-opus-5-5", fallback: "claude-sonnet-5-5", reasoning: "high", context: "long", skills: ["research", "planning"], mcp: ["github", "docs"],
      grants: grants(READ), instructions: INS("Make sure the team builds the right thing.", "Research the problem, compare options with trade-offs and write an implementation plan."), budget: BUD("frontier", 15, 70, 10) } },
  { id: "impl", title: "Implementation Agent", glyph: "star", color: "#a463ff", core: true, stage: "2. Build", reportsTo: "lead",
    spec: "Bounded code changes on an isolated branch, with tests", blurb: "Builds the plan on its own branch.",
    config: { provider: "anthropic", model: "claude-sonnet-5-5", fallback: "claude-haiku-5-5", reasoning: "medium", context: "standard", skills: ["implementation"], mcp: ["github", "filesystem"],
      grants: grants(BUILD, ["data.dev_write", "run.ci"]), instructions: INS("Turn approved plans into tested code.", "Implement the plan in small commits on a feature branch, with tests, and open a PR."), budget: BUD("balanced", 25, 120, 12, 2) } },
  { id: "reviewer", title: "Senior Code Reviewer", glyph: "check", color: "#22c98e", core: true, stage: "3. Review", reportsTo: "lead",
    spec: "Reviews at a pinned head; never reviews its own work", blurb: "Independent review on a different model from the builder.",
    config: { provider: "openai", model: "gpt-5-codex", fallback: "claude-opus-5-5", reasoning: "high", context: "long", skills: ["code-review", "security-review"], mcp: ["github"],
      grants: grants([...READ, "run.tests", "repo.pr"]), instructions: INS("Catch defects before Jay sees them.", "Review each PR at a pinned head for correctness, security and tests. Request changes with evidence."), budget: BUD("balanced", 15, 70, 8) } },
  { id: "ui", title: "UI Testing Lead", glyph: "heart", color: "#ff4fa0", core: true, stage: "4. Test", reportsTo: "lead",
    spec: "Playwright runs, screenshots and accessibility checks", blurb: "Proves the UI works on real screens.",
    config: { provider: "anthropic", model: "claude-sonnet-5-5", fallback: "claude-haiku-5-5", reasoning: "medium", context: "standard", skills: ["ui-testing", "accessibility"], mcp: ["playwright", "github"],
      grants: grants([...READ, "run.tests", "run.dev", "run.browser", "run.terminal"]), instructions: INS("Make sure what ships works for people.", "Run the UI test plan at 1366 and 1920, attach screenshots and send defects back to implementation."), budget: BUD("balanced", 10, 50, 6) } },
  { id: "devops", title: "DevOps / Release Lead", glyph: "box", color: "#ffb020", core: true, stage: "5. Verify", reportsTo: "lead",
    spec: "Release readiness, gates and post-deploy verification", blurb: "Prepares releases. Never deploys without Jay.",
    config: { provider: "anthropic", model: "claude-haiku-5-5", fallback: "claude-sonnet-5-5", reasoning: "medium", context: "standard", skills: ["release"], mcp: ["github", "docs"],
      grants: grants([...READ, "run.tests", "run.terminal"], ["prod.diagnose", "prod.deploy", "prod.rollback", "prod.restart", "run.ci"]),
      instructions: INS("Ship safely, inside the release windows.", "Check readiness against the gate, prepare release notes and verify after Jay's approved deploy."), budget: BUD("fast", 8, 40, 5) } },
  { id: "security", title: "Security Reviewer", glyph: "shield", color: "#38c6e8", stage: "3. Review", reportsTo: "lead",
    spec: "Threat review of changes, dependencies and permissions", blurb: "Looks for security mistakes.",
    config: { provider: "anthropic", model: "claude-opus-5-5", fallback: "gpt-5-codex", reasoning: "high", context: "long", skills: ["security-review", "code-review"], mcp: ["github"],
      grants: grants([...READ, "repo.pr"]), instructions: INS("Keep the projects safe.", "Review changes that touch auth, secrets, data or permissions and report findings with severity."), budget: BUD("frontier", 12, 60, 10) } },
  { id: "architect", title: "Architecture Reviewer", glyph: "layers", color: "#c49bff", stage: "1. Plan", reportsTo: "lead",
    spec: "Design reviews for larger changes", blurb: "Reviews designs before code is written.",
    config: { provider: "anthropic", model: "claude-opus-5-5", fallback: "claude-sonnet-5-5", reasoning: "max", context: "long", skills: ["architecture", "planning"], mcp: ["github", "docs"],
      grants: grants(READ), instructions: INS("Keep the systems simple and sound.", "Review designs and plans for larger changes and propose simpler alternatives."), budget: BUD("frontier", 12, 50, 10) } },
  { id: "database", title: "Database Specialist", glyph: "db", color: "#7fd34e", stage: "2. Build", reportsTo: "lead",
    spec: "Schemas, migrations and query performance", blurb: "Owns data changes, with approval.",
    config: { provider: "anthropic", model: "claude-sonnet-5-5", fallback: "claude-opus-5-5", reasoning: "high", context: "standard", skills: ["database", "implementation"], mcp: ["github", "filesystem"],
      grants: grants([...BUILD], ["data.dev_write"]), instructions: INS("Keep data correct and fast.", "Design schema changes and migrations with rollback plans. Migrations need Jay's approval."), budget: BUD("balanced", 15, 70, 10) } },
  { id: "ux", title: "Product / UX Researcher", glyph: "image", color: "#ff8fb1", stage: "1. Plan", reportsTo: "lead",
    spec: "User needs, flows and usability findings", blurb: "Brings the user's view into planning.",
    config: { provider: "anthropic", model: "claude-sonnet-5-5", fallback: "claude-haiku-5-5", reasoning: "medium", context: "standard", skills: ["ux-research", "research"], mcp: ["docs"],
      grants: grants(READ), instructions: INS("Make the product easy to use.", "Study flows, write usability findings and propose improvements with evidence."), budget: BUD("balanced", 8, 40, 5) } },
  { id: "docs", title: "Documentation Agent", glyph: "doc" as IconName, color: "#ffd23f", stage: "5. Verify", reportsTo: "lead",
    spec: "Keeps READMEs, runbooks and release notes current", blurb: "Writes docs as the code changes.",
    config: { provider: "anthropic", model: "claude-haiku-5-5", fallback: "claude-sonnet-5-5", reasoning: "low", context: "standard", skills: ["docs"], mcp: ["github", "docs"],
      grants: grants([...READ, "repo.branch", "repo.worktree", "repo.commit", "repo.push", "repo.pr"]), instructions: INS("Keep the documentation true.", "Update READMEs, runbooks and release notes in the same PR as the change."), budget: BUD("fast", 5, 25, 3) } },
];
export const CUSTOM_TEMPLATE: AgentTemplate = {
  id: "custom", title: "Custom agent", glyph: "gear", color: "#38c6e8", stage: "2. Build", reportsTo: "lead", spec: "", blurb: "Start from a blank, safe default.",
  config: { provider: "anthropic", model: "claude-sonnet-5-5", fallback: "", reasoning: "medium", context: "standard", skills: [], mcp: ["github"], grants: grants(READ),
    instructions: INS("", ""), budget: BUD("balanced", 10, 50, 5) },
};
export const templateOf = (id: string) => AGENT_TEMPLATES.find((t) => t.id === id) ?? CUSTOM_TEMPLATE;
export const TEMPLATE_OF_SEED: Record<string, string> = { claude: "lead", iris: "research", nova: "impl", atlas: "reviewer", pixel: "ui", orion: "devops" };

export const AVATAR_GLYPHS: IconName[] = ["spark", "search", "star", "check", "heart", "box", "shield", "layers", "db", "image", "code", "rocket"];
export const AGENT_COLORS = ["#ff7a45", "#4f7bff", "#a463ff", "#22c98e", "#ff4fa0", "#ffb020", "#38c6e8", "#c49bff", "#7fd34e", "#ff8fb1", "#ffd23f"];
/** IDs no agent may take. */
export const RESERVED_IDS = ["jay", "admin", "root", "system", "ccd", "owner", "coordinator", "commandcenter", "all", "everyone", "unknown", "null", "undefined", "agent", "new", "bot"];

// ---------------------------------------------------------------- projects
export type ProjectType = "personal" | "client" | "employer" | "infra";
export const PROJECT_TYPES: { id: ProjectType; label: string; hint: string }[] = [
  { id: "personal", label: "Personal", hint: "Jay's own products." },
  { id: "client", label: "Client", hint: "Work for a client. Private repositories only." },
  { id: "employer", label: "Employer / Restricted", hint: "Employer code. Never on jay-server; restricted modes only." },
  { id: "infra", label: "Internal infrastructure", hint: "CommandCenter's own tooling." },
];
export const PROJECT_COLORS = ["#38c6e8", "#e05cff", "#7fd34e", "#ffd23f", "#ff6b6b", "#5ce1c6", "#c49bff", "#ff8fb1"];
export const PROJECT_ICONS: IconName[] = ["code", "db", "phone", "rocket", "shield", "layers", "chart", "image"];
/** Repositories the GitHub app already sees (demo list). Connecting one changes nothing on GitHub. */
export const KNOWN_REPOS = ["JayDalool/SamVisionAI", "JayDalool/gyst-lifeops", "JayDalool/MyFamilyExpenses", "JayDalool/GauzeMate", "JayDalool/CommandCenter",
  "JayDalool/listing-scraper", "JayDalool/home-inventory"];
export const ENVIRONMENTS = ["Local", "Development", "Staging", "Production"] as const;
export const ENV_FACTS = ["hosting", "domain", "deploy", "database", "health"] as const;
export const ENV_FACT_LABEL: Record<(typeof ENV_FACTS)[number], string> = { hosting: "Hosting", domain: "Domain", deploy: "Deployment method", database: "Database", health: "Health check" };
export type TargetMode = "restricted" | "controlled_production" | "autonomous_product" | "experimental_autonomy" | "paused";
export const TARGET_MODES: { id: TargetMode; label: string; hint: string }[] = [
  { id: "restricted", label: "Restricted", hint: "Read and suggest only. No pushes." },
  { id: "controlled_production", label: "Controlled production", hint: "Agents prepare; Jay approves every merge and release." },
  { id: "autonomous_product", label: "Autonomous product", hint: "Agents run the pipeline; Jay approves releases." },
  { id: "experimental_autonomy", label: "Experimental autonomy", hint: "Low-risk work may complete on its own. Shadow-evaluated first." },
  { id: "paused", label: "Paused", hint: "No agent works on it." },
];
/** The steps every new project goes through (proposed D-024). Its target mode only applies at the end. */
export const ONBOARDING_STAGES = ["Created", "Onboarding / Observation", "Project fingerprint", "First audit", "Draft operating profile", "Admission review", "Jay approves the mode"];

export interface DeployRules {
  preset: "strict" | "standard" | "custom"; merge: Grant; deploy: Grant; prodWrite: Grant; windows: string[]; tz: string;
  reviewers: number; migrations: Grant; downtime: Grant; browserProd: Grant; database: Grant;
}
export const DEPLOY_PRESETS: Record<"strict" | "standard", Omit<DeployRules, "preset" | "windows" | "tz">> = {
  strict: { merge: "deny", deploy: "deny", prodWrite: "deny", reviewers: 2, migrations: "deny", downtime: "deny", browserProd: "deny", database: "deny" },
  standard: { merge: "deny", deploy: "approval", prodWrite: "deny", reviewers: 1, migrations: "approval", downtime: "approval", browserProd: "deny", database: "deny" },
};
/** How a project's deploy rules limit agent permissions (the "project" gate in effective()). */
export function projectRules(d: DeployRules): Grants {
  const r: Grants = {};
  for (const p of PERMISSIONS) r[p.id] = "allow";
  r["repo.merge"] = d.merge; r["prod.deploy"] = d.deploy; r["prod.rollback"] = d.deploy; r["prod.restart"] = minGrant(d.downtime, d.deploy);
  r["prod.browser_write"] = minGrant(d.browserProd, d.prodWrite); r["data.prod"] = d.database; r["data.dev_write"] = d.migrations;
  return r;
}
export interface ProjectBudgetCfg { monthlyWarnUsd: number; costWarnUsd: number; infraWarnUsd: number; maxParallelAgents: number; preferredModel: string; paidTools: Grant }
