// A ccd that runs the nine-stage flow (flow/contract.md), for the specs that need one: the fixture's projects with a
// stage on every ticket and a size on all but one, sessions holding tickets on SamVision, a parent with two children,
// and one ticket's work with its stages, history and criteria. Everything here is made up for the test.
import raw from "../tests/fixture.json" with { type: "json" };
import type { Page } from "@playwright/test";
import type { Agent, FlowSeat, FlowStage, State, TaskList, Ticket, TicketStatus, TicketWork } from "../src/api/types";
import { NOW } from "./fixture";

const fx = raw as unknown as { state: State; tasks: TaskList };
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const T = Math.floor(NOW / 1000), H = 3600;

const NINE: FlowStage[] = ["intake", "investigate", "techReview", "build", "userCheck", "codeReview", "merge", "release", "done"];
/** The route a ticket had before the flow: what one nobody has sized still runs. */
const SEVEN = NINE.filter((s) => s !== "techReview" && s !== "userCheck");
const SMALL = NINE.filter((s) => s !== "investigate" && s !== "techReview");

const STAGE: Partial<Record<TicketStatus, FlowStage>> = { INBOX: "intake", PROPOSED: "intake", RESEARCHING: "investigate",
  READY_TO_IMPLEMENT: "build", IN_PROGRESS: "build", IN_REVIEW: "codeReview", READY_TO_MERGE: "merge", VERIFYING: "release",
  DONE: "done", BLOCKED: "investigate" };

/** Sessions added to SamVision, each holding one ticket. */
export const HOLDS = { "wE:pA": "SV-056", "wE:pB": "SV-011", "wE:pC": "SV-057", "wE:pD": "SV-031" } as const;

export function flowState(): State {
  const st = clone(fx.state);
  const lane = st.agents.find((a) => a.id === "wE:pA")!;
  const add = (id: string, name: string, status: Agent["status"]) =>
    st.agents.push({ ...clone(lane), id, pane_id: id, session_id: `s-${id}`, agent_name: name, status, cwd: `/srv/server/worktrees/samvisionai/${name}` });
  add("wE:pB", "sv-011-investigate", "working");
  add("wE:pC", "sv-057-review", "working");
  add("wE:pD", "sv-031-verify", "working");
  add("wE:pF", "sv-spare", "idle");
  return st;
}

export function flowTasks(): TaskList {
  const list = clone(fx.tasks);
  const sv = list.tickets.find((t) => t.key === "SV-056")!;
  const top = Math.max(...list.tickets.map((t) => t.id));
  const make = (n: number, key: string, more: Partial<Ticket>): Ticket => ({ ...clone(sv), id: top + n, key, number: Number(key.split("-")[1]),
    agentRole: null, agentPaneId: null, agentSessionId: null, assignee: null, labels: [], flags: [], parent: null,
    subtasks: { total: 0, done: 0 }, branch: null, prNumber: null, prUrl: null, ...more });
  list.tickets.push(
    make(1, "SV-057", { title: "Cluster colours by sale count", status: "IN_REVIEW", parent: "SV-056", labels: ["ui"] }),
    make(2, "SV-058", { title: "Cluster legend", status: "INBOX", parent: "SV-056" }),
    make(3, "SV-060", { title: "Saved search filters", status: "RESEARCHING" }),
    make(4, "SV-061", { title: "Typo in the sign-in error", status: "IN_PROGRESS", type: "BUG" }));
  const set: Record<string, Partial<Ticket>> = {
    "SV-056": { status: "IN_PROGRESS", agentPaneId: "wE:pA", agentRole: "IMPLEMENTER", subtasks: { total: 2, done: 0 } },
    "SV-011": { agentPaneId: "wE:pB", agentRole: "PLANNER" },
    "SV-057": { agentPaneId: "wE:pC", agentRole: "REVIEWER", size: "small", route: SMALL },            // changes a screen
    "SV-058": { size: "small", route: SMALL.filter((s) => s !== "userCheck") },
    "SV-031": { agentPaneId: "wE:pD", agentRole: "VERIFIER" },
    // nobody sized it; the policy makes it risky, so ccd shows it as risky while it runs the seven stages it had
    "SV-042": { size: "risky", route: SEVEN, visibleStage: "Needs Jay" },
    "SV-060": { stage: "techReview", size: "risky", stale: true },
    "SV-061": { size: "small", route: SMALL.filter((s) => s !== "userCheck") },
    "SV-014": { size: null, route: SEVEN },       // nobody sized it: it keeps the seven stages it had before the flow
  };
  for (const t of list.tickets) {
    Object.assign(t, { size: "standard", stale: false, route: NINE }, set[t.key]);
    t.stage = set[t.key]?.stage ?? STAGE[t.status] ?? null;
  }
  return list;
}

