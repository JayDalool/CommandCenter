// Activity (hq/pages/Activity.tsx) on the test fixture: Classic's rows and filters, grouped by day, older pages from the
// same endpoint, and alerts that link to Classic's Alerts screen, where they are acknowledged.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { buildActivity } from "../src/hq/data";
import type { CcdEvent } from "../src/api/types";
import { state, tasks } from "./helpers";

const T0 = new Date("2026-10-27T15:00:00Z").getTime() / 1000;
const ev = (seq: number, kind: string, text: string, at = T0 - seq * 60, extra: Partial<CcdEvent> = {}): CcdEvent =>
  ({ seq, at, kind, severity: "info", project: "samvision", ref: null, text, agentId: null, ...extra }) as CcdEvent;

function load(activity: CcdEvent[]) {
  vi.useFakeTimers({ toFake: ["Date"], now: T0 * 1000 });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta, activity });
}

async function show(hash = "#/activity") {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-activity")!;
}

const texts = (page: HTMLElement) => [...page.querySelectorAll(".hq-act-row .hq-act-text")].map((e) => e.textContent!.replace(/^.* · /, ""));

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("Activity", () => {
  const feed = [
    ev(1, "agent.state", "sv-056-impl started working"),
    ev(2, "pr.opened", "PR #94 opened"),
    ev(3, "action.focus", "focus click"),                                   // not meaningful: Classic hides it
    ev(4, "task.moved", "SV-056 moved to review", T0 - 2 * 86400, { ref: "SV-056" }),
  ];

  it("shows Classic's rows, newest first, grouped by day, with tasks linked", async () => {
    load(feed);
    const page = await show();
    const want = buildActivity(feed, app.store.get().tickets).map((r) => r.text);
    expect(texts(page)).toEqual(want);
    expect(texts(page)).not.toContain("focus click");
    expect(page.querySelectorAll(".hq-act-day")).toHaveLength(2);
    expect(within(page).getByRole("link", { name: "SV-056 moved to review" })).toHaveAttribute("href", "#/tasks/SV-056");
  });

  it("filters with Classic's categories", async () => {
    load(feed);
    const page = await show();
    fireEvent.click(within(page).getByRole("button", { name: /^Pull requests/ }));
    expect(texts(page)).toEqual(["PR #94 opened"]);
    expect(within(page).getByRole("button", { name: /^All \(3\)/ })).toBeInTheDocument();
  });

  it("loads older events from the same endpoint, below the oldest one loaded", async () => {
    load(feed);
    const spy = vi.spyOn(app.api, "activity").mockResolvedValue({ events: [ev(0, "ci.passed", "main checks passed", T0 - 3 * 86400)] } as never);
    const page = await show();
    await act(async () => { fireEvent.click(within(page).getByRole("button", { name: "Load older" })); });
    expect(spy).toHaveBeenCalledWith({ limit: 200, before: 1 });
    expect(texts(page)).toContain("main checks passed");
  });

  it("lists alerts with a link to Classic's Alerts screen, and has no acknowledge button", async () => {
    load(feed);
    const page = await show();
    const panel = within(page).getByRole("region", { name: /Alerts/ });
    const n = app.store.get().state!.alerts.length;
    expect(n).toBeGreaterThan(0);
    within(panel).getAllByRole("link").forEach((a) => expect(a).toHaveAttribute("href", "#/alerts"));
    expect(within(panel).queryByRole("button")).toBeNull();
  });
});
