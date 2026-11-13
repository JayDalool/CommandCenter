// HQ on a phone and a tablet in a real browser. At 390px: no sidebar or tab strip, a tab bar at the bottom, a More
// sheet, Developer Mode still in the top bar, and no screen that scrolls sideways (HQ's pages and the Classic screens it
// shows). At iPad widths: the icons-only sidebar, Pop out, and no tab bar. Back works through the tab bar and the sheet.
import type { Page } from "@playwright/test";
import { test, expect, open, problems } from "./fixture";
import { LOAD, isBare } from "./routes";

test.use({ ui: "hq" });

const wide = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test("390px: every screen fits the width, with the tab bar and without the sidebar", async ({ page, watch }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const routes = [...LOAD.filter((r) => !isBare(r)), "approvals", "budgets", "messages", "revenue"];
  const sideways: string[] = [];
  for (const r of routes) {
    await open(page, r);
    if (!await wide(page)) sideways.push(r);
  }
  expect(sideways).toEqual([]);
  await expect(page.locator(".hq-side")).toBeHidden();
  await expect(page.locator(".hq-tabs")).toBeHidden();
  await expect(page.getByRole("navigation", { name: "Tab bar" })).toBeVisible();
  expect(await problems(page, watch)).toEqual([]);
});

test("390px: the tab bar and the More sheet move between pages, and Back returns", async ({ page, watch }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "dashboard");
  await expect(page.locator(".hq-top-right .hq-pop")).toBeHidden();
  const bar = page.getByRole("navigation", { name: "Tab bar" });
  await expect(bar.getByRole("link", { name: "Office" })).toHaveAttribute("aria-current", "page");
  // The bar sits at the bottom of the window, inside it.
  const box = (await bar.boundingBox())!;
  expect(Math.round(box.y + box.height)).toBe(844);
  // Developer Mode stays in the top bar, short: whether writes are allowed is never hidden. It still unlocks.
  const dev = page.locator(".hq-top-right").getByRole("button", { name: "Developer Mode locked. Unlock" });
  await expect(dev).toBeVisible();
  await expect(dev).toHaveText(/^Dev\s*○$/, { useInnerText: true });
  await dev.click();
  await expect(page.getByRole("dialog", { name: "Developer Unlock" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Developer Unlock" })).toHaveCount(0);

  await bar.getByRole("link", { name: /^Decisions/ }).click();
  await expect(page).toHaveURL(/#\/needs$/);
  await expect(page.locator(".hq-top h1")).toHaveText("Decisions");

  const more = bar.getByRole("button", { name: "More" });
  await more.click();
  const sheet = page.getByRole("dialog", { name: "More" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Done" })).toBeFocused();
  expect(await wide(page)).toBe(true);
  await sheet.getByRole("link", { name: /^Teams/ }).click();
  await expect(sheet).toHaveCount(0);
  await expect(page).toHaveURL(/#\/agents$/);
  await expect(more).toHaveClass(/is-current/);

  await page.goBack();
  await expect(page).toHaveURL(/#\/needs$/);
  await more.click();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(more).toBeFocused();
  expect(await problems(page, watch)).toEqual([]);
});

for (const [w, h] of [[820, 1180], [1024, 768]]) {
  test(`${w}px (iPad): icons-only sidebar, Pop out, no tab bar, nothing sideways`, async ({ page, watch }) => {
    await page.setViewportSize({ width: w, height: h });
    for (const r of ["dashboard", "needs", "agents", "projects", "tasks", "settings", "approvals", "budgets"]) {
      await open(page, r);
      expect(await wide(page), r).toBe(true);
    }
    await open(page, "dashboard");
    await expect(page.locator(".hq-side")).toBeVisible();
    await expect(page.locator(".hq-shell")).toHaveClass(/is-icons/);
    await expect(page.getByRole("button", { name: "Pop out" })).toBeVisible();
    await expect(page.locator(".hq-top-right .dev-dot")).toHaveText(/^Developer\s*○$/, { useInnerText: true });
    await expect(page.getByRole("navigation", { name: "Tab bar" })).toBeHidden();
    expect(await problems(page, watch)).toEqual([]);
  });
}