const step = (stage: FlowStage, state: "done" | "active" | "todo", seat: FlowSeat | "jay" | null, session: string | null, at: number | null) =>
  ({ stage, state, seat, by: session ? `agent:${session}` : null, session, at });

/** SV-056's work: through technical review (sent back once), now in build. */
export function flowWork(base: TicketWork): TicketWork {
  return { ...base, size: "standard",
    requirements: ["Markers that overlap join one cluster", "The map is repainted, never rebuilt"],
    criteria: [
      { id: "c1", text: "Markers closer than 40 px join one cluster", state: "pass", by: "agent:sv-056-impl", at: T - H, head: "3f9c2ab" },
      { id: "c2", text: "A cluster shows how many markers it holds", state: "open", by: null, at: null, head: null },
      { id: "c3", text: "Zooming in splits a cluster", state: "fail", by: "agent:sv-056-impl", at: T - H, head: "3f9c2ab" }],
    flow: { size: "standard", rounds: 1, idleSince: T - 600, stale: false, waitingOn: null,
      holder: { seat: "developer", session: "sv-056-impl", since: T - 3 * H }, next: { stage: "userCheck", seat: "userReviewer" },
      stages: [step("intake", "done", "lead", "samvision", T - 26 * H), step("investigate", "done", "investigator", "sv-056-plan", T - 22 * H),
        step("techReview", "done", "techReviewer", "sv-056-tech", T - 20 * H), step("build", "active", "developer", "sv-056-impl", T - 3 * H),
        step("userCheck", "todo", "userReviewer", null, null), step("codeReview", "todo", "codeReviewer", null, null),
        step("merge", "todo", "jay", null, null), step("release", "todo", "verifier", null, null), step("done", "todo", null, null, null)] },
    handoffs: [
      { at: T - 26 * H, stage: "intake", kind: "advanced", from: "lead", to: "investigator", by: "agent:samvision", note: null },
      { at: T - 22 * H, stage: "investigate", kind: "advanced", from: "investigator", to: "techReviewer", by: "agent:sv-056-plan", note: "Reproduced on the test map" },
      { at: T - 21 * H, stage: "techReview", kind: "sentBack", from: "techReviewer", to: "investigator", by: "agent:sv-056-tech", note: "Name the files the cluster layer touches" },
      { at: T - 20.5 * H, stage: "investigate", kind: "advanced", from: "investigator", to: "techReviewer", by: "agent:sv-056-plan", note: null },
      { at: T - 20 * H, stage: "techReview", kind: "advanced", from: "techReviewer", to: "developer", by: "agent:sv-056-tech", note: "Plan approved" }],
    closing: null };
}

/** Serves that ccd on this page. The work of every other ticket stays the fixture's (nothing recorded yet). */
export async function serveFlow(page: Page) {
  const json = (body: unknown) => ({ json: body, headers: { "cache-control": "no-store" } });
  await page.route("**/api/state", (r) => r.fulfill(json(flowState())));
  await page.route("**/api/tasks", (r) => r.fulfill(json(flowTasks())));
  await page.route("**/api/tasks/SV-056/work", async (r) => {
    const base = await (await r.fetch()).json() as TicketWork;
    return r.fulfill(json(flowWork({ ...base, status: "IN_PROGRESS" })));
  });
}
