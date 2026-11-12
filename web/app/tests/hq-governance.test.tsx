// Jay's menu and the pages behind it (hq/frame/JayMenu.tsx, hq/pages/Approvals.tsx, Budgets.tsx, NotConnected.tsx) on
// the test fixture. Approvals and Budgets read the server's own data and change nothing; Messages and Revenue have no
// backend yet and say Not connected, with no sample data. Classic has none of these pages and says where they are.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { ApiError } from "../src/api/client";
import type { BudgetsState, UsageState } from "../src/api/types";
import { buildDecisions } from "../src/hq/data";
import { state, tasks } from "./helpers";

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}

async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  const v = render(<App />);
  for (let i = 0; i < 3; i++) await act(async () => {});
  return v.container;
}

const USAGE: UsageState = {
  available: true, days: 30, pricesAsOf: "2026-10-01", note: "Estimated.",
  total: { replies: 120, input: 1e6, output: 2e5, cacheRead: 0, cacheWrite: 0, costUsd: 41.5, unpriced: 0 },
  budgets: [{ project: "samvision", monthlyUsd: 50, monthlyTokens: null, spentUsd: 61.2, spentTokens: 0 },
    { project: "gyst", monthlyUsd: 40, monthlyTokens: null, spentUsd: 10, spentTokens: 0 }],
};
const line = (o: Partial<BudgetsState["lines"][number]>): BudgetsState["lines"][number] => ({
  scope: "project", key: "samvision", period: "month", limitUsd: 50, limitTokens: null, spentUsd: 49, spentTokens: 0,
  unpricedReplies: 0, unpricedUsdAtFallback: 0, assessedUsd: 49, alerts: [50, 80, 95], source: "measured", state: "alert",
  holdReason: null, pct: 98, threshold: 95, onCourseToHold: false, ...o });
const SHADOW: BudgetsState = {
  mode: "shadow", enforced: false, safetyKinds: [], wouldHold: [{ scope: "agent", key: "agent:nova" }],
  meter: { lastReadAt: null, stale: true, staleAfterSeconds: 900 }, prices: { asOf: "2026-10-01", ageDays: 26, maxAgeDays: 90 },
  dataAlerts: [{ kind: "unattributed-usage", detail: "usage tied to no project, counted toward the company budget" }],
  lines: [line({ scope: "company", key: "company", limitUsd: 300, assessedUsd: 90, pct: 30, state: "ok", threshold: null }),
    line({}), line({ scope: "agent", key: "agent:nova", period: "day", limitUsd: 5, assessedUsd: 6, pct: 120, state: "hold", holdReason: "limit" })],
};

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq", theme: "dark" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", theme: "dark" }); });

describe("Jay's menu", () => {
  it("replaces the theme button, and opens Approvals, Budgets, Settings, the theme and Classic", async () => {
    load();
    const c = await show("#/projects");
    expect(within(c).queryByRole("button", { name: "Toggle light and dark" })).toBeNull();
    const btn = within(c).getByRole("button", { name: "Jay's menu" });
    fireEvent.click(btn);
    const menu = within(c).getByRole("menu", { name: "Jay's menu" });
    const items = [...menu.querySelectorAll("[role^=menuitem]")].map((e) => e.textContent?.replace(/\s+/g, " ").trim());
    expect(items.map((t) => t?.replace(/\d+ waiting/, "").trim())).toEqual(["Approvals", "Budgets", "Settings6",
      "Connection and sign-out", "Dark", "Light", "Match system", "Back to Classic"]);
    expect(within(menu).getByRole("menuitem", { name: /^Approvals/ })).toHaveAttribute("href", "#/approvals");
    expect(within(menu).getByRole("menuitem", { name: /^Budgets/ })).toHaveAttribute("href", "#/budgets");
    expect(within(menu).getByRole("menuitem", { name: "Connection and sign-out" })).toHaveAttribute("href", "#/settings?tab=connection");
    expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: /^Approvals/ }));

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Budgets" }));
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Back to Classic" }));

    expect(within(menu).getByRole("menuitemradio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(menu).getByRole("menuitemradio", { name: "Light" }));
    expect(prefs.get().theme).toBe("light");
    expect(within(menu).getByRole("menuitemradio", { name: "Light" })).toHaveAttribute("aria-checked", "true");

    fireEvent.keyDown(menu, { key: "Escape" });
    expect(within(c).queryByRole("menu", { name: "Jay's menu" })).toBeNull();
    expect(document.activeElement).toBe(btn);
  });

  it("says how many approvals wait, and Back to Classic switches the interface", async () => {
    load();
    const n = buildDecisions(app.store.get()).summary.approvals;
    expect(n).toBeGreaterThan(0);
    const c = await show("#/projects");
    const btn = within(c).getByRole("button", { name: "Jay's menu" });
    fireEvent.click(btn);
    expect(within(c).getByRole("menuitem", { name: /^Approvals/ })).toHaveTextContent(`${n} waiting`);
    act(() => { fireEvent.click(within(c).getByRole("menuitem", { name: "Back to Classic" })); });
    expect(prefs.get().ui).toBe("classic");
  });
});

describe("Approvals", () => {
  it("lists only the merges and deploys waiting for Jay, and approves nothing itself", async () => {
    load();
    vi.spyOn(app.api, "inbox").mockReturnValue(new Promise(() => {}));
    const want = buildDecisions(app.store.get()).items.filter((d) => d.kind === "Approval");
    const c = await show("#/approvals");
    const page = c.querySelector<HTMLElement>("#main > .hq-approvals")!;
    expect(page).not.toBeNull();
    const rows = [...page.querySelectorAll(".hq-dec")];
    expect(rows).toHaveLength(want.length);
    for (const r of rows) expect(r.querySelector(".hq-pill")?.textContent).toMatch(/^(Merge|Deploy)$/);
    if (!want.length) expect(page).toHaveTextContent("No merge or deploy is waiting for you.");
    expect(within(page).getByRole("region", { name: "Agent approval requests" })).toHaveTextContent("Not enabled");
    // Links to where Jay acts, never a button that approves, merges or deploys.
    expect(within(page).queryAllByRole("button")).toHaveLength(0);
  });
});

