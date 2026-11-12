// Needs My Attention (roadmap P3.6): the one Needs-Jay queue from tickets/model.ts, in HQ's words.
//
// Same items, same order and same count as Classic's queue: this only labels them. Each item says where
// it is answered; nothing here answers, approves or merges, and recording a decision never merges.
import type { Ticket } from "../../api/types";
import { jayQueue, type JayItem } from "../../tickets/model";
import type { HqSource } from "./evidence";

/** The prototype's four kinds, plus Action for chores that are not a decision (CI red, My actions). */
export type DecisionKind = "Decision" | "Question" | "Review" | "Approval" | "Action";
export type Tone = "bad" | "warn" | "info" | "violet" | "ok" | "idle";

export interface DecisionItem {
  id: string;
  kind: DecisionKind;
  /** What Jay does: Answer, Merge, Approve plan, Review UI, Deploy, Unblock, Fix, Decide, Do… */
  verb: string;
  project: string;
  /** The ticket key when the item is about one (a gate, questions, a flagged ticket, a blocked task session). */
  ticket: string | null;
  ref: string;
  title: string;
  sub: string;
  pill: [string, Tone];
  tone: Tone;
  /** Someone is stuck until Jay acts: a session waiting on an answer, or a failure gate. */
  blocker: boolean;
  urgent: boolean;
  since: number | null;
  url: string | null;
  /** The pane waiting on an answer, when there is one. */
  agentId: string | null;
  source: JayItem;
}

export interface DecisionsView {
  items: DecisionItem[];
  summary: { total: number; urgent: number; blockers: number; approvals: number; questions: number };
}

const FLAG_PILL: Record<string, [string, Tone]> = {
  needs_legal: ["Legal", "warn"], needs_ui_review: ["Review UI", "violet"], needs_deploy: ["Deploy", "warn"],
  needs_jay: ["Needs input", "warn"],
};

function classify(j: JayItem): { kind: DecisionKind; pill: [string, Tone]; blocker: boolean } {
  switch (j.kind) {
    case "answer": return { kind: "Question", pill: ["Blocker", "bad"], blocker: true };
    case "questions": return { kind: "Question", pill: ["Needs input", "warn"], blocker: false };
    case "gate":
      if (j.gate === "failure") return { kind: "Decision", pill: ["Blocker", "bad"], blocker: true };
      if (j.gate === "plan") return { kind: "Decision", pill: ["Plan", "info"], blocker: false };
      if (j.gate === "ui") return { kind: "Review", pill: ["Review UI", "violet"], blocker: false };
      if (j.gate === "merge") return { kind: "Approval", pill: ["Merge", "ok"], blocker: false };
      if (j.gate === "deploy") return { kind: "Approval", pill: ["Deploy", "warn"], blocker: false };
      return { kind: "Decision", pill: ["Decide", "info"], blocker: false };
    case "merge": return { kind: "Approval", pill: ["Merge", "ok"], blocker: false };
    case "ticket": {
      const f = j.flags[0] ?? "needs_jay";
      return { kind: f === "needs_ui_review" ? "Review" : "Decision", pill: FLAG_PILL[f] ?? ["Needs input", "warn"], blocker: false };
    }
    case "ci": return { kind: "Action", pill: ["CI red", "bad"], blocker: false };
    default: return { kind: "Action", pill: ["To do", "idle"], blocker: false };
  }
}

function subOf(j: JayItem, t: Ticket | undefined): string {
  const who = j.ticket ?? j.label ?? j.ref;
  switch (j.kind) {
    case "answer": return `${who} is waiting for your answer`;
    case "questions": return `${j.questions ?? "Open"} question${j.questions === 1 ? "" : "s"} on ${j.ref}`;
    case "gate": return `${j.verb} · ${j.ref}${t ? ` · ${t.title}` : ""}`;
    case "merge": return `Pull request ${j.ref} · you merge; nothing here merges it`;
    case "ticket": return `${j.ref}${t ? ` · ${t.title}` : ""}`;
    case "ci": return "Main branch checks are failing";
    default: return j.ref;
  }
}

/** Every item waiting for Jay, from the same queue as Classic's Needs You. Nothing is invented or dropped. */
export function buildDecisions(src: HqSource): DecisionsView {
  const byKey = new Map(src.tickets.map((t) => [t.key, t]));
  const queue = jayQueue(src.state, undefined, src.tickets);
  const items = queue.map((j): DecisionItem => {
    const ticketKey = j.ticket ?? (byKey.has(j.ref) ? j.ref : null);
    const t = ticketKey ? byKey.get(ticketKey) : undefined;
    const c = classify(j);
    const urgent = c.blocker || c.pill[1] === "bad" || t?.priority === "URGENT";
    return { id: j.id, kind: c.kind, verb: j.verb, project: j.project, ticket: ticketKey, ref: j.ref, title: j.text,
      sub: subOf(j, t), pill: c.pill, tone: c.pill[1], blocker: c.blocker, urgent, since: j.since, url: j.url,
      agentId: j.agentId ?? null, source: j };
  });
  return { items, summary: {
    total: items.length,
    urgent: items.filter((i) => i.urgent).length,
    blockers: items.filter((i) => i.blocker).length,
    approvals: items.filter((i) => i.kind === "Approval").length,
    questions: items.filter((i) => i.kind === "Question").length,
  } };
}
