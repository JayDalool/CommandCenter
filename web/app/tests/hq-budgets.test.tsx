// CC-064 (a): the weekly budget on HQ's Budgets page. One estimated-dollar amount, a slider per app that always adds up to
// 100 (by keyboard too), saving needs Developer Unlock, and it all works with the onboarding groundwork off (the shadow
// budgets answer 404). Every figure says estimate. Test data is made up.
import { act, cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { developer, setDevSession } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import type { BudgetWeek, BudgetWeekLine, UsageState } from "../src/api/types";
import { amountCents, centsText, evenShares, rebalance, shareCents } from "../src/hq/pages/budgetShares";
import { state, tasks } from "./helpers";

const APPS = [{ key: "samvision", name: "SamVision" }, { key: "gyst", name: "GYST" }, { key: "mfe", name: "MFE" }];
const line = (o: Partial<BudgetWeekLine>): BudgetWeekLine => ({ scope: "app", key: "samvision", name: "SamVision", share: 50,
  limitUsd: 50, limitTokens: null, spentUsd: 42.5, spentTokens: 0, pct: 85, level: 80, reached: 80, currency: "USD", estimate: true,
  weekKey: "2026-11-23", ...o });
const WEEK = (o: Partial<BudgetWeek> = {}): BudgetWeek => ({ enabled: true, currency: "USD", estimate: true,
  note: "Estimate, not your bill", stale: false, weekStart: 1795500000, weekEnd: 1796100000, weekKey: "2026-11-23", apps: APPS,
  defaultWeek: { weekday: 1, hour: 0, tz: "America/Winnipeg" },
  settings: { weekUsd: "100.00", weekTokens: null, shares: { samvision: 50, gyst: 30, mfe: 20 }, week: { weekday: 1, hour: 0, tz: "America/Winnipeg" } },
  meter: { lastReadAt: 1795500000, stale: false, staleAfterSeconds: 900 },
  lines: [line({ scope: "account", key: "*", name: "All apps", share: null, limitUsd: 100, spentUsd: 55, pct: 55, level: 50, reached: 50 }),
    line({}), line({ key: "gyst", name: "GYST", share: 30, limitUsd: 30, spentUsd: 3, pct: 10, level: 0, reached: 0 }),
    line({ key: "mfe", name: "MFE", share: 20, limitUsd: 20, spentUsd: 0, pct: 0, level: 0, reached: 0 })],
  changedAt: 1795400000, changedBy: "jay", ...o });
const NONE = (): BudgetWeek => ({ enabled: false, currency: "USD", estimate: true, note: "Estimate, not your bill", stale: false,
  weekStart: 1795500000, weekEnd: 1796100000, apps: APPS, defaultWeek: { weekday: 1, hour: 0, tz: "America/Winnipeg" }, lines: [],
  meter: { lastReadAt: null, stale: true, staleAfterSeconds: 900 } });
const USAGE = (budgetWeek: BudgetWeek): UsageState => ({ available: true, days: 30, pricesAsOf: "2026-10-01", note: "Estimated.",
  total: { replies: 1, input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 1, unpriced: 0 }, budgets: [], budgetWeek });

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-25T15:00:00Z") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}
async function show(week: BudgetWeek) {
  vi.spyOn(app.api, "usage").mockResolvedValue(USAGE(week));
  vi.spyOn(app.api, "budgets").mockRejectedValue(new ApiError(404, "not found"));      // the groundwork is off
  location.hash = "#/budgets";
  await loadHqFrame();
  const v = render(<App />);
  for (let i = 0; i < 4; i++) await act(async () => {});
  return v.container;
}
const panel = (c: HTMLElement) => within(c).getByRole("region", { name: "Weekly budget" });
const slider = (c: HTMLElement, name: string) => within(panel(c)).getByRole("slider", { name }) as HTMLInputElement;
const values = (c: HTMLElement) => APPS.map((a) => Number(slider(c, a.name).value));

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  developer.set({ active: false, expiresAt: null, error: null });
  prefs.patch({ ui: "hq", theme: "dark" });
});
afterEach(() => { cleanup(); setDevSession(null); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", theme: "dark" }); });

describe("the weekly budget's arithmetic", () => {
  it("reads dollars and cents exactly, and refuses anything else", () => {
    expect(amountCents("250")).toBe(25000);
    expect(amountCents("250.5")).toBe(25050);
    expect(amountCents(" 0.01 ")).toBe(1);
    for (const bad of ["", "0", "0.00", "-5", "1e3", "12.345", "$5", "abc", "1,000", "1000000000"]) expect(amountCents(bad), bad).toBeNull();
    expect(centsText(25050)).toBe("250.50");
    expect(centsText(5)).toBe("0.05");
  });
  it("rounds a share of the amount to the cent, half up, as the server does", () => {
    expect(shareCents(10001, 33)).toBe(3300);       // 33.0033
    expect(shareCents(50, 1)).toBe(1);              // 0.005 -> 0.01
    expect(shareCents(10000, 0)).toBe(0);
  });
  it("starts even and keeps the total at exactly 100 whichever slider moves", () => {
    expect(evenShares(["a", "b", "c"])).toEqual({ a: 34, b: 33, c: 33 });
    let s: Record<string, number> = { a: 50, b: 30, c: 20 };
    for (const [k, v] of [["a", 90], ["b", 7], ["c", 100], ["a", 0], ["b", 33], ["c", 1], ["a", 13]] as const) {
      s = rebalance(s, k, v);
      expect(Object.values(s).reduce((n, x) => n + x, 0), `${k}=${v}`).toBe(100);
      expect(s[k]).toBe(v);
      expect(Object.values(s).every((x) => Number.isInteger(x) && x >= 0)).toBe(true);
    }
    expect(rebalance({ a: 50, b: 30, c: 20 }, "a", 100)).toEqual({ a: 100, b: 0, c: 0 });
    expect(rebalance({ a: 100, b: 0, c: 0 }, "a", 40)).toEqual({ a: 40, b: 30, c: 30 });   // nothing to share in proportion: even
    expect(rebalance({ a: 100 }, "a", 30)).toEqual({ a: 100 });
  });
});

describe("Budgets: the weekly budget", () => {
  it("says no budget is set and nothing is held, with the groundwork off", async () => {
    load();
    const c = await show(NONE());
    const p = panel(c);
    expect(p).toHaveTextContent("Estimate · not your bill");
    expect(p).toHaveTextContent("No weekly budget is set, so there are no alerts");
    expect(p).toHaveTextContent("Nothing is held or stopped");
    expect(within(c).getByRole("region", { name: "Company, project and agent budgets" })).toHaveTextContent("Not enabled");
    expect(values(c)).toEqual([34, 33, 33]);                                       // an even start
    expect(within(p).getByRole("button", { name: "Save budget" })).toBeDisabled();  // no amount yet
  });

  it("shows each line's spend, share and level, all as estimates", async () => {
    load();
    const c = await show(WEEK());
    const p = panel(c);
    expect(p).toHaveTextContent("Estimate · not your bill");
    const rows = [...p.querySelectorAll<HTMLElement>(".hq-bud-line")].map((r) => r.textContent!.replace(/\s+/g, " "));
    expect(rows[0]).toContain("All apps");
    expect(rows[0]).toContain("$55.00 of $100");
    expect(rows[0]).toContain("55%");
    expect(rows[0]).toContain("Alert 50%");
    expect(rows[1]).toContain("SamVision");
    expect(rows[1]).toContain("50% share");
    expect(rows[1]).toContain("Alert 80%");
    expect(rows[2]).toContain("Within budget");
    expect(values(c)).toEqual([50, 30, 20]);
  });

  it("a stale meter says alerts wait, and no line claims a level", async () => {
    load();
    const w = WEEK({ stale: true, lines: WEEK().lines.map((l) => ({ ...l, level: 0 })) });
    const p = panel(await show(w));
    expect(p).toHaveTextContent("Meter not read in the last 15 minutes");
    expect(p.querySelectorAll(".hq-bud-line .hq-pill")[1]).toHaveTextContent("Meter not read");
  });

  it("the sliders add up to 100 with the keyboard, and the dollars follow", async () => {
    load();
    const c = await show(WEEK());
    const a = slider(c, "SamVision");
    expect(panel(c).querySelector(".hq-bud-total")).toHaveTextContent("Shares add up to 100%");
    a.focus();
    fireEvent.change(a, { target: { value: "60" } });                              // what ArrowRight x10 amounts to
    expect(values(c)).toEqual([60, 24, 16]);
    expect(values(c).reduce((n, x) => n + x, 0)).toBe(100);
    expect(panel(c)).toHaveTextContent("60% · about $60.00");                        // 60% of the saved 100.00
    expect(panel(c)).toHaveTextContent("Shares add up to 100%");
    fireEvent.change(slider(c, "GYST"), { target: { value: "100" } });
    expect(values(c)).toEqual([0, 100, 0]);
    expect(a).toHaveAttribute("aria-valuetext", "0 percent");
  });

  it("saving needs Developer Unlock: locked, the dialog opens and nothing is sent", async () => {
    load();
    const save = vi.spyOn(app.api, "saveBudgetWeek").mockResolvedValue(WEEK());
    const c = await show(WEEK());
    const p = panel(c);
    expect(p).toHaveTextContent("Saving needs Developer Unlock");
    fireEvent.change(within(p).getByLabelText("Weekly amount (US dollars, estimate)"), { target: { value: "120.50" } });
    fireEvent.click(within(p).getByRole("button", { name: "Save budget" }));
    await act(async () => {});
    expect(save).not.toHaveBeenCalled();
  });

  it("unlocked, it saves exactly the amount, the shares and the reset, and shows the answer", async () => {
    load();
    developer.set({ active: true, expiresAt: Date.now() + 3600_000, error: null });
    const saved = WEEK({ settings: { weekUsd: "120.50", weekTokens: null, shares: { samvision: 60, gyst: 24, mfe: 16 },
      week: { weekday: 0, hour: 17, tz: "America/Winnipeg" } }, changedAt: 1795500001 });
    const save = vi.spyOn(app.api, "saveBudgetWeek").mockResolvedValue(saved);
    const c = await show(WEEK());
    const p = panel(c);
    expect(p).not.toHaveTextContent("Saving needs Developer Unlock");
    expect(within(p).getByRole("button", { name: "Save budget" })).toBeDisabled();   // nothing changed yet
    fireEvent.change(within(p).getByLabelText("Weekly amount (US dollars, estimate)"), { target: { value: "120.50" } });
    fireEvent.change(within(p).getByLabelText("Week starts on"), { target: { value: "0" } });
    fireEvent.change(within(p).getByLabelText("At"), { target: { value: "17" } });
    fireEvent.change(slider(c, "SamVision"), { target: { value: "60" } });
    fireEvent.click(within(p).getByRole("button", { name: "Save budget" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({ weekUsd: "120.50", shares: { samvision: 60, gyst: 24, mfe: 16 },
      week: { weekday: 0, hour: 17, tz: "America/Winnipeg" } });
    await waitFor(() => expect(p).toHaveTextContent("Saved."));
    expect(values(c)).toEqual([60, 24, 16]);
  });

  it("a bad amount blocks the save, and a refusal from ccd is shown", async () => {
    load();
    developer.set({ active: true, expiresAt: Date.now() + 3600_000, error: null });
    const save = vi.spyOn(app.api, "saveBudgetWeek").mockRejectedValue(new ApiError(400, "shares must add up to 100, not 99"));
    const c = await show(WEEK());
    const p = panel(c);
    const amount = within(p).getByLabelText("Weekly amount (US dollars, estimate)");
    fireEvent.change(amount, { target: { value: "12.345" } });
    expect(p).toHaveTextContent("Enter dollars and cents");
    expect(within(p).getByRole("button", { name: "Save budget" })).toBeDisabled();
    fireEvent.change(amount, { target: { value: "99" } });
    fireEvent.click(within(p).getByRole("button", { name: "Save budget" }));
    await waitFor(() => expect(p).toHaveTextContent("shares must add up to 100, not 99"));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("an older ccd with no budgetWeek shows no weekly panel and the page still works", async () => {
    load();
    vi.spyOn(app.api, "usage").mockResolvedValue({ ...USAGE(WEEK()), budgetWeek: undefined });
    vi.spyOn(app.api, "budgets").mockRejectedValue(new ApiError(404, "not found"));
    location.hash = "#/budgets";
    await loadHqFrame();
    const v = render(<App />);
    for (let i = 0; i < 4; i++) await act(async () => {});
    expect(within(v.container).queryByRole("region", { name: "Weekly budget" })).toBeNull();
    expect(v.container.querySelector("#main .hq-budgets")).not.toBeNull();
  });
});
