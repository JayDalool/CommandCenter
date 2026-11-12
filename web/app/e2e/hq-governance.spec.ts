// Jay's menu and the pages behind it in a real browser: Approvals and Budgets read the server's own data and write
// nothing, Budgets says Not enabled while the server answers 404 for the shadow budgets (the switch is off), and
// Messages and Revenue say Not connected. No page scrolls sideways.
import { test, expect, open, problems } from "./fixture";

test.use({ ui: "hq" });

for (const [route, heading] of [["approvals", "Approvals"], ["budgets", "Budgets"], ["messages", "Messages"], ["revenue", "Revenue"]]) {
  test(`#/${route} opens clean`, async ({ page, watch }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, route);
    await expect(page.locator("#main .hq-page h2").first()).toHaveText(heading);
    if (route === "budgets") await expect(page.getByRole("region", { name: "Company, project and agent budgets" })).toContainText("Not enabled");
    if (route === "messages" || route === "revenue") await expect(page.locator("#main")).toContainText("Not connected");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await problems(page, watch)).toEqual([]);
  });
}

test("Jay's menu opens Budgets and switches the theme", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "dashboard");
  await page.getByRole("button", { name: "Jay's menu" }).click();
  const menu = page.getByRole("menu", { name: "Jay's menu" });
  await expect(menu.getByRole("menuitem", { name: /^Approvals/ })).toBeFocused();
  await menu.getByRole("menuitemradio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await menu.getByRole("menuitem", { name: "Budgets" }).click();
  await expect(page).toHaveURL(/#\/budgets$/);
  await expect(menu).toHaveCount(0);
  await expect(page.locator("#main .hq-budgets")).toBeVisible();
  expect(await problems(page, watch)).toEqual([]);
});
