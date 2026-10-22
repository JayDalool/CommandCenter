// THE ORGANISATION STORE (DEMO). One shared, synchronised record of every project, agent, task and
// conversation in the prototype. Every page reads the same objects: seed.ts exports PROJECTS, AGENTS,
// TASKS and CONVERSATIONS, and this module keeps those arrays in step with the store, in every window.
//
// Nothing here talks to ccd, GitHub or a WorkerNode. Approving a wizard only changes this mock store,
// and the UI says so. A real build would call the APIs proposed in AUDIT_AND_MIGRATION_PLAN.md §12.
import { SharedStore, isRecord } from "../lib/shared";
import { useStore } from "../lib/store";
import { AGENTS, CONVERSATIONS, PROJECTS, TASKS, findProject, leadOf, type Agent, type Conversation, type IconName, type Life, type Member, type Project, type Task } from "./seed";
import {
  AGENT_TEMPLATES, CUSTOM_TEMPLATE, DEPLOY_PRESETS, ENVIRONMENTS, TARGET_MODES, TASK_MODES, TEMPLATE_OF_SEED, templateOf,
  type AgentBudget, type AgentConfig, type DeployRules, type Grants, type Instructions, type ProjectBudgetCfg, type ProjectType,
  type Provider, type Reasoning, type TargetMode, type TaskMode,
} from "./catalog";

// ---------------------------------------------------------------- records
export interface AgentProfile extends AgentConfig { version: number; at: number; note: string }
export interface EnvCfg { on: boolean; hosting: string; domain: string; deploy: string; database: string; health: string }
export interface ProjectProfile {
  type: ProjectType; target: TargetMode; taskMode: TaskMode;
  /** "onboarding" until Jay approves the operating profile after admission review. */
  phase: "onboarding" | "active"; stage: number;
  repo: { mode: "existing" | "proposed"; provider: "github"; name: string; branch: string; visibility: "private" | "public"; clone: string };
  envs: Record<string, EnvCfg>; discover: boolean; workers: string[]; deploy: DeployRules; budget: ProjectBudgetCfg; missing: string[];
}
export interface AuditEvent { id: string; at: number; actor: string; kind: string; subject: string; text: string }
export interface SavedDraft { id: string; kind: "agent" | "project"; label: string; at: number; data: AgentDraft | ProjectDraft }
export interface Org {
  v: number; projects: Project[]; agents: Agent[]; tasks: Task[]; convs: Conversation[];
  /** Config versions per agent, oldest first. The last one is current. */
  profiles: Record<string, AgentProfile[]>;
  projectProfiles: Record<string, ProjectProfile>;
  audit: AuditEvent[]; drafts: SavedDraft[];
}

// ---------------------------------------------------------------- drafts
export interface AgentDraft {
  kind: "agent"; step: number; mode: "new" | "edit" | "plan"; editing?: string; savedId?: string; touched: boolean;
  template: string; name: string; id: string; idTouched: boolean; title: string; spec: string; description: string; color: string; glyph: IconName;
  provider: Provider; model: string; fallback: string; reasoning: Reasoning; context: "standard" | "long";
  project: string; reportsTo: string; supervises: string[]; stage: string; secondary: string[];
  skills: string[]; mcp: string[]; repos: string[]; machines: string[]; grants: Grants; instructions: Instructions; budget: AgentBudget;
}
export interface ProjectDraft {
  kind: "project"; step: number; savedId?: string; touched: boolean;
  name: string; key: string; keyTouched: boolean; prefix: string; prefixTouched: boolean; icon: IconName; color: string; description: string; type: ProjectType;
  repoMode: "existing" | "proposed"; repo: string; branch: string; visibility: "private" | "public"; clone: string;
  envs: Record<string, EnvCfg>; discover: boolean; workers: string[];
  lead: string; members: string[]; planned: AgentDraft[];
  target: TargetMode; taskMode: TaskMode; budget: ProjectBudgetCfg; deploy: DeployRules;
}

