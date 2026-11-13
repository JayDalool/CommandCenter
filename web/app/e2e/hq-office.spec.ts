// My Office's Briefing and Where we are panels in a real browser: on a ccd with nothing to report, on one with a busy
// night and milestones (the panels fit a desktop and a phone, and a new milestone goes to ccd as one JSON POST), and
// on an older ccd that has neither route (the page says so and shows no figure).
import { test, expect, open, problems, settle, NOW } from "./fixture";

test.use({ ui: "hq" });

const wide = () => document.documentElement.scrollWidth <= window.innerWidth;
const S = Math.floor(NOW / 1000);
const zero = { merged: 0, done: 0, failedChecks: 0, opened: 0, questionsAsked: 0, questionsAnswered: 0, deploys: 0, needsYou: 0 };
const stone = (id: string, title: string, o = {}) => ({ id, title, state: "todo", due: null, note: null, doneAt: null, by: "jay", ...o });
const BRIEF = {
  since: S - 12 * 3600, until: S, quiet: false,
  totals: { ...zero, merged: 2, opened: 3, failedChecks: 1, questionsAsked: 2, needsYou: 5 },
  projects: [
    { key: "samvision", name: "SamVision", ...zero, merged: 2, opened: 2, questionsAsked: 2, needsYou: 3, mainChecks: "passing", spendUsd: 4.2,
      highlights: [1, 2, 3, 4, 5].map((i) => ({ at: S - i * 1800, kind: "pr.opened", ref: `#9${i}`,
        text: `PR #9${i} opened: a pull request with a title long enough to wrap on a narrow phone screen` })) },
    { key: "gyst", name: "GYST", ...zero, opened: 1, failedChecks: 1, mainChecks: "failing", spendUsd: null, highlights: [] },
    { key: "mfe", name: "MFE", ...zero, mainChecks: "unknown", spendUsd: null, highlights: [] },
  ],
};
interface View { projects: Record<string, { revision: number; technical: unknown[]; business: unknown[] }> }
const stones = (): View => ({ projects: {
  samvision: { revision: 3,
    technical: [stone("m_a", "Set up the back end", { state: "done", doneAt: S - 3600 }), stone("m_b", "Set up the front end with the new valuation layout and its phone version", { state: "doing", due: "2026-12-20" })],
    business: [stone("m_c", "Contact the lawyer", { due: "2020-01-05", note: "Ask about the licence wording" })] },
  gyst: { revision: 0, technical: [], business: [] },
} });

test("a quiet ccd: nothing happened, no milestones yet, at desktop and phone width", async ({ page, watch }) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "dashboard");
    await expect(page.getByRole("region", { name: /^Briefing/ })).toContainText("Nothing happened in the last 12 hours.");
    const where = page.getByRole("region", { name: /^Where we are/ });
    await expect(where.locator(".hq-ms-proj")).toHaveCount(5);
    await expect(where.locator(".hq-ms-proj").first()).toContainText("No milestones yet");
    expect(await page.evaluate(wide), `${width}`).toBe(true);
  }
  expect(await problems(page, watch)).toEqual([]);
});

