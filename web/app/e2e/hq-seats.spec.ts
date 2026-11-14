// Teams › Seats in a real browser: each project's seats, the tickets in flight with their row of stages, and one
// ticket opened in place. Once on the fixture as it is (a ccd from before the nine-stage flow) and once as a ccd that
// runs it (e2e/flow.ts). The page only looks: nothing is written.
import type { Locator, Page } from "@playwright/test";
import { test, expect, open, problems } from "./fixture";
import { serveFlow } from "./flow";

test.use({ ui: "hq" });

const wide = () => document.documentElement.scrollWidth <= window.innerWidth;
const box = async (l: Locator) => (await l.boundingBox())!;
const team = (page: Page, name: string) => page.getByRole("region", { name: new RegExp(`^${name}`) });
/** Every ticket row keeps its parts inside itself, at any width. */
const rowsFit = (page: Page) => page.locator("#main .hq-fl-row").evaluateAll((rows) => rows.every((row) => {
  const c = row.getBoundingClientRect();
  return [...row.children].every((el) => { const b = el.getBoundingClientRect(); return b.left >= c.left - 0.5 && b.right <= c.right + 0.5; });
}));

test("before the flow: five seats and seven stages per project, on a desktop and a phone; a ticket opens in place", async ({ page, watch }) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "agents");
    await expect(page.getByRole("group", { name: "View" }).getByRole("button", { name: "Seats" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText(/does not run the nine-stage flow yet/)).toBeVisible();
    const sv = team(page, "SamVision");
    const seats = sv.getByRole("list", { name: "SamVision seats" }).getByRole("listitem");
    await expect(seats).toHaveCount(5);
    await expect(seats.first()).toContainText("Lead");
    await expect(seats.first().getByRole("link", { name: "samvision" })).toBeVisible();
    await expect(seats.nth(2)).toHaveText("DVDeveloperFree");
    // a desktop has the seats in one row; a phone stacks them, and a free seat is one line there
    const first = await box(seats.first()), third = await box(seats.nth(2));
    if (width === 1440) expect(third.y).toBe(first.y);
    else { expect(third.y).toBeGreaterThan(first.y); expect(third.height).toBeLessThan(40); }

    const rows = sv.getByRole("list", { name: "SamVision tickets in flight" }).locator("> li");
    await expect(rows).toHaveCount(5);
    await expect(sv.getByRole("img", { name: "Code review, stage 4 of 7" })).toBeVisible();
    await expect(rows.filter({ hasText: "SV-014" })).toContainText("Blocked");
    expect(await rowsFit(page), `rows at ${width}`).toBe(true);
    expect(await page.evaluate(wide), `at ${width}`).toBe(true);

    // open one from the keyboard
    const toggle = sv.getByRole("button", { name: /^SV-056/ });
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const stages = sv.getByRole("list", { name: "Stages of SV-056" }).getByRole("listitem");
    await expect(stages).toHaveText(["InvestigateDone", "BuildDone", "Code reviewNow", "MergeNot started", "ReleaseNot started"]);
    await expect(sv.getByRole("link", { name: "Watch the live session" })).toHaveAttribute("href", "#/workspace?task=SV-056&open=1");
    await expect(sv.getByRole("link", { name: "Open ticket" })).toHaveAttribute("href", "#/tasks/SV-056");
    expect(await page.evaluate(wide), `opened at ${width}`).toBe(true);
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(sv.locator(".hq-tf")).toHaveCount(0);
  }
  // the other two views are still one press away, and a reload comes back to the seats
  await page.getByRole("button", { name: "Org chart" }).click();
  await expect(page.getByRole("region", { name: "Org chart" })).toBeVisible();
  await page.reload();
  await expect(page.locator("#main .hq-seats").first()).toBeVisible();
  expect(watch.writes).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});

