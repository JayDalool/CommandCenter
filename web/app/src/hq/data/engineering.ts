// Engineering workbench (roadmap P3.3): tickets by visible stage, with the release gate.
//
// Stages come from lib/control.ts stageOf (ccd's visibleStage when sent), so HQ and Classic never
// disagree on where a task is. A task's session status is shown only from herdr's live report.
import type { Agent, Priority, Ticket, TicketStatus, VisibleStage } from "../../api/types";
import { VISIBLE_STAGES } from "../../api/types";
import { isActive, stageOf } from "../../lib/control";
import { PRIORITY_META, assigneeKind, assigneeLabel, isBlocked, ticketForAgent } from "../../tickets/model";
import { agentsById, presenceOf, type Evidence, type HqSource, type Presence } from "./evidence";

export interface EngTask {
  key: string;
  project: string;
  title: string;
  stage: VisibleStage;
  status: TicketStatus;
  priority: Priority;
  assignee: string;
  assigneeKind: ReturnType<typeof assigneeKind>;
  pr: { number: number; url: string | null } | null;
  gate: Ticket["gate"] | null;
  gateReason: string | null;
  openQuestions: number;
  blocked: boolean;
  needsJay: boolean;
  flags: string[];
  labels: string[];
  updatedAt: number;
  /** The task's own session, when the ticket names one. Null means none is recorded, not "idle". */
  session: { paneId: string; presence: Presence } | null;
}

export interface EngColumn { stage: VisibleStage; tasks: EngTask[] }

export interface EngineeringView {
  columns: EngColumn[];
  total: number;
  counts: Record<VisibleStage, number>;
  /** Ready to Merge: what waits on Jay's merge. Merge stays owner-only; this list never merges. */
  releaseGate: EngTask[];
  projects: string[];
}

export interface EngFilter { project?: string | null }

export function engTask(t: Ticket, byKey: Map<string, Ticket>, agents: Map<string, Agent>, ev: Evidence): EngTask {
  const stage = stageOf(t);
  // The ticket's recorded pane, else a session ticketForAgent ties to it (assigned by agent name or id).
  // A project's coordinator is never treated as a task session.
  const paneId = t.agentPaneId ?? [...agents.values()]
    .find((a) => a.role !== "coordinator" && ticketForAgent([t], a)?.key === t.key)?.id ?? null;
  return {
    key: t.key, project: t.project, title: t.title, stage, status: t.status, priority: t.priority,
    assignee: assigneeLabel(t.assignee), assigneeKind: assigneeKind(t.assignee),
    pr: t.prNumber != null ? { number: t.prNumber, url: t.prUrl } : null,
    gate: t.gate ?? null, gateReason: t.gateReason ?? null, openQuestions: t.openQuestions ?? 0,
    blocked: isBlocked(t, byKey), needsJay: stage === "Needs Jay", flags: t.flags, labels: t.labels, updatedAt: t.updatedAt,
    session: paneId ? { paneId, presence: presenceOf(agents.get(paneId), ev) } : null,
  };
}

const sortTasks = (a: EngTask, b: EngTask) =>
  PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank || b.updatedAt - a.updatedAt;

/** Open, unarchived tickets in stage columns (Closed is History's, not the workbench's). */
export function buildEngineering(src: HqSource, ev: Evidence, f: EngFilter = {}): EngineeringView {
  const byKey = new Map(src.tickets.map((t) => [t.key, t]));
  const open = src.tickets.filter((t) => isActive(t) && (!f.project || t.project === f.project));
  const agents = agentsById(src.state);
  const tasks = open.map((t) => engTask(t, byKey, agents, ev));
  const stages = VISIBLE_STAGES.filter((s) => s !== "Closed");
  const columns = stages.map((stage) => ({ stage, tasks: tasks.filter((t) => t.stage === stage).sort(sortTasks) }));
  const counts = Object.fromEntries(VISIBLE_STAGES.map((s) => [s, tasks.filter((t) => t.stage === s).length])) as Record<VisibleStage, number>;
  return { columns, total: tasks.length, counts, releaseGate: columns.find((c) => c.stage === "Ready to Merge")!.tasks,
    projects: [...new Set(src.tickets.filter(isActive).map((t) => t.project))].sort() };
}
