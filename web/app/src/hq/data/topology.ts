// Operations Topology (roadmap P3.1): projects, pipeline stages and hosts from /api/state, tickets and workers.
//
// Data only, no layout: the page positions nodes. Edges carry evidence so the picture never implies a
// dependency that is not there. A host's status comes from its own feed (ccd's host vitals, a worker's
// heartbeat); a stale or missing feed is Unknown. Worker nodes are read only if the caller already has
// them; nothing here fetches.
import type { Ticket, WorkerNode, WorkersState } from "../../api/types";
import { isActive, stageOf } from "../../lib/control";
import { isBlocked } from "../../tickets/model";
import { officeProjects, projectHealth, type Health } from "./office";
import { agentsById, presenceOf, type Evidence, type HqSource, type Presence } from "./evidence";

/** Same groups as the prototype's graph.ts. */
export const STAGE_GROUPS = [
  { id: "plan", label: "Planning" },
  { id: "build", label: "Build & Test" },
  { id: "review", label: "Review" },
  { id: "qa", label: "UI Testing" },
  { id: "release", label: "Release & Verify" },
] as const;
export type StageGroup = (typeof STAGE_GROUPS)[number]["id"];

/** Where a ticket sits in the pipeline by its status (a gate or question does not move it; it flags it). */
export function groupOf(t: Ticket): StageGroup {
  switch (t.status) {
    case "IN_PROGRESS": case "BLOCKED": return "build";
    case "IN_REVIEW": return "review";
    case "READY_TO_MERGE": return "release";
    // stageOf's own UI-testing test, applied directly: stageOf returns "Needs Jay" first when a gate or question is open.
    case "VERIFYING": return t.labels.includes("ui") || t.flags.includes("needs_ui_review") || t.type === "DESIGN" ? "qa" : "release";
    default: return "plan";
  }
}

export interface TopoTask { key: string; project: string; title: string; blocked: boolean; needsJay: boolean }
export interface TopoStage { id: StageGroup; label: string; tasks: TopoTask[];
  /** The project → stage edges: one per project with tasks here. */
  flows: { project: string; count: number; blocked: boolean; needsJay: boolean }[] }
export interface TopoProject {
  key: string; name: string; health: Health; healthWhy: string; sessions: number;
  coordinator: { paneId: string; presence: Presence } | null;
  /** The root → project edge: blocked when any of its open work is blocked, idle when it has none. */
  edge: "active" | "blocked" | "idle";
}
export type HostStatus = "online" | "offline" | "pending" | "revoked" | "unknown";
export interface TopoHost {
  id: string; name: string; kind: "ccd" | WorkerNode["kind"]; status: HostStatus; why: string;
  /** Live sessions herdr reports on it (ccd's host only; workers run none yet). */
  sessions: number | null;
  cpuPct: number | null; memPct: number | null; diskPct: number | null; asOf: number | null;
}
export interface TopologyView {
  projects: TopoProject[];
  stages: TopoStage[];
  hosts: TopoHost[];
  workers: { available: boolean };
}

export interface TopoFilter { projects?: string[]; status?: "all" | "attention" | "blocked" }

/** A worker heartbeat older than this is not evidence it is online. */
export const WORKER_HEARTBEAT_S = 180;

export function workerHost(n: WorkerNode, ev: Evidence): TopoHost {
  const age = n.lastHeartbeat != null ? ev.now - n.lastHeartbeat : null;
  const status: HostStatus = n.status === "revoked" ? "revoked" : n.status === "pending" ? "pending"
    : n.status === "offline" ? "offline" : age != null && age <= WORKER_HEARTBEAT_S && ev.stream === "live" ? "online" : "unknown";
  return { id: n.id, name: n.id, kind: n.kind, status, why: status === "unknown" ? "No recent heartbeat" : n.status,
    sessions: null, cpuPct: null, memPct: null, diskPct: null, asOf: n.lastHeartbeat };
}

export function buildTopology(src: HqSource, ev: Evidence, f: TopoFilter = {}, workers?: WorkersState | null): TopologyView {
  const st = src.state;
  const byKey = new Map(src.tickets.map((t) => [t.key, t]));
  const agents = agentsById(st);
  const shown = officeProjects(src).filter((p) => !f.projects?.length || f.projects.includes(p.key));
  const keys = new Set(shown.map((p) => p.key));
  const tasks = src.tickets.filter((t) => isActive(t) && keys.has(t.project)).map((t) => ({ t, blocked: isBlocked(t, byKey),
    needsJay: stageOf(t) === "Needs Jay" }))
    .filter((x) => f.status === "blocked" ? x.blocked : f.status === "attention" ? x.blocked || x.needsJay : true);

  const stages: TopoStage[] = STAGE_GROUPS.map((g) => {
    const mine = tasks.filter((x) => groupOf(x.t) === g.id);
    const flows = [...new Set(mine.map((x) => x.t.project))].map((p) => {
      const pm = mine.filter((x) => x.t.project === p);
      return { project: p, count: pm.length, blocked: pm.some((x) => x.blocked), needsJay: pm.some((x) => x.needsJay) };
    });
    return { id: g.id, label: g.label, flows,
      tasks: mine.map((x) => ({ key: x.t.key, project: x.t.project, title: x.t.title, blocked: x.blocked, needsJay: x.needsJay })) };
  }).filter((s) => s.tasks.length);

  const projects = shown.map((p): TopoProject => {
    const h = projectHealth(st, p.key, ev);
    const c = st?.coordinators?.[p.key];
    const mine = tasks.filter((x) => x.t.project === p.key);
    return { key: p.key, name: p.name, health: h.health, healthWhy: h.why,
      sessions: (st?.agents ?? []).filter((a) => a.project === p.key).length,
      coordinator: c?.paneId && agents.has(c.paneId) ? { paneId: c.paneId, presence: presenceOf(agents.get(c.paneId), ev) } : null,
      edge: mine.some((x) => x.blocked) ? "blocked" : mine.length ? "active" : "idle" };
  });

  const ho = st?.host;
  const hostStatus: HostStatus = ev.host === "live" ? "online" : "unknown";
  const hosts: TopoHost[] = st ? [{
    id: "server", name: "Server", kind: "ccd", status: hostStatus,
    why: ev.host === "live" ? "Vitals live" : ev.host === "stale" ? "Vitals are stale" : st.sources.host.error ?? "No vitals",
    sessions: ev.sessions === "live" ? st.agents.filter((a) => a.live).length : null,
    cpuPct: ho?.cpuPct ?? null,
    memPct: ho?.memTotal && ho.memUsed != null ? Math.round((ho.memUsed / ho.memTotal) * 100) : null,
    diskPct: ho?.disk ?? null, asOf: ho?.asOf ?? null,
  }] : [];
  if (workers?.available) hosts.push(...workers.nodes.map((n) => workerHost(n, ev)));
  return { projects, stages, hosts, workers: { available: !!workers?.available } };
}
