// Pure ticket logic: vocabulary, filtering, grouping, the Needs-Jay queue. No React here.
import type { Agent, Blocked, Need, State, Ticket, TicketStatus, Priority } from "../api/types";
import { STATUSES, OFF_PIPELINE, PRIORITIES } from "../api/types";

export type Tone = "working" | "blocked" | "failed" | "review" | "verifying" | "waiting" | "idle" | "done" | "unknown"
  | "jay";

export const STATUS_META: Record<TicketStatus, { label: string; short: string; tone: Tone }> = {
  INBOX: { label: "Inbox", short: "INBX", tone: "idle" },
  PROPOSED: { label: "Proposed", short: "PROP", tone: "waiting" },
  RESEARCHING: { label: "Researching", short: "RSCH", tone: "review" },
  READY_TO_IMPLEMENT: { label: "Ready", short: "RDY", tone: "waiting" },
  IN_PROGRESS: { label: "In progress", short: "PROG", tone: "working" },
  IN_REVIEW: { label: "In review", short: "REVW", tone: "review" },
  READY_TO_MERGE: { label: "Ready to merge", short: "MRGE", tone: "jay" },
  VERIFYING: { label: "Verifying", short: "VRFY", tone: "verifying" },
  DONE: { label: "Done", short: "DONE", tone: "done" },
  BLOCKED: { label: "Blocked", short: "BLKD", tone: "blocked" },
  DENIED: { label: "Denied", short: "DENY", tone: "unknown" },
  CANCELLED: { label: "Cancelled", short: "CNCL", tone: "unknown" },
};

export const PRIORITY_META: Record<Priority, { label: string; rank: number; bars: number }> = {
  URGENT: { label: "Urgent", rank: 0, bars: 4 },
  HIGH: { label: "High", rank: 1, bars: 3 },
  MEDIUM: { label: "Medium", rank: 2, bars: 2 },
  LOW: { label: "Low", rank: 3, bars: 1 },
  NO_PRIORITY: { label: "No priority", rank: 4, bars: 0 },
};

export const FLAG_LABEL: Record<string, string> = {
  needs_jay: "needs:jay", needs_legal: "needs:legal", needs_ui_review: "needs:ui-review", needs_deploy: "needs:deploy",
};

export const PIPELINE: readonly TicketStatus[] = STATUSES;
export const OFF: readonly TicketStatus[] = OFF_PIPELINE;
export const ALL_STATUSES: readonly TicketStatus[] = [...STATUSES, ...OFF_PIPELINE];
export const CLOSED = new Set<TicketStatus>(["DONE", "DENIED", "CANCELLED"]);

export function statusIndex(s: TicketStatus) { return ALL_STATUSES.indexOf(s); }

/** "jay" → human; "role:IMPLEMENTER" → role; "agent:samvision" → a specific agent. */
export function assigneeKind(a: string | null): "none" | "human" | "role" | "agent" {
  if (!a) return "none";
  if (a === "jay") return "human";
  return a.startsWith("role:") ? "role" : "agent";
}

export function assigneeLabel(a: string | null): string {
  if (!a) return "Unassigned";
  if (a === "jay") return "Jay";
  const [, ref] = a.split(":");
  return a.startsWith("role:") ? ref.charAt(0) + ref.slice(1).toLowerCase() : ref;
}

export interface TicketFilter {
  q?: string;
  project?: string[];
  status?: TicketStatus[];
  priority?: Priority[];
  type?: string[];
  assignee?: string[];   // exact assignee strings, plus "none"
  label?: string[];
  needsJay?: boolean;
  blocked?: boolean;
  hasPr?: boolean;
  noPr?: boolean;
  includeClosed?: boolean;
}

/** Search: key prefix, words in title, label, branch. Cheap enough to run on every keystroke. */
export function matches(t: Ticket, q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  const hay = `${t.key} ${t.title} ${t.labels.join(" ")} ${t.branch ?? ""} ${t.prNumber ? "#" + t.prNumber : ""} ${
    t.assignee ?? ""} ${t.type ?? ""}`.toLowerCase();
  return s.split(/\s+/).every((w) => hay.includes(w));
}

export function isBlocked(t: Ticket, byKey: Map<string, Ticket>): boolean {
  if (t.status === "BLOCKED") return true;
  return t.blockedBy.some((k) => { const o = byKey.get(k); return !o || !CLOSED.has(o.status); });
}

