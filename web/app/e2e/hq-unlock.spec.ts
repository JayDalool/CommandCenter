// Developer Unlock that lasts (flow contract §6, web side) in a real browser, against a stand-in for ccd's developer
// routes: "Remember this device" keeps the session through a reload, Settings lists the devices and locks them all,
// and a remembered device whose token is more than 8 hours old types it again. The developer token is typed into a
// password field and must never reach a URL or the browser's storage.
import type { Page } from "@playwright/test";
import { test, expect, open, problems, settle, NOW, TOKEN } from "./fixture";

test.use({ ui: "hq" });

/** Right length for a session id and a developer token; neither is a credential. */
const SESSION = "e2e_dev_session_not_a_secret_0000000000000";
const DEV_TOKEN = "e2e_developer_token_not_a_secret_000000000";
const now = Math.floor(NOW / 1000);
const wide = () => document.documentElement.scrollWidth <= window.innerWidth;

interface Ccd { unlocked: boolean; remembered: boolean; reenterIn: number; calls: string[]; problems: string[] }

/** ccd's developer routes as PR #105 answers them, for one session. Everything else stays the read-only fixture. */
async function serveDeveloper(page: Page, start: Partial<Ccd> = {}): Promise<Ccd> {
  const ccd: Ccd = { unlocked: false, remembered: false, reenterIn: 8 * 3600, calls: [], problems: [], ...start };
  const json = (body: unknown, status = 200) => ({ status, json: body, headers: { "cache-control": "no-store" } });
  await page.route(/\/api\/developer(\/[a-z-]+)?$/, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const mine = ccd.unlocked && req.headers()["x-ccd-developer"] === SESSION;
    ccd.calls.push(`${req.method()} ${path}`);
    if (req.headers()["x-ccd-token"] !== TOKEN) ccd.problems.push(`no token header: ${req.method()} ${path}`);
    if (req.url().includes(DEV_TOKEN) || req.url().includes(SESSION)) ccd.problems.push(`secret in a URL: ${req.url()}`);
    if (req.method() === "GET" && path === "/api/developer") {
      return route.fulfill(json({ active: mine, expiresIn: mine ? 29 * 86400 : null, remembered: mine && ccd.remembered,
        reenterIn: mine ? ccd.reenterIn : null, configured: true, tokenFile: null }));
    }
    if (req.method() === "POST" && path === "/api/developer/unlock") {
      const body = req.postDataJSON() as { token?: string; remember?: unknown };
      if (body.token !== DEV_TOKEN) return route.fulfill(json({ ok: false, error: "wrong developer token" }, 403));
      ccd.unlocked = true; ccd.remembered = body.remember === true; ccd.reenterIn = 8 * 3600;
      return route.fulfill(json({ ok: true, session: SESSION, expiresIn: ccd.remembered ? 30 * 86400 : 8 * 3600,
        remembered: ccd.remembered, idleLimit: ccd.remembered ? null : 7200, reenterIn: ccd.reenterIn }));
    }
    if (!mine) return route.fulfill(json({ ok: false, error: "Developer Unlock required" }, 403));
    if (req.method() === "GET" && path === "/api/developer/devices") {
      return route.fulfill(json({ devices: [
        { id: "a1", label: "Chrome on Windows", kind: ccd.remembered ? "remember" : "plain", remembered: ccd.remembered,
          createdAt: now - 60, lastUsedAt: now, expiresAt: now + 30 * 86400, current: true },
        { id: "b2", label: "Safari on iPhone", kind: "remember", remembered: true, createdAt: now - 4 * 86400,
          lastUsedAt: now - 2 * 3600, expiresAt: now + 26 * 86400, current: false },
      ] }));
    }
    if (req.method() === "POST" && path === "/api/developer/lock-all") { ccd.unlocked = false; return route.fulfill(json({ ok: true, ended: 2 })); }
    if (req.method() === "POST" && path === "/api/developer/lock") { ccd.unlocked = false; return route.fulfill(json({ ok: true })); }
    return route.fallback();
  });
  return ccd;
}

