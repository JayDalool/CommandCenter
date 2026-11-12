// HQ live-data layer: view models from Classic's store, checked against tests/fixture.json.
import { describe, expect, it, vi } from "vitest";
import { state, tasks, ev as event } from "./helpers";
import type { CcdEvent, State, Ticket, WorkersState } from "../src/api/types";
import { jayQueue } from "../src/tickets/model";
import { projectPanels } from "../src/screens/Dashboard";
import { isActive } from "../src/lib/control";
import {
  buildActivity, buildAlerts, buildDecisions, buildEngineering, buildHq, buildOffice, buildTeams, buildTopology,
  evidence, groupOf, officeProjects, presenceOf, type HqSource,
} from "../src/hq/data";

// Same pattern as hq-tokens.test.ts: a plain-string module name, so the type check needs no @types/node.
const NODE_FS: string = "node:fs";
const { readFileSync, readdirSync } = (await import(NODE_FS)) as {
  readFileSync(path: string, encoding: "utf8"): string; readdirSync(path: string): string[] };
const here = (import.meta as unknown as { dirname: string }).dirname;  // web/app/tests

type Conn = HqSource["conn"];
function src(over: { st?: State; tickets?: Ticket[]; activity?: CcdEvent[]; conn?: Partial<Conn> } = {}) {
  const st = over.st ?? state();
  const tl = tasks();
  const now = st.at + 5;
  const s: HqSource = { state: st, tickets: over.tickets ?? tl.tickets, activity: over.activity ?? [], taskProjects: tl.projects,
    conn: { status: "live", lastMessageAt: now * 1000, ...over.conn } };
  return { s, now, ev: evidence(s, now) };
}
/** herdr's last snapshot two minutes old: over lib/freshness.ts's 90 s limit. */
function staleHerdr(): State { const st = state(); st.sources.herdr.lastSnapshotAt = st.at - 120; return st; }

describe("evidence", () => {
  it("reads herdr's status when its feed is live", () => {
    const { s, ev } = src();
    expect(ev.sessions).toBe("live");
    const by = (id: string) => presenceOf(s.state!.agents.find((a) => a.id === id), ev);
    expect(by("wE:p2")).toBe("idle");
    expect(by("wE:pA")).toBe("working");
    expect(by("wE:p4")).toBe("waiting");
  });

  it("a stale session feed makes every status Unknown, never Working", () => {
    const { s, ev } = src({ st: staleHerdr() });
    expect(ev.sessions).toBe("stale");
    expect(s.state!.agents.map((a) => presenceOf(a, ev))).toEqual(["unknown", "unknown", "unknown"]);
  });

  it("a dropped event stream makes every status Unknown", () => {
    const { s, ev } = src({ conn: { status: "offline" } });
    expect(s.state!.agents.every((a) => presenceOf(a, ev) === "unknown")).toBe(true);
  });

  it("an unreachable herdr makes every status Unknown", () => {
    const st = state(); st.sources.herdr.ok = false;
    const { s, ev } = src({ st });
    expect(s.state!.agents.every((a) => presenceOf(a, ev) === "unknown")).toBe(true);
  });

  it("a session herdr no longer reports is Offline when live, Unknown when stale", () => {
    expect(presenceOf(undefined, src().ev)).toBe("offline");
    expect(presenceOf(undefined, src({ st: staleHerdr() }).ev)).toBe("unknown");
  });
});

