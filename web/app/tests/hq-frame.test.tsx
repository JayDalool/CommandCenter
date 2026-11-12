// The HQ frame (hq/frame): its tabs, titles and sidebar, and the fallback to Classic when it cannot be shown.
import { Component, Suspense, lazy, useState, type ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { AppShell, HqBoundary, ScreenMark, loadHqFrame } from "../src/components/Shell";
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

  it("My Office replaces the Dashboard, and the bell is in the top bar, once", async () => {
    await show("dashboard");
    expect(document.querySelector("#main > .hq-office")).not.toBeNull();
    expect(document.querySelector(".dash-top")).toBeNull();
    expect(document.querySelectorAll(".hq-top [aria-label*='otification']").length).toBe(1);
    expect(document.querySelectorAll("[aria-label*='otification']").length).toBe(1);
  });
});

describe("Workspace Focus in HQ", () => {
  afterEach(() => { cleanup(); prefs.patch({ ui: "classic", wsFocus: false }); });

  it("hides the frame without remounting the screen (its terminals stay connected)", async () => {
    let mounts = 0;
    function Probe() { useState(() => { mounts++; return 0; }); return <p>screen</p>; }
    prefs.patch({ ui: "hq", wsFocus: false });
    location.hash = "#/workspace";
    await loadHqFrame();
    render(<AppShell flush><Probe /></AppShell>);
    await act(async () => {});
    expect(document.querySelector(".hq-side")).not.toBeNull();
    await act(async () => { prefs.patch({ wsFocus: true }); });
    expect(document.querySelector(".hq-side")).toBeNull();
    expect(document.querySelector(".hq-shell.is-focus")).not.toBeNull();
    await act(async () => { prefs.patch({ wsFocus: false }); });
    expect(document.querySelector(".hq-side")).not.toBeNull();
    expect(screen.getByText("screen")).toBeInTheDocument();
    expect(mounts).toBe(1);
  });
});

describe("fallback", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("shows Classic when the frame's chunk cannot be fetched", async () => {
    const toast = vi.spyOn(app, "toast").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Missing = lazy(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module: /assets/Frame-x.js")));
    render(<HqBoundary fallback={<p>classic</p>}><Suspense fallback={null}><Missing /></Suspense></HqBoundary>);
    expect(await screen.findByText("classic")).toBeInTheDocument();
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/shows Classic/), "bad");
  });

  it("does not blame HQ for an error in the Classic screen inside it: the error goes on as in Classic", () => {
    const toast = vi.spyOn(app, "toast").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    class Root extends Component<{ children: ReactNode }, { e: string | null }> {
      state = { e: null as string | null };
      static getDerivedStateFromError(e: Error) { return { e: e.message }; }
      render() { return this.state.e ? <p>root caught {this.state.e}</p> : this.props.children; }
    }
    const Broken = () => { throw new Error("screen bug"); };
    render(<Root><HqBoundary fallback={<p>classic</p>}><ScreenMark><Broken /></ScreenMark></HqBoundary></Root>);
    expect(screen.getByText("root caught screen bug")).toBeInTheDocument();
    expect(screen.queryByText("classic")).toBeNull();
    expect(toast).not.toHaveBeenCalled();
  });

  it("shows Classic and says so when the frame throws", () => {
    const toast = vi.spyOn(app, "toast").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});   // React reports the caught error
    const Broken = () => { throw new Error("frame bug"); };
    render(<HqBoundary fallback={<p>classic</p>}><Broken /></HqBoundary>);
    expect(screen.getByText("classic")).toBeInTheDocument();
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/shows Classic/), "bad");
  });
});
