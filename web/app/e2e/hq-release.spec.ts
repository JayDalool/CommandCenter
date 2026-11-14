// Live or not live, and the weekly release day (flow contract §5, web side) in a real browser. The fixture is a ccd
// with nothing set: no project is live. A stand-in for ccd's release and unlock routes covers a live project, the
// change in Settings (Developer Unlock first), and that the change is still there after a reload.
import type { Page } from "@playwright/test";
import { test, expect, open, problems, settle, RELEASE_NEXT, TOKEN } from "./fixture";

test.use({ ui: "hq" });

/** Right length for a session id and a developer token; neither is a credential. */
const SESSION = "e2e_dev_session_not_a_secret_0000000000000";
const DEV_TOKEN = "e2e_developer_token_not_a_secret_000000000";
const KEYS = ["commandcenter", "gauzemate", "gyst", "mfe", "samvision"];
const wide = () => document.documentElement.scrollWidth <= window.innerWidth;

interface Ccd { live: string[]; weekday: number; time: string; unlocked: boolean; calls: string[]; problems: string[] }

/** ccd's release routes, and the two developer routes a change needs. Everything else stays the read-only fixture. */
async function serveRelease(page: Page, start: Partial<Ccd> = {}): Promise<Ccd> {
  const ccd: Ccd = { live: [], weekday: 3, time: "22:00", unlocked: false, calls: [], problems: [], ...start };
  const json = (body: unknown, status = 200) => ({ status, json: body, headers: { "cache-control": "no-store" } });
  // The stand-in keeps the fixture's date for "next" whatever the weekday: the page shows what ccd sends.
  const body = () => ({ window: { weekday: ccd.weekday, time: ccd.time, tz: "America/Winnipeg", next: RELEASE_NEXT, hours: 2 },
    cutoff: RELEASE_NEXT - 10 * 3600, projects: Object.fromEntries(KEYS.map((k) => [k, { live: ccd.live.includes(k) }])) });
  await page.route(/\/api\/(release(\/window|\/projects\/[a-z]+)?|developer(\/unlock)?)$/, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const mine = ccd.unlocked && req.headers()["x-ccd-developer"] === SESSION;
    if (req.method() !== "GET") ccd.calls.push(`${req.method()} ${path} ${req.postData() ?? ""}`);
    if (req.headers()["x-ccd-token"] !== TOKEN) ccd.problems.push(`no token header: ${req.method()} ${path}`);
    if (req.url().includes(DEV_TOKEN) || req.url().includes(SESSION)) ccd.problems.push(`secret in a URL: ${req.url()}`);
    if (req.method() === "GET" && path === "/api/developer") return route.fulfill(json({ active: mine, expiresIn: mine ? 7200 : null }));
    if (req.method() === "POST" && path === "/api/developer/unlock") {
      if ((req.postDataJSON() as { token?: string }).token !== DEV_TOKEN) return route.fulfill(json({ ok: false, error: "wrong developer token" }, 403));
      ccd.unlocked = true;
      return route.fulfill(json({ ok: true, session: SESSION, expiresIn: 7200 }));
    }
    if (req.method() === "GET" && path === "/api/release") return route.fulfill(json(body()));
    if (req.method() !== "PUT") return route.fallback();
    if (!mine) return route.fulfill(json({ ok: false, error: "Developer Unlock required" }, 403));
    const sent = req.postDataJSON() as { live?: unknown; weekday?: unknown; time?: unknown };
    if (path === "/api/release/window") {
      if (typeof sent.weekday !== "number" || typeof sent.time !== "string") return route.fulfill(json({ ok: false, error: "weekday and time are required" }, 400));
      ccd.weekday = sent.weekday; ccd.time = sent.time;
      return route.fulfill(json(body()));
    }
    const key = path.slice("/api/release/projects/".length);
    if (!KEYS.includes(key)) return route.fulfill(json({ ok: false, error: "unknown project" }, 404));
    if (typeof sent.live !== "boolean") return route.fulfill(json({ ok: false, error: "live must be true or false" }, 400));
    ccd.live = sent.live ? [...new Set([...ccd.live, key])] : ccd.live.filter((k) => k !== key);
    return route.fulfill(json(body()));
  });
  return ccd;
}

const card = (page: Page, name: string) => page.locator("#main a.hq-proj", { hasText: name });
const row = (page: Page, name: string) => page.locator("#set-release .hq-set-row", { hasText: name });

test("a ccd with nothing set: every project says Not live, and nothing is wider than the window", async ({ page, watch }) => {
  for (const [w, h] of [[1280, 900], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, "dashboard");
    await expect(card(page, "SamVision").locator(".hq-live")).toHaveText("Not live");
    await expect(page.locator("#main a.hq-proj .hq-live")).toHaveText(Array(5).fill("Not live"));
    expect(await page.evaluate(wide), `My Office at ${w}`).toBe(true);
    await open(page, "projects");
    await expect(page.locator("#main .hq-live").first()).toHaveText("Not live");
    expect(await page.evaluate(wide), `Company at ${w}`).toBe(true);
    await open(page, "settings?tab=profiles");
    await expect(page.locator("#set-release")).toContainText("Wednesday 10 p.m. Central");
    await expect(page.locator("#set-release")).toContainText("Changing these needs Developer Unlock.");
    expect(await page.evaluate(wide), `Settings at ${w}`).toBe(true);
  }
  expect(await problems(page, watch)).toEqual([]);
});