describe("My Office (P3.2)", () => {
  it("project counts match the Classic Dashboard panels", () => {
    const { s, ev } = src();
    const office = buildOffice(s, ev);
    const queue = jayQueue(s.state, undefined, s.tickets);
    const panels = projectPanels(officeProjects(s), s.tickets, [], queue, ev.now);
    expect(office.projects.map((p) => p.key)).toEqual(panels.map((p) => p.key));
    for (const p of office.projects) {
      const d = panels.find((x) => x.key === p.key)!;
      expect(p.counts, p.key).toEqual(d.counts);
      expect(p.activeTasks, p.key).toBe(d.active.length);
    }
    expect(office.kpis.needsYou.total).toBe(queue.length);
  });

  it("health only from evidence: red main is degraded, missing GitHub data is Unknown", () => {
    const { s, ev } = src();
    const o = buildOffice(s, ev);
    const h = (k: string) => o.projects.find((p) => p.key === k)!.health;
    expect(h("samvision")).toBe("healthy");
    expect(h("gyst")).toBe("degraded");
    expect(h("commandcenter")).toBe("unknown");   // tickets, but no repository feed in this snapshot
    expect(o.kpis.health.state).toBe("degraded");
  });

  it("company health is Unknown when the feeds are stale, never Healthy", () => {
    for (const s of [src({ st: staleHerdr() }), src({ conn: { status: "offline" } })]) {
      const o = buildOffice(s.s, s.ev);
      expect(o.kpis.health.state).toBe("unknown");
      expect(o.agents.every((a) => a.presence === "unknown")).toBe(true);
    }
    const st = state(); for (const k of Object.keys(st.sources.github)) st.sources.github[k].asOf = st.at - 3600;
    const s = src({ st });
    expect(buildOffice(s.s, s.ev).projects.filter((p) => st.projects.some((x) => x.key === p.key)).map((p) => p.health))
      .toEqual(["unknown", "unknown", "unknown", "unknown"]);
  });

  it("agents are exactly herdr's sessions and lead updates are not invented", () => {
    const { s, ev } = src();
    const o = buildOffice(s, ev);
    expect(o.agents.map((a) => a.id).sort()).toEqual(s.state!.agents.map((a) => a.id).sort());
    expect(o.kpis.sessions).toEqual({ total: 3, working: 1, waiting: 1, offline: 0, unknown: 0 });
    expect(o.leadUpdates.available).toBe(false);
  });

  it("alerts: active and unacknowledged only", () => {
    const st = state(); st.alerts[0].ack = true; st.alerts[1].active = false;
    const { s, ev } = src({ st });
    const ids = buildOffice(s, ev).alerts.map((a) => a.id);
    expect(ids).not.toContain(st.alerts[0].id);
    expect(ids).not.toContain(st.alerts[1].id);
    expect(ids.length).toBe(st.alerts.length - 2);
  });
});

describe("Needs My Attention (P3.6)", () => {
  it("is the Needs-Jay queue, same items in the same order", () => {
    const { s } = src();
    const d = buildDecisions(s);
    expect(d.items.map((i) => i.id)).toEqual(jayQueue(s.state, undefined, s.tickets).map((j) => j.id));
  });

  it("labels each item by what Jay does", () => {
    const { s } = src();
    const d = buildDecisions(s);
    const answer = d.items.find((i) => i.source.kind === "answer")!;
    expect(answer).toMatchObject({ kind: "Question", blocker: true, urgent: true, agentId: "wE:p4" });
    expect(d.items.filter((i) => i.source.kind === "merge").every((i) => i.kind === "Approval")).toBe(true);
    expect(d.items.find((i) => i.source.kind === "ci")).toMatchObject({ kind: "Action", urgent: true });
    expect(d.items.find((i) => i.ref === "SV-014")).toMatchObject({ kind: "Decision", pill: ["Legal", "warn"], urgent: true });
    expect(d.summary.total).toBe(d.items.length);
    expect(d.summary.blockers).toBe(1);
  });

  it("a gate is one item for its ticket, labelled by the gate", () => {
    const tl = tasks().tickets;
    const st = state();
    st.needs.push({ project: "samvision", ref: "SV-056", text: "Review UI", kind: "gate", url: null, gate: "ui" } as never);
    st.needs.push({ project: "samvision", ref: "SV-042", text: "Deploy", kind: "gate", url: null, gate: "deploy" } as never);
    const d = buildDecisions(src({ st, tickets: tl }).s);
    expect(d.items.find((i) => i.ref === "SV-056")).toMatchObject({ kind: "Review", ticket: "SV-056" });
    expect(d.items.find((i) => i.ref === "SV-042" && i.source.kind === "gate")).toMatchObject({ kind: "Approval", pill: ["Deploy", "warn"] });
  });
});

describe("Engineering (P3.3)", () => {
  it("every open ticket once, by its visible stage, with the release gate", () => {
    const { s, ev } = src();
    const e = buildEngineering(s, ev);
    const open = s.tickets.filter(isActive);
    expect(e.total).toBe(open.length);
    expect(e.columns.flatMap((c) => c.tasks.map((t) => t.key)).sort()).toEqual(open.map((t) => t.key).sort());
    expect(e.columns.some((c) => c.stage === "Closed")).toBe(false);
    expect(e.releaseGate.map((t) => t.key)).toEqual(e.columns.find((c) => c.stage === "Ready to Merge")!.tasks.map((t) => t.key));
    expect(e.counts["Blocked"]).toBe(1);
  });

  it("filters by project", () => {
    const { s, ev } = src();
    const e = buildEngineering(s, ev, { project: "samvision" });
    expect(e.columns.flatMap((c) => c.tasks).every((t) => t.project === "samvision")).toBe(true);
  });

  it("a task's session status comes from herdr, never from the ticket", () => {
    const tl = tasks().tickets;
    tl.find((t) => t.key === "SV-056")!.agentPaneId = "wE:pA";
    tl.find((t) => t.key === "CC-001")!.agentPaneId = "gone:p9";
    const live = src({ tickets: tl });
    const e = buildEngineering(live.s, live.ev);
    const task = (k: string) => e.columns.flatMap((c) => c.tasks).find((t) => t.key === k)!;
    expect(task("SV-056").session).toEqual({ paneId: "wE:pA", presence: "working" });
    expect(task("CC-001").session).toEqual({ paneId: "gone:p9", presence: "offline" });
    expect(task("GYST-011").session).toBeNull();
    // The coordinator is never a task session, even when the ticket is assigned to it by name.
    expect(task("GZ-903").session).toBeNull();
    const stale = src({ st: staleHerdr(), tickets: tl });
    const e2 = buildEngineering(stale.s, stale.ev);
    expect(e2.columns.flatMap((c) => c.tasks).find((t) => t.key === "SV-056")!.session!.presence).toBe("unknown");
  });
});

