// HQ pop-out windows (hq/windows): the strict pop-out address, the shape-checked messages between windows, the main
// window's Pop out, placeholder, shaded tab and Return here, and the pop-out window itself. Nothing here starts or
// stops a session, and no message carries a secret.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { href } from "../src/lib/router";
import { POP_VIEWS, STALE_MS, isWinMsg, placeOn, popOut, popViewOf, popped, receive, resetWindows, savePlace, savedPlace, sweep,
  whereIs, type Place } from "../src/hq/windows/manager";
import { viewOfRoute } from "../src/hq/windows/controls";
import { fixture, state, tasks } from "./helpers";

const PLACE: Place = { x: 1920, y: 0, w: 1400, h: 900 };

function load() {
  const t = tasks();
  const now = fixture.state.sources.herdr.lastSnapshotAt! * 1000 + 10_000;
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: now, tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta, conn: { status: "live", lastMessageAt: now, attempt: 0 } });
}

async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  if (hash.startsWith("#/pop/")) await import("../src/hq/windows/PopWindow");   // the pop-out window's own chunk
  const v = render(<App />);
  for (let i = 0; i < 3; i++) await act(async () => {});
  return v.container;
}

let posted: unknown[] = [];
beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  posted = [];
  vi.spyOn(BroadcastChannel.prototype, "postMessage").mockImplementation((m: unknown) => { posted.push(m); });
  resetWindows();
  try { localStorage.removeItem("cc.hq.windows"); } catch { /* none */ }
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("pop-out address and messages", () => {
  it("accepts only #/pop/<an HQ page>, with nothing after it", () => {
    for (const v of POP_VIEWS) expect(popViewOf(`#/pop/${v}`)).toBe(v);
    for (const h of ["#/pop/projects?x=1", "#/pop/projects/samvision", "#/pop/settings", "#/pop/", "#/pop", "#/projects",
      "#/pop/projects#x", "#/pop/PROJECTS"]) expect(popViewOf(h)).toBeNull();
  });

  it("acts only on messages of the exact shapes it sends", () => {
    expect(isWinMsg({ t: "here", view: "projects", place: PLACE })).toBe(true);
    expect(isWinMsg({ t: "who" })).toBe(true);
    expect(isWinMsg({ t: "return", view: "needs" })).toBe(true);
    for (const bad of [null, "who", { t: "who", token: "x" }, { t: "here", view: "settings", place: PLACE },
      { t: "here", view: "projects", place: { ...PLACE, x: Number.NaN } }, { t: "here", view: "projects" },
      { t: "focus", view: "projects", extra: 1 }, { t: "open", hash: "#/projects" }, { t: "return", view: "x" }]) {
      expect(isWinMsg(bad)).toBe(false);
    }
  });

  it("tracks a pop-out from its messages and forgets one that stops answering", () => {
    receive({ t: "here", view: "projects", place: PLACE }, 1000);
    expect(popped.get().projects?.place).toEqual(PLACE);
    receive({ t: "here", view: "settings", place: PLACE }, 1000);   // not an HQ pop-out view: ignored
    expect(Object.keys(popped.get())).toEqual(["projects"]);
    sweep(1000 + STALE_MS);
    expect(popped.get().projects).toBeTruthy();
    sweep(1001 + STALE_MS);
    expect(popped.get().projects).toBeUndefined();
    receive({ t: "here", view: "needs", place: PLACE }, 5000);
    receive({ t: "gone", view: "needs" });
    expect(popped.get()).toEqual({});
  });

  it("which addresses can pop out: an HQ page, not one task, one project or a Classic Tasks view", () => {
    const r = (h: string) => { const [screen, id = null] = h.split("/"); return { screen, id, params: new URLSearchParams() }; };
    expect(viewOfRoute(r("projects"))).toBe("projects");
    expect(viewOfRoute(r("overview"))).toBe("dashboard");
    expect(viewOfRoute(r("projects/samvision"))).toBeNull();
    expect(viewOfRoute(r("tasks/SV-1"))).toBeNull();
    expect(viewOfRoute({ screen: "tasks", id: null, params: new URLSearchParams("view=board") })).toBeNull();
    expect(viewOfRoute(r("settings"))).toBeNull();
  });
});

