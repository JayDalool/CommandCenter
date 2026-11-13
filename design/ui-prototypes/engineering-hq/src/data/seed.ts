// DEMO DATA. Every value below is a locally seeded sample for the design prototype.
//
// What is TRUE (from the repo, server/ccd/registry.py and policy/projects/*.toml, 2026-10-22):
//   project keys, names, ticket prefixes, GauzeMate paused, merge = owner (CommandCenter: low-risk
//   docs/tests only), autonomy modes as *targets* evaluated in shadow only, SamVision release windows
//   (Thu/Sat 01:00 America/Winnipeg), WorkerNode kinds (server, laptop).
// What is NOT real: agent persona names, task titles beyond the keys' shape, times, statuses,
//   counts, conversations, CPU/memory numbers and every revenue figure. The UI labels them Demo.

/** Seeded keys: samvision, gyst, mfe, gauzemate, commandcenter. New projects add their own. */
export type ProjectKey = string;

export interface ProjectBudget { monthlyUsd: number; perTaskUsd: number; alertPct: number }
export interface Project {
  key: ProjectKey; name: string; prefix: string; color: string; blurb: string;
  mode: string; modeLabel: string; merge: string; health: "healthy" | "degraded" | "paused" | "unknown" | "onboarding";
  env: string; version: string; pausedReason?: string; releaseWindows?: string[]; icon: IconName;
  /** owner/name. repoState "proposed" means only proposed to Jay; nothing exists on GitHub. */
  repo: string; repoState: "connected" | "proposed";
  envs: string[]; machines: string[]; budget: ProjectBudget; created?: number;
  /** Who works on it and to whom each reports. The lead is the member who reports to "jay". */
  team: Member[];
}
export interface Member { id: string; reportsTo: string }
export type IconName = "image" | "layers" | "chart" | "heart" | "cc" | "code" | "db" | "phone" | "rocket" | "gear" | "server" | "laptop" | "search" | "check" | "shield" | "star" | "spark" | "box" | "doc" | "help";

const T = (...m: [string, string][]): Member[] => m.map(([id, reportsTo]) => ({ id, reportsTo }));
export const PROJECTS: Project[] = [
  { key: "samvision", name: "SamVision", prefix: "SV", color: "#4fbf8f", icon: "image",
    blurb: "Real-estate analysis tools for realtors: comparables, pricing and listing insight.",
    mode: "controlled_production", modeLabel: "Controlled production", merge: "Jay merges every PR",
    health: "healthy", env: "Staging", version: "v0.4.2", releaseWindows: ["Thu 01:00", "Sat 01:00"],
    repo: "JayDalool/SamVisionAI", repoState: "connected", envs: ["Development", "Staging", "Production"], machines: ["server"], budget: { monthlyUsd: 600, perTaskUsd: 40, alertPct: 80 }, team: T(["claude", "jay"], ["iris", "claude"], ["nova", "claude"], ["atlas", "claude"], ["pixel", "claude"], ["orion", "claude"]) },
  { key: "gyst", name: "GYST / LifeOps", prefix: "GYST", color: "#9a86d8", icon: "layers",
    blurb: "Jay's personal LifeOps software. Personal-data changes always need Jay.",
    mode: "autonomous_product", modeLabel: "Autonomous product (target · shadow only)", merge: "Jay merges every PR",
    health: "healthy", env: "Development", version: "v0.3.1",
    repo: "JayDalool/gyst-lifeops", repoState: "connected", envs: ["Development"], machines: ["server"], budget: { monthlyUsd: 300, perTaskUsd: 25, alertPct: 80 }, team: T(["claude", "jay"], ["nova", "claude"]) },
  { key: "mfe", name: "MyFamilyExpenses", prefix: "MFE", color: "#d1a94a", icon: "chart",
    blurb: "Family expense tracking. Separate from GYST.",
    mode: "controlled_production", modeLabel: "Controlled production", merge: "Jay merges every PR",
    health: "healthy", env: "Production", version: "v0.2.0",
    repo: "JayDalool/MyFamilyExpenses", repoState: "connected", envs: ["Development", "Production"], machines: ["server"], budget: { monthlyUsd: 250, perTaskUsd: 25, alertPct: 80 }, team: T(["claude", "jay"], ["pixel", "claude"], ["atlas", "claude"]) },
  { key: "gauzemate", name: "GauzeMate", prefix: "GZ", color: "#d9748a", icon: "heart",
    blurb: "Paused by Jay until designs and files are added. No agent works on it.",
    mode: "paused", modeLabel: "Paused", merge: "Jay merges every PR", health: "paused", env: "—", version: "v0.1.5",
    pausedReason: "Jay paused GauzeMate until he adds designs and files",
    repo: "JayDalool/GauzeMate", repoState: "connected", envs: ["Development"], machines: ["server"], budget: { monthlyUsd: 0, perTaskUsd: 0, alertPct: 80 },
    // D-024 Annex C2 (Jay, 2026-10-24): no active Project Lead while GauzeMate is paused. The other four projects are led
    // by the Claude Project Lead, a stable role whose backing model may change; each project's history stays separate.
    team: [] },
  { key: "commandcenter", name: "CommandCenter", prefix: "CC", color: "#6a9ad8", icon: "cc",
    blurb: "This control plane. Experimental autonomy is evaluated in shadow mode only (D-008).",
    mode: "experimental_autonomy", modeLabel: "Experimental autonomy (shadow only)", merge: "Auto-merge for low-risk docs/tests only",
    health: "healthy", env: "Production", version: "v1.2.0",
    repo: "JayDalool/CommandCenter", repoState: "connected", envs: ["Development", "Production"], machines: ["server"], budget: { monthlyUsd: 500, perTaskUsd: 30, alertPct: 80 }, team: T(["claude", "jay"], ["nova", "claude"], ["atlas", "claude"], ["orion", "claude"]) },
];
/** NOTE: PROJECTS, AGENTS, TASKS and CONVERSATIONS are LIVE views. data/org.ts keeps them in step with the
 *  shared organisation store (onboarded agents, created projects), in every window. */
