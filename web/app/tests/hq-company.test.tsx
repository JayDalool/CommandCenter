// Company (hq/pages/Topology.tsx) on the test fixture: projects, open work by pipeline stage, and hosts, from
// buildTopology; worker nodes from GET /api/workers with status from their heartbeat. Graph view (the default) draws
// them as nodes with an inspector; List view as three columns. Only filters and selection, no actions.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { href } from "../src/lib/router";
import { buildTopology, evidence } from "../src/hq/data";
import { hostId, layoutTopology, ALL_LAYERS, TASK_NODES } from "../src/hq/pages/topo-graph";
import type { WorkerNode, WorkersState } from "../src/api/types";
import { fixture, state, tasks } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;

function load() {
  const t = tasks();
  const now = SNAPSHOT + 10_000;
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: now, tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta, conn: { status: "live", lastMessageAt: now, attempt: 0 } });
}

async function show(hash = "#/projects") {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-topology");
}

/** Switch to List view, the three columns. */
function list(page: HTMLElement) {
  fireEvent.click(within(within(page).getByRole("group", { name: "View" })).getByRole("button", { name: "List" }));
  return page;
}
const canvas = (page: HTMLElement) => within(page).getByTestId("topology-canvas");
const nodes = (page: HTMLElement) => [...page.querySelectorAll<HTMLElement>("[data-node]")].map((n) => n.dataset.node);
const edges = (page: HTMLElement) => [...page.querySelectorAll<SVGGElement>("[data-edge]")];
const inspector = (page: HTMLElement) => within(page).getByRole("complementary", { name: "Inspector" });

const view = (f = {}) => buildTopology(app.store.get(), evidence(app.store.get(), Date.now() / 1000), f);
const taskKeys = (page: HTMLElement) => [...page.querySelectorAll(".hq-topo-tasks code")].map((c) => c.textContent);
const shown = (v: ReturnType<typeof view>) => v.stages.flatMap((s) => s.tasks.slice(0, 5).map((t) => t.key));

const node = (id: string, heartbeatAgo: number | null): WorkerNode => ({ id, kind: "laptop", owner: "jay", status: "online", state: "active",
  capabilities: {}, version: "1", enrolledAt: 0, enrolledBy: "jay", approvedAt: 0, approvedBy: "jay",
  lastHeartbeat: heartbeatAgo == null ? null : Date.now() / 1000 - heartbeatAgo, revokedAt: null, fingerprint: null });

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("Company, List view", () => {
  it("shows every project, opening Classic's project screen, and the open work by stage", async () => {
    load();
    const page = list((await show())!);
    const v = view();
    const projects = [...page.querySelectorAll<HTMLAnchorElement>("a.hq-topo-node")].map((a) => a.getAttribute("href"));
    expect(projects).toEqual(v.projects.map((p) => href("projects", p.key)));
    expect(v.stages.length).toBeGreaterThan(1);
    expect(taskKeys(page)).toEqual(shown(v));
    for (const s of v.stages) expect(within(page).getByRole("region", { name: s.label })).toHaveTextContent(`${s.tasks.length} task`);
  });

  it("filters to blocked work and back", async () => {
    load();
    const page = list((await show())!);
    const n = (v: ReturnType<typeof view>) => v.stages.reduce((k, s) => k + s.tasks.length, 0);
    expect(n(view({ status: "blocked" }))).toBeGreaterThan(0);
    expect(n(view({ status: "blocked" }))).toBeLessThan(n(view()));
    fireEvent.click(within(page).getByRole("button", { name: "Blocked" }));
    expect(taskKeys(page)).toEqual(shown(view({ status: "blocked" })));
    fireEvent.click(within(page).getByRole("button", { name: "Clear" }));
    expect(taskKeys(page)).toEqual(shown(view()));
    const filters = page.querySelectorAll('[role="group"] button').length;
    expect(page.querySelectorAll("button")).toHaveLength(filters);
  });

  it("filters by project", async () => {
    load();
    const page = list((await show())!);
    const p = view().projects[0];
    fireEvent.click(within(within(page).getByRole("group", { name: "Filter by project" })).getByRole("button", { name: p.name }));
    expect([...page.querySelectorAll("a.hq-topo-node")].map((a) => a.getAttribute("href"))).toEqual([href("projects", p.key)]);
    expect(taskKeys(page)).toEqual(shown(view({ projects: [p.key] })));
  });

  it("shows worker nodes, Online only with a recent heartbeat", async () => {
    load();
    const w: WorkersState = { available: true, nodes: [node("laptop-a", 30), node("laptop-b", 3600)], events: [] };
    vi.spyOn(app.api, "workers").mockResolvedValue(w);
    const page = list((await show())!);
    const hosts = within(page).getByRole("region", { name: /^Hosts/ });
    const card = (name: string) => within(hosts).getByText(name).closest(".hq-topo-host")!;
    expect(card("laptop-a")).toHaveTextContent("Online");
    expect(card("laptop-b")).toHaveTextContent("Unknown");
    expect(card("Server")).toBeTruthy();
  });
});

