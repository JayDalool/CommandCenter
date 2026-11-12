// The Classic/HQ switch end to end: Settings, the HQ sidebar's Back to Classic, ?ui= links, reloads, other windows,
// pop-outs, and where the label sits.
import type { Page } from "@playwright/test";
import { test, expect, open, problems, settle, ORIGIN } from "./fixture";

const hqOn = (page: Page) => page.locator("html").getAttribute("data-ui");

test("Settings › Interface turns the HQ preview on, and Back to Classic turns it off", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1600, height: 900 });   // the HQ sidebar with its labels, so the label reads in full
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

  await page.goto(`${ORIGIN}/?ui=hq#/dashboard`);
  await page.goto(`${ORIGIN}/?ui=nonsense#/dashboard`);
  await settle(page);
  expect(await hqOn(page), "nor from the HQ preview").toBe("hq");
  expect(await problems(page, watch)).toEqual([]);
});

test("another open window follows the switch, and does not write its old choice back", async ({ page, context, watch }) => {
  await page.setViewportSize({ width: 1600, height: 900 });   // wide enough for the HQ sidebar's own toggle
  await open(page, "dashboard");
  const other = await context.newPage();
  await other.goto(`${ORIGIN}/?ui=hq#/tasks`);
  await settle(other);
  await expect(page.locator("html"), "the first window follows").toHaveAttribute("data-ui", "hq");

  // A routine preference in the first window must not put Classic back.
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await other.reload();
  await settle(other);
  expect(await hqOn(other)).toBe("hq");

  // Back to Classic in one window holds in the other.
  await page.getByRole("button", { name: "Expand navigation" }).click();
  await other.getByRole("button", { name: "Back to Classic" }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-ui", /.*/);
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await other.reload();
  await settle(other);
  expect(await hqOn(other)).toBeNull();
  expect(await problems(page, watch)).toEqual([]);
  expect(await problems(other, watch)).toEqual([]);
});

test("Back to Classic from the keyboard leaves focus in the navigation", async ({ page, watch }) => {
  await page.goto(`${ORIGIN}/?ui=hq#/tasks`);
  await settle(page);
  await page.getByRole("button", { name: "Back to Classic" }).focus();
  await page.keyboard.press("Enter");
  expect(await hqOn(page)).toBeNull();
  // The HQ sidebar goes with HQ: focus lands at the foot of Classic's rail once it is drawn.
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest(".rail .rail-foot"))).toBe(true);
  expect(await problems(page, watch)).toEqual([]);
});

/** Where the label is, and whether it covers anything: it must sit between the sidebar's links and its foot, inside the
 *  sidebar, and every control around it must still be the one a click lands on. */
const placement = (page: Page) => page.evaluate(() => {
  const box = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
  const hits = (el: Element) => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); };
  const tag = document.querySelector<HTMLElement>(".hq-tag")!, rail = box(".hq-side"), t = tag.getBoundingClientRect();
  const controls = [...document.querySelectorAll(".hq-side .hq-nav a, .hq-side .hq-side-foot button, .hq-tag button")];
  // A window up to 1440px wide has an icons-only sidebar and no toggle at its foot.
  const foot = document.querySelector(".hq-side .hq-side-foot")?.getBoundingClientRect() ?? null;
  return {
    visible: t.width > 0 && t.height > 0,
    inRail: t.left >= rail.left && t.right <= rail.right + 0.5 && t.top >= rail.top && t.bottom <= rail.bottom,
    belowScreens: t.top >= box(".hq-side .hq-nav-low").bottom,
    aboveFoot: t.bottom <= (foot ? foot.top : rail.bottom) + 0.5,
    footInRail: (foot ? foot.bottom : t.bottom) <= rail.bottom + 0.5,
    fits: tag.scrollWidth <= tag.clientWidth,
    covered: controls.filter((el) => !hits(el)).map((el) => el.textContent || el.getAttribute("aria-label")),
  };
});

for (const [w, h, mini] of [[1600, 900, false], [1366, 768, false], [1600, 900, true], [1100, 500, false]] as const) {
  test(`the label sits at the foot of the sidebar and covers nothing (${w}x${h}${mini ? ", collapsed" : ""})`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`${ORIGIN}/?ui=hq#/dashboard`);
    await settle(page);
    if (mini) { await page.getByRole("button", { name: "Collapse navigation" }).click(); await settle(page); }
    expect(await placement(page)).toEqual({ visible: true, inRail: true, belowScreens: true, aboveFoot: true, footInRail: true,
      fits: true, covered: [] });
  });
}

test("a window too short for the label hides it, and the sidebar still fits", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 440 });
  await page.goto(`${ORIGIN}/?ui=hq#/dashboard`);
  await settle(page);
  await expect(page.locator(".hq-tag")).toBeHidden();
  const fits = await page.evaluate(() => document.querySelector(".hq-side .hq-nav-low")!.getBoundingClientRect().bottom
    <= document.querySelector(".hq-side")!.getBoundingClientRect().bottom + 0.5);
  expect(fits).toBe(true);
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
