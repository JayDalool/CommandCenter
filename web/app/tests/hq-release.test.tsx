// Live or not live, and the weekly release window (hq/release.tsx, Settings › Operating profiles; ccd's release
// store, flow contract §5). ccd says which projects are live and when live projects release; the page shows a
// label beside each project and lets Jay change either with Developer Unlock. An older ccd has no such route, and
// then nothing about it is shown.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { developer } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import { clock, dayText, refreshRelease, release, resetRelease, windowText } from "../src/hq/release";
import type { ReleaseState } from "../src/api/types";
import { ev, state, tasks } from "./helpers";

// Wednesday 18 November 2026, 22:00 in Winnipeg (UTC-6 in November) is 04:00 UTC on the 19th.
const NEXT = Date.UTC(2026, 10, 19, 4, 0) / 1000;
const CUTOFF = Date.UTC(2026, 10, 18, 18, 0) / 1000;
const rel = (live: string[] = ["samvision"], window: Partial<ReleaseState["window"]> = {}): ReleaseState => ({
  window: { weekday: 3, time: "22:00", tz: "America/Winnipeg", next: NEXT, hours: 2, ...window }, cutoff: CUTOFF,
  projects: Object.fromEntries(["samvision", "gyst", "mfe", "gauzemate", "commandcenter"].map((k) => [k, { live: live.includes(k) }])),
});

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-14T09:30:00") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}
const settle = async () => { for (let i = 0; i < 5; i++) await act(async () => {}); };
async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  await settle();
  return document.querySelector<HTMLElement>("#main")!;
}
const tags = (el: ParentNode) => [...el.querySelectorAll<HTMLElement>(".hq-live")].map((t) => t.textContent);
const card = (main: HTMLElement, name: string) => [...main.querySelectorAll<HTMLElement>("a.hq-proj")].find((a) => a.textContent!.includes(name))!;

