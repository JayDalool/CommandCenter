// CC-100: the criteria editor on a ticket's HQ page (#/tasks/KEY), at phone and desktop width, in both themes, by
// keyboard alone. ccd is stubbed: the work record is early (investigation) so no Developer Unlock is needed, and the
// criteria POST is answered by the spec, which asserts the body. The Unlock paths are covered by vitest.
import type { Page } from "@playwright/test";
import { test, expect, open, problems } from "./fixture";

test.use({ ui: "hq" });

const WIDTHS = [375, 1280];
const wide = () => document.documentElement.scrollWidth <= window.innerWidth;
const crit = (id: string, text: string) => ({ id, text, state: "open", by: null, at: null, head: null });

async function serve(page: Page) {
  const posts: unknown[] = [];
  let criteria = [crit("c1", "Five comps show"), crit("c2", "Sold dates are used")];
  const work = () => ({ key: "SV-056", status: "RESEARCHING", stage: "PLAN", stages: [], plan: {}, planState: "none",
    policy: { plan: "auto", planReasons: [], merge: "owner", ui: false, deploy: false }, gate: null, gateReason: null,
    confirmed: [], branch: null, worktree: null, prs: [], roles: {}, review: { verdict: null, head: null, cycles: 0 },
    verification: null, merge: null, handoff: null, blocked: null, findings: [], size: "standard", requirements: [],
    criteria, flow: { size: "standard", stage: "investigate", stages: [], route: [] } });
  await page.route("**/api/tasks/SV-056/work", (r) => r.fulfill({ json: work() }));
  await page.route("**/api/tasks/SV-056/work/criteria", (r) => {
    const body = r.request().postDataJSON() as { criteria: ({ id: string; text: string } | string)[] };
    posts.push(body);
    criteria = body.criteria.map((c, i) => (typeof c === "string" ? crit(`c${i + 5}`, c) : crit(c.id, c.text)));
    return r.fulfill({ json: work() });
  });
  return posts;
}

for (const theme of ["dark", "light"] as const) {
  test.describe(`${theme} theme`, () => {
    test.use({ theme });
    for (const width of WIDTHS) {
      test(`edit, add, delete and save by keyboard at ${width} wide`, async ({ page, watch }) => {
        await page.setViewportSize({ width, height: 900 });
        const posts = await serve(page);
        await open(page, "tasks/SV-056");
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        const section = page.getByRole("region", { name: "Acceptance criteria" });
        await expect(section.getByText("Five comps show")).toBeVisible();

        await section.getByRole("button", { name: "Edit" }).focus();
        await page.keyboard.press("Enter");
        const first = section.getByRole("textbox", { name: "Criterion c1" });
        await first.focus();
        await page.keyboard.press("End");
        await page.keyboard.type(" today");
        await page.keyboard.press("Tab");                       // Remove c1
        await page.keyboard.press("Tab");                       // Criterion c2
        await page.keyboard.press("Enter");                     // the last row: Enter adds a new one and focuses it
        const added = section.getByRole("textbox", { name: /^New criterion/ });
        await expect(added).toBeFocused();
        await page.keyboard.type("Brand new");
        await section.getByRole("button", { name: "Remove Criterion c2" }).focus();
        await page.keyboard.press("Enter");                     // delete c2
        expect(await page.evaluate(wide)).toBe(true);
        await added.focus();
        await page.keyboard.press("Control+Enter");             // save from the keyboard

        await expect.poll(() => posts.length).toBe(1);
        expect(posts[0]).toEqual({ criteria: [{ id: "c1", text: "Five comps show today" }, "Brand new"] });
        await expect(section.getByText("Brand new")).toBeVisible();
        await expect(section.getByRole("button", { name: "Edit" })).toBeFocused();   // focus returns where it came from
        expect(await page.evaluate(wide)).toBe(true);
        expect(await problems(page, watch)).toEqual([]);
      });
    }
  });
}

test("Escape leaves the editor without saving", async ({ page, watch }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  const posts = await serve(page);
  await open(page, "tasks/SV-056");
  const section = page.getByRole("region", { name: "Acceptance criteria" });
  await section.getByRole("button", { name: "Edit" }).click();
  await section.getByRole("textbox", { name: "Criterion c1" }).focus();
  await page.keyboard.type("zzz");
  await page.keyboard.press("Escape");
  await expect(section.getByRole("textbox", { name: "Criterion c1" })).toBeHidden();
  await expect(section.getByText("Five comps show", { exact: true })).toBeVisible();
  expect(posts).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});

// CC-100 user check: a draft opened on one ticket was saved onto the next one Jay moved to.
test("moving to another ticket drops the draft; Save never writes it onto that ticket", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const posts = await serve(page);
  const other: string[] = [];
  await page.route("**/api/tasks/CC-001/work/criteria", (r) => { other.push(r.request().url()); return r.fulfill({ status: 500, json: { ok: false, error: "must not be called" } }); });
  // Visit the other ticket first: the pane keeps a loaded ticket's form mounted, which is how the draft leaked.
  await open(page, "tasks/CC-001");
  await expect(page.getByRole("region", { name: "Acceptance criteria" })).toBeVisible();
  await page.evaluate(() => { location.hash = "#/tasks/SV-056"; });
  const section = page.getByRole("region", { name: "Acceptance criteria" });
  await section.getByRole("button", { name: "Edit" }).click();
  await section.getByRole("textbox", { name: "Criterion c1" }).fill("draft for SV-056");
  await page.evaluate(() => { location.hash = "#/tasks/CC-001"; });
  await expect(page.getByRole("region", { name: "Acceptance criteria" }).getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Criterion c1" })).toHaveCount(0);
  await page.keyboard.press("Control+Enter");
  expect([posts, other]).toEqual([[], []]);
});

test("Ctrl+Enter saves from the Size select, and Esc outside the form does not close the pane", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const posts = await serve(page);
  await open(page, "tasks/SV-056");
  const section = page.getByRole("region", { name: "Acceptance criteria" });
  await section.getByRole("button", { name: "Edit" }).click();
  await section.getByRole("textbox", { name: "Criterion c1" }).fill("via the size select");
  await expect(section.getByText("Left empty: no due date is set.")).toBeVisible();
  await section.getByRole("combobox", { name: "Size" }).focus();
  await page.keyboard.press("Control+Enter");
  await expect.poll(() => posts.length).toBe(1);

  await section.getByRole("button", { name: "Edit" }).click();
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/#\/tasks\/SV-056$/);
  await expect(section.getByRole("textbox", { name: "Criterion c1" })).toBeVisible();
});
