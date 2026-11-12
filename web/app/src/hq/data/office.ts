// My Office (roadmap P3.2): projects, what needs Jay, alerts and sessions, from Classic's store.
//
// Per-project counts follow the Classic Dashboard's rules exactly (screens/Dashboard.tsx projectPanels),
// so the two never disagree. Health is shown only from evidence: a stale feed reads Unknown.
// Lead updates have no source until P5.1, so the view says so instead of showing anything.
import type { Alert, CiMark, State, Ticket } from "../../api/types";
import { byProjectOrder, isActive, stageOf } from "../../lib/control";
import { buildDecisions, type DecisionItem } from "./decisions";
import { buildTeams, type TeamMember } from "./teams";
import { projectGithub, type Evidence, type HqSource } from "./evidence";

export type Health = "healthy" | "degraded" | "unknown";

export interface OfficeProject {
  key: string;
  name: string;
  prefix: string;
  health: Health;
  healthWhy: string;
  mainCi: CiMark | null;
  activeTasks: number;
  /** Same four numbers as the Classic Dashboard panel. */
  counts: { needs: number; progress: number; review: number; merge: number };
  blocked: number;
  sessions: number;
  lead: string | null;
}

export interface OfficeView {
  kpis: {
    projects: number;
    sessions: { total: number; working: number; waiting: number };
    needsYou: { total: number; urgent: number };
    health: { state: Health; why: string };
  };
  projects: OfficeProject[];
  /** The top of Needs My Attention; the full list is the Decisions view. */
  attention: DecisionItem[];
  alerts: Alert[];
  agents: TeamMember[];
  leadUpdates: { available: false; reason: string };
}

/** The Dashboard's project list: the task registry (else projectsConfig), only what the server tracks. */
export function officeProjects(src: HqSource): { key: string; name: string; prefix: string }[] {
  const st = src.state;
  const reg = src.taskProjects?.length ? src.taskProjects
    : (st?.projectsConfig ?? []).map((p) => ({ key: p.key, name: p.name, prefix: p.prefix ?? "" }));
  const live = new Set((st?.projects ?? []).map((p) => p.key));
  return byProjectOrder(reg.filter((p) => !live.size || live.has(p.key) || src.tickets.some((t) => t.project === p.key && isActive(t)))
    .map((p) => ({ key: p.key, name: st?.projects.find((x) => x.key === p.key)?.name ?? p.name, prefix: p.prefix })));
}

export function projectHealth(st: State | null, key: string, ev: Evidence): { health: Health; why: string } {
  const pv = st?.projects.find((p) => p.key === key);
  if (!pv) return { health: "unknown", why: "No repository data" };
  const gh = projectGithub(st, key, ev);
  if (gh !== "live") return { health: "unknown", why: gh === "down" ? "GitHub not reporting" : "GitHub data is stale" };
  if (pv.main_ci === "✗") return { health: "degraded", why: "Main branch checks failing" };
  if (pv.errors.length) return { health: "degraded", why: pv.errors[0] };
  return { health: "healthy", why: pv.main_ci === "✓" ? "Main branch green" : "No failures reported" };
}

function counts(key: string, tickets: Ticket[], needs: DecisionItem[]) {
  const stages = tickets.filter((t) => t.project === key && isActive(t)).map(stageOf);
  const n = (...s: string[]) => stages.filter((x) => s.includes(x)).length;
  const mine = needs.filter((j) => j.project === key).length;
  return { needs: mine, progress: n("Planning", "Implementing", "UI Testing", "Verifying", "Deploying"), review: n("Reviewing"),
    merge: n("Ready to Merge"), blocked: n("Blocked"), active: stages.length };
}

export function buildOffice(src: HqSource, ev: Evidence): OfficeView {
  const st = src.state;
  const decisions = buildDecisions(src);
  const teams = buildTeams(src, ev);
  const projects = officeProjects(src).map((p): OfficeProject => {
    const h = projectHealth(st, p.key, ev);
    const c = counts(p.key, src.tickets, decisions.items);
    const team = teams.teams.find((t) => t.key === p.key);
    return { key: p.key, name: p.name, prefix: p.prefix, health: h.health, healthWhy: h.why,
      mainCi: st?.projects.find((x) => x.key === p.key)?.main_ci ?? null, activeTasks: c.active,
      counts: { needs: c.needs, progress: c.progress, review: c.review, merge: c.merge }, blocked: c.blocked,
      sessions: team ? team.members.length + (team.lead ? 1 : 0) : 0, lead: team?.lead?.name ?? null };
  });
  const tracked = projects.filter((p) => st?.projects.some((x) => x.key === p.key));
  const health: OfficeView["kpis"]["health"] = ev.sessions !== "live" || ev.stream !== "live"
    ? { state: "unknown", why: ev.stream !== "live" ? "Event stream not live" : "Session feed not live" }
    : tracked.some((p) => p.health === "degraded")
      ? { state: "degraded", why: `${tracked.filter((p) => p.health === "degraded").length} project(s) degraded` }
      : tracked.some((p) => p.health === "unknown") || !tracked.length
        ? { state: "unknown", why: "Some project data is stale" }
        : { state: "healthy", why: "All feeds live, no failures" };
  const agents = [...teams.teams.flatMap((t) => (t.lead ? [t.lead, ...t.members] : t.members)), ...teams.unassigned];
  return {
    kpis: {
      projects: projects.length,
      sessions: { total: teams.sessions.total, working: teams.sessions.working, waiting: teams.sessions.waiting },
      needsYou: { total: decisions.summary.total, urgent: decisions.summary.urgent },
      health,
    },
    projects,
    attention: decisions.items.slice(0, 4),
    alerts: (st?.alerts ?? []).filter((a) => a.active && !a.ack).sort((a, b) => b.since - a.since),
    agents,
    leadUpdates: { available: false, reason: "Lead updates arrive with Project Lead conversations (P5.1)" },
  };
}