describe("Topology (P3.1)", () => {
  it("stages hold every open ticket of the shown projects", () => {
    const { s, ev } = src();
    const t = buildTopology(s, ev);
    expect(t.stages.flatMap((g) => g.tasks).length).toBe(s.tickets.filter(isActive).length);
    for (const g of t.stages) expect(g.flows.reduce((n, f) => n + f.count, 0)).toBe(g.tasks.length);
    expect(t.stages.find((g) => g.id === "build")!.flows.find((f) => f.project === "samvision")!.blocked).toBe(true);
    expect(t.projects.find((p) => p.key === "samvision")!.edge).toBe("blocked");
  });

  it("groups by status: a gate or question flags a task without moving it", () => {
    const t = tasks().tickets.find((x) => x.key === "SV-056")!;
    expect(groupOf(t)).toBe("review");
    expect(groupOf({ ...t, gate: "ui", openQuestions: 2 })).toBe("review");
    // A UI ticket in VERIFYING stays in UI Testing when a question or gate is open (stageOf says "Needs Jay" then).
    const ui = { ...t, status: "VERIFYING" as const, labels: ["ui"] };
    expect(groupOf(ui)).toBe("qa");
    expect(groupOf({ ...ui, openQuestions: 1 })).toBe("qa");
    expect(groupOf({ ...ui, gate: "deploy" })).toBe("qa");
    expect(groupOf({ ...ui, labels: [], openQuestions: 1 })).toBe("release");
  });

  it("filters: projects and attention", () => {
    const { s, ev } = src();
    const t = buildTopology(s, ev, { projects: ["gyst"] });
    expect(t.projects.map((p) => p.key)).toEqual(["gyst"]);
    expect(t.stages.flatMap((g) => g.tasks).every((x) => x.project === "gyst")).toBe(true);
    const a = buildTopology(s, ev, { status: "blocked" });
    expect(a.stages.flatMap((g) => g.tasks).every((x) => x.blocked)).toBe(true);
  });

  it("the server is Online only while its vitals are live", () => {
    const live = src();
    const h = buildTopology(live.s, live.ev).hosts[0];
    expect(h).toMatchObject({ id: "server", status: "online", sessions: 3, diskPct: 46, memPct: 62, cpuPct: null });
    const st = state(); st.sources.host.asOf = st.at - 3600;
    const stale = src({ st });
    expect(buildTopology(stale.s, stale.ev).hosts[0].status).toBe("unknown");
    const off = src({ conn: { status: "offline" } });
    expect(buildTopology(off.s, off.ev).hosts[0]).toMatchObject({ status: "unknown", sessions: null });
  });

  it("worker nodes only when the caller has them; status from the heartbeat", () => {
    const { s, ev } = src();
    expect(buildTopology(s, ev).workers.available).toBe(false);
    const node = (id: string, status: string, beat: number | null) => ({ id, kind: "laptop", owner: "jay", status, state: "active",
      capabilities: {}, version: null, enrolledAt: 0, enrolledBy: "jay", approvedAt: null, approvedBy: null,
      lastHeartbeat: beat, revokedAt: null, fingerprint: null });
    const w = { available: true, events: [], nodes: [node("fresh", "online", ev.now - 30), node("quiet", "online", ev.now - 900),
      node("gone", "revoked", null), node("new", "pending", null)] } as unknown as WorkersState;
    const hosts = buildTopology(s, ev, {}, w).hosts;
    expect(hosts.map((h) => [h.id, h.status])).toEqual([["server", "online"], ["fresh", "online"], ["quiet", "unknown"],
      ["gone", "revoked"], ["new", "pending"]]);
  });
});

