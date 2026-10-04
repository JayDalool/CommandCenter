import { filterTickets, sortTickets, groupByStatus, stepStatus, jayQueue, assigneeKind, assigneeLabel, matches,
  ticketForAgent, isBlocked } from "../src/tickets/model";
import { state, tasks } from "./helpers";

const all = tasks().tickets;
const byKey = (k: string) => all.find((t) => t.key === k)!;

describe("ticket filtering", () => {
  it("hides closed and archived tickets unless asked", () => {
    expect(filterTickets(all, {}).some((t) => t.status === "DONE")).toBe(false);
    expect(filterTickets(all, { includeClosed: true }).some((t) => t.status === "DONE")).toBe(true);
  });
  it("filters by project, status, priority, type and assignee", () => {
    expect(filterTickets(all, { project: ["gauzemate"] }).every((t) => t.project === "gauzemate")).toBe(true);
    expect(filterTickets(all, { status: ["BLOCKED"] }).map((t) => t.key)).toEqual(["SV-014"]);
    expect(filterTickets(all, { priority: ["URGENT"] }).map((t) => t.key).sort()).toEqual(["SV-014", "SV-042"]);
    expect(filterTickets(all, { type: ["OWNER_ACTION"] }).every((t) => t.type === "OWNER_ACTION")).toBe(true);
    expect(filterTickets(all, { assignee: ["jay"] }).every((t) => t.assignee === "jay")).toBe(true);
    expect(filterTickets(all, { assignee: ["none"] }).every((t) => t.assignee === null)).toBe(true);
  });
  it("needs-Jay, blocked, has PR, no PR and labels", () => {
    expect(filterTickets(all, { needsJay: true }).every((t) => t.flags.length || t.assignee === "jay")).toBe(true);
    const blocked = filterTickets(all, { blocked: true }).map((t) => t.key);
    expect(blocked).toContain("SV-014");
    expect(blocked).toContain("CC-002");  // blocked by an open ticket
    const withPr = filterTickets(all, { hasPr: true });
    expect(withPr.map((t) => t.key)).toContain("SV-056");
    expect(withPr.every((t) => t.prNumber != null)).toBe(true);
    expect(filterTickets(all, { noPr: true }).some((t) => t.key === "SV-056")).toBe(false);
    expect(filterTickets(all, { label: ["p4b"] }).map((t) => t.key).sort()).toEqual(["CC-001", "CC-002"]);
  });
  it("search is word-based across key, title, labels and PR", () => {
    expect(matches(byKey("SV-056"), "sv-056")).toBe(true);
    expect(matches(byKey("SV-056"), "map clusters")).toBe(true);
    expect(matches(byKey("SV-056"), "#94")).toBe(true);
    expect(matches(byKey("SV-056"), "map nonsense")).toBe(false);
  });
  it("a blocker that is closed no longer blocks", () => {
    const m = new Map(all.map((t) => [t.key, { ...t }]));
    expect(isBlocked(m.get("CC-002")!, m)).toBe(true);
    m.get("CC-001")!.status = "DONE";
    expect(isBlocked(m.get("CC-002")!, m)).toBe(false);
  });
});

describe("ordering", () => {
  it("groups by status with priority first", () => {
    const g = groupByStatus(all);
    expect(g.get("IN_PROGRESS")!.map((t) => t.priority)[0]).toBe("HIGH");
    expect([...g.keys()][0]).toBe("INBOX");
  });
  it("sorts by priority then recency", () => {
    expect(sortTickets(all, "priority")[0].priority).toBe("URGENT");
  });
  it("steps along the pipeline and not off it", () => {
    expect(stepStatus("IN_PROGRESS", 1)).toBe("IN_REVIEW");
    expect(stepStatus("INBOX", -1)).toBe("INBOX");
    expect(stepStatus("DONE", 1)).toBe("DONE");
    expect(stepStatus("BLOCKED", 1)).toBe("BLOCKED");
  });
});

describe("assignees", () => {
  it("human, role and agent are distinct", () => {
    expect(assigneeKind("jay")).toBe("human");
    expect(assigneeKind("role:PLANNER")).toBe("role");
    expect(assigneeKind("agent:samvision")).toBe("agent");
    expect(assigneeKind(null)).toBe("none");
    expect(assigneeLabel("role:IMPLEMENTER")).toBe("Implementer");
  });
  it("links an agent to its ticket", () => {
    const st = state();
    const gm = st.agents.find((a) => a.agent_name === "gauzemate")!;
    expect(ticketForAgent(all, gm)?.key).toBe("GM-026");
  });
});

describe("the Needs-Jay queue", () => {
  it("puts blocked agents first, then merges, then flagged tickets", () => {
    const q = jayQueue(state());
    expect(q[0].kind).toBe("answer");
    expect(q[0].text).toMatch(/initials/);
    const kinds = q.map((x) => x.kind);
    expect(kinds.indexOf("merge")).toBeLessThan(kinds.indexOf("ticket"));
    const legal = q.find((x) => x.ref === "SV-014")!;
    expect(legal.verb).toBe("Legal");
    expect(q.filter((x) => x.kind === "ticket").length).toBe(7);
  });
  it("is empty without state", () => { expect(jayQueue(null)).toEqual([]); });
});