describe("Budgets", () => {
  it("shows the project limits from usage, and says Not enabled while the shadow budgets are off", async () => {
    load();
    vi.spyOn(app.api, "usage").mockResolvedValue(USAGE);
    const budgets = vi.spyOn(app.api, "budgets").mockRejectedValue(new ApiError(404, "not found"));
    const c = await show("#/budgets");
    const page = c.querySelector<HTMLElement>("#main > .hq-budgets")!;
    expect(budgets).toHaveBeenCalled();
    expect(page).toHaveTextContent("$41.50");
    const limits = within(page).getByRole("region", { name: /Project limits this month/ });
    const rows = [...limits.querySelectorAll(".hq-bud-line")];
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(/\$61\.20 of \$50\.00 · over/);
    expect(rows[1]).toHaveTextContent("$10.00 of $40.00");
    const shadow = within(page).getByRole("region", { name: "Company, project and agent budgets" });
    expect(shadow).toHaveTextContent("Not enabled");
    expect(shadow.querySelectorAll(".hq-bud-line")).toHaveLength(0);
    expect(within(page).getByText("Over a limit").parentElement).toHaveTextContent("1");
  });

  it("shows the shadow budgets as shadow, with what would hold and a stale meter", async () => {
    load();
    vi.spyOn(app.api, "usage").mockResolvedValue(USAGE);
    vi.spyOn(app.api, "budgets").mockResolvedValue(SHADOW);
    const c = await show("#/budgets");
    const shadow = within(c).getByRole("region", { name: "Company, project and agent budgets" });
    expect(shadow).toHaveTextContent("Shadow: nothing is held");
    const lines = [...shadow.querySelectorAll(".hq-bud-line")];
    expect(lines.map((l) => l.querySelector(".hq-pill")?.textContent)).toEqual(["Within limit", "Alert 95%", "Would hold"]);
    expect(lines[0]).toHaveTextContent("Whole company");
    expect(lines[2]).toHaveTextContent(/agent:nova.*Today/);
    expect(shadow).toHaveTextContent(/spend is Unknown/);
    expect(shadow).toHaveTextContent("unattributed usage");
    expect(within(c).getByText("Shadow budgets").parentElement).toHaveTextContent("1 line would hold");
  });

  it("keeps the last shadow reading when a later read fails, and says so", async () => {
    load();
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], now: new Date("2026-10-27T15:00:00Z") });
    vi.spyOn(app.api, "usage").mockResolvedValue(USAGE);
    vi.spyOn(app.api, "budgets").mockResolvedValueOnce(SHADOW).mockRejectedValueOnce(new ApiError(0, "ccd unreachable"));
    const c = await show("#/budgets");
    const shadow = within(c).getByRole("region", { name: "Company, project and agent budgets" });
    expect(shadow.querySelectorAll(".hq-bud-line")).toHaveLength(3);
    await act(async () => { vi.advanceTimersByTime(60_000); });
    await act(async () => {});
    expect(shadow.querySelectorAll(".hq-bud-line")).toHaveLength(3);
    expect(shadow).toHaveTextContent("Could not re-read the shadow budgets (ccd unreachable). Showing the last reading.");
  });

  it("says when it could not read the shadow budgets, without calling them off", async () => {
    load();
    vi.spyOn(app.api, "usage").mockResolvedValue(USAGE);
    vi.spyOn(app.api, "budgets").mockRejectedValue(new ApiError(500, "boom"));
    const c = await show("#/budgets");
    const shadow = within(c).getByRole("region", { name: "Company, project and agent budgets" });
    expect(shadow).toHaveTextContent("Could not read the shadow budgets: boom");
    expect(shadow).not.toHaveTextContent("Not enabled");
  });
});

describe("Messages and Revenue", () => {
  it.each([["#/messages", "Messages is not connected", "#/needs"], ["#/revenue", "Revenue is not connected", "#/budgets"]])(
    "%s says Not connected, shows no sample data, and points to where to go", async (hash, title, to) => {
      load();
      const c = await show(hash);
      const panel = within(c).getByRole("region", { name: title });
      expect(panel).toHaveTextContent("Not connected");
      expect(panel.querySelector(`a[href="${to}"]`)).not.toBeNull();
      expect(c.querySelector("#main")!.textContent).not.toMatch(/\$\d|Demo|demo/);
    });

  it("Messages and Revenue sit in the sidebar", async () => {
    load();
    const c = await show("#/dashboard");
    const nav = within(c).getByRole("navigation", { name: "Screens" });
    expect(within(nav).getByRole("link", { name: "Messages" })).toHaveAttribute("href", "#/messages");
    expect(within(nav).getByRole("link", { name: "Revenue" })).toHaveAttribute("href", "#/revenue");
  });
});

describe("Classic", () => {
  it.each(["approvals", "budgets", "messages", "revenue"])("#/%s says the page is in the HQ preview", async (route) => {
    load();
    prefs.patch({ ui: "classic" });
    const c = await show(`#/${route}`);
    expect(c.querySelector(".hq-page")).toBeNull();
    expect(c.querySelector("#main")).toHaveTextContent(/is in the HQ preview/);
  });
});
