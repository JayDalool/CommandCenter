// The Classic/HQ switch end to end: Settings, the rail's Back to Classic, ?ui= links, reloads and pop-outs.
import { test, expect, open, problems, settle, ORIGIN } from "./fixture";

const hqOn = (page: import("@playwright/test").Page) => page.locator("html").getAttribute("data-ui");

test("Settings › Interface turns the HQ preview on, and Back to Classic turns it off", async ({ page, watch }) => {
  await open(page, "settings");
  expect(await hqOn(page)).toBeNull();
  const row = page.getByRole("group", { name: "Interface" });
  await row.getByRole("button", { name: "HQ preview" }).click();
  expect(await hqOn(page)).toBe("hq");
  await expect(page.locator(".hq-tag")).toContainText("HQ preview");

  await page.reload();
  await settle(page);
  expect(await hqOn(page), "kept after a reload").toBe("hq");

  await page.getByRole("button", { name: "Back to Classic" }).click();
  expect(await hqOn(page)).toBeNull();
  await expect(page.locator(".hq-tag")).toHaveCount(0);
  await expect(row.getByRole("button", { name: "Classic" })).toHaveAttribute("aria-pressed", "true");
  expect(await problems(page, watch)).toEqual([]);
});

test("?ui=hq and ?ui=classic switch, then leave the address", async ({ page, watch }) => {
  await page.goto(`${ORIGIN}/?ui=hq#/tasks`);
  await settle(page);
  expect(await hqOn(page)).toBe("hq");
  expect(page.url()).toBe(`${ORIGIN}/#/tasks`);

  await page.goto(`${ORIGIN}/?ui=classic#/dashboard`);
  await settle(page);
  expect(await hqOn(page)).toBeNull();
  expect(page.url()).toBe(`${ORIGIN}/#/dashboard`);
  await expect(page.locator(".hq-tag")).toHaveCount(0);

  await page.goto(`${ORIGIN}/?ui=nonsense#/dashboard`);
  await settle(page);
  expect(await hqOn(page), "an unknown value changes nothing").toBeNull();
  expect(page.url()).toBe(`${ORIGIN}/#/dashboard`);
  expect(await problems(page, watch)).toEqual([]);
});

test("a pop-out keeps the mode and shows no label", async ({ page, context, watch }) => {
  await page.goto(`${ORIGIN}/?ui=hq#/dashboard`);
  await settle(page);
  const pop = await context.newPage();
  await pop.goto(`${ORIGIN}/#/room`);
  await settle(pop);
  expect(await hqOn(pop)).toBe("hq");
  await expect(pop.locator(".hq-tag")).toHaveCount(0);
  expect(await problems(page, watch)).toEqual([]);
  expect(await problems(pop, watch)).toEqual([]);
});
