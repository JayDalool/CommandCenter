// A ticket as a manager-readable dossier (spec §6): why, problem, cause, plan, acceptance criteria.
// The same rule as ccd/records.py dossier(): explicit "## Why" … sections in the description win;
// the recorded plan fills in what the description does not say. Nothing is invented.
import type { TicketDetail, TicketWork, TimelineEvent } from "../api/types";

function section(desc: string, names: string[]): string {
  const out: string[] = [];
  let on = false;
  for (const line of desc.split(/\r?\n/)) {
    const m = /^#{1,3}\s+(.*?)\s*$/.exec(line);
    if (m) { on = names.includes(m[1].trim().toLowerCase().replace(/:$/, "")); continue; }
    if (on) out.push(line);
  }
  return out.join("\n").trim();
}

export interface Dossier { why: string; problem: string; cause: string; plan: string[]; acceptance: string[]; planBy: string | null }

export function dossier(t: Pick<TicketDetail, "description">, w: TicketWork | null): Dossier {
  const d = t.description ?? "";
  const plan = w?.plan ?? {};
  let why = section(d, ["why", "why we're doing this", "why we are doing this", "goal"]);
  if (!why) why = d.trim() && !/^#{1,3}\s/m.test(d) ? d.trim() : plan.summary ?? "";
  const acc = section(d, ["acceptance criteria", "acceptance", "done when"]).split("\n")
    .map((l) => l.replace(/^\s*[-*]\s*(\[[ xX]\]\s*)?/, "").trim()).filter(Boolean);
  const steps = plan.requirements?.length ? plan.requirements
    : (plan.approach ?? "").split(/\n+/).map((l) => l.replace(/^\s*(\d+[.)]|[-*])\s*/, "").trim()).filter(Boolean);
  return {
    why, problem: section(d, ["problem", "what is broken", "what's missing"]), cause: section(d, ["cause", "root cause"]),
    plan: steps, acceptance: acc.length ? acc : plan.tests ?? [], planBy: w?.roles?.planner?.model ?? null,
  };
}

/** The stage walk from the audit trail, backward moves marked (Review → Implementation is a step back). */
const ORDER = ["INBOX", "PROPOSED", "RESEARCHING", "READY_TO_IMPLEMENT", "IN_PROGRESS", "IN_REVIEW", "READY_TO_MERGE",
  "VERIFYING", "DONE"];
export interface Step { at: number; from: string; to: string; why: string; back: boolean; actor: string }
export function walk(timeline: TimelineEvent[]): Step[] {
  return timeline.filter((e) => e.field === "status" && e.to).map((e) => ({
    at: e.at, from: e.from ?? "—", to: e.to!, why: e.trigger ?? "", actor: e.actor,
    back: ORDER.indexOf(e.to!) >= 0 && ORDER.indexOf(e.from ?? "") > ORDER.indexOf(e.to!),
  }));
}

export const STATUS_WORD: Record<string, string> = { INBOX: "Inbox", PROPOSED: "Proposed", RESEARCHING: "Planning",
  READY_TO_IMPLEMENT: "Plan accepted", IN_PROGRESS: "Implementation", IN_REVIEW: "Review", READY_TO_MERGE: "Ready to merge",
  VERIFYING: "Verification", DONE: "Closed", BLOCKED: "Blocked", DENIED: "Denied", CANCELLED: "Cancelled" };