describe("Teams (P3.5)", () => {
  it("a lead only where a coordinator session exists", () => {
    const { s, ev } = src();
    const t = buildTeams(s, ev);
    const team = (k: string) => t.teams.find((x) => x.key === k)!;
    expect(team("samvision").lead).toMatchObject({ id: "wE:p2", presence: "idle" });
    expect(team("samvision").members.map((m) => m.id)).toEqual(["wE:pA"]);
    expect(team("gauzemate").lead).toMatchObject({ id: "wE:p4", presence: "waiting" });
    expect(team("gyst").lead).toBeNull();
    expect(team("gyst").leadWhy).toBe("No coordinator session");
    expect(team("mfe").members).toEqual([]);
  });

  it("invents nobody: every member is a herdr session, subagents carry no status", () => {
    const { s, ev } = src();
    const t = buildTeams(s, ev);
    const people = t.teams.flatMap((x) => (x.lead ? [x.lead, ...x.members] : x.members)).concat(t.unassigned);
    expect(people.map((m) => m.id).sort()).toEqual(s.state!.agents.map((a) => a.id).sort());
    const sv = t.teams.find((x) => x.key === "samvision")!;
    expect(sv.defined.length).toBeGreaterThan(0);
    expect(sv.defined.some((d) => d.name === "samvision" || d.name === "sv-056-impl")).toBe(false);
    expect(Object.keys(sv.defined[0]).sort()).toEqual(["model", "name"]);
  });

  it("a coordinator whose pane is gone is no lead", () => {
    const st = state(); st.agents = st.agents.filter((a) => a.id !== "wE:p2");
    const { s, ev } = src({ st });
    const sv = buildTeams(s, ev).teams.find((x) => x.key === "samvision")!;
    expect(sv.lead).toBeNull();
    expect(sv.leadWhy).toBe("Coordinator session not found");
  });
});

describe("Activity and Alerts (P3.7)", () => {
  const events = [event(1, "task.updated", { ref: "SV-056" }), event(2, "action.focus"), event(3, "pr.opened", { project: "gyst" }),
    event(4, "task.updated", { ref: "SV-050" }), event(5, "agent.blocked", { agentId: "wE:p4" })];

  it("Classic's rows: meaningful, newest first, closed tasks hidden unless asked", () => {
    const tl = tasks().tickets;
    expect(buildActivity(events, tl).map((r) => r.seq)).toEqual([5, 3, 1]);
    expect(buildActivity(events, tl, { withClosed: true }).map((r) => r.seq)).toEqual([5, 4, 3, 1]);
    expect(buildActivity(events, tl, { filter: "PRS" }).map((r) => r.seq)).toEqual([3]);
    expect(buildActivity(events, tl, { project: "gyst" }).map((r) => r.seq)).toEqual([3]);
    expect(buildActivity(events, tl)[2]).toMatchObject({ cat: "TASK", ticket: "SV-056" });
  });

  it("older pages merge without duplicates", () => {
    const rows = buildActivity(events.slice(2), tasks().tickets, { older: [events[0], events[2]] });
    expect(rows.map((r) => r.seq)).toEqual([5, 3, 1]);
  });

  it("alerts: unacknowledged first, newest first", () => {
    const st = state(); st.alerts[0].ack = true; st.alerts[2].since += 10;
    const a = buildAlerts(st.alerts);
    expect(a.rows[a.rows.length - 1].id).toBe(st.alerts[0].id);
    expect(a.rows[0].id).toBe(st.alerts[2].id);
    expect(a.unacked).toBe(st.alerts.length - 1);
  });
});

describe("the layer itself", () => {
  it("builds every page with no network call", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { s, now } = src();
    const hq = buildHq(s, now);
    expect(Object.keys(hq)).toEqual(["evidence", "office", "engineering", "decisions", "topology", "teams", "activity", "alerts"]);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("renders an empty store without throwing", () => {
    const empty: HqSource = { state: null, tickets: [], activity: [], conn: { status: "offline", lastMessageAt: null } };
    const hq = buildHq(empty, 0);
    expect(hq.office.kpis.health.state).toBe("unknown");
    expect(hq.teams.teams).toEqual([]);
    expect(hq.topology.hosts).toEqual([]);
  });

  it("imports no API client, store, React or HQ frame code", () => {
    const dir = `${here}/../src/hq/data`;
    const files = readdirSync(dir);
    expect(files.length).toBeGreaterThanOrEqual(8);
    for (const f of files) {
      const text = readFileSync(`${dir}/${f}`, "utf8");
      const imports = [...text.matchAll(/from "([^"]+)"/g)].map((m) => m[1]);
      for (const i of imports) expect(i, `${f} imports ${i}`).not.toMatch(/api\/client|store\/app|^react|hq\/frame|components\/Shell|App$/);
    }
  });
});