describe("Company, Graph view", () => {
  it("draws Jay, every project, every stage with open work and every host, each once", async () => {
    load();
    const page = (await show())!;
    const v = view();
    expect(nodes(page).sort()).toEqual(["root", ...v.projects.map((p) => `p:${p.key}`), ...v.stages.map((s) => `s:${s.id}`),
      ...v.hosts.map(hostId)].sort());
    // One flow edge per project with work in a stage, red dashed where any of it is blocked.
    const flows = v.stages.flatMap((s) => s.flows.map((f) => ({ id: `e:${f.project}:${s.id}`, blocked: f.blocked })));
    const drawn = edges(page).filter((e) => e.classList.contains("ek-flow"));
    expect(drawn.map((e) => e.dataset.edge).sort()).toEqual(flows.map((f) => f.id).sort());
    for (const f of flows) expect(drawn.find((e) => e.dataset.edge === f.id)!.classList.contains("is-blocked")).toBe(f.blocked);
    expect(flows.some((f) => f.blocked)).toBe(true);
  });

  it("opens with Jay in the inspector and shows a selected project's details and links", async () => {
    load();
    const page = (await show())!;
    expect(inspector(page)).toHaveTextContent("Needs you");
    const p = view().projects[0];
    fireEvent.click(within(canvas(page)).getByRole("button", { name: new RegExp(`^${p.name},`) }));
    const insp = inspector(page);
    expect(within(insp).getByRole("heading", { name: p.name })).toBeInTheDocument();
    expect(within(insp).getByRole("link", { name: "Open project" })).toHaveAttribute("href", href("projects", p.key));
    expect(within(insp).getByRole("link", { name: "All in Engineering" })).toHaveAttribute("href", href("tasks", null, { project: p.key }));
    fireEvent.click(within(insp).getByRole("button", { name: "Back to Jay" }));
    expect(inspector(page)).toHaveTextContent("Needs you");
  });

  it("shows a stage's tasks as nodes, then a task's details", async () => {
    load();
    const page = (await show())!;
    const s = view().stages.find((x) => x.tasks.length)!;
    fireEvent.click(within(canvas(page)).getByRole("button", { name: `Show ${s.label} tasks` }));
    const keys = s.tasks.slice(0, TASK_NODES).map((t) => `t:${t.key}`);
    expect(nodes(page).filter((n) => n!.startsWith("t:"))).toEqual(keys);
    const t = s.tasks[0];
    fireEvent.click(page.querySelector<HTMLElement>(`[data-node="t:${t.key}"]`)!);
    expect(within(inspector(page)).getByRole("link", { name: "Open task" })).toHaveAttribute("href", href("tasks", t.key));
    fireEvent.click(within(canvas(page)).getByRole("button", { name: `Hide ${s.label} tasks` }));
    expect(nodes(page).some((n) => n!.startsWith("t:"))).toBe(false);
  });

  it("filters the graph and hides a kind of line", async () => {
    load();
    const page = (await show())!;
    const p = view().projects[0];
    fireEvent.click(within(within(page).getByRole("group", { name: "Filter by project" })).getByRole("button", { name: p.name }));
    expect(nodes(page).filter((n) => n!.startsWith("p:"))).toEqual([`p:${p.key}`]);
    expect(edges(page).some((e) => e.classList.contains("ek-host"))).toBe(true);
    fireEvent.click(within(within(page).getByRole("group", { name: "Show lines" })).getByRole("button", { name: "Runs on" }));
    expect(edges(page).some((e) => e.classList.contains("ek-host"))).toBe(false);
  });

  it("shows a worker node's heartbeat status in the inspector", async () => {
    load();
    vi.spyOn(app.api, "workers").mockResolvedValue({ available: true, nodes: [node("laptop-b", 3600)], events: [] });
    const page = (await show())!;
    fireEvent.click(within(canvas(page)).getByRole("button", { name: "laptop-b, unknown" }));
    expect(inspector(page)).toHaveTextContent("No recent heartbeat");
  });

  it("shows no Working, Online or vitals when the feed is not live", async () => {
    load();
    const now = Date.now() + 24 * 86_400_000;
    vi.setSystemTime(now);
    app.store.set({ ...app.store.get(), stateAt: now, conn: { status: "offline", lastMessageAt: null, attempt: 1 } });
    const page = (await show())!;
    const graph = canvas(page);
    expect(within(graph).queryAllByText(/^(Working|Online)$/)).toHaveLength(0);
    expect(graph.querySelector(".hq-gmeters")).toBeNull();
    for (const p of view().projects) {
      const n = page.querySelector(`[data-node="p:${p.key}"]`)!;
      expect(n).toHaveTextContent("session");
      expect(n).toHaveTextContent("(last)");
      if (p.coordinator) expect(n).toHaveTextContent("Lead unknown");
    }
    expect(view().projects.some((p) => p.coordinator)).toBe(true);
  });

  it("keeps the pan and zoom when a stage's tasks are shown", async () => {
    load();
    // jsdom has no layout: give the canvas a size so the graph is fitted at all.
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 1000, bottom: 640,
      width: 1000, height: 640, toJSON: () => ({}) });
    const page = (await show())!;
    expect(page.querySelector<HTMLElement>(".hq-world")!.style.transform).not.toContain("scale(0.8)");
    const world = page.querySelector<HTMLElement>(".hq-world")!;
    fireEvent.click(within(page).getByRole("button", { name: "Zoom in" }));
    const zoomed = world.style.transform;
    fireEvent.click(within(canvas(page)).getAllByRole("button", { name: /^Show .* tasks$/ })[0]);
    expect(world.style.transform).toBe(zoomed);
  });

  it("changes nothing: no form, and every button filters, zooms or selects", async () => {
    load();
    const page = (await show())!;
    expect(page.querySelector("form")).toBeNull();
    for (const b of page.querySelectorAll("button")) {
      expect(b.closest('[role="group"], [role="toolbar"], [data-testid="topology-canvas"], [aria-label="Inspector"]')).not.toBeNull();
    }
  });
});