test("a live project is marked on My Office and Company, and its panel says when it releases", async ({ page, watch }) => {
  const ccd = await serveRelease(page, { live: ["samvision"] });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "dashboard");
  await expect(card(page, "SamVision").locator(".hq-live")).toHaveText("Live");
  await expect(card(page, "SamVision").locator(".hq-live")).toHaveAttribute("title", /^Live\. Changes go out together in the weekly release: Wednesday 10 p\.m\. Central\. Next: Wed, /);
  await expect(card(page, "GYST").locator(".hq-live")).toHaveText("Not live");

  await open(page, "projects");
  const node = page.getByRole("button", { name: /^SamVision, .*, live$/ });
  await expect(node.locator(".hq-live")).toHaveText("Live");
  await expect(page.getByRole("button", { name: /^GYST, .*, not live$/ })).toBeVisible();
  await node.click();
  const note = page.locator("#main .hq-live-note");
  await expect(note).toContainText("Changes go out together in the weekly release, Wednesday 10 p.m. Central. Next: Wed, ");
  await note.getByRole("link", { name: "Change" }).click();
  await expect(page).toHaveURL(/#\/settings\?tab=profiles$/);
  await settle(page);
  await expect(row(page, "SamVision").getByRole("button", { name: "Live", exact: true })).toHaveAttribute("aria-pressed", "true");

  // List view carries the same label.
  await open(page, "projects");
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "List" }).click();
  await expect(page.locator("#main a.hq-topo-node", { hasText: "SamVision" }).locator(".hq-live")).toHaveText("Live");
  expect(ccd.calls).toEqual([]);
  expect(ccd.problems).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});

test("Settings: locked sends nothing; unlocked makes a project live and moves the day, kept through a reload", async ({ page, watch }) => {
  const ccd = await serveRelease(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "settings?tab=profiles");
  const gyst = row(page, "GYST");
  const live = gyst.getByRole("button", { name: "Live", exact: true });

  // Locked: the press opens Developer Unlock and nothing is sent.
  await live.click();
  const dialog = page.getByRole("dialog", { name: "Developer Unlock" });
  await expect(dialog).toBeVisible();
  expect(ccd.calls).toEqual([]);
  await dialog.getByLabel("Developer token").fill(DEV_TOKEN);
  await dialog.getByRole("button", { name: "Unlock" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator("#set-release")).not.toContainText("Changing these needs Developer Unlock.");
  await expect(live).toHaveAttribute("aria-pressed", "false");     // unlocking does not make the change by itself

  await live.click();
  await expect(live).toHaveAttribute("aria-pressed", "true");
  await expect(gyst).toContainText("Changes wait for the weekly release.");

  const day = row(page, "Release day");
  await day.getByRole("button", { name: "Thu" }).click();
  await expect(day).toContainText("Thursday 10 p.m. Central");
  const time = row(page, "Release time").getByLabel("Release time");
  await time.fill("21:30");
  await time.blur();
  await expect(day).toContainText("Thursday 9:30 p.m. Central");
  expect(ccd.calls.slice(1)).toEqual([
    'PUT /api/release/projects/gyst {"live":true}',
    'PUT /api/release/window {"weekday":4,"time":"22:00"}',
    'PUT /api/release/window {"weekday":4,"time":"21:30"}',
  ]);

  await page.reload();
  await settle(page);
  await expect(row(page, "GYST").getByRole("button", { name: "Live", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(row(page, "Release day")).toContainText("Thursday 9:30 p.m. Central");
  await open(page, "dashboard");
  await expect(card(page, "GYST").locator(".hq-live")).toHaveText("Live");
  expect(await page.evaluate((secret) => JSON.stringify({ ...localStorage }).includes(secret) || JSON.stringify({ ...sessionStorage }).includes(secret), DEV_TOKEN)).toBe(false);
  expect(ccd.problems).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});

test("a ccd without the release store shows no label and no settings group", async ({ page, watch }) => {
  await page.route(/\/api\/release$/, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "dashboard");
  await expect(page.locator("#main a.hq-proj").first()).toBeVisible();
  await expect(page.locator("#main .hq-live")).toHaveCount(0);
  await open(page, "settings?tab=profiles");
  await expect(page.locator("#hq-set-title")).toBeVisible();
  await expect(page.locator("#set-release")).toHaveCount(0);
  // The browser logs the 404 itself, once: the store does not ask an older ccd again.
  const found = await problems(page, watch);
  expect(found.filter((p) => !/404/.test(p))).toEqual([]);
  expect(found.filter((p) => /404/.test(p))).toHaveLength(1);
});
