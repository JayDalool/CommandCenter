// Work mode (Jay, 2026-11-15) in HQ: Settings › Operating profiles lists every project with an Off/On switch for ccd
// reminding its idle lead of the tickets it can move (GET and PUT /api/work-mode, ccd/workmode.py), and Engineering
// shows each ticket's due date. An older ccd has no work-mode route, and then the group is not shown.
import { act, cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { developer, setDevSession } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import { workHint } from "../src/hq/pages/Settings";
import type { Ticket, WorkModeProject, WorkModeState } from "../src/api/types";
import { state, tasks } from "./helpers";

const TZ = "America/Winnipeg";
// The unix time at which a clock in `tz` reads this wall time, from the machine's own zone data (never a fixed
// offset: Winnipeg's November 2026 offset differs between tz data versions).
function at(tz: string, year: number, month: number, day: number, hour: number, minute = 0): number {
  const want = Date.UTC(year, month - 1, day, hour, minute);
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric",
    day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date(want));
  const n = (type: string) => Number(parts.find((x) => x.type === type)?.value);
  return (2 * want - Date.UTC(n("year"), n("month") - 1, n("day"), n("hour"), n("minute"))) / 1000;
}

const off: WorkModeProject = { on: false, since: null, why: null, lastReminderAt: null, remindersToday: 0, restUntil: null,
  next: [], paused: false };
function wm(projects: Record<string, Partial<WorkModeProject>> = {}): WorkModeState {
  return {
    projects: Object.fromEntries(["samvision", "gyst", "mfe", "gauzemate", "commandcenter"]
      .map((k) => [k, { ...off, ...(k === "gauzemate" ? { paused: true } : {}), ...projects[k] }])),
    limits: { idleS: 180, gapS: 600, restAfter: 3, restS: 7200, dayMax: 36 },
  };
}

