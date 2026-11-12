// Company (hq/pages/Topology.tsx) on the test fixture: projects, open work by pipeline stage, and hosts, from
// buildTopology; worker nodes from GET /api/workers with status from their heartbeat; only filters, no actions.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { href } from "../src/lib/router";
import { buildTopology, evidence } from "../src/hq/data";
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

describe("Company", () => {
  it("shows every project, opening Classic's project screen, and the open work by stage", async () => {
    load();
    const page = (await show())!;
    const v = view();
    const projects = [...page.querySelectorAll<HTMLAnchorElement>("a.hq-topo-node")].map((a) => a.getAttribute("href"));
    expect(projects).toEqual(v.projects.map((p) => href("projects", p.key)));
    expect(v.stages.length).toBeGreaterThan(1);
    expect(taskKeys(page)).toEqual(shown(v));
    for (const s of v.stages) expect(within(page).getByRole("region", { name: s.label })).toHaveTextContent(`${s.tasks.length} task`);
  });

  it("filters to blocked work and back, and has no buttons but its filters", async () => {
    load();
    const page = (await show())!;
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
    const page = (await show())!;
    const p = view().projects[0];
    fireEvent.click(within(within(page).getByRole("group", { name: "Filter by project" })).getByRole("button", { name: p.name }));
    expect([...page.querySelectorAll("a.hq-topo-node")].map((a) => a.getAttribute("href"))).toEqual([href("projects", p.key)]);
    expect(taskKeys(page)).toEqual(shown(view({ projects: [p.key] })));
  });

  it("shows worker nodes, Online only with a recent heartbeat", async () => {
    load();
    const w: WorkersState = { available: true, nodes: [node("laptop-a", 30), node("laptop-b", 3600)], events: [] };
    vi.spyOn(app.api, "workers").mockResolvedValue(w);
    const page = (await show())!;
    const hosts = within(page).getByRole("region", { name: /^Hosts/ });
    const card = (name: string) => within(hosts).getByText(name).closest(".hq-topo-host")!;
    expect(card("laptop-a")).toHaveTextContent("Online");
    expect(card("laptop-b")).toHaveTextContent("Unknown");
    expect(card("Server")).toBeTruthy();
  });

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