export const project = (k: string) => PROJECTS.find((p) => p.key === k) ?? PROJECTS[0];
export const findProject = (k: string | undefined) => PROJECTS.find((p) => p.key === k) ?? null;
export const leadOf = (p: Project) => p.team.find((m) => m.reportsTo === "jay")?.id ?? null;

export type Presence = "working" | "idle" | "researching" | "reviewing" | "waiting" | "blocked" | "queued" | "paused" | "offline" | "disconnected" | "unknown" | "notstarted" | "offboarded";
export const PRESENCE_LABEL: Record<Presence, string> = { working: "Working", idle: "Idle", researching: "Researching", reviewing: "Reviewing",
  waiting: "Waiting for Jay", blocked: "Blocked", queued: "Queued", paused: "Paused", offline: "Offline", disconnected: "Disconnected", unknown: "Unknown",
  notstarted: "Not started", offboarded: "Offboarded" };

/** Model IDs as ccd's usage meter records them (server/ccd/meter.py). The label is for display only. */
export const MODELS: Record<string, { label: string; vendor: string }> = {
  "claude-opus-5-5": { label: "Claude Opus 5.5", vendor: "Anthropic" },
  "claude-sonnet-5-5": { label: "Claude Sonnet 5.5", vendor: "Anthropic" },
  "claude-haiku-5-5": { label: "Claude Haiku 5.5", vendor: "Anthropic" },
  "gpt-5-codex": { label: "GPT-5 Codex", vendor: "OpenAI" },
};
export const modelLabel = (id?: string) => (id ? MODELS[id]?.label ?? id : "No session");

/**
 * A persona is a STABLE ROLE. Its name, colour and specialisation never change; the model and the
 * session behind it can (see AgentState). Persona names come from the concept art (approved by Jay).
 */