function load(extra: (t: Ticket[]) => Ticket[] = (t) => t) {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date(at(TZ, 2026, 11, 16, 10) * 1000) });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: extra(t.tickets), ticketsLoaded: true,
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
const group = (main: HTMLElement) => main.querySelector<HTMLElement>("#set-work-mode");
const row = (main: HTMLElement, name: string) => [...group(main)!.querySelectorAll<HTMLElement>(".hq-set-row")].find((r) => r.textContent!.startsWith(name))!;

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  developer.set({ active: false, expiresAt: null, error: null });
  prefs.patch({ ui: "hq", style: "professional" });
});
afterEach(() => { cleanup(); setDevSession(null); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional" }); });

describe("what each project's row says", () => {
  it("off, on, resting, and a reason ccd sends that the page does not know", () => {
    expect(workHint(off)).toBe("Off. The lead works when someone messages it.");
    expect(workHint({ ...off, paused: true })).toBe("Off. The project is paused.");
    expect(workHint({ ...off, on: true })).toBe("Waiting for the first check.");
    expect(workHint({ ...off, on: true, why: "lead working", next: ["CC-053", "CC-054"], remindersToday: 2 }))
      .toBe("The lead is working. Next: CC-053, CC-054. 2 reminders today.");
    expect(workHint({ ...off, on: true, why: "input line not empty or not recognised", next: ["CC-053"] }))
      .toBe("Held back: there is text in the lead's input box, and ccd never types over it. Next: CC-053.");
    expect(workHint({ ...off, on: true, why: "resting: no ticket moved", restUntil: at(TZ, 2026, 11, 16, 15, 40), remindersToday: 3 }, TZ,
      at(TZ, 2026, 11, 16, 13, 40))).toBe("Resting until 3:40 p.m.: no ticket moved after the last reminders. 3 reminders today.");
    expect(workHint({ ...off, on: true, why: "resting: no ticket moved", restUntil: at(TZ, 2026, 11, 17, 0, 30) }, TZ,
      at(TZ, 2026, 11, 16, 22, 30))).toBe("Resting until Tue, Nov 17, 12:30 a.m.: no ticket moved after the last reminders.");
    expect(workHint({ ...off, on: true, why: "something new" })).toBe("Something new.");
  });
});

describe("Settings › Operating profiles › Work mode", () => {
  it("is not there on an older ccd", async () => {
    vi.spyOn(app.api, "workMode").mockRejectedValue(new ApiError(404, "not found"));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(group(main)).toBeNull();
  });

  it("lists every project with its switch and what ccd last did", async () => {
    vi.spyOn(app.api, "workMode").mockResolvedValue(wm({
      commandcenter: { on: true, why: "reminded", next: ["CC-053"], remindersToday: 1 },
    }));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(within(group(main)!).getByRole("heading", { name: "Work mode" })).toBeInTheDocument();
    expect(within(row(main, "Command Center")).getByRole("button", { name: "On" })).toHaveAttribute("aria-pressed", "true");
    expect(row(main, "Command Center")).toHaveTextContent("The lead was reminded. Next: CC-053. 1 reminder today.");
    expect(within(row(main, "SamVision")).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
    expect(row(main, "SamVision")).toHaveTextContent("Off. The lead works when someone messages it.");
    expect(row(main, "GauzeMate")).toHaveTextContent("Off. The project is paused.");
    expect(group(main)).toHaveTextContent("at most every 10 minutes");
    expect(group(main)).toHaveTextContent("never merges or deploys and never types over a draft");
    expect(group(main)).toHaveTextContent("rests 2 hours after 3 reminders with no ticket moving, and sends at most 36 a day");
  });

  it("locked: a press asks for Developer Unlock and sends nothing", async () => {
    vi.spyOn(app.api, "workMode").mockResolvedValue(wm());
    const set = vi.spyOn(app.api, "setWorkMode");
    const asked = vi.fn();
    window.addEventListener("cc:dev-unlock", asked);
    try {
      load();
      const main = await show("#/settings?tab=profiles");
      expect(group(main)).toHaveTextContent("Changing it needs Developer Unlock.");
      fireEvent.click(within(row(main, "SamVision")).getByRole("button", { name: "On" }));
      await settle();
      expect(set).not.toHaveBeenCalled();
      expect(asked).toHaveBeenCalledTimes(1);
      expect(within(row(main, "SamVision")).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
    } finally { window.removeEventListener("cc:dev-unlock", asked); }
  });

  it("unlocked: one press switches a project on, and ccd's answer is shown; a refusal is said", async () => {
    vi.spyOn(app.api, "workMode").mockResolvedValue(wm());
    const set = vi.spyOn(app.api, "setWorkMode").mockResolvedValueOnce(wm({ samvision: { on: true, next: ["SV-082"] } }))
      .mockRejectedValueOnce(new ApiError(403, "Developer Unlock required: work mode is Jay's switch"));
    load();
    const main = await show("#/settings?tab=profiles");
    act(() => developer.set({ active: true, expiresAt: Date.now() / 1000 + 3600, error: null }));
    fireEvent.click(within(row(main, "SamVision")).getByRole("button", { name: "On" }));
    await waitFor(() => expect(within(row(main, "SamVision")).getByRole("button", { name: "On" })).toHaveAttribute("aria-pressed", "true"));
    expect(set.mock.calls).toEqual([["samvision", true]]);
    expect(row(main, "SamVision")).toHaveTextContent("Waiting for the first check. Next: SV-082.");
    fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "On" }));
    await settle();
    expect(within(group(main)!).getByRole("alert")).toHaveTextContent("Developer Unlock required");
    expect(within(row(main, "GYST")).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("Engineering › Due", () => {
  it("shows each open ticket's due date in Winnipeg time, and says when it is overdue", async () => {
    // Today (the 16th) at midnight is not late yet: only a day that has passed is.
    const due = at(TZ, 2026, 11, 18, 23, 59), late = at(TZ, 2026, 11, 15, 23, 59), today = at(TZ, 2026, 11, 16, 0, 0);
    load((all) => {
      const open = all.filter((t) => !["DONE", "DENIED", "CANCELLED"].includes(t.status) && !t.archived);
      return all.map((t) => t.key === open[0].key ? { ...t, dueAt: due } : t.key === open[1].key ? { ...t, dueAt: late }
        : t.key === open[2].key ? { ...t, dueAt: today } : { ...t, dueAt: null });
    });
    const main = await show("#/tasks");
    const page = main.querySelector<HTMLElement>(".hq-eng")!;
    expect(within(page).getByRole("columnheader", { name: "Due" })).toBeInTheDocument();
    const cells = [...page.querySelectorAll<HTMLElement>(".hq-table tbody td.c-due")];
    const texts = cells.map((c) => c.textContent);
    expect(texts).toContain("Nov 18");
    const overdue = cells.find((c) => c.textContent === "Overdue · Nov 15")!;
    expect(overdue).toHaveClass("t-bad");
    expect(overdue).toHaveAttribute("title", "Overdue since Sun, Nov 15");
    expect(cells.find((c) => c.textContent === "Nov 16")).not.toHaveClass("t-bad");
    expect(texts.filter((x) => x === "—").length).toBe(cells.length - 3);
  });
});
