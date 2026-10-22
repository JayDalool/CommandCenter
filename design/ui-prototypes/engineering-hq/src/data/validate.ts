// Readable validation for the onboarding wizards. Pure functions: (draft, organisation) → issues.
// Errors block approval; warnings are shown on the review step and need no action.
import type { Agent, Project } from "./seed";
import { GRANT_LABEL, GRANT_RANK, PERMISSIONS, PROVIDERS, RESERVED_IDS, TASK_MODES, TOOLS, WORKERS, effective, perm, projectRules, worker, type Grant, type TargetMode, type TaskMode } from "./catalog";
import { projectProfile, type AgentDraft, type Org, type ProjectDraft } from "./org";

export interface Issue { step: string; field?: string; msg: string; fix?: { label: string; apply: <T extends AgentDraft | ProjectDraft>(d: T) => T } }
export interface Result { errors: Issue[]; warnings: Issue[] }

const NAME_RE = /^[\p{L}][\p{L}\p{N} .'-]{0,31}$/u;
const ID_RE = /^[a-z][a-z0-9-]{1,31}$/;
const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");
/** Edit distance, for "these two names are easy to confuse". */
function dist(a: string, b: string) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return d[a.length][b.length];
}

/** Context for validating an agent that belongs to a project which is itself still a draft (plan a new agent). */
export interface DraftProjectCtx { key: string; name: string; repo: string; workers: string[]; type: ProjectDraft["type"]; deploy: ProjectDraft["deploy"]; taskMode: TaskMode; members: string[]; planned: AgentDraft[] }