export type Life = "active" | "paused" | "offboarded";
export interface Agent {
  /** Stable ID. Never changes, never reused; history is attributed to it. The name can change. */
  id: string; name: string; role: string; spec: string; stage: string; color: string; glyph: IconName;
  template?: string; created?: number; description?: string;
  /** Lifecycle. Missing means active. */
  life?: Life; lifeNote?: string;
}
export const AGENTS: Agent[] = [
  { id: "claude", name: "Claude", role: "Project Lead", spec: "Turns Jay's requests into scoped tasks, delegates, keeps Jay informed", stage: "Coordinates", color: "#ff7a45", glyph: "spark" },
  { id: "iris", name: "Iris", role: "Research / Planning Lead", spec: "Requirements, research and implementation plans", stage: "1. Plan", color: "#4f7bff", glyph: "search" },
  { id: "nova", name: "Nova", role: "Implementation Agent", spec: "Bounded code changes on an isolated branch, with tests", stage: "2. Build", color: "#a463ff", glyph: "star" },
  { id: "atlas", name: "Atlas", role: "Independent Code Reviewer", spec: "Reviews at a pinned head; never reviews its own work", stage: "3. Review", color: "#22c98e", glyph: "check" },
  { id: "pixel", name: "Pixel", role: "UI Testing Lead", spec: "Playwright runs, screenshots and accessibility checks", stage: "4. Test", color: "#ff4fa0", glyph: "heart" },
  { id: "orion", name: "Orion", role: "Release / DevOps Lead", spec: "Release readiness, gates and post-deploy verification", stage: "5. Verify", color: "#ffb020", glyph: "box" },
];
const UNKNOWN_AGENT: Agent = { id: "unknown", name: "Unknown agent", role: "Not in the directory", spec: "", stage: "", color: "#5d6a85", glyph: "help" as IconName };
export const agent = (id: string) => AGENTS.find((a) => a.id === id) ?? (id === "jay" ? { ...UNKNOWN_AGENT, id: "jay", name: "Jay", role: "Engineering Director" } : UNKNOWN_AGENT);
export const lifeOf = (id: string): Life => AGENTS.find((a) => a.id === id)?.life ?? "active";
/** Agents that can work (active or paused). Offboarded agents stay in AGENTS so history still names them. */
export const rosterAgents = () => AGENTS.filter((a) => a.life !== "offboarded");
/** The projects an agent belongs to. */
export const projectsOf = (id: string) => PROJECTS.filter((p) => p.team.some((m) => m.id === id));

/** What the persona is doing NOW. Every field can change between sessions. */
export interface AgentState {
  status: Presence; detail: string; task?: string; project?: ProjectKey;
  model?: string; session?: string; questions?: number; at: number;
}
const T0 = Date.now();
const ago = (min: number) => T0 - min * 60_000;
export const INITIAL_AGENT_STATE: Record<string, AgentState> = {
  claude: { status: "working", detail: "coordinating", task: "SV-025", project: "samvision", model: "claude-opus-5-5", session: "lead-sv-3c9e", at: ago(2) },
  iris: { status: "idle", detail: "planning complete", task: "SV-031", project: "samvision", model: "claude-opus-5-5", session: "plan-sv-81a0", at: ago(38) },
  nova: { status: "working", detail: "implementing · tests 41/48", task: "SV-025", project: "samvision", model: "claude-sonnet-5-5", session: "impl-sv-5d12", at: ago(1) },
  atlas: { status: "reviewing", detail: "PR #839 at head 7f3a9c1", task: "SV-029", project: "samvision", model: "gpt-5-codex", session: "rev-sv-c470", at: ago(6) },
  pixel: { status: "blocked", detail: "release window undecided", task: "MFE-014", project: "mfe", model: "claude-sonnet-5-5", session: "qa-mfe-2b7f", at: ago(47) },
  orion: { status: "waiting", detail: "release v0.4.2", task: "CC-058", project: "commandcenter", model: "claude-haiku-5-5", session: "rel-cc-9e05", questions: 1, at: ago(21) },
};
/** Earlier sessions behind each persona (demo): the role stays, the model and session change. */
export const SESSION_HISTORY: Record<string, { session: string; model: string; task: string; ended: string }[]> = {
  claude: [{ session: "lead-sv-17b2", model: "claude-opus-5-5", task: "SV-024", ended: "2 days ago" }],
  iris: [{ session: "plan-gy-44c1", model: "claude-sonnet-5-5", task: "GYST-018", ended: "3 days ago" }],
  nova: [{ session: "impl-gy-0a9d", model: "claude-sonnet-5-5", task: "GYST-019", ended: "6h ago" }, { session: "impl-cc-7e21", model: "claude-opus-5-5", task: "CC-061", ended: "1 day ago" }],
  atlas: [{ session: "rev-mf-d3e8", model: "gpt-5-codex", task: "MFE-012", ended: "2 days ago" }],
  pixel: [{ session: "qa-mf-61b0", model: "claude-haiku-5-5", task: "MFE-012", ended: "2 days ago" }],
  orion: [{ session: "rel-sv-0c44", model: "claude-sonnet-5-5", task: "SV-024", ended: "5 days ago" }],
};