test("a busy night and milestones: both panels fit, the lists open, and Add sends one JSON POST", async ({ page, watch }) => {
  let view = stones();
  const posts: { url: string; type: string | undefined; body: unknown }[] = [];
  await page.route("**/api/briefing**", (r) => r.fulfill({ json: BRIEF }));
  await page.route("**/api/milestones", (r) => r.fulfill({ json: view }));
  await page.route("**/api/milestones/gyst", async (r) => {
    const body = r.request().postDataJSON();
    posts.push({ url: new URL(r.request().url()).pathname, type: r.request().headers()["content-type"], body });
    const m = stone("m_new", body.title, { due: body.due ?? null });
    view = { projects: { ...view.projects, gyst: { revision: 1, technical: [], business: [m] } } };
    await r.fulfill({ json: { milestone: m, revision: 1 } });
  });

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "dashboard");
    const brief = page.getByRole("region", { name: /^Briefing/ });
    await expect(brief.locator(".hq-brief-proj")).toHaveCount(2);
    await expect(brief).toContainText("No activity: MFE");
    // the page is not reloaded between the two widths, so the list is opened once and stays open
    if (width === 1440) await brief.getByRole("button", { name: "Show 2 more" }).click();
    await expect(brief.locator(".hq-brief-hl li")).toHaveCount(5);
    const where = page.getByRole("region", { name: /^Where we are/ });
    const sv = where.locator(".hq-ms-proj").filter({ hasText: "SamVision" });
    await expect(sv.locator(".hq-ms-track").first()).toContainText("1 of 2");
    await expect(sv.locator(".hq-ms-track").nth(1).locator(".t-bad")).toContainText("overdue");
    // the project's name and its button share the first line; nothing inside either panel pokes out of it
    const fits = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>(".hq-brief, .hq-ms")].every((panel) => {
      const p = panel.getBoundingClientRect();
      return [...panel.querySelectorAll<HTMLElement>("*")].every((el) => { const b = el.getBoundingClientRect(); return b.width === 0 || (b.left >= p.left - 0.5 && b.right <= p.right + 0.5); });
    }));
    expect(fits, `${width}`).toBe(true);
    const name = (await sv.locator(".hq-ms-name").boundingBox())!, btn = (await sv.getByRole("button", { name: "Edit SamVision milestones" }).boundingBox())!;
    expect(Math.abs((name.y + name.height / 2) - (btn.y + btn.height / 2)), `${width}`).toBeLessThan(6);

    await sv.getByRole("button", { name: "Edit SamVision milestones" }).click();
    await expect(sv.getByRole("region", { name: "Technical milestones" }).locator(".hq-ms-item")).toHaveCount(2);
    await expect(sv.getByRole("region", { name: "Real life milestones" })).toContainText("Ask about the licence wording");
    expect(await page.evaluate(wide), `${width} open`).toBe(true);
    await sv.getByRole("button", { name: "Close SamVision milestones" }).click();
  }

  // still at phone width: add a real-life milestone to a project that has none
  const gyst = page.getByRole("region", { name: /^Where we are/ }).locator(".hq-ms-proj").filter({ hasText: "GYST" });
  await gyst.getByRole("button", { name: "Add GYST milestones" }).click();
  const life = gyst.getByRole("region", { name: "Real life milestones" });
  await life.getByRole("textbox", { name: "New real life milestone" }).fill("Send the email to the client");
  await life.getByRole("textbox", { name: "New real life milestone" }).press("Enter");
  await expect(gyst.locator(".hq-ms-track").nth(1)).toContainText("0 of 1");
  await expect(life.locator(".hq-ms-item")).toContainText("Send the email to the client");
  expect(posts).toEqual([{ url: "/api/milestones/gyst", type: "application/json", body: { track: "business", title: "Send the email to the client", due: null } }]);
  expect(await page.evaluate(wide)).toBe(true);
  expect(await problems(page, watch)).toEqual([]);
});

test("an older ccd without the routes: each panel says so and shows no figure", async ({ page, watch }) => {
  await page.route("**/api/briefing**", (r) => r.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route("**/api/milestones", (r) => r.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "dashboard");
  const brief = page.getByRole("region", { name: /^Briefing/ }), where = page.getByRole("region", { name: /^Where we are/ });
  await expect(brief).toContainText("This server does not have the briefing yet.");
  await expect(where).toContainText("This server does not have milestones yet.");
  await expect(page.locator(".hq-brief-stats, .hq-ms-proj")).toHaveCount(0);
  // the rest of My Office is as it was
  await expect(page.locator(".hq-proj")).toHaveCount(5);
  await settle(page);
  // the browser's own console line for each 404 is expected; nothing else is
  expect((await problems(page, watch)).filter((p) => !/Failed to load resource.*404/.test(p))).toEqual([]);
});