export function validateAgent(d: AgentDraft, o: Org, draftProject?: DraftProjectCtx): Result {
  const errors: Issue[] = [], warnings: Issue[] = [];
  const E = (step: string, msg: string, field?: string, fix?: Issue["fix"]) => errors.push({ step, msg, field, fix });
  const W = (step: string, msg: string, field?: string) => warnings.push({ step, msg, field });
  const others = o.agents.filter((a) => a.id !== d.editing);
  const plannedOthers = (draftProject?.planned ?? []).filter((a) => a.id !== d.id || a !== d);

  // template
  if (!d.template) E("template", "Choose a template, or start from a custom agent.", "template");

  // identity
  const name = d.name.trim();
  if (!name) E("identity", "Give the agent a display name.", "name");
  else if (!NAME_RE.test(name)) E("identity", "The name must start with a letter and use letters, numbers, spaces, dots, apostrophes or hyphens (up to 32 characters).", "name");
  else if (["jay", "commandcenter", "system", "admin"].includes(norm(name))) E("identity", `"${name}" is reserved. Choose another name.`, "name");
  else {
    const same = [...others.filter((a) => a.life !== "offboarded"), ...plannedOthers.map((a) => ({ name: a.name, id: a.id }) as Agent)].find((a) => norm(a.name) === norm(name));
    if (same) E("identity", `${same.name} already exists. Two agents can't share a display name, so Jay can always tell who said what.`, "name");
    else {
      const close = others.filter((a) => a.life !== "offboarded").find((a) => dist(norm(a.name), norm(name)) <= 1 || norm(a.name).replace(/[^a-z]/g, "") === norm(name).replace(/[^a-z]/g, ""));
      if (close) W("identity", `"${name}" is easy to confuse with ${close.name}. Consider a more distinct name.`, "name");
      const gone = others.find((a) => a.life === "offboarded" && norm(a.name) === norm(name));
      if (gone) W("identity", `An offboarded agent was also called ${gone.name}. Its history stays under its own ID (${gone.id}), but the shared name may confuse old records.`, "name");
    }
  }
  if (!d.editing) {
    if (!d.id) E("identity", "The agent needs an ID.", "id");
    else if (!ID_RE.test(d.id)) E("identity", "The ID must start with a letter and use only lowercase letters, numbers and hyphens (2–32 characters).", "id");
    else if (RESERVED_IDS.includes(d.id)) E("identity", `The ID "${d.id}" is reserved for the system.`, "id");
    else if (o.agents.some((a) => a.id === d.id)) {
      const a = o.agents.find((x) => x.id === d.id)!;
      E("identity", a.life === "offboarded" ? `The ID "${d.id}" belonged to ${a.name}, who was offboarded. IDs are never reused, so old records stay attributed.` : `The ID "${d.id}" is already used by ${a.name}.`, "id");
    } else if (plannedOthers.some((a) => a.id === d.id)) E("identity", `The ID "${d.id}" is already planned for another new agent in this project.`, "id");
  }
  if (!d.title.trim()) E("identity", "Give the agent a role title, such as Implementation Agent.", "title");
  if (!d.spec.trim()) W("identity", "Add a specialisation so the team knows what to hand this agent.", "spec");

  // intelligence
  const prov = PROVIDERS.find((p) => p.id === d.provider);
  if (!prov) E("intelligence", "Choose a provider.", "provider");
  if (!d.model) E("intelligence", "Choose the model that backs this persona.", "model");
  else if (prov && !prov.models.includes(d.model)) E("intelligence", `${d.model} is not a ${prov.label} model. Choose one of ${prov.models.join(", ")}.`, "model");
  if (d.fallback && d.fallback === d.model) E("intelligence", "The fallback model must differ from the primary model.", "fallback");
  if (d.fallback && prov && !prov.models.includes(d.fallback)) W("intelligence", "The fallback uses a different provider. Cross-provider fallback needs Jay's policy approval.", "fallback");

  // organisation
  const proj: { key: string; name: string; repo: string; workers: string[]; type: string; team: { id: string; reportsTo: string }[]; rules: Record<string, Grant>; taskMode: TaskMode } | null = draftProject
    ? { key: draftProject.key, name: draftProject.name || "the new project", repo: draftProject.repo, workers: draftProject.workers, type: draftProject.type,
      team: draftProject.members.map((id) => ({ id, reportsTo: "?" })), rules: projectRules(draftProject.deploy), taskMode: draftProject.taskMode }
    : (() => { const p = o.projects.find((x) => x.key === d.project); if (!p) return null; const pp = projectProfile(p.key, o);
      return { key: p.key, name: p.name, repo: p.repo, workers: p.machines, type: pp.type, team: p.team, rules: projectRules(pp.deploy), taskMode: pp.taskMode }; })();
  if (!d.project) E("organization", "Choose the project this agent works on. Agents are not global.", "project");
  else if (!proj) E("organization", `The project "${d.project}" doesn't exist. Choose an existing project.`, "project");
  else if (!draftProject) {
    const p = o.projects.find((x) => x.key === d.project) as Project;
    if (p.health === "paused") W("organization", `${p.name} is paused. The agent will show as Paused until Jay resumes the project.`, "project");
    const lead = p.team.find((m) => m.reportsTo === "jay" && m.id !== d.editing);
    if (d.reportsTo === "jay" && lead) E("organization", `${p.name} already has a lead (${o.agents.find((a) => a.id === lead.id)?.name}). Report to the lead, or reassign the lead first.`, "reportsTo");
    if (d.reportsTo !== "jay" && !p.team.some((m) => m.id === d.reportsTo && m.id !== d.editing)) E("organization", "Choose a manager who is on this project's team.", "reportsTo");
    const off = o.agents.find((a) => a.id === d.reportsTo && a.life === "offboarded");
    if (off) E("organization", `${off.name} has been offboarded and can't supervise anyone.`, "reportsTo");
    if (d.supervises.includes(d.reportsTo)) E("organization", "An agent can't supervise its own manager.", "supervises");
    if (d.editing && d.supervises.length) {
      // no cycles: walk up from the manager
      let cur = d.reportsTo, hops = 0;
      while (cur && cur !== "jay" && hops++ < 20) { if (cur === d.editing) { E("organization", "That reporting line would make a loop.", "reportsTo"); break; } cur = p.team.find((m) => m.id === cur)?.reportsTo ?? "jay"; }
    }
  }
  if (!d.stage) W("organization", "Pick a pipeline stage so the team knows where this agent fits.", "stage");

  // capabilities
  if (!d.skills.length) W("capabilities", "No skills selected. The agent will only follow its instructions.", "skills");
  for (const t of TOOLS) {
    const g = d.grants[t.perm] ?? "deny";
    if (t.cap && g !== "deny" && !d.machines.some((m) => worker(m)?.caps.includes(t.cap!)))
      W("capabilities", `${t.label} is authorised, but none of its machines has ${t.cap === "dev_server" ? "a dev server" : t.cap}. It won't be able to use it.`, t.id);
  }

  // access
  if (!d.machines.length) E("access", "Choose at least one machine the agent may run on.", "machines");
  const eligible = d.machines.filter((m) => !proj || proj.workers.includes(m));
  if (proj && d.machines.length && !eligible.length) E("access", `None of the chosen machines is eligible for ${proj.name}. Eligible: ${proj.workers.map((w) => worker(w)?.label).join(", ") || "none"}.`, "machines");
  else if (proj) for (const m of d.machines) if (!proj.workers.includes(m)) E("access", `${worker(m)?.label} is not an eligible machine for ${proj.name}.`, "machines");
  for (const m of d.machines) { const w = worker(m); if (w && !w.agentNode) W("access", `${w.label} is not an agent execution node today. Using it needs Jay's approval and a policy change.`, "machines"); }
  if (proj?.type === "employer" && d.machines.includes("server")) E("access", "Employer projects may not run on jay-server.", "machines");
  if (proj) for (const r of d.repos) if (r !== proj.repo) E("access", `${r} is not ${proj.name}'s repository. An agent only gets repositories of the projects it works on.`, "repos");
  if (proj && !d.repos.length && GRANT_RANK[d.grants["repo.read"] ?? "deny"] > 0) W("access", "No repository selected, so its repository permissions have nothing to apply to.", "repos");

  // permissions
  for (const p of PERMISSIONS) {
    const g = d.grants[p.id] ?? "deny";
    if (GRANT_RANK[g] > GRANT_RANK[p.ceiling]) E("permissions", `${p.label}: ${p.boundary ?? "above CommandCenter's limit"}`, p.id);
    if (proj && GRANT_RANK[g] > GRANT_RANK[proj.rules[p.id] ?? "allow"])
      E("permissions", `${p.label} is set to ${GRANT_LABEL[g]}, but ${proj.name}'s deployment rules only allow ${GRANT_LABEL[proj.rules[p.id]].toLowerCase()}.`, p.id,
        { label: "Match the project's limits", apply: (x) => ({ ...x, grants: { ...(x as AgentDraft).grants, [p.id]: proj.rules[p.id] } }) });
  }
  if ((d.grants["repo.push"] ?? "deny") !== "deny" && (d.grants["repo.commit"] ?? "deny") === "deny") W("permissions", "Push is allowed but Commit is denied, so there is nothing to push.", "repo.push");

  // instructions
  if (!d.instructions.mission.trim()) E("instructions", "Write a one-sentence mission.", "mission");
  if (!d.instructions.responsibilities.trim()) W("instructions", "List its responsibilities so the lead can delegate well.", "responsibilities");

  // budget
  const b = d.budget;
  for (const [k, v] of [["daily", b.dailyWarnUsd], ["weekly", b.weeklyWarnUsd], ["per-task", b.perTaskWarnUsd], ["approval threshold", b.expensiveApprovalUsd]] as const)
    if (!(Number.isFinite(v) && v >= 0)) E("budget", `The ${k} amount must be zero or more.`, k);
  if (b.dailyWarnUsd > b.weeklyWarnUsd) E("budget", "The daily warning can't be higher than the weekly warning.", "daily");
  if (b.perTaskWarnUsd > b.dailyWarnUsd && b.dailyWarnUsd > 0) W("budget", "A single task could pass the daily warning on its own.", "perTask");
  if (!(Number.isInteger(b.maxParallel) && b.maxParallel >= 1 && b.maxParallel <= 8)) E("budget", "Parallel work must be between 1 and 8.", "maxParallel");

  return { errors, warnings };
}

