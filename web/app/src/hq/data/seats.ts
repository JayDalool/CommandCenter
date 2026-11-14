// Teams › Seats (the new flow, flow/contract.md): each project's seats and the tickets in flight, built from
// the tickets and sessions ccd reports.
//
// A seat is a job in the flow (investigator, developer, code reviewer …), not a session. A session sits in one
// while it holds a ticket in that job, and the seat is Free the rest of the time. Nothing is invented: a session
// whose ticket does not say what it does there is listed apart, and a ccd from before the new flow shows only the
// stages and seats it can tell apart (no technical review, no user check).
import type { FlowSeat, FlowStage, Ticket, TicketStatus } from "../../api/types";
import { isActive } from "../../lib/control";
import type { Evidence, HqSource } from "./evidence";
import { buildTeams, type TeamMember, type TeamsView } from "./teams";

export const FLOW_STAGES: FlowStage[] = ["intake", "investigate", "techReview", "build", "userCheck", "codeReview", "merge",
  "release", "done"];
export const STAGE_LABEL: Record<FlowStage, string> = {
  intake: "Intake", investigate: "Investigate", techReview: "Technical review", build: "Build", userCheck: "User check",
  codeReview: "Code review", merge: "Merge", release: "Release", done: "Done",
};
export const FLOW_SEATS: FlowSeat[] = ["lead", "investigator", "techReviewer", "developer", "userReviewer", "designReviewer",
  "codeReviewer", "verifier"];
export const SEAT_LABEL: Record<FlowSeat | "jay", string> = {
  lead: "Lead", investigator: "Investigator", techReviewer: "Technical reviewer", developer: "Developer",
  userReviewer: "User reviewer", designReviewer: "Design reviewer", codeReviewer: "Code reviewer", verifier: "Verifier", jay: "You",
};
/** Who does each stage. The merge is Jay's, so no seat holds it. */
export const STAGE_SEAT: Record<FlowStage, FlowSeat | "jay"> = {
  intake: "lead", investigate: "investigator", techReview: "techReviewer", build: "developer", userCheck: "userReviewer",
  codeReview: "codeReviewer", merge: "jay", release: "verifier", done: "lead",
};

/** COORDINATOR is not here: the lead's seat is the team's lead and nobody else's, so any other session with that
 *  role sits in no seat. */
const ROLE_SEAT: Record<string, FlowSeat> = { PLANNER: "investigator", IMPLEMENTER: "developer", REVIEWER: "codeReviewer",
  VERIFIER: "verifier" };
/** The seat of the session a ticket records as its agent. A reviewer sits in the review the ticket is at. */
const seatFor = (role: string, at: FlowStage | null): FlowSeat | null =>
  role === "REVIEWER" && (at === "techReview" || at === "userCheck") ? STAGE_SEAT[at] as FlowSeat : ROLE_SEAT[role] ?? null;
/** With no recorded role, only the stages one session does alone say what the ticket's holder is doing. A ticket in
 *  a review is held by whoever built it as often as by its reviewer, so no seat is guessed there. */
const DOING: Partial<Record<FlowStage, FlowSeat>> = { investigate: "investigator", build: "developer" };
/** A ccd from before the new flow sends no stage: its status says which stage the ticket is in. */
const STATUS_STAGE: Partial<Record<TicketStatus, FlowStage>> = { INBOX: "intake", PROPOSED: "intake", RESEARCHING: "investigate",
  READY_TO_IMPLEMENT: "build", IN_PROGRESS: "build", IN_REVIEW: "codeReview", READY_TO_MERGE: "merge", VERIFYING: "release",
  DONE: "done" };
const OLD_STAGES: FlowStage[] = FLOW_STAGES.filter((s) => s !== "techReview" && s !== "userCheck");
const OLD_SEATS: FlowSeat[] = ["lead", "investigator", "developer", "codeReviewer", "verifier"];

export function stageOf(t: Ticket): FlowStage | null {
  return t.stage && FLOW_STAGES.includes(t.stage) ? t.stage : STATUS_STAGE[t.status] ?? null;
}

export interface RailStep { stage: FlowStage; state: "done" | "active" | "todo" | "skipped" }

/** A screen changes: the same test ccd uses for its UI gate (pipeline.policy). */
const isUi = (t: Ticket) => t.flags.includes("needs_ui_review") || t.type === "DESIGN" || t.labels.includes("ui");

/** The stages a ticket goes through. ccd says so when it sends `route`. Without it this is a guess from the size:
 *  a ticket nobody sized keeps the seven stages it had before the flow, and a small one skips three of the nine. */
export function routeOf(t: Ticket, flow: boolean): FlowStage[] {
  const sent = t.route?.filter((s) => FLOW_STAGES.includes(s));
  if (sent?.length) return sent;
  if (!flow || !t.size) return OLD_STAGES;
  return t.size !== "small" ? FLOW_STAGES
    : FLOW_STAGES.filter((s) => s !== "investigate" && s !== "techReview" && (s !== "userCheck" || isUi(t)));
}

/** The row of stages. `flow` = this ccd runs the nine stages, so every ticket is drawn on the same nine places and a
 *  stage off its route is skipped; where the ticket is always shows. */
export function railOf(t: Ticket, flow: boolean): RailStep[] {
  const at = stageOf(t), on = routeOf(t, flow);
  const stages = flow ? FLOW_STAGES : OLD_STAGES;
  const i = at ? stages.indexOf(at) : -1;
  return stages.map((stage, n) => ({ stage,
    state: n === i ? "active" : !on.includes(stage) ? "skipped" : i >= 0 && n < i ? "done" : "todo" }));
}

