// CC-064 (a): the weekly budget on Budgets at a desktop and a phone width. Its sliders always add up to 100, by keyboard
// too, and the page never scrolls sideways. ccd is the fixture; /api/usage is answered with made-up weekly lines.
import { test, expect, open, problems } from "./fixture";

test.use({ ui: "hq" });

const APPS = [{ key: "samvision", name: "SamVision" }, { key: "gyst", name: "GYST" }, { key: "mfe", name: "MFE" }];
const line = (key: string, name: string, share: number | null, limit: number, spent: number, level: number) =>
  ({ scope: key === "*" ? "account" : "app", key, name, share, limitUsd: limit, limitTokens: null, spentUsd: spent, spentTokens: 0,
    pct: Math.round(100 * spent / limit), level, reached: level, currency: "USD", estimate: true, weekKey: "2026-11-23" });
const BUDGET_WEEK = {
  enabled: true, currency: "USD", estimate: true, note: "Estimate, not your bill", stale: false, weekStart: 1795500000,
  weekEnd: 1796100000, weekKey: "2026-11-23", apps: APPS, defaultWeek: { weekday: 1, hour: 0, tz: "America/Winnipeg" },
  settings: { weekUsd: "100.00", weekTokens: null, shares: { samvision: 50, gyst: 30, mfe: 20 }, week: { weekday: 1, hour: 0, tz: "America/Winnipeg" } },
  meter: { lastReadAt: 1795500000, stale: false, staleAfterSeconds: 900 },
  lines: [line("*", "All apps", null, 100, 55, 50), line("samvision", "SamVision", 50, 50, 42.5, 80), line("gyst", "GYST", 30, 30, 3, 0),
    line("mfe", "MFE", 20, 20, 0, 0)],
  changedAt: 1795400000, changedBy: "jay",
};

for (const [name, width, height] of [["desktop", 1440, 900], ["phone", 390, 844]] as const) {
  test(`the weekly budget at ${width} px: sliders add up to 100 by keyboard, no sideways scroll`, async ({ page, watch }) => {
    await page.setViewportSize({ width, height });
    await page.route("**/api/usage*", (r) => r.fulfill({ json: { available: false, budgetWeek: BUDGET_WEEK } }));
    await open(page, "budgets");
    const panel = page.getByRole("region", { name: "Weekly budget" });
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("Estimate · not your bill");
    await expect(panel.getByRole("slider")).toHaveCount(3);
    const sum = async () => (await panel.getByRole("slider").evaluateAll((els) => els.map((e) => Number((e as HTMLInputElement).value)))).reduce((a, b) => a + b, 0);
    expect(await sum()).toBe(100);
    const first = panel.getByRole("slider", { name: "SamVision" });
    await first.focus();
    for (let i = 0; i < 7; i++) await page.keyboard.press("ArrowRight");
    await expect(first).toHaveValue("57");
    expect(await sum()).toBe(100);
    await page.keyboard.press("End");
    await expect(first).toHaveValue("100");
    expect(await sum()).toBe(100);
    await expect(panel.locator(".hq-bud-total")).toContainText("Shares add up to 100%");
    // Saving is behind Developer Unlock and nothing is written by this test.
    await expect(panel).toContainText("Saving needs Developer Unlock");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), name).toBe(true);
    expect(await problems(page, watch)).toEqual([]);
  });
}
