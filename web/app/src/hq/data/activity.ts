// Activity and Alerts (roadmap P3.7): the same rows as Classic's Activity and Alerts screens.
//
// Rows come from the store's activity (the live feed plus whatever older pages the caller loaded) and
// /api/state alerts. The filters and order are Classic's; nothing is summarised or invented.
import type { Alert, CcdEvent, Ticket } from "../../api/types";
import { categorize, meaningful, type FeedCat } from "../../components/Feed";

export type ActivityFilter = "ALL" | "AGENTS" | "TASKS" | "PRS" | "CI" | "JAY" | "HOST";
export const ACTIVITY_FILTERS: Record<ActivityFilter, FeedCat[] | null> = {
  ALL: null, AGENTS: ["AGENT"], TASKS: ["TASK"], PRS: ["PR"], CI: ["CI"], JAY: ["JAY"], HOST: ["HOST", "ALERT"],
};

export interface ActivityRowView {
  seq: number; at: number; cat: FeedCat; kind: string; severity: string; project: string | null;
  ref: string | null; ticket: string | null; text: string; agentId: string | null;
}

export interface ActivityOptions { filter?: ActivityFilter; project?: string | null; withClosed?: boolean; older?: CcdEvent[] }

const CLOSED = ["DONE", "DENIED", "CANCELLED"];

export function buildActivity(activity: CcdEvent[], tickets: Ticket[], o: ActivityOptions = {}): ActivityRowView[] {
  const closed = new Set(tickets.filter((t) => CLOSED.includes(t.status) || t.archived).map((t) => t.key));
  const keys = new Set(tickets.map((t) => t.key));
  const want = ACTIVITY_FILTERS[o.filter ?? "ALL"];
  const seen = new Set(activity.map((e) => e.seq));
  // Classic's mergeActivity (store/app.ts), without importing the store: newest first, one row per seq.
  return [...activity, ...(o.older ?? []).filter((e) => !seen.has(e.seq))].sort((a, b) => b.seq - a.seq)
    .filter((e) => meaningful(e) && (!o.project || e.project === o.project) && (!want || want.includes(categorize(e.kind)))
      && (o.withClosed || !e.ref || !closed.has(e.ref)))
    .map((e) => { const cat = categorize(e.kind);
      return { seq: e.seq, at: e.at, cat, kind: e.kind, severity: e.severity, project: e.project, ref: e.ref,
        ticket: cat === "TASK" && e.ref && keys.has(e.ref) ? e.ref : null, text: e.text, agentId: e.agentId }; });
}

/** Classic's Alerts order: unacknowledged first, newest first. */
export function buildAlerts(alerts: Alert[] | null | undefined): { rows: Alert[]; unacked: number } {
  const rows = [...(alerts ?? [])].sort((a, b) => Number(a.ack) - Number(b.ack) || b.since - a.since);
  return { rows, unacked: rows.filter((a) => !a.ack).length };
}