const slug = (s: string, max = 24) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, max).replace(/-+$/, "");
export const idFromName = (name: string) => slug(name, 32);
export const keyFromName = (name: string) => slug(name, 24);
export function prefixFromName(name: string) {
  const words = name.toUpperCase().replace(/[^A-Z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length) return "";
  return (words.length > 1 ? words.map((w) => w[0]).join("") : words[0]).slice(0, 4);
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export function agentDraftFrom(templateId: string, project = "samvision", mode: AgentDraft["mode"] = "new"): AgentDraft {
  const t = templateOf(templateId);
  const p = findProject(project);
  const lead = p ? leadOf(p) : null;
  const c = clone(t.config);
  return {
    kind: "agent", step: templateId ? 1 : 0, mode, touched: false, template: t.id, name: "", id: "", idTouched: false,
    title: t.id === "custom" ? "" : t.title, spec: t.spec, description: t.blurb === CUSTOM_TEMPLATE.blurb ? "" : t.blurb, color: t.color, glyph: t.glyph,
    provider: c.provider, model: c.model, fallback: c.fallback, reasoning: c.reasoning, context: c.context,
    project, reportsTo: t.reportsTo === "jay" || !lead ? (lead ? lead : "jay") : lead, supervises: [], stage: t.stage, secondary: [],
    skills: c.skills, mcp: c.mcp, repos: p && p.repoState === "connected" ? [p.repo] : [], machines: ["server"], grants: c.grants, instructions: c.instructions, budget: c.budget,
  };
}
export const blankAgentDraft = (project = "samvision"): AgentDraft => ({ ...agentDraftFrom("", project), step: 0, template: "" });

/** An agent's current configuration as an editable draft (Edit). */
export function agentDraftOf(id: string, o: Org = org.get()): AgentDraft {
  const a = o.agents.find((x) => x.id === id)!;
  const prof = currentProfile(id, o);
  const home = o.projects.find((p) => p.team.some((m) => m.id === id));
  const member = home?.team.find((m) => m.id === id);
  return {
    kind: "agent", step: 1, mode: "edit", editing: id, touched: false, template: prof.template, name: a.name, id: a.id, idTouched: true,
    title: a.role, spec: a.spec, description: a.description ?? "", color: a.color, glyph: a.glyph,
    provider: prof.provider, model: prof.model, fallback: prof.fallback, reasoning: prof.reasoning, context: prof.context,
    project: home?.key ?? "", reportsTo: member?.reportsTo ?? "jay", supervises: home ? home.team.filter((m) => m.reportsTo === id).map((m) => m.id) : [],
    stage: a.stage, secondary: [], skills: [...prof.skills], mcp: [...prof.mcp], repos: [...prof.repos], machines: [...prof.machines],
    grants: { ...prof.grants }, instructions: { ...prof.instructions }, budget: { ...prof.budget },
  };
}

const envBlank = (on: boolean): EnvCfg => ({ on, hosting: "", domain: "", deploy: "", database: "", health: "" });
export function blankProjectDraft(): ProjectDraft {
  return {
    kind: "project", step: 0, touched: false, name: "", key: "", keyTouched: false, prefix: "", prefixTouched: false, icon: "rocket", color: "#38c6e8", description: "", type: "personal",
    repoMode: "existing", repo: "", branch: "main", visibility: "private", clone: "~/work/",
    envs: Object.fromEntries(ENVIRONMENTS.map((e) => [e, envBlank(e === "Local" || e === "Development")])), discover: true, workers: ["server"],
    lead: "", members: [], planned: [], target: "controlled_production", taskMode: "assisted",
    budget: { monthlyWarnUsd: 300, costWarnUsd: 25, infraWarnUsd: 50, maxParallelAgents: 3, preferredModel: "claude-sonnet-5-5", paidTools: "approval" },
    deploy: { preset: "standard", ...DEPLOY_PRESETS.standard, windows: [], tz: "America/Winnipeg" },
  };
}

// ---------------------------------------------------------------- seed
const SEED = clone({ projects: PROJECTS, agents: AGENTS, tasks: TASKS, convs: CONVERSATIONS });

function seedProfile(a: Agent): AgentProfile[] {
  const t = AGENT_TEMPLATES.find((x) => x.id === TEMPLATE_OF_SEED[a.id]) ?? CUSTOM_TEMPLATE;
  const repos = SEED.projects.filter((p) => p.team.some((m) => m.id === a.id)).map((p) => p.repo);
  return [{ ...clone(t.config), template: t.id, repos, machines: ["server"], version: 1, at: Date.now() - 30 * 864e5, note: "Seeded persona" }];
}
function seedProjectProfile(p: Project): ProjectProfile {
  const envs = Object.fromEntries(ENVIRONMENTS.map((e) => [e, envBlank(e === "Local" || p.envs.includes(e))]));
  return {
    type: p.key === "commandcenter" ? "infra" : "personal", target: (p.mode as TargetMode), taskMode: p.health === "paused" ? "manual" : "assisted",
    phase: "active", stage: 6, repo: { mode: "existing", provider: "github", name: p.repo, branch: "main", visibility: "private", clone: `~/work/${p.key}` },
    envs, discover: false, workers: p.machines, deploy: { preset: "standard", ...DEPLOY_PRESETS.standard, windows: p.releaseWindows ?? [], tz: "America/Winnipeg" },
    budget: { monthlyWarnUsd: p.budget.monthlyUsd, costWarnUsd: p.budget.perTaskUsd, infraWarnUsd: 50, maxParallelAgents: 3, preferredModel: "claude-sonnet-5-5", paidTools: "approval" },
    missing: [],
  };
}
export function seedOrg(): Org {
  const s = clone(SEED);
  return {
    v: 1, ...s, profiles: Object.fromEntries(s.agents.map((a) => [a.id, seedProfile(a)])),
    projectProfiles: Object.fromEntries(s.projects.map((p) => [p.key, seedProjectProfile(p)])), audit: [], drafts: [],
  };
}

const isOrg = (v: unknown): v is Org => isRecord(v) && typeof v.v === "number" && Array.isArray(v.projects) && Array.isArray(v.agents) && Array.isArray(v.tasks)
  && Array.isArray(v.convs) && isRecord(v.profiles) && isRecord(v.projectProfiles) && Array.isArray(v.audit) && Array.isArray(v.drafts)
  && v.projects.every((p) => isRecord(p) && typeof p.key === "string" && Array.isArray(p.team)) && v.agents.every((a) => isRecord(a) && typeof a.id === "string" && typeof a.name === "string");

export const org = new SharedStore<Org>("org1", seedOrg(), isOrg);

/** Keep seed.ts's exported arrays pointing at the store's records (same objects, in place). */
function sync() {
  const o = org.get();
  const put = <T,>(arr: T[], next: T[]) => { arr.splice(0, arr.length, ...next); };
  put(PROJECTS, o.projects); put(AGENTS, o.agents); put(TASKS, o.tasks); put(CONVERSATIONS, o.convs);
}
sync();
org.subscribe(sync);

export const useOrg = () => useStore(org);
export const currentProfile = (id: string, o: Org = org.get()) => (o.profiles[id] ?? []).at(-1) ?? seedProfile(o.agents.find((a) => a.id === id) ?? AGENTS[0])[0];
export const projectProfile = (key: string, o: Org = org.get()) => o.projectProfiles[key] ?? seedProjectProfile(o.projects.find((p) => p.key === key) ?? PROJECTS[0]);

// ---------------------------------------------------------------- actions (all mock; actor is always Jay)
let seq = 0;
const evId = () => `ev-${Date.now().toString(36)}-${(seq++).toString(36)}`;
function audit(o: Org, kind: string, subject: string, text: string): AuditEvent[] {
  return [...o.audit, { id: evId(), at: Date.now(), actor: "jay", kind, subject, text }];
}
function change(f: (o: Org) => Org) { org.set((o) => ({ ...f(o), v: o.v + 1 })); }

const profileFrom = (d: AgentDraft, version: number, note: string): AgentProfile => ({
  template: d.template || "custom", provider: d.provider, model: d.model, fallback: d.fallback, reasoning: d.reasoning, context: d.context,
  skills: [...d.skills], mcp: [...d.mcp], repos: [...d.repos], machines: [...d.machines], grants: { ...d.grants }, instructions: { ...d.instructions }, budget: { ...d.budget },
  version, at: Date.now(), note,
});
const agentFrom = (d: AgentDraft): Agent => ({
  id: d.id, name: d.name.trim(), role: d.title.trim(), spec: d.spec.trim(), stage: d.stage, color: d.color, glyph: d.glyph,
  template: d.template || "custom", created: Date.now(), description: d.description.trim(), life: "active",
});
/** Put `id` into a project team, reporting to `reportsTo`; `supervises` now report to it. */
function placeInTeam(p: Project, id: string, reportsTo: string, supervises: string[]): Project {
  const team = p.team.filter((m) => m.id !== id).map((m) => (supervises.includes(m.id) ? { ...m, reportsTo: id } : m));
  return { ...p, team: [...team, { id, reportsTo }] };
}

/** Approve & Add Agent. MOCK ONLY: no credentials, no session, nothing sent to ccd. */
export function activateAgent(d: AgentDraft) {
  change((o) => {
    const a = agentFrom(d);
    return {
      ...o,
      agents: [...o.agents, a],
      projects: o.projects.map((p) => (p.key === d.project ? placeInTeam(p, a.id, d.reportsTo, d.supervises) : p)),
      convs: [...o.convs, { id: `dm-${a.id}`, title: a.name, sub: a.role, agent: a.id, project: d.project, kind: "dm" }],
      profiles: { ...o.profiles, [a.id]: [profileFrom(d, 1, "Created by Jay with the New Agent wizard")] },
      drafts: o.drafts.filter((x) => x.id !== d.savedId),
      audit: audit(o, "agent.activated", a.id, `Added ${a.name} (${a.role}) to ${findProject(d.project)?.name ?? d.project}. Status: Not started. No credentials issued.`),
    };
  });
}

/** Approve changes to an existing agent. The ID never changes; a rename keeps every record attributed. */
export function updateAgent(d: AgentDraft) {
  const id = d.editing!;
  change((o) => {
    const before = o.agents.find((a) => a.id === id);
    if (!before || before.life === "offboarded") return o;   // a retired ID is never edited back onto a team
    const notes: string[] = [];
    if (before.name !== d.name.trim()) notes.push(`renamed ${before.name} → ${d.name.trim()}`);
    const prev = currentProfile(id, o);
    if (prev.model !== d.model) notes.push(`model ${prev.model} → ${d.model}`);
    if (prev.machines.join() !== d.machines.join()) notes.push(`machines → ${d.machines.join(", ") || "none"}`);
    if (JSON.stringify(prev.grants) !== JSON.stringify(d.grants)) notes.push("permissions changed");
    const home = o.projects.find((p) => p.team.some((m) => m.id === id));
    const projects = o.projects.map((p) => {
      if (home && p.key === home.key && home.key !== d.project) return { ...p, team: p.team.filter((m) => m.id !== id).map((m) => (m.reportsTo === id ? { ...m, reportsTo: p.team.find((x) => x.id === id)?.reportsTo ?? "jay" } : m)) };
      if (p.key === d.project) return placeInTeam(p, id, d.reportsTo, d.supervises);
      return p;
    });
    const versions = o.profiles[id] ?? [];
    return {
      ...o, projects,
      agents: o.agents.map((a) => (a.id === id ? { ...a, name: d.name.trim(), role: d.title.trim(), spec: d.spec.trim(), stage: d.stage, color: d.color, glyph: d.glyph, description: d.description.trim() } : a)),
      convs: o.convs.map((c) => (c.agent === id && c.kind === "dm" && !c.id.endsWith("-lead") ? { ...c, title: d.name.trim(), sub: d.title.trim() } : c)),
      profiles: { ...o.profiles, [id]: [...versions, profileFrom(d, (versions.at(-1)?.version ?? 0) + 1, notes.join("; ") || "Edited")] },
      drafts: o.drafts.filter((x) => x.id !== d.savedId),
      audit: audit(o, "agent.updated", id, `${d.name.trim()}: ${notes.join("; ") || "details edited"}. Config v${(versions.at(-1)?.version ?? 0) + 1}.`),
    };
  });
}

export function setLife(id: string, life: Exclude<Life, "offboarded">, note = "") {
  change((o) => ({
    ...o, agents: o.agents.map((a) => (a.id === id ? { ...a, life, lifeNote: note } : a)),
    audit: audit(o, life === "paused" ? "agent.paused" : "agent.resumed", id, `${o.agents.find((a) => a.id === id)?.name}: ${life === "paused" ? "paused" : "resumed"}${note ? ` (${note})` : ""}.`),
  }));
}

/** Move an agent from one project team to another, or change whom it reports to. */
export function reassign(id: string, from: string, to: string, reportsTo: string) {
  change((o) => {
    const fromP = o.projects.find((p) => p.key === from);
    const up = fromP?.team.find((m) => m.id === id)?.reportsTo ?? "jay";
    const projects = o.projects.map((p) => {
      if (p.key === from && from !== to) return { ...p, team: p.team.filter((m) => m.id !== id).map((m) => (m.reportsTo === id ? { ...m, reportsTo: up } : m)) };
      if (p.key === to) return { ...p, team: [...p.team.filter((m) => m.id !== id), { id, reportsTo }] };
      return p;
    });
    const name = o.agents.find((a) => a.id === id)?.name ?? id;
    const toName = o.projects.find((p) => p.key === to)?.name ?? to;
    const boss = reportsTo === "jay" ? "Jay" : o.agents.find((a) => a.id === reportsTo)?.name ?? reportsTo;
    return { ...o, projects, audit: audit(o, "agent.reassigned", id, from === to ? `${name} now reports to ${boss} in ${toName}.` : `${name} moved from ${fromP?.name ?? from} to ${toName}, reporting to ${boss}.`) };
  });
}

/**
 * Offboard. The agent can no longer be assigned work, but nothing is deleted: tasks, decisions, reviews,
 * messages, usage and audit stay attributed to its ID. Open tasks move to `handover`, keeping the former owner.
 */
export function offboard(id: string, handover: string, reason: string) {
  change((o) => {
    const name = o.agents.find((a) => a.id === id)?.name ?? id;
    const open = (t: Task) => t.owner === id && !["Closed"].includes(t.stage);
    const moved = o.tasks.filter(open).map((t) => t.key);
    const projects = o.projects.map((p) => {
      const me = p.team.find((m) => m.id === id);
      if (!me) return p;
      let team = p.team.filter((m) => m.id !== id);
      if (me.reportsTo === "jay" && handover) {   // it led this project: the handover agent leads it now
        team = [...team.filter((m) => m.id !== handover), { id: handover, reportsTo: "jay" }];
        team = team.map((m) => (m.reportsTo === id ? { ...m, reportsTo: handover } : m));
      } else team = team.map((m) => (m.reportsTo === id ? { ...m, reportsTo: me.reportsTo } : m));
      return { ...p, team };
    });
    return {
      ...o, projects,
      agents: o.agents.map((a) => (a.id === id ? { ...a, life: "offboarded" as Life, lifeNote: reason } : a)),
      tasks: o.tasks.map((t) => (open(t) && handover ? { ...t, owner: handover, formerOwners: [...(t.formerOwners ?? []), id] } : t)),
      convs: o.convs.map((c) => (c.agent === id ? { ...c, archived: true } : c)),
      audit: audit(o, "agent.offboarded", id, `${name} offboarded${reason ? ` (${reason})` : ""}. ${moved.length ? `${moved.join(", ")} handed to ${o.agents.find((a) => a.id === handover)?.name}. ` : ""}History kept under ID ${id}.`),
    };
  });
}

/** Approve Mock Project. MOCK ONLY: no repository is created, nothing is provisioned, nothing is sent to ccd. */
export function createProject(d: ProjectDraft) {
  change((o) => {
    const key = d.key;
    const prefix = d.prefix;
    const plannedIds = d.planned.map((a) => a.id);
    const lead = d.lead;
    const team: Member[] = [];
    if (lead) team.push({ id: lead, reportsTo: "jay" });
    for (const m of d.members) if (m !== lead) team.push({ id: m, reportsTo: lead || "jay" });
    for (const a of d.planned) if (a.id !== lead) team.push({ id: a.id, reportsTo: a.reportsTo && a.reportsTo !== "jay" ? a.reportsTo : lead || "jay" });
    const targetLabel = TARGET_MODES.find((m) => m.id === d.target)?.label ?? d.target;
    const p: Project = {
      key, name: d.name.trim(), prefix, color: d.color, icon: d.icon, blurb: d.description.trim() || "New project. Onboarding: CommandCenter is observing only.",
      mode: "onboarding", modeLabel: `Onboarding · observation only (target: ${targetLabel})`, merge: "Jay merges every PR", health: "onboarding",
      env: "Onboarding", version: "—", repo: d.repo.trim(), repoState: d.repoMode === "existing" ? "connected" : "proposed",
      envs: ENVIRONMENTS.filter((e) => d.envs[e]?.on), machines: [...d.workers],
      budget: { monthlyUsd: d.budget.monthlyWarnUsd, perTaskUsd: d.budget.costWarnUsd, alertPct: 80 }, created: Date.now(), team,
      releaseWindows: d.deploy.windows.length ? d.deploy.windows : undefined,
    };
    const owner = lead || "jay";
    const tasks: Task[] = [{ key: `${prefix}-001`, project: key, title: "Onboarding: project fingerprint and first audit", stage: "Planning", priority: "Medium", owner, updated: "now",
      why: "Every new project starts in onboarding. CommandCenter observes, fingerprints the repository and audits it before any operating mode applies.",
      plan: ["Fingerprint the repository (read-only)", "First audit: tests, CI, dependencies, secrets hygiene", "Draft an operating profile", "Bring the admission review to Jay"],
      criteria: ["No writes to the repository during onboarding", "Admission review ready for Jay"], questions: [], labels: ["onboarding"] }];
    if (d.repoMode === "proposed") tasks.push({ key: `${prefix}-002`, project: key, title: "Approve repository creation", stage: "Needs Jay", priority: "High", owner, updated: "now",
      why: `The repository ${d.repo} is only proposed. Nothing exists on GitHub until Jay authorises its creation.`, plan: [], criteria: ["Jay authorises or declines"],
      questions: [`Create ${d.repo} (${d.visibility})?`], labels: ["needs-jay"] });
    const planned = d.planned.map((a) => agentFrom({ ...a, project: key }));
    const convs: Conversation[] = [{ id: `team-${key}`, title: `# ${key}-team`, sub: "Team channel", project: key, kind: "team" }];
    if (lead) convs.unshift({ id: `${key}-lead`, title: o.agents.find((a) => a.id === lead)?.name ?? planned.find((a) => a.id === lead)?.name ?? lead, sub: `Project Lead · ${p.name}`, agent: lead, project: key, kind: "dm" });
    for (const a of planned) convs.push({ id: `dm-${a.id}`, title: a.name, sub: a.role, agent: a.id, project: key, kind: "dm" });
    const pp: ProjectProfile = {
      type: d.type, target: d.target, taskMode: d.taskMode, phase: "onboarding", stage: 1,
      repo: { mode: d.repoMode, provider: "github", name: d.repo.trim(), branch: d.branch.trim(), visibility: d.visibility, clone: d.clone.trim() },
      envs: clone(d.envs), discover: d.discover, workers: [...d.workers], deploy: clone(d.deploy), budget: { ...d.budget }, missing: missingFacts(d),
    };
    return {
      ...o, projects: [...o.projects, p], agents: [...o.agents, ...planned], tasks: [...o.tasks, ...tasks], convs: [...o.convs, ...convs],
      profiles: { ...o.profiles, ...Object.fromEntries(d.planned.map((a) => [a.id, [profileFrom({ ...a, project: key }, 1, `Planned with project ${p.name}`)]])) },
      projectProfiles: { ...o.projectProfiles, [key]: pp },
      drafts: o.drafts.filter((x) => x.id !== d.savedId),
      audit: audit(o, "project.created", key, `Created ${p.name} (${prefix}) in Onboarding / Observation. Target ${targetLabel} applies only after admission review and Jay's approval.${d.repoMode === "proposed" ? ` Repository ${d.repo} proposed, not created.` : ""}${plannedIds.length ? ` Planned agents: ${plannedIds.join(", ")}.` : ""}`),
    };
  });
}

export function missingFacts(d: ProjectDraft): string[] {
  const m: string[] = [];
  for (const e of ENVIRONMENTS) {
    const c = d.envs[e];
    if (!c?.on || e === "Local") continue;
    if (!c.hosting) m.push(`${e} hosting`);
    if (e === "Production" && !c.health) m.push("Production health check");
  }
  if (d.discover && m.length) return m.map((x) => `${x} (to discover during onboarding)`);
  return m;
}

// ---- drafts (saved explicitly with Save Draft; resumed from the Agents page) ----
export function saveDraft(d: AgentDraft | ProjectDraft): string {
  const id = d.savedId ?? `draft-${Date.now().toString(36)}-${(seq++).toString(36)}`;
  const label = d.kind === "agent" ? (d.name || templateOf(d.template).title || "Untitled agent") : (d.name || "Untitled project");
  change((o) => ({ ...o, drafts: [...o.drafts.filter((x) => x.id !== id), { id, kind: d.kind, label, at: Date.now(), data: { ...clone(d), savedId: id, touched: false } }] }));
  return id;
}
export function deleteDraft(id: string) { change((o) => ({ ...o, drafts: o.drafts.filter((x) => x.id !== id) })); }

export const TASK_MODE_LABEL = Object.fromEntries(TASK_MODES.map((m) => [m.id, m.label])) as Record<TaskMode, string>;