describe("Company layout", () => {
  it("keeps every edge between drawn nodes and no two nodes in a row overlapping", () => {
    load();
    const v = view();
    const g = layoutTopology(v, v.stages.map((s) => s.id), ALL_LAYERS);
    const ids = new Set(g.nodes.map((n) => n.id));
    expect(g.edges.every((e) => ids.has(e.from) && ids.has(e.to))).toBe(true);
    for (const y of new Set(g.nodes.map((n) => n.y))) {
      const row = g.nodes.filter((n) => n.y === y).sort((a, b) => a.x - b.x);
      for (let i = 1; i < row.length; i++) expect(row[i].x).toBeGreaterThanOrEqual(row[i - 1].x + row[i - 1].w);
    }
    expect(g.nodes.every((n) => n.x >= 0 && n.x + n.w <= g.bounds.w && n.y + n.h <= g.bounds.h)).toBe(true);
  });
});

describe("Company", () => {
  it("says when worker nodes are not enabled", async () => {
    load();
    vi.spyOn(app.api, "workers").mockResolvedValue({ available: false, nodes: [], events: [] });
    const page = (await show())!;
    expect(within(page).getByText("Worker nodes are not enabled on this server.")).toBeInTheDocument();
  });

  it("keeps Classic's project screen for one project", async () => {
    load();
    expect(await show(href("projects", app.store.get().state!.projects[0].key))).toBeNull();
    expect(document.querySelector("#main .hq-page")).toBeNull();
  });
});