/** What the browser keeps of the session, and that the typed token is nowhere in its storage. */
const kept = (page: Page) => page.evaluate((secret) => ({
  local: localStorage.getItem("ccd.dev"), tab: sessionStorage.getItem("ccd.dev"),
  leaked: JSON.stringify({ ...localStorage }).includes(secret) || JSON.stringify({ ...sessionStorage }).includes(secret),
}), DEV_TOKEN);

test("Remember this device: unlocked through a reload, listed in Settings, ended by Lock all devices", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const ccd = await serveDeveloper(page);
  await open(page, "settings?tab=security");
  const main = page.locator("#main");
  await expect(main.getByText("Locked", { exact: true })).toBeVisible();
  await expect(main.getByText("Not shown while locked")).toBeVisible();

  await main.getByRole("button", { name: "Unlock…" }).click();
  const dialog = page.getByRole("dialog", { name: "Developer Unlock" });
  const box = dialog.getByRole("checkbox", { name: /Remember this device for 30 days/ });
  await expect(box).not.toBeChecked();
  await box.check();
  await expect(dialog.getByLabel("Developer token")).toHaveAttribute("type", "password");
  await dialog.getByLabel("Developer token").fill(DEV_TOKEN);
  await dialog.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(dialog).toBeHidden();

  await expect(main.getByText("Unlocked, remembered")).toBeVisible();
  await expect(main.getByText(/Open for another 8 hours/)).toBeVisible();
  const devices = main.locator("#set-devices");
  await expect(devices.locator(".hq-set-row").nth(0)).toContainText("Chrome on Windows");
  await expect(devices.locator(".hq-set-row").nth(0)).toContainText("This device");
  await expect(devices.locator(".hq-set-row").nth(0)).toContainText("Remembered for 30 days · last used just now · ends in 30 days");
  await expect(devices.locator(".hq-set-row").nth(1)).toContainText("Safari on iPhone");
  await expect(devices.locator(".hq-set-row").nth(1)).toContainText("last used 2h ago · ends in 26 days");
  let k = await kept(page);
  expect(JSON.parse(k.local!)).toMatchObject({ id: SESSION, remembered: true });
  expect(k.tab).toBeNull();
  expect(k.leaked).toBe(false);
  await expect(page.locator("body")).not.toContainText(SESSION);

  // A new start of the same browser: still unlocked, after asking ccd whether the session stands.
  ccd.calls.length = 0;
  await page.reload();
  await settle(page);
  await expect(main.getByText("Unlocked, remembered")).toBeVisible();
  await expect(devices.locator(".hq-set-row").nth(0)).toContainText("This device");
  expect(ccd.calls).toContain("GET /api/developer");

  await main.getByRole("button", { name: "Lock all devices…" }).click();
  const sure = page.getByRole("dialog", { name: "Lock all devices?" });
  await sure.getByRole("button", { name: "Cancel" }).click();
  await expect(main.getByText("Unlocked, remembered")).toBeVisible();
  await main.getByRole("button", { name: "Lock all devices…" }).click();
  await sure.getByRole("button", { name: "Lock all devices" }).click();
  await expect(main.getByText("Locked", { exact: true })).toBeVisible();
  await expect(main.getByText("Not shown while locked")).toBeVisible();
  k = await kept(page);
  expect(k.local).toBeNull();
  expect(k.tab).toBeNull();
  expect(ccd.calls).toContain("POST /api/developer/lock-all");

  // Ended somewhere else (Lock all devices on another device): the next start finds out and locks.
  await page.evaluate((id) => localStorage.setItem("ccd.dev", JSON.stringify({ id, expiresAt: null, remembered: true })), SESSION);
  await page.reload();
  await settle(page);
  await expect(main.getByText("Locked", { exact: true })).toBeVisible();
  expect((await kept(page)).local).toBeNull();

  expect(ccd.problems).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});

