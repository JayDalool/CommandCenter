// Teams and the agent directory (roadmap P3.5): who works on each project, from real sessions only.
//
// A lead is shown only when the project's coordinator resolves to a session herdr reports. No persona,
// name or lead is invented: a project with no coordinator session has lead = null and says why.
// Subagents a coordinator can call (ProjectView.team without a pane) are listed as defined, with no status.
import type { Agent, AgentRole, State, Ticket } from "../../api/types";
import { isActive } from "../../lib/control";
import { ticketForAgent } from "../../tickets/model";
import { presenceOf, type Evidence, type HqSource, type Presence } from "./evidence";

export interface TeamMember {
  id: string;
  name: string;
  role: AgentRole;
  agent: string;
  presence: Presence;
  /** epoch s since the session has been waiting on Jay, when herdr says so. */
  waitingSince: number | null;
  ticket: string | null;
  cwd: string;
  /** The project key this session is the lead of. Absent on every other session. */
  leadOf?: string;
}

export interface Team {
  key: string;
  name: string;
  lead: TeamMember | null;
  /** Why there is no lead, in Jay's words. Null when there is one. */
  leadWhy: string | null;
  members: TeamMember[];
  /** Subagents the coordinator can call. They have no session of their own, so no status. */
  defined: { name: string; model: string }[];
  openTasks: number;
}

export interface TeamsView {
  teams: Team[];
  /** Sessions herdr reports with no project. */
  unassigned: TeamMember[];
  /** total counts every pane herdr lists; offline and unknown say how many of those are not confirmed running. */
  sessions: { total: number; working: number; waiting: number; offline: number; unknown: number };
}

export function member(a: Agent, tickets: Ticket[], ev: Evidence): TeamMember {
  return { id: a.id, name: a.agent_name || a.label || a.id, role: a.role, agent: a.agent, presence: presenceOf(a, ev),
    waitingSince: a.blockedSinceMs != null && ev.sessions === "live" ? a.blockedSinceMs / 1000 : null,
    ticket: ticketForAgent(tickets, a)?.key ?? null, cwd: a.cwd };
}

function leadOf(st: State, key: string, agents: Agent[]): { agent: Agent | null; why: string | null } {
  const c = st.coordinators?.[key];
  if (!c) return { agent: null, why: "No coordinator registered" };
  if (!c.paneId) return { agent: null, why: c.state === "multiple" ? "Several sessions could be the coordinator" : "No coordinator session" };
  const a = agents.find((x) => x.id === c.paneId);
  if (!a) return { agent: null, why: "Coordinator session not found" };
  return { agent: a, why: null };
}

export function buildTeams(src: HqSource, ev: Evidence): TeamsView {
  const st = src.state;
  if (!st) return { teams: [], unassigned: [], sessions: { total: 0, working: 0, waiting: 0, offline: 0, unknown: 0 } };
  const agents = st.agents;
  const teams = st.projects.map((p): Team => {
    const { agent: lead, why } = leadOf(st, p.key, agents);
    const members = agents.filter((a) => a.project === p.key && a.id !== lead?.id).map((a) => member(a, src.tickets, ev));
    const defined = p.team.filter((m) => !m.pane_id && !agents.some((a) => a.agent_name === m.name))
      .map((m) => ({ name: m.name, model: m.model }));
    return { key: p.key, name: p.name, lead: lead ? { ...member(lead, src.tickets, ev), leadOf: p.key } : null, leadWhy: why, members, defined,
      openTasks: src.tickets.filter((t) => t.project === p.key && isActive(t)).length };
  });
  const known = new Set(st.projects.map((p) => p.key));
  const unassigned = agents.filter((a) => !a.project || !known.has(a.project)).map((a) => member(a, src.tickets, ev));
  const all = agents.map((a) => presenceOf(a, ev));
  return { teams, unassigned, sessions: { total: all.length, working: all.filter((p) => p === "working").length,
    waiting: all.filter((p) => p === "waiting").length, offline: all.filter((p) => p === "offline").length, unknown: all.filter((p) => p === "unknown").length } };
}
