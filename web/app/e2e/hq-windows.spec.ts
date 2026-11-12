// HQ pop-out windows in a real browser: Pop out opens the page in its own window at #/pop/<view> (no token, no
// parameters), the main window shows where it went, Return here closes it, and closing the window by hand brings the
// page back. Every window is watched like the first page (fixture.ts): no errors, no writes, no token in a URL.
import { test, expect, open, problems, ORIGIN } from "./fixture";

test.use({ ui: "hq" });

const POP = `${ORIGIN}/#/pop/projects`;
const clean = async (page: Parameters<typeof problems>[0], watch: Parameters<typeof problems>[1]) =>
  (await problems(page, watch)).filter((p) => p !== `opened a window: ${POP}`);

test("Company pops out to its own window and comes back with Return here", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await open(page, "projects");
  await page.getByRole("button", { name: "Pop out" }).click();
  const [pop] = await Promise.all([page.waitForEvent("popup"), page.getByRole("menuitem", { name: /^New window/ }).click()]);
  await pop.waitForLoadState("networkidle");
  expect(pop.url()).toBe(POP);
  await expect(pop.locator(".hq-popwin .hq-topology")).toBeVisible();
  await expect(pop.locator(".hq-side")).toHaveCount(0);
  expect(await pop.title()).toBe("Company · Command Center");

  const placeholder = page.getByRole("region", { name: "Company is open in its own window" });
  await expect(placeholder).toBeVisible();
  await expect(page.locator("#main .hq-topology")).toHaveCount(0);
  await expect(page.locator(".hq-tab.is-out")).toContainText("Company");

  await Promise.all([pop.waitForEvent("close"), placeholder.getByRole("button", { name: "Return here" }).click()]);
  await expect(page.locator("#main .hq-topology")).toBeVisible();
  expect(watch.popups).toEqual([POP]);
  expect(await clean(page, watch)).toEqual([]);
});

test("closing the pop-out by hand brings the page back to the main window", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await open(page, "projects");
  await page.getByRole("button", { name: "Pop out" }).click();
  const [pop] = await Promise.all([page.waitForEvent("popup"), page.getByRole("menuitem", { name: /^New window/ }).click()]);
  await expect(pop.locator(".hq-popwin .hq-topology")).toBeVisible();
  await expect(page.getByRole("region", { name: "Company is open in its own window" })).toBeVisible();
  await pop.close({ runBeforeUnload: true });
  await expect(page.locator("#main .hq-topology")).toBeVisible();
  expect(await clean(page, watch)).toEqual([]);
});

test("a link in the pop-out opens in the main window", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await open(page, "projects");
  await page.getByRole("button", { name: "Pop out" }).click();
  const [pop] = await Promise.all([page.waitForEvent("popup"), page.getByRole("menuitem", { name: /^New window/ }).click()]);
  await pop.locator('.hq-popwin [data-node="root"]').waitFor();
  await pop.getByRole("link", { name: "Decisions" }).click();
  await expect(page).toHaveURL(`${ORIGIN}/#/needs`);
  expect(pop.url()).toBe(POP);
  expect(await clean(page, watch)).toEqual([]);
});

// The pop-out's own address is #/pop/tasks: Engineering shows the list (no task "tasks", no request for it), and a
// row opens its task in the main window while the pop-out stays where it is.
test("Engineering pops out as the list, and a row opens its task in the main window", async ({ page, watch }) => {
  const ENG = `${ORIGIN}/#/pop/tasks`;
  await page.setViewportSize({ width: 1600, height: 900 });
  await open(page, "tasks");
  await page.getByRole("button", { name: "Pop out" }).click();
  const [pop] = await Promise.all([page.waitForEvent("popup"), page.getByRole("menuitem", { name: /^New window/ }).click()]);
  const row = pop.locator(".hq-popwin .hq-eng tbody tr").first();
  await row.waitFor();
  await expect(pop.locator(".hq-eng-detail")).toHaveCount(0);
  const key = (await row.locator(".c-key code").textContent())!;
  await row.locator(".c-title").click();
  await expect(page).toHaveURL(`${ORIGIN}/#/tasks/${key}`);
  expect(pop.url()).toBe(ENG);
  await expect(pop.locator(".hq-eng-detail")).toHaveCount(0);
  expect((await problems(page, watch)).filter((p) => p !== `opened a window: ${ENG}`)).toEqual([]);
});