export function filterTickets(all: Ticket[], f: TicketFilter): Ticket[] {
  const byKey = new Map(all.map((t) => [t.key, t]));
  const inSet = <T,>(v: T, set?: T[]) => !set || set.length === 0 || set.includes(v);
  return all.filter((t) =>
    !t.archived
    && (f.includeClosed || f.status?.length || !CLOSED.has(t.status))
    && inSet(t.project, f.project)
    && inSet(t.status, f.status)
    && inSet(t.priority, f.priority)
    && inSet(t.type ?? "", f.type)
    && (!f.assignee?.length || f.assignee.includes(t.assignee ?? "none"))
    && (!f.label?.length || f.label.every((l) => t.labels.includes(l)))
    && (!f.needsJay || t.flags.length > 0 || t.assignee === "jay")
    && (!f.blocked || isBlocked(t, byKey))
    && (!f.hasPr || t.prNumber != null)
    && (!f.noPr || t.prNumber == null)
    && (!f.q || matches(t, f.q)));
}

export type SortKey = "updated" | "priority" | "status" | "key";
export function sortTickets(ts: Ticket[], key: SortKey = "updated"): Ticket[] {
  const out = [...ts];
  const cmp: Record<SortKey, (a: Ticket, b: Ticket) => number> = {
    updated: (a, b) => b.updatedAt - a.updatedAt,
    priority: (a, b) => PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank || b.updatedAt - a.updatedAt,
    status: (a, b) => statusIndex(a.status) - statusIndex(b.status) || PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank,
    key: (a, b) => a.project.localeCompare(b.project) || a.number - b.number,
  };
  return out.sort(cmp[key]);
}

export function groupByStatus(ts: Ticket[]): Map<TicketStatus, Ticket[]> {
  const m = new Map<TicketStatus, Ticket[]>(ALL_STATUSES.map((s) => [s, []]));
  for (const t of ts) m.get(t.status)?.push(t);
  for (const [, list] of m) list.sort((a, b) => PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank
    || b.updatedAt - a.updatedAt);
  return m;
}

/** Neighbouring pipeline status for keyboard moves (Shift+←/→). Off-pipeline states stay put. */
export function stepStatus(s: TicketStatus, dir: -1 | 1): TicketStatus {
  const i = PIPELINE.indexOf(s);
  if (i < 0) return s;
  return PIPELINE[Math.max(0, Math.min(PIPELINE.length - 1, i + dir))];
}

// ---------- the one Needs-Jay queue ----------

export type NeedKind = "answer" | "merge" | "ticket" | "task" | "actions" | "ci";
export interface JayItem {
  id: string;
  kind: NeedKind;
  verb: string;          // what Jay does: Answer, Merge, Decide, Review UI, Deploy, Do, Fix
  project: string;
  ref: string;
  text: string;
  flags: string[];
  since: number | null;  // epoch s
  url: string | null;
  agentId?: string;
}

const VERB_BY_FLAG: Record<string, string> = { needs_legal: "Legal", needs_ui_review: "Review UI", needs_deploy: "Deploy",
  needs_jay: "Decide" };

/** Blocked agents first (someone is waiting right now), then merges, then flagged tickets, then the rest. */
export function jayQueue(st: State | null, agents?: Agent[]): JayItem[] {
  if (!st) return [];
  const out: JayItem[] = [];
  const blockedSince = new Map((agents ?? st.agents).map((a) => [a.id, a.blockedSinceMs]));
  for (const b of st.blocked as Blocked[]) {
    const ms = blockedSince.get(b.pane_id);
    out.push({ id: `answer:${b.pane_id}`, kind: "answer", verb: "Answer", project: b.project, ref: b.name,
      text: b.question, flags: [], since: ms ? ms / 1000 : null, url: null, agentId: b.pane_id });
  }
  const order: Record<string, number> = { merge: 1, ticket: 2, task: 3, ci: 4, actions: 5 };
  const rest = [...(st.needs as Need[])].sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9));
  for (const n of rest) {
    const kind = (["merge", "ticket", "task", "actions", "ci"].includes(n.kind) ? n.kind : "task") as NeedKind;
    const verb = kind === "merge" ? "Merge" : kind === "ci" ? "Fix" : kind === "ticket"
      ? VERB_BY_FLAG[(n.flags ?? [])[0] ?? "needs_jay"] ?? "Decide" : "Do";
    out.push({ id: `${n.kind}:${n.project}:${n.ref}`, kind, verb, project: n.project, ref: n.ref,
      text: n.text.replace(/^merge · /, "").replace(/^you do it · /, ""), flags: n.flags ?? [],
      since: n.since ?? null, url: n.url });
  }
  return out;
}

export function ticketForAgent(tickets: Ticket[], a: Agent): Ticket | undefined {
  const open = tickets.filter((t) => !CLOSED.has(t.status) && !t.archived);
  return open.find((t) => t.agentPaneId === a.id)
    ?? open.find((t) => a.agent_name && t.assignee === `agent:${a.agent_name}`)
    ?? open.find((t) => t.assignee === `agent:${a.id}`);
}

export const PRIORITY_ORDER = PRIORITIES;