describe("placing windows", () => {
  it("opens one named window per view, where it was last", () => {
    const open = vi.spyOn(window, "open").mockReturnValue({ closed: false, focus() {}, close() {} } as unknown as Window);
    savePlace("projects", PLACE);
    expect(popOut("projects")).toBe(true);
    const [url, name, features] = open.mock.calls[0];
    expect(String(url).endsWith("#/pop/projects")).toBe(true);
    expect(name).toBe("cc-hq-projects");
    expect(features).toBe("popup=yes,left=1920,top=0,width=1400,height=900");
    expect(popped.get().projects).toBeTruthy();
  });

  it("says so and changes nothing when the browser blocks the window", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(popOut("needs")).toBe(false);
    expect(popped.get().needs).toBeUndefined();
  });

  it("keeps a sensible remembered place only", () => {
    savePlace("tasks", { x: 0, y: 0, w: 40, h: 40 });
    expect(savedPlace("tasks")).toBeNull();
    localStorage.setItem("cc.hq.windows", JSON.stringify({ tasks: { x: "a", y: 0, w: 900, h: 700 } }));
    expect(savedPlace("tasks")).toBeNull();
  });

  it("centres a new window on the chosen monitor and says where a window is", () => {
    expect(placeOn({ left: 1920, top: 0, width: 2560, height: 1440 })).toEqual({ x: 2500, y: 220, w: 1400, h: 1000 });
    const here = { x: 0, y: 0, w: 1600, h: 1000 };
    expect(whereIs({ x: 2000, y: 0, w: 1200, h: 800 }, here, 1920)).toBe("on the screen to the right");
    expect(whereIs({ x: -1800, y: 0, w: 1200, h: 800 }, here, 1920)).toBe("on the screen to the left");
    expect(whereIs({ x: 300, y: 100, w: 1000, h: 700 }, here, 1920)).toBe("on this screen");
  });
});