beforeEach(() => {
  resetRelease();
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  developer.set({ active: false, expiresAt: null, error: null });
  prefs.patch({ ui: "hq", style: "professional" });
});
afterEach(() => { cleanup(); resetRelease(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional" }); });

describe("the words", () => {
  it("reads a 24-hour time as Jay says it", () => {
    expect(clock("22:00")).toBe("10 p.m.");
    expect(clock("09:30")).toBe("9:30 a.m.");
    expect(clock("00:00")).toBe("12 a.m.");
    expect(clock("12:05")).toBe("12:05 p.m.");
    expect(clock("25:00")).toBe("25:00");          // not a time: shown as ccd sent it
    expect(clock("soon")).toBe("soon");
  });

  it("names the window and the day in the window's own zone", () => {
    expect(windowText(rel().window)).toBe("Wednesday 10 p.m. Central");
    expect(windowText({ weekday: 5, time: "06:15", tz: "Europe/Paris", next: 0 })).toBe("Friday 6:15 a.m. Europe/Paris");
    expect(dayText(NEXT, "America/Winnipeg")).toBe("Wed, Nov 18");   // the 19th in UTC, still Wednesday in Winnipeg
    expect(dayText(NEXT, "Not/AZone")).toMatch(/2026/);              // an unknown zone still gives a date
  });
});

describe("reading ccd's release state", () => {
  it("an older ccd (404) is not asked again, and shows nothing", async () => {
    const get = vi.spyOn(app.api, "release").mockRejectedValue(new ApiError(404, "not found"));
    load();
    const main = await show("#/dashboard");
    expect(release.get().state).toBe("none");
    expect(tags(main)).toEqual([]);
    act(() => app.store.set((d) => ({ ...d, activity: [ev(900, "release.live"), ...d.activity] })));
    await settle();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("a failed first read is tried again by the next screen; a failed refresh keeps what is showing", async () => {
    const get = vi.spyOn(app.api, "release").mockRejectedValueOnce(new ApiError(0, "ccd unreachable")).mockResolvedValue(rel());
    await refreshRelease();
    expect(release.get()).toMatchObject({ state: "error", error: "ccd unreachable", data: null });
    load();
    const main = await show("#/dashboard");
    expect(release.get().state).toBe("ok");
    expect(tags(card(main, "SamVision"))).toEqual(["Live"]);

    get.mockRejectedValueOnce(new ApiError(500, "boom"));
    await act(async () => { await refreshRelease(); });
    expect(release.get().state).toBe("ok");
    expect(tags(card(main, "SamVision"))).toEqual(["Live"]);
  });

  it("reads again when ccd says the switch or the window changed", async () => {
    const get = vi.spyOn(app.api, "release").mockResolvedValue(rel([]));
    load();
    const main = await show("#/dashboard");
    expect(tags(card(main, "GYST"))).toEqual(["Not live"]);
    get.mockResolvedValue(rel(["gyst"]));
    act(() => app.store.set((d) => ({ ...d, activity: [ev(901, "release.live", { project: "gyst" }), ...d.activity] })));
    await settle();
    expect(get).toHaveBeenCalledTimes(2);
    expect(tags(card(main, "GYST"))).toEqual(["Live"]);
    act(() => app.store.set((d) => ({ ...d, activity: [ev(902, "task.updated"), ...d.activity] })));   // any other event: no read
    await settle();
    expect(get).toHaveBeenCalledTimes(2);
  });
});

describe("My Office", () => {
  it("labels each project Live or Not live, and says when a live one releases", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel(["samvision"]));
    load();
    const main = await show("#/dashboard");
    expect(tags(card(main, "SamVision"))).toEqual(["Live"]);
    expect(tags(card(main, "GauzeMate"))).toEqual(["Not live"]);
    const live = card(main, "SamVision").querySelector<HTMLElement>(".hq-live")!;
    expect(live.title).toBe("Live. Changes go out together in the weekly release: Wednesday 10 p.m. Central. Next: Wed, Nov 18.");
    expect(card(main, "GauzeMate").querySelector<HTMLElement>(".hq-live")!.title).toMatch(/^Not live\. No release window/);
  });

  it("shows no label for a project ccd does not list", async () => {
    const r = rel(["samvision"]);
    delete r.projects.mfe;
    vi.spyOn(app.api, "release").mockResolvedValue(r);
    load();
    const main = await show("#/dashboard");
    expect(tags(card(main, "MFE"))).toEqual([]);
    expect(tags(card(main, "SamVision"))).toEqual(["Live"]);
  });
});

describe("Settings › Operating profiles", () => {
  const group = (main: HTMLElement) => main.querySelector<HTMLElement>("#set-release");
  const row = (main: HTMLElement, name: string) => [...group(main)!.querySelectorAll<HTMLElement>(".hq-set-row")].find((r) => r.textContent!.startsWith(name))!;
  const unlock = () => act(() => developer.set({ active: true, expiresAt: Date.now() / 1000 + 3600, error: null }));

  it("is not there on an older ccd", async () => {
    vi.spyOn(app.api, "release").mockRejectedValue(new ApiError(404, "not found"));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(group(main)).toBeNull();
  });

  it("lists every project with its switch, and the window in words", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel(["samvision"]));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(within(group(main)!).getByRole("heading", { name: "Live projects and release day" })).toBeInTheDocument();
    expect(within(row(main, "SamVision")).getByRole("button", { name: "Live" })).toHaveAttribute("aria-pressed", "true");
    expect(within(row(main, "GYST")).getByRole("button", { name: "Not live" })).toHaveAttribute("aria-pressed", "true");
    expect(row(main, "SamVision")).toHaveTextContent("Changes wait for the weekly release.");
    // A project with tickets and no entry in ccd's projects config still shows its name, not its key.
    expect(row(main, "Command Center")).toHaveTextContent("Changes can go out as soon as they are merged.");
    const day = row(main, "Release day");
    expect(day).toHaveTextContent("Wednesday 10 p.m. Central.");
    expect(within(day).getByRole("button", { name: "Wed" })).toHaveAttribute("aria-pressed", "true");
    const time = row(main, "Release time");
    expect(time).toHaveTextContent("Next release: 10 p.m. on Wed, Nov 18. A change merged by noon on Wed, Nov 18 is in it.");
    expect(within(time).getByLabelText("Release time")).toHaveValue("22:00");
  });

  it("after noon on release day, says the cut-off has passed", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel(["samvision"]));
    load();
    vi.setSystemTime(new Date((CUTOFF + 3600) * 1000));
    const main = await show("#/settings?tab=profiles");
    expect(row(main, "Release time")).toHaveTextContent(
      "Next release: 10 p.m. on Wed, Nov 18. The noon cut-off on Wed, Nov 18 has passed: a change merged now waits for the release after it.");
  });

  it("locked: a press asks for Developer Unlock and sends nothing", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel([]));
    const setLive = vi.spyOn(app.api, "setLive");
    const asked = vi.fn();
    window.addEventListener("cc:dev-unlock", asked);
    try {
      load();
      const main = await show("#/settings?tab=profiles");
      expect(group(main)).toHaveTextContent("Changing these needs Developer Unlock.");
      fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "Live" }));
      await settle();
      expect(setLive).not.toHaveBeenCalled();
      expect(asked).toHaveBeenCalledTimes(1);
      expect(within(row(main, "GYST")).getByRole("button", { name: "Not live" })).toHaveAttribute("aria-pressed", "true");
    } finally { window.removeEventListener("cc:dev-unlock", asked); }
  });

  it("unlocked: makes a project live with one press, and shows ccd's answer everywhere", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel([]));
    const setLive = vi.spyOn(app.api, "setLive").mockResolvedValue(rel(["gyst"]));
    load();
    const main = await show("#/settings?tab=profiles");
    unlock();
    fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "Not live" }));   // already so: nothing sent
    fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "Live" }));
    await settle();
    expect(setLive).toHaveBeenCalledTimes(1);
    expect(setLive).toHaveBeenCalledWith("gyst", true);
    expect(within(row(main, "GYST")).getByRole("button", { name: "Live" })).toHaveAttribute("aria-pressed", "true");
    expect(release.get().data!.projects.gyst.live).toBe(true);
  });

  it("a refusal is shown in ccd's words and nothing changes", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel([]));
    vi.spyOn(app.api, "setLive").mockRejectedValue(new ApiError(403, "only Jay can change the release settings"));
    load();
    const main = await show("#/settings?tab=profiles");
    unlock();
    fireEvent.click(within(row(main, "MFE")).getByRole("button", { name: "Live" }));
    await settle();
    expect(within(group(main)!).getByRole("alert")).toHaveTextContent("only Jay can change the release settings");
    expect(within(row(main, "MFE")).getByRole("button", { name: "Not live" })).toHaveAttribute("aria-pressed", "true");
  });

  it("changes the release day and time, each keeping the other", async () => {
    vi.spyOn(app.api, "release").mockResolvedValue(rel());
    const setWindow = vi.spyOn(app.api, "setReleaseWindow")
      .mockResolvedValueOnce(rel(["samvision"], { weekday: 4 }))
      .mockResolvedValueOnce(rel(["samvision"], { weekday: 4, time: "21:30" }));
    load();
    const main = await show("#/settings?tab=profiles");
    unlock();
    fireEvent.click(within(row(main, "Release day")).getByRole("button", { name: "Thu" }));
    await settle();
    expect(setWindow).toHaveBeenLastCalledWith(4, "22:00");
    expect(row(main, "Release day")).toHaveTextContent("Thursday 10 p.m. Central");
    const time = within(row(main, "Release time")).getByLabelText("Release time");
    fireEvent.change(time, { target: { value: "21:30" } });
    fireEvent.blur(time);
    await settle();
    expect(setWindow).toHaveBeenLastCalledWith(4, "21:30");
    expect(row(main, "Release day")).toHaveTextContent("Thursday 9:30 p.m. Central");
  });
});