export interface SeatRow {
  seat: FlowSeat;
  who: TeamMember | null;
  ticket: Ticket | null;
  stage: FlowStage | null;
}

export interface FlightRow {
  t: Ticket;
  stage: FlowStage | null;
  rail: RailStep[];
  /** Sessions on this ticket now, each with the seat it sits in (null when the ticket does not say). */
  on: { who: TeamMember; seat: FlowSeat | null }[];
  needsJay: boolean;
  blocked: boolean;
  /** This ccd runs the flow and nobody has sized the ticket yet, so it keeps the stages it had before. */
  notSized: boolean;
  children: FlightRow[];
}

export interface SeatsTeam {
  key: string;
  name: string;
  /** Why the lead's seat is empty, in Jay's words. Null when someone is in it. */
  leadWhy: string | null;
  seats: SeatRow[];
  /** Tickets past intake, or with someone on them: parents first, every open child under its parent. */
  flight: FlightRow[];
  /** How many tickets the list holds (children and parents brought along from intake included), and how many
   *  more wait at intake. */
  inFlight: number;
  atIntake: number;
  /** Sessions of this project in no seat: no ticket, or a ticket that does not say what they do on it. */
  loose: TeamMember[];
  openTasks: number;
}

export interface SeatsView {
  teams: SeatsTeam[];
  unassigned: TeamMember[];
  /** This ccd runs the nine-stage flow (it sends a stage with every ticket). */
  flow: boolean;
  sessions: TeamsView["sessions"];
}

const needsJay = (t: Ticket) => t.visibleStage === "Needs Jay" || !!t.gate || (t.openQuestions ?? 0) > 0;
const blocked = (t: Ticket) => t.status === "BLOCKED" || t.visibleStage === "Blocked";
/** Closest to done first, so the eye lands on what can be finished; what needs Jay leads its group. */
const order = (a: FlightRow, b: FlightRow) => Number(b.needsJay) - Number(a.needsJay)
  || FLOW_STAGES.indexOf(b.stage ?? "intake") - FLOW_STAGES.indexOf(a.stage ?? "intake") || a.t.number - b.t.number;

export function buildSeats(src: HqSource, ev: Evidence): SeatsView {
  const base = buildTeams(src, ev);
  const flow = src.tickets.some((t) => t.stage !== undefined);
  const teams = base.teams.map((team): SeatsTeam => {
    const open = src.tickets.filter((t) => t.project === team.key && isActive(t));
    const byKey = new Map(open.map((t) => [t.key, t]));
    const people = team.lead ? [team.lead, ...team.members] : team.members;
    const seatOf = (m: TeamMember, t: Ticket): FlowSeat | null => {
      if (m.leadOf) return "lead";
      const at = stageOf(t);
      return t.agentPaneId === m.id && t.agentRole ? seatFor(t.agentRole, at) : at ? DOING[at] ?? null : null;
    };
    const on = new Map<string, FlightRow["on"]>();
    for (const m of people) {
      const t = m.ticket ? byKey.get(m.ticket) : undefined;
      if (t) on.set(t.key, [...(on.get(t.key) ?? []), { who: m, seat: seatOf(m, t) }]);
    }

    const shown = flow ? FLOW_SEATS : OLD_SEATS;
    const seats = shown.flatMap((seat): SeatRow[] => {
      if (seat === "lead") {
        const t = team.lead?.ticket ? byKey.get(team.lead.ticket) ?? null : null;
        return [{ seat, who: team.lead, ticket: t, stage: t ? stageOf(t) : null }];
      }
      const rows = [...on].flatMap(([key, list]) => list.filter((x) => x.seat === seat && !x.who.leadOf)
        .map((x): SeatRow => ({ seat, who: x.who, ticket: byKey.get(key)!, stage: stageOf(byKey.get(key)!) })));
      return rows.length ? rows : [{ seat, who: null, ticket: null, stage: null }];
    });

    const row = (t: Ticket): FlightRow => ({ t, stage: stageOf(t), rail: railOf(t, flow), on: on.get(t.key) ?? [],
      needsJay: needsJay(t), blocked: blocked(t), notSized: flow && !t.size, children: [] });
    const inFlight = (t: Ticket) => stageOf(t) !== "intake" || on.has(t.key);
    const rows = new Map(open.filter(inFlight).map((t) => [t.key, row(t)]));
    // A child in flight brings its parent along, so the tree reads whole even when the parent itself is waiting.
    for (const r of [...rows.values()]) {
      const p = r.t.parent ? byKey.get(r.t.parent) : undefined;
      if (p && !rows.has(p.key)) rows.set(p.key, row(p));
    }
    // …and a parent shows every open child, so what has to finish before it can is in one place.
    for (const t of open) if (t.parent && rows.has(t.parent) && !rows.has(t.key)) rows.set(t.key, row(t));
    const roots: FlightRow[] = [];
    for (const r of rows.values()) {
      const p = r.t.parent ? rows.get(r.t.parent) : undefined;
      (p ? p.children : roots).push(r);
    }
    roots.sort(order);
    roots.forEach((r) => r.children.sort(order));

    const seated = new Set([...on.values()].flat().filter((x) => x.seat).map((x) => x.who.id));
    return { key: team.key, name: team.name, leadWhy: team.leadWhy, seats, flight: roots, inFlight: rows.size,
      atIntake: open.length - rows.size,
      loose: team.members.filter((m) => !seated.has(m.id)), openTasks: team.openTasks };
  });
  return { teams, unassigned: base.unassigned, flow, sessions: base.sessions };
}
