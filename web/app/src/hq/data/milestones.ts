// Where a project stands on one track of milestones, from the list ccd keeps (GET /api/milestones). Pure: nothing here
// decides a milestone's state, it only reads the states Jay or the project's lead set.
import type { Milestone } from "../../api/types";

export interface TrackSummary {
  total: number;
  done: number;
  /** The one in hand: the first in progress, else the first not started. Null when there are none or all are done. */
  current: Milestone | null;
  /** "Now" for one in progress, "Next" for one not started. */
  label: "Now" | "Next" | null;
  /** The current one has a due date before today. */
  overdue: boolean;
}

/** `today` is YYYY-MM-DD in the browser's own time zone, as the due dates are. */
export function trackSummary(list: readonly Milestone[], today: string): TrackSummary {
  const doing = list.find((m) => m.state === "doing"), current = doing ?? list.find((m) => m.state === "todo") ?? null;
  return { total: list.length, done: list.filter((m) => m.state === "done").length, current,
    label: current ? (doing ? "Now" : "Next") : null, overdue: !!current?.due && current.due < today };
}

/** A local calendar day as YYYY-MM-DD. */
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "Nov 20" for a YYYY-MM-DD, read as a local day (new Date("2026-11-20") would be UTC and can show the day before). */
export function dueLabel(due: string): string {
  const [y, m, d] = due.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