// ---------------------------------------------------------------- projects
export const MAX_TASK_MODE: Record<TargetMode, TaskMode> = {
  restricted: "manual", paused: "manual", controlled_production: "assisted", autonomous_product: "autonomous", experimental_autonomy: "autonomous",
};
const MODE_RANK: Record<TaskMode, number> = { manual: 0, assisted: 1, autonomous: 2 };
const KEY_RE = /^[a-z][a-z0-9-]{1,23}$/;
const PREFIX_RE = /^[A-Z][A-Z0-9]{1,4}$/;
const REPO_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/;
const BRANCH_RE = /^(?!\/|.*\/$|.*\.\.|.*\/\/)[A-Za-z0-9._\/-]{1,100}$/;

export function validateProject(d: ProjectDraft, o: Org, agentIssues?: (a: AgentDraft) => Result): Result {
  const errors: Issue[] = [], warnings: Issue[] = [];
  const E = (step: string, msg: string, field?: string, fix?: Issue["fix"]) => errors.push({ step, msg, field, fix });
  const W = (step: string, msg: string, field?: string) => warnings.push({ step, msg, field });

  // identity
  const name = d.name.trim();
  if (!name) E("identity", "Give the project a name.", "name");
  else if (name.length > 40) E("identity", "Keep the name under 40 characters.", "name");
  else if (o.projects.some((p) => norm(p.name) === norm(name))) E("identity", `A project called ${name} already exists.`, "name");
  if (!d.key) E("identity", "The project needs a key.", "key");
  else if (!KEY_RE.test(d.key)) E("identity", "The key must start with a letter and use lowercase letters, numbers and hyphens (2–24 characters).", "key");
  else if (o.projects.some((p) => p.key === d.key)) E("identity", `The key "${d.key}" is already used by ${o.projects.find((p) => p.key === d.key)!.name}.`, "key");
  else if (RESERVED_IDS.includes(d.key)) E("identity", `The key "${d.key}" is reserved.`, "key");
  if (!d.prefix) E("identity", "Choose a ticket prefix, such as SV.", "prefix");
  else if (!PREFIX_RE.test(d.prefix)) E("identity", "The ticket prefix must be 2–5 capital letters or digits, starting with a letter.", "prefix");
  else if (o.projects.some((p) => p.prefix === d.prefix)) E("identity", `The prefix ${d.prefix} is already used by ${o.projects.find((p) => p.prefix === d.prefix)!.name}. Ticket keys would collide.`, "prefix");

  // repository
  const repo = d.repo.trim();
  if (!repo) E("repository", d.repoMode === "existing" ? "Choose or enter the repository to connect." : "Name the proposed repository.", "repo");
  else if (/^https?:|@|:\/\//.test(repo) || /[?#]/.test(repo)) E("repository", "Enter the repository as owner/name (for example JayDalool/SamVisionAI), not a URL. Never paste a URL that contains a token.", "repo");
  else if (!REPO_RE.test(repo)) E("repository", "That doesn't look like a repository. Use owner/name, with letters, numbers, dots, hyphens or underscores.", "repo");
  else {
    const taken = o.projects.find((p) => p.repo.toLowerCase() === repo.toLowerCase());
    if (taken) E("repository", `${repo} is already bound to ${taken.name}. One repository belongs to one project.`, "repo");
  }
  if (!d.branch.trim()) E("repository", "Name the default branch.", "branch");
  else if (!BRANCH_RE.test(d.branch.trim())) E("repository", "The default branch name isn't valid.", "branch");
  if (d.visibility === "public" && (d.type === "client" || d.type === "employer")) E("repository", `${d.type === "client" ? "Client" : "Employer"} projects must use a private repository.`, "visibility");
  if (d.repoMode === "proposed") W("repository", `${repo || "The repository"} is only proposed. Nothing is created on GitHub; creating it needs Jay's separate authorisation.`, "repo");
  if (d.clone && /\.\.|[;&|`$]/.test(d.clone)) E("repository", "The local clone location can't contain '..' or shell characters.", "clone");

  // environments
  const prod = d.envs.Production?.on;
  if (!Object.values(d.envs).some((e) => e.on)) E("environments", "Turn on at least one environment.", "envs");
  if (prod && (d.deploy.deploy === "allow" || d.deploy.prodWrite === "allow" || d.deploy.reviewers < 1))
    E("environments", "Production needs protection: deploys and production writes must need approval or be denied, with at least one required reviewer.", "Production",
      { label: "Use the Standard protection preset", apply: (x) => ({ ...x, deploy: { ...(x as ProjectDraft).deploy, preset: "standard", deploy: "approval", prodWrite: "deny", reviewers: Math.max(1, (x as ProjectDraft).deploy.reviewers) } }) });
  for (const [e, c] of Object.entries(d.envs)) if (c.on && c.domain && !/^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,}$/i.test(c.domain)) E("environments", `${e}: "${c.domain}" isn't a valid domain name.`, e);
  if (prod && !d.envs.Production.health && !d.discover) W("environments", "Production has no health check. Add one or let CommandCenter discover it during onboarding.", "Production");

  // workers
  if (!d.workers.length) E("workers", "Choose at least one machine that may run this project's work.", "workers");
  if (d.type === "employer" && d.workers.includes("server")) E("workers", "Employer and restricted projects may not use jay-server.", "workers");
  for (const w of d.workers) { const x = WORKERS.find((y) => y.id === w); if (x && !x.agentNode) W("workers", `${x.label} is not an agent execution node today. Agents can't run there until Jay changes the policy.`, "workers"); }
  if (d.workers.length && !d.workers.some((w) => worker(w)?.agentNode)) W("workers", "No eligible agent execution node is selected, so agents could only observe.", "workers");

  // team
  const teamIds = [...new Set([d.lead, ...d.members, ...d.planned.map((a) => a.id)].filter(Boolean))];
  if (!d.lead) W("team", "No lead yet. The project can be created, but nobody will coordinate it or bring Jay its decisions.", "lead");
  for (const id of teamIds) {
    const a = o.agents.find((x) => x.id === id);
    if (a?.life === "offboarded") E("team", `${a.name} has been offboarded and can't join a team.`, id);
    if (a?.life === "paused") W("team", `${a.name} is paused and won't work on this project until resumed.`, id);
  }
  if (d.lead && !teamIds.includes(d.lead)) E("team", "The lead must be on the team.", "lead");
  if (agentIssues) for (const a of d.planned) { const r = agentIssues(a); if (r.errors.length) E("team", `Planned agent ${a.name || a.id}: ${r.errors[0].msg}`, a.id); }
  for (const a of d.planned) if (o.agents.some((x) => x.id === a.id)) E("team", `The planned agent ID "${a.id}" is now taken. Edit the planned agent.`, a.id);

  // operating profile
  if (d.type === "employer" && !["restricted", "controlled_production", "paused"].includes(d.target))
    E("profile", "Employer projects can only target Restricted, Controlled production or Paused.", "target");
  if (MODE_RANK[d.taskMode] > MODE_RANK[MAX_TASK_MODE[d.target]])
    E("profile", `${TASK_MODES.find((m) => m.id === d.taskMode)!.label} is more permissive than the ${d.target.replace(/_/g, " ")} target allows. Tasks can be more restrictive than the project, never more permissive.`, "taskMode",
      { label: `Use ${TASK_MODES.find((m) => m.id === MAX_TASK_MODE[d.target])!.label}`, apply: (x) => ({ ...x, taskMode: MAX_TASK_MODE[(x as ProjectDraft).target] }) });
  if (d.target === "experimental_autonomy" && prod) W("profile", "Experimental autonomy with a production environment: low-risk work only, and it is evaluated in shadow first.", "target");
  if (d.target === "autonomous_product" && d.deploy.preset === "strict") W("profile", "Autonomous product with Strict deployment rules: agents can build but never release. That may be what you want.", "target");

  // budget
  const b = d.budget;
  for (const [k, v] of [["monthly", b.monthlyWarnUsd], ["model cost", b.costWarnUsd], ["infrastructure", b.infraWarnUsd]] as const)
    if (!(Number.isFinite(v) && v >= 0)) E("budget", `The ${k} warning must be zero or more.`, k);
  if (!(Number.isInteger(b.maxParallelAgents) && b.maxParallelAgents >= 1 && b.maxParallelAgents <= 12)) E("budget", "Parallel agents must be between 1 and 12.", "maxParallelAgents");
  if (b.costWarnUsd > b.monthlyWarnUsd && b.monthlyWarnUsd > 0) W("budget", "The per-task warning is higher than the monthly warning.", "costWarnUsd");

  // deployment rules
  if (d.deploy.merge === "allow") E("deploy", "Merging can't be fully automatic for a new project. Jay merges every PR until an operating profile says otherwise.", "merge");
  if (d.deploy.database === "allow") E("deploy", "Production database access is never available to agents.", "database");
  if (d.deploy.browserProd === "allow") E("deploy", "Changing production through a browser is never available to agents.", "browserProd");
  if (!(Number.isInteger(d.deploy.reviewers) && d.deploy.reviewers >= 0 && d.deploy.reviewers <= 3)) E("deploy", "Required reviewers must be between 0 and 3.", "reviewers");
  if (prod && !d.deploy.windows.length && d.deploy.deploy !== "deny") W("deploy", "No release windows. Deploys could be requested at any time (each still needs Jay).", "windows");

  return { errors, warnings };
}

/** For the review step: what an agent may do in its project, in words. */
export function capabilitySentences(d: AgentDraft, rules: Record<string, Grant>, workers: string[], mode: TaskMode, projectName: string) {
  const can: string[] = [], ask: string[] = [], cannot: string[] = [];
  for (const p of PERMISSIONS) {
    const r = effective(p.id, d.grants, rules, d.machines.filter((m) => workers.includes(m)), mode).result;
    (r === "allow" ? can : r === "approval" ? ask : cannot).push(p.label);
  }
  const s = (l: string[]) => l.map((x) => x.charAt(0).toLowerCase() + x.slice(1));
  const out: { tone: "ok" | "warn" | "bad"; text: string }[] = [];
  if (d.grants["repo.commit"] !== "deny" && can.includes(perm("repo.commit").label)) out.push({ tone: "ok", text: `Can modify ${projectName} development branches` });
  else out.push({ tone: "bad", text: `Cannot change ${projectName} code` });
  out.push({ tone: "bad", text: "Cannot merge" });
  out.push(ask.includes(perm("prod.deploy").label) ? { tone: "warn", text: "May prepare deploys; each needs Jay's approval" } : { tone: "bad", text: "Cannot deploy" });
  for (const m of d.machines) { const w = worker(m); if (w) out.push(w.agentNode ? { tone: "ok", text: `May use ${w.label}` } : { tone: "warn", text: `May use ${w.label} only after Jay approves it` }); }
  out.push({ tone: "bad", text: "Production changes denied (observe only)" });
  out.push({ tone: "bad", text: "No secrets, no credentials, no infrastructure" });
  return { out, can: s(can), ask: s(ask), cannot: s(cannot) };
}