describe("the main window", () => {
  it("offers Pop out on an HQ page, and shows where the page went once it is popped", async () => {
    load();
    const c = await show("#/projects");
    expect(posted).toContainEqual({ t: "who" });
    expect(within(c).getByRole("button", { name: "Pop out" })).toBeInTheDocument();
    expect(c.querySelector("#main > .hq-topology")).not.toBeNull();

    act(() => receive({ t: "here", view: "projects", place: PLACE }));
    expect(c.querySelector("#main .hq-topology")).toBeNull();
    const ph = within(c).getByRole("region", { name: "Company is open in its own window" });
    expect(within(c).queryByRole("button", { name: "Pop out" })).toBeNull();
    expect(c.querySelector(".hq-tab.is-out")).toHaveTextContent("Company");

    fireEvent.click(within(ph).getByRole("button", { name: "Focus window" }));
    expect(posted).toContainEqual({ t: "focus", view: "projects" });
    expect(within(ph).getByRole("status")).toHaveTextContent("Company · Command Center");

    fireEvent.click(within(ph).getByRole("button", { name: "Return here" }));
    expect(posted).toContainEqual({ t: "return", view: "projects" });
    expect(c.querySelector("#main > .hq-topology")).not.toBeNull();
  });

  it("offers no Pop out for one project or one task", async () => {
    load();
    const c = await show(href("tasks", app.store.get().tickets[0].key));
    expect(within(c).queryByRole("button", { name: "Pop out" })).toBeNull();
  });

  it("opens a new window from the menu", async () => {
    load();
    const open = vi.spyOn(window, "open").mockReturnValue({ closed: false, focus() {}, close() {} } as unknown as Window);
    const c = await show("#/needs");
    fireEvent.click(within(c).getByRole("button", { name: "Pop out" }));
    fireEvent.click(within(within(c).getByRole("menu")).getByRole("menuitem", { name: /^New window/ }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(String(open.mock.calls[0][0]).endsWith("#/pop/needs")).toBe(true);
    expect(within(c).getByRole("region", { name: "Decisions is open in its own window" })).toBeInTheDocument();
  });
});

describe("the pop-out window", () => {
  it("shows the page with no sidebar, says it is open, and opens links in the main window", async () => {
    load();
    const main = { closed: false, focus: vi.fn(), location: { hash: "#/dashboard" } };
    vi.stubGlobal("opener", main);
    const c = await show("#/pop/projects");
    expect(c.querySelector(".hq-side")).toBeNull();
    expect(c.querySelector(".hq-popwin .hq-topology")).not.toBeNull();
    expect(within(c).getByRole("button", { name: "Return to main window" })).toBeInTheDocument();
    expect(posted.some((m) => isWinMsg(m) && m.t === "here" && m.view === "projects")).toBe(true);
    expect(JSON.stringify(posted)).not.toMatch(/token/i);

    const link = c.querySelector<HTMLAnchorElement>('.hq-popwin .hq-screen a[href^="#/"]')!;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    link.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(main.location.hash).toBe(link.getAttribute("href"));
    expect(main.focus).toHaveBeenCalled();
  });

  // The pop-out's own address is #/pop/tasks: Engineering must not read "tasks" as a task key, and opening a task
  // from it goes to the main window, as its links do, so the pop-out keeps showing the list.
  it("pops Engineering out as the list, and opens a task in the main window", async () => {
    load();
    const main = { closed: false, focus: vi.fn(), location: { hash: "#/dashboard" } };
    vi.stubGlobal("opener", main);
    const loadTicket = vi.spyOn(app, "loadTicket");
    const c = await show("#/pop/tasks");
    expect(c.querySelector(".hq-popwin .hq-eng")).not.toBeNull();
    expect(c.querySelector(".hq-eng-detail")).toBeNull();
    expect(loadTicket).not.toHaveBeenCalled();
    const row = c.querySelector<HTMLTableRowElement>(".hq-popwin .hq-eng tbody tr")!;
    const key = row.querySelector(".c-key code")!.textContent!;
    fireEvent.click(row.querySelector(".c-title")!);
    expect(main.location.hash).toBe(href("tasks", key));
    expect(main.focus).toHaveBeenCalled();
    expect(location.hash).toBe("#/pop/tasks");
    expect(c.querySelector(".hq-eng-detail")).toBeNull();
    expect(loadTicket).not.toHaveBeenCalled();
  });

  it("with no main window left, opening a task turns the pop-out into an ordinary window", async () => {
    load();
    vi.stubGlobal("opener", null);
    const c = await show("#/pop/tasks");
    const row = c.querySelector<HTMLTableRowElement>(".hq-popwin .hq-eng tbody tr")!;
    const key = row.querySelector(".c-key code")!.textContent!;
    fireEvent.click(row.querySelector(".c-title")!);
    expect(location.hash).toBe(href("tasks", key));
  });

  it("closes itself when the main window takes the page back", async () => {
    load();
    const close = vi.spyOn(window, "close").mockImplementation(() => {});
    await show("#/pop/projects");
    act(() => receive({ t: "return", view: "needs" }));
    expect(close).not.toHaveBeenCalled();
    act(() => receive({ t: "return", view: "projects" }));
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("shows nothing but a note in Classic, or for an address that is not a pop-out", async () => {
    load();
    prefs.patch({ ui: "classic" });
    let c = await show("#/pop/projects");
    expect(c).toHaveTextContent("Pages open in their own window only in the HQ preview");
    expect(c.querySelector(".hq-popwin")).toBeNull();
    cleanup();
    prefs.patch({ ui: "hq" });
    c = await show("#/pop/projects?x=1");
    expect(c).toHaveTextContent("Nothing to show in this window");
  });
});