export type Stage = "Planning" | "Implementing" | "Reviewing" | "UI Testing" | "Verifying" | "Ready to Merge" | "Deploying" | "Needs Jay" | "Blocked" | "Closed" | "Paused";
export interface Task {
  key: string; project: ProjectKey; title: string; stage: Stage; priority: "High" | "Medium" | "Low";
  owner: string; updated: string; why: string; plan: string[]; criteria: string[]; questions: string[]; pr?: string; labels: string[];
  /** Earlier owners, oldest first. Kept when an agent is offboarded so the work stays attributable. */
  formerOwners?: string[];
}
export const TASKS: Task[] = [
  { key: "SV-025", project: "samvision", title: "Rental comparison redesign", stage: "Implementing", priority: "High", owner: "nova", updated: "2h ago",
    why: "Realtors compare rentals across tabs today; a single view with inline filters should cut the steps and keep every calculation identical.",
    plan: ["Single-page comparison layout behind a flag", "Inline filters and sort", "Keep pricing calculations byte-identical", "Playwright screens at 1366 and 1920"],
    criteria: ["Same numbers as today for 50 fixture listings", "Page load stays under 2 s", "No change to the live site until Jay approves", "Accessible (WCAG 2.1 AA)"],
    questions: ["Option A (single page) or Option B (split flow)?"], pr: "#842", labels: ["ui", "frontend"] },
  { key: "SV-031", project: "samvision", title: "Comparable-sales scoring refresh", stage: "Planning", priority: "Medium", owner: "iris", updated: "4h ago",
    why: "Scoring weights are a year old.", plan: ["Research current weighting", "Back-test against closed sales"], criteria: ["Back-test error within 5%"], questions: [], labels: ["data"] },
  { key: "SV-029", project: "samvision", title: "Listing import retry and backoff", stage: "Reviewing", priority: "Medium", owner: "atlas", updated: "5h ago",
    why: "Imports fail on transient errors.", plan: ["Retry with backoff", "Dead-letter list"], criteria: ["No duplicate listings"], questions: [], pr: "#839", labels: ["backend"] },
  { key: "CC-061", project: "commandcenter", title: "Engineering HQ prototype", stage: "Implementing", priority: "High", owner: "nova", updated: "now",
    why: "Move from a monitoring dashboard to an engineering-company HQ Jay manages.", plan: ["Isolated prototype", "Pop out any tab", "Screenshot comparison"],
    criteria: ["Seven pages clickable", "Original tab shaded when popped", "No production change"], questions: ["Keep the repo's project colours or the concept's?"], labels: ["ui", "design"] },
  { key: "CC-058", project: "commandcenter", title: "Autonomy v3 shadow comparisons", stage: "Verifying", priority: "Medium", owner: "orion", updated: "1d ago",
    why: "Record what autonomy would have done, change nothing.", plan: ["Shadow ledger", "Daily diff"], criteria: ["Shadow only; no execution"], questions: [], labels: ["autonomy"] },
  { key: "GYST-019", project: "gyst", title: "Agent memory persistence layer", stage: "Ready to Merge", priority: "Medium", owner: "nova", updated: "6h ago",
    why: "Sessions forget context between days.", plan: ["Local store", "Retention rules"], criteria: ["Personal-data trigger reviewed by Jay"], questions: [], pr: "#57", labels: ["personal-data"] },
  { key: "GYST-018", project: "gyst", title: "Evaluation pipeline for routines", stage: "Implementing", priority: "Low", owner: "nova", updated: "2d ago",
    why: "Measure routine suggestions.", plan: ["Fixtures", "Scoring"], criteria: ["Repeatable run"], questions: [], labels: [] },
  { key: "MFE-014", project: "mfe", title: "Mobile settings and notifications", stage: "Blocked", priority: "High", owner: "pixel", updated: "8h ago",
    why: "Settings screen is desktop only.", plan: ["Responsive settings", "Notification toggles"], criteria: ["Works at 375 px"], questions: ["Release window for MFE is still open — pick one?"], labels: ["mobile"] },
  { key: "MFE-012", project: "mfe", title: "Quarterly budget tracking", stage: "UI Testing", priority: "Low", owner: "pixel", updated: "2d ago",
    why: "Families asked for quarter views.", plan: ["Quarter rollup"], criteria: ["Totals match monthly sums"], questions: [], labels: ["ui"] },
  { key: "GZ-015", project: "gauzemate", title: "Onboarding flow", stage: "Paused", priority: "Low", owner: "claude", updated: "13d ago",
    why: "Paused with the project.", plan: [], criteria: [], questions: [], labels: [] },
];
export const task = (k: string) => TASKS.find((t) => t.key === k) ?? null;