test("without the box: a plain session that the tab keeps and the browser does not", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const ccd = await serveDeveloper(page);
  await open(page, "settings?tab=security");
  const main = page.locator("#main");
  await main.getByRole("button", { name: "Unlock…" }).click();
  const dialog = page.getByRole("dialog", { name: "Developer Unlock" });
  await dialog.getByLabel("Developer token").fill("not the token");
  await dialog.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("wrong developer token");
  await dialog.getByLabel("Developer token").fill(DEV_TOKEN);
  await dialog.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(main.getByText("Unlocked", { exact: true })).toBeVisible();
  await expect(main.getByText("Terminals and file changes", { exact: true })).toHaveCount(0);   // a remembered device's row
  await expect(main.getByText(/Token typed, not remembered/)).toBeVisible();
  const k = await kept(page);
  expect(k.local).toBeNull();
  expect(JSON.parse(k.tab!)).toMatchObject({ id: SESSION });
  expect(k.leaked).toBe(false);

  await main.getByRole("button", { name: "Lock", exact: true }).click();
  await expect(main.getByText("Locked", { exact: true })).toBeVisible();
  expect(ccd.calls).toContain("POST /api/developer/lock");
  expect(ccd.problems).toEqual([]);
  // The wrong token's 403 is the browser's own console line, once; nothing else was refused.
  expect(await problems(page, watch)).toEqual(["console error: Failed to load resource: the server responded with a status of 403 (Forbidden)"]);
});

for (const width of [390, 320]) {
  test(`on a ${width}px phone: the token typed again on a remembered device, nothing wider than the screen`, async ({ page, watch }) => {
    await page.setViewportSize({ width, height: 844 });
    // A remembered device from an earlier day: the session stands, the token is too old for a terminal.
    const ccd = await serveDeveloper(page, { unlocked: true, remembered: true, reenterIn: 0 });
    await page.addInitScript((id) => {
      try { if (!sessionStorage.getItem("e2e.seeded")) { sessionStorage.setItem("e2e.seeded", "1"); localStorage.setItem("ccd.dev", JSON.stringify({ id, expiresAt: null, remembered: true })); } } catch { /* no storage */ }
    }, SESSION);
    await open(page, "settings?tab=security");
    const main = page.locator("#main");
    await expect(main.getByText("Unlocked, remembered")).toBeVisible();
    await expect(main.getByText(/typed more than 8 hours ago/)).toBeVisible();
    await expect(main.getByText("Chrome on Windows")).toBeVisible();
    expect(await page.evaluate(wide)).toBe(true);

    await main.getByRole("button", { name: "Type the token…" }).click();
    const dialog = page.getByRole("dialog", { name: "Developer Unlock" });
    await expect(dialog).toContainText("more than 8 hours since the developer token was typed");
    await expect(dialog.getByRole("checkbox")).toHaveCount(0);
    await expect(dialog.getByText(/Sign in with SSH/)).toHaveCount(0);
    expect(await page.evaluate(wide)).toBe(true);
    expect(await dialog.evaluate((d) => { const r = d.getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth; })).toBe(true);
    await dialog.getByLabel("Developer token").fill(DEV_TOKEN);
    await dialog.getByRole("button", { name: "Unlock", exact: true }).click();
    await expect(dialog).toBeHidden();

    await expect(main.getByText(/Open for another 8 hours/)).toBeVisible();
    await expect(main.getByText("Unlocked, remembered")).toBeVisible();   // typed again, the device stays remembered
    expect(ccd.remembered).toBe(true);
    expect(JSON.parse((await kept(page)).local!)).toMatchObject({ id: SESSION, remembered: true });
    expect(await page.evaluate(wide)).toBe(true);
    expect(ccd.problems).toEqual([]);
    expect(await problems(page, watch)).toEqual([]);
  });
}
