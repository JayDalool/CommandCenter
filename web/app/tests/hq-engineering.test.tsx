// Engineering (hq/pages/Engineering.tsx) on the test fixture: every open task by stage, the release gate, Classic's task
// detail at #/tasks/KEY, and presence only from evidence.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { buildEngineering, evidence } from "../src/hq/data";
import { fixture, state, tasks } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;

function load(live: boolean) {
  const t = tasks();
  const now = live ? SNAPSHOT + 10_000 : new Date("2026-10-27T15:00:00Z").getTime();
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: now, tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta,
    conn: live ? { status: "live", lastMessageAt: now, attempt: 0 } : { status: "offline", lastMessageAt: null, attempt: 1 } });
}

async function show(hash = "#/tasks") {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-eng")!;
}

const view = () => buildEngineering(app.store.get(), evidence(app.store.get(), Date.now() / 1000));
const keys = (page: HTMLElement) => [...page.querySelectorAll(".hq-table tbody tr code")].map((c) => c.textContent);

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("Engineering", () => {
  it("replaces the Tasks list in HQ and shows every open task, with the stage counts", async () => {
    load(true);
    const page = await show();
    expect(page).not.toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Engineering");
    const v = view();
    expect(v.total).toBeGreaterThan(0);
    expect(keys(page).sort()).toEqual(v.columns.flatMap((c) => c.tasks.map((t) => t.key)).sort());
    const stages = within(page).getByRole("group", { name: "Filter by stage" });
    expect(within(stages).getByRole("button", { name: /Implementing/ }).querySelector("b"))
      .toHaveTextContent(String(v.counts.Implementing));
  });

  it("filters by stage, and Clear brings every task back", async () => {
    load(true);
    const page = await show();
    const v = view();
    const stage = v.columns.find((c) => c.tasks.length && c.tasks.length < v.total)!;
    fireEvent.click(within(page).getByRole("button", { name: new RegExp(`^${stage.tasks.length}\\s*${stage.stage}$`) }));
    expect(keys(page)).toEqual(stage.tasks.map((t) => t.key));
    fireEvent.click(within(page).getByRole("button", { name: "Clear" }));
    expect(keys(page)).toHaveLength(v.total);
  });

  it("lists what waits for Jay's merge, and says nothing here merges", async () => {
    load(true);
    const page = await show();
    const gate = within(page).getByRole("region", { name: /Release gate/ });
    const v = view();
    const links = within(gate).queryAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(v.releaseGate.map((t) => `#/tasks/${t.key}`));
    expect(gate).toHaveTextContent("Nothing on this page merges");
    expect(within(gate).queryByRole("button")).toBeNull();
    expect(within(page).queryAllByRole("button").filter((b) => /^merge/i.test(b.textContent ?? ""))).toEqual([]);
  });

  it("opens Classic's task detail at the task's own address", async () => {
    load(true);
    const key = view().total ? view().columns.flatMap((c) => c.tasks)[0].key : "";
    const page = await show(`#/tasks/${key}`);
    expect(page.querySelector(".hq-eng-detail aside.td")).not.toBeNull();
    expect(within(page).getByRole("link", { name: key })).toHaveAttribute("aria-current", "true");
  });

  it("shows a session as Unknown, never Working, when the feed is not live", async () => {
    load(false);
    const page = await show();
    const sessions = [...page.querySelectorAll(".hq-table tbody tr")].map((r) => r.children[6].textContent);
    expect(sessions.length).toBeGreaterThan(0);
    expect(sessions).not.toContain("Working");
  });

  it("New task opens today's new-ticket flow, for the project in view", async () => {
    load(true);
    const page = await show("#/tasks?project=samvision");
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener("cc:new-task", on);
    fireEvent.click(within(page).getByRole("button", { name: "New task" }));
    window.removeEventListener("cc:new-task", on);
    expect(seen).toEqual([{ project: "samvision" }]);
  });
});