export interface Conversation { id: string; title: string; sub: string; agent?: string; project?: ProjectKey; kind: "dm" | "team" | "slack"; archived?: boolean }
export const CONVERSATIONS: Conversation[] = [
  { id: "sv-lead", title: "Claude", sub: "Project Lead · SamVision", agent: "claude", project: "samvision", kind: "dm" },
  { id: "nova", title: "Nova", sub: "Implementation Agent", agent: "nova", project: "samvision", kind: "dm" },
  { id: "iris", title: "Iris", sub: "Research / Planning Lead", agent: "iris", project: "samvision", kind: "dm" },
  { id: "atlas", title: "Atlas", sub: "Independent Code Reviewer", agent: "atlas", project: "samvision", kind: "dm" },
  { id: "pixel", title: "Pixel", sub: "UI Testing Lead", agent: "pixel", project: "mfe", kind: "dm" },
  { id: "orion", title: "Orion", sub: "Release / DevOps Lead", agent: "orion", project: "commandcenter", kind: "dm" },
  { id: "cc-lead", title: "Claude", sub: "Project Lead · CommandCenter", agent: "claude", project: "commandcenter", kind: "dm" },
  { id: "team-samvision", title: "# samvision-team", sub: "Team channel", project: "samvision", kind: "team" },
  { id: "slack", title: "Slack", sub: "Not connected", kind: "slack" },
];
export const conversation = (id: string) => CONVERSATIONS.find((c) => c.id === id) ?? null;
/** The private conversation with a project's lead (its own if there is one, else the lead's main one). */
export function leadConversation(key: string): Conversation | null {
  const p = findProject(key); const lead = p ? leadOf(p) : null;
  if (!lead) return null;
  return CONVERSATIONS.find((c) => c.kind === "dm" && !c.archived && c.agent === lead && c.project === key)
    ?? CONVERSATIONS.find((c) => c.kind === "dm" && !c.archived && c.agent === lead) ?? null;
}
export const teamConversation = (key: string) => CONVERSATIONS.find((c) => c.kind === "team" && c.project === key) ?? null;
export const healthOf = (p: Project) => p.health === "paused" ? { label: "Paused", tone: "idle" } : p.health === "onboarding" ? { label: "Onboarding", tone: "info" }
  : p.health === "degraded" ? { label: "Degraded", tone: "warn" } : p.health === "unknown" ? { label: "Unknown", tone: "idle" } : { label: "Healthy", tone: "ok" };