test("with the flow: eight seats, who sits where, children under their parent, and a ticket's stages, criteria and history", async ({ page, watch }) => {
  await serveFlow(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "agents");
  await expect(page.getByText(/does not run the nine-stage flow yet/)).toHaveCount(0);
  const sv = team(page, "SamVision");
  await expect(sv).toContainText("8 tickets in flight · 2 at intake");
  const seats = sv.getByRole("list", { name: "SamVision seats" }).getByRole("listitem");
  await expect(seats).toHaveText([/^LDLead/, /^INInvestigator.*sv-011-investigateOn SV-011 · Investigate$/, "TRTechnical reviewerFree",
    /^DVDeveloper.*sv-056-implOn SV-056 · Build$/, "URUser reviewerFree", "DRDesign reviewerFree",
    /^CRCode reviewer.*sv-057-reviewOn SV-057 · Code review$/, /^VFVerifier.*sv-031-verifyOn SV-031 · Release$/]);
  await expect(sv.getByRole("list", { name: "SamVision sessions not in a seat" })).toHaveText("sv-spareIdle");

  // what needs Jay is first; a child sits under its parent, indented; a small ticket's skipped stages are drawn apart
  const rows = sv.getByRole("list", { name: "SamVision tickets in flight" }).locator("> li");
  await expect(rows.first()).toContainText("SV-042");
  await expect(rows.first().getByRole("link", { name: "Needs you" })).toHaveAttribute("href", "#/needs");
  const parent = rows.filter({ hasText: "SV-056" });
  const kids = parent.getByRole("list", { name: "Children of SV-056" }).locator("> li");
  await expect(kids).toHaveText([/^SV-057/, /^SV-058/]);
  expect((await box(kids.first().locator("code"))).x).toBeGreaterThan((await box(parent.locator("code").first())).x);
  const skipped = kids.first().getByRole("img", { name: "Code review, stage 6 of 9" }).locator("i.is-skipped");
  await expect(skipped).toHaveCount(2);                                   // SV-057 changes a screen, so it keeps its user check
  expect((await box(skipped.first())).height).toBeLessThan(2);
  await expect(rows.filter({ hasText: "SV-060" })).toContainText("StaleRisky");
  await expect(rows.filter({ hasText: "SV-014" })).toContainText("Not sized");
  await expect(rows.filter({ hasText: "SV-014" }).locator(".hq-rail i")).toHaveCount(7);
  expect(await rowsFit(page)).toBe(true);

  await parent.getByRole("button", { name: /^SV-056/ }).click();
  const panel = parent.locator(".hq-tf");
  await expect(panel.getByRole("list", { name: "On SV-056 now" })).toHaveText("Developer sv-056-implWorking");
  await expect(panel.getByRole("list", { name: "Stages of SV-056" }).getByRole("listitem")).toHaveText([
    /^IntakeDone · Lead · samvision · \d+[hd]$/, /^InvestigateDone · Investigator · sv-056-plan · \d+h$/,
    /^Technical reviewDone · Technical reviewer · sv-056-tech · \d+h$/, /^BuildNow · Developer · sv-056-impl · \dh$/,
    "User checkNot started · User reviewer", "Code reviewNot started · Code reviewer", "MergeNot started · You",
    "ReleaseNot started · Verifier", "DoneNot started"]);
  await expect(panel.locator(".hq-tf-crit li")).toHaveText(["Markers closer than 40 px join one clusterPassed",
    "A cluster shows how many markers it holdsNot checked", "Zooming in splits a clusterFailed"]);
  await expect(panel.locator(".hq-tf-hist li")).toHaveCount(5);
  await expect(panel.locator(".hq-tf-hist li").nth(2)).toContainText("Technical reviewer sent it back to Investigator · Name the files the cluster layer touches");
  expect(await page.evaluate(wide)).toBe(true);

  // a phone: the opened ticket stays inside the page
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel).toBeVisible();
  const p = await box(panel);
  expect(p.x).toBeGreaterThanOrEqual(0);
  expect(p.x + p.width).toBeLessThanOrEqual(390);
  expect(await rowsFit(page)).toBe(true);
  expect(await page.evaluate(wide)).toBe(true);
  expect(watch.writes).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});
