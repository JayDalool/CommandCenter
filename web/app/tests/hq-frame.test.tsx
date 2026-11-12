// The HQ frame (hq/frame): its tabs, titles and sidebar, and the fallback to Classic when it cannot be shown.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { HqBoundary, loadHqFrame } from "../src/components/Shell";
import { hqTitle, sectionOf, viewKey } from "../src/hq/frame/nav";
import { MAX_TABS, close, parseTabs, tabs, visit } from "../src/hq/frame/tabs";
import { state, tasks } from "./helpers";

describe("tabs", () => {
  it("adds a view once and remembers the last address it showed", () => {
    let l = visit([], "settings", "#/settings");
    l = visit(l, "tasks", "#/tasks");
    l = visit(l, "settings", "#/settings?tab=audit");
    expect(l).toEqual([{ key: "settings", hash: "#/settings?tab=audit" }, { key: "tasks", hash: "#/tasks" }]);
    expect(visit(l, "tasks", "#/tasks")).toBe(l);
  });

  it(`keeps at most ${MAX_TABS}, dropping the oldest`, () => {
    let l = visit([], "a", "#/a");
    for (let i = 0; i < MAX_TABS; i++) l = visit(l, `v${i}`, `#/v${i}`);
    expect(l).toHaveLength(MAX_TABS);
    expect(l[0].key).toBe("v0");
    expect(l.at(-1)!.key).toBe(`v${MAX_TABS - 1}`);
  });

  it("closing the current tab goes to its right-hand neighbour, else the left, else My Office", () => {
    const l = [{ key: "a", hash: "#/a" }, { key: "b", hash: "#/b" }, { key: "c", hash: "#/c" }];
    expect(close(l, "b", "b")).toEqual({ list: [l[0], l[2]], go: "#/c" });
    expect(close(l, "c", "c")).toEqual({ list: [l[0], l[1]], go: "#/b" });
    expect(close(l, "a", "c")).toEqual({ list: [l[1], l[2]], go: null });
    expect(close([l[0]], "a", "a")).toEqual({ list: [], go: "#/dashboard" });
  });

  it("reads only well-formed stored tabs", () => {
    expect(parseTabs('[{"key":"tasks","hash":"#/tasks"},{"key":"x","hash":"javascript:alert(1)"},7,null]'))
      .toEqual([{ key: "tasks", hash: "#/tasks" }]);
    expect(parseTabs("not json")).toEqual([]);
    expect(parseTabs('{"key":"tasks"}')).toEqual([]);
  });
});

describe("names", () => {
  it("uses HQ's names where it has one and Classic's otherwise", () => {
    expect(hqTitle("dashboard", null)).toBe("My Office");
    expect(hqTitle("needs", null)).toBe("Decisions");
    expect(hqTitle("tasks", null)).toBe("Engineering");
    expect(hqTitle("tasks", "SV-056")).toBe("SV-056");
    expect(hqTitle("projects", "samvision", "SamVision")).toBe("SamVision");
    expect(hqTitle("prs", null)).toBe("Pull requests");
    expect(hqTitle("server", null)).toBe("Server");
  });

  it("files aliases and Alerts under their sidebar item, and shares a tab between aliases", () => {
    expect(["overview", "console", "alerts", "tasks"].map(sectionOf)).toEqual(["dashboard", "files", "activity", "tasks"]);
    expect(viewKey({ screen: "overview", id: null })).toBe(viewKey({ screen: "dashboard", id: null }));
    expect(viewKey({ screen: "tasks", id: "SV-1" })).toBe("tasks/SV-1");
  });
});

describe("the frame in the app", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    vi.spyOn(app, "boot").mockResolvedValue(undefined);
    const t = tasks();
    app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
      taskProjects: t.projects, meta: t.meta });
    tabs.set([]);
    prefs.patch({ ui: "hq", railCollapsed: false });
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); tabs.set([]); });

  async function show(route: string) {
    location.hash = `#/${route}`;
    await loadHqFrame();
    const view = render(<App />);
    await act(async () => {});
    return view;
  }

  it("names the screen, marks its sidebar item and opens a tab for it", async () => {
    await show("needs");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Decisions");
    const nav = screen.getByRole("navigation", { name: "Screens" });
    expect(within(nav).getByRole("link", { name: /Decisions/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /My Office/ })).toHaveAttribute("href", "#/dashboard");
    const strip = screen.getByRole("navigation", { name: "Open views" });
    expect(within(strip).getByRole("link", { name: "Decisions" })).toHaveAttribute("aria-current", "page");
    // The only tab cannot be closed: there would be nothing left to show.
    expect(within(strip).queryByRole("button", { name: /Close/ })).toBeNull();
  });

  it("closing the current tab opens the next one", async () => {
    await show("tasks");
    await act(async () => { location.hash = "#/activity"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    const strip = screen.getByRole("navigation", { name: "Open views" });
    expect(within(strip).getAllByRole("link").map((a) => a.textContent)).toEqual(["Engineering", "Activity"]);
    await act(async () => { fireEvent.click(within(strip).getByRole("button", { name: "Close Activity tab" })); });
    expect(location.hash).toBe("#/tasks");
  });

  it("search opens Classic's palette, and the sidebar collapses to icons", async () => {
    await show("tasks");
    const pal = vi.fn();
    window.addEventListener("cc:palette", pal);
    fireEvent.click(screen.getByRole("button", { name: /Search screens/ }));
    expect(pal).toHaveBeenCalledTimes(1);
    window.removeEventListener("cc:palette", pal);
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(prefs.get().railCollapsed).toBe(true);
    expect(document.querySelector(".hq-shell.is-icons")).not.toBeNull();
    prefs.patch({ railCollapsed: false });
  });

  it("on the Dashboard the top bar leaves the bell to the Dashboard's own header", async () => {
    await show("dashboard");
    expect(document.querySelectorAll(".hq-top .bell, .hq-top [aria-label*='otification']")).toHaveLength(0);
  });
});

describe("fallback", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("shows Classic and says so when the frame throws", () => {
    const toast = vi.spyOn(app, "toast").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});   // React reports the caught error
    const Broken = () => { throw new Error("frame bug"); };
    render(<HqBoundary fallback={<p>classic</p>}><Broken /></HqBoundary>);
    expect(screen.getByText("classic")).toBeInTheDocument();
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/shows Classic/), "bad");
  });
});