export interface ChatMessage { cid: string; from: string; at: string; text: string; list?: string[]; card?: string; ask?: string }
export const SEED_CHAT: Record<string, ChatMessage[]> = {
  "sv-lead": [
    { cid: "s1", from: "jay", at: "7:58 PM", text: "Claude, can you give me a status update on SV-025 (Rental comparison redesign)?\n\nAlso, reminder: production must remain untouched until I approve the changes. No live deployments." },
    { cid: "s2", from: "claude", at: "8:02 PM", text: "Understood. Production will remain untouched.\n\nHere's the workflow we've set up for SV-025:",
      list: ["Requirements and acceptance criteria have been created.", "I've delegated research and planning to Iris.", "Nova is handling the implementation.",
        "Atlas will perform an independent code review.", "Pixel will run UI testing.", "Orion will verify the deployment (after your approval)."] },
    { cid: "s3", from: "claude", at: "8:24 PM", text: "Current status:", card: "SV-025" },
    { cid: "s4", from: "claude", at: "8:26 PM", text: "One open question: Iris found two workable layouts for the comparison flow. Option A keeps realtors on a single page; Option B splits search and details. I recommend A. I've put both, with evidence, in the Decision Room.", ask: "D-SV-025" },
  ],
  nova: [{ cid: "n1", from: "nova", at: "4:18 PM", text: "PR #842 is in progress. Initial layout is behind the flag; numbers match on 50/50 fixtures." }],
  iris: [{ cid: "i1", from: "iris", at: "2:11 PM", text: "Research plan completed for SV-025. Two layout options documented with trade-offs." }],
  atlas: [{ cid: "a1", from: "atlas", at: "1:56 PM", text: "Noted. I'll review once Nova's PR is at a stable head." }],
  pixel: [{ cid: "p1", from: "pixel", at: "11:03 AM", text: "Test plan is ready. 18 screens, 1366 and 1920." }],
  orion: [{ cid: "o1", from: "orion", at: "9:24 AM", text: "Standing by for approval. Nothing will deploy without your gate." }],
  "cc-lead": [{ cid: "c1", from: "claude", at: "Yesterday", text: "Autonomy v3 is running in shadow only. It records what it would have done; nothing executes." }],
  "team-samvision": [
    { cid: "t1", from: "claude", at: "2h ago", text: "SV-025 is making good progress. Nova is about 70% complete." },
    { cid: "t2", from: "nova", at: "4h ago", text: "Pushed a new commit for the comparison layout. Ready for review → PR #842" },
    { cid: "t3", from: "atlas", at: "6h ago", text: "Left comments on PR #839. Main issue is error handling; should be a quick fix." },
  ],
  slack: [],
};

export const HOSTS = [
  { id: "server", name: "jay-server", kind: "server", status: "online", sessions: 8, cpu: 24, mem: 62, disk: 38 },
  { id: "laptop", name: "laptop (WSL)", kind: "laptop", status: "unknown", sessions: 0, cpu: 0, mem: 0, disk: 0 },
] as const;

export const DECISION = {
  id: "D-SV-025", task: "SV-025", title: "Choose the rental comparison workflow for SamVision", due: "Thu",
  options: [
    { id: "A", title: "Single-page comparison flow", sub: "Keep realtors on a single page with inline filters and pricing.", tag: "Recommended",
      pros: ["Faster, simpler experience", "Fewer steps for a typical comparison", "Lower engineering complexity", "Easier to maintain"], cons: [] as string[] },
    { id: "B", title: "Split workflow (search → details)", sub: "A two-step flow with a separate details page.", tag: "Alternative",
      pros: ["Richer detail per listing", "Better for complex cases"], cons: ["More steps per comparison"] },
  ],
};

export const SPARK = {
  a: [4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11, 10, 12],
  b: [5, 4, 6, 5, 7, 6, 5, 7, 8, 7, 9, 8, 9, 10],
  c: [3, 5, 4, 6, 5, 4, 6, 7, 6, 8, 7, 6, 8, 9],
  d: [6, 5, 7, 4, 6, 5, 7, 6, 8, 5, 7, 9, 6, 8],
};
