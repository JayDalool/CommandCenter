// HQ's Settings in a real browser: every section opens clean at desktop width without sideways scroll, a phone shows
// the section list first and one section with a way back (focus follows), and Appearance switches the theme.
import { test, expect, open, problems } from "./fixture";

test.use({ ui: "hq" });

const SECTIONS = ["general", "appearance", "notifications", "windows", "security", "connections", "profiles", "workers",
  "audit", "more", "help"];
const wide = () => document.documentElement.scrollWidth <= window.innerWidth;

test("every section opens clean, with nothing wider than the window", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  for (const s of SECTIONS) {
    await open(page, `settings?tab=${s}`);
    await expect(page.locator(".hq-set-nav [aria-current=page]")).toHaveAttribute("href", `#/settings?tab=${s}`);
    await expect(page.locator("#hq-set-title")).toBeVisible();
    expect(await page.evaluate(wide), s).toBe(true);
  }
  expect(await problems(page, watch)).toEqual([]);
});

test("on a phone: the list, one section with a way back, and focus that follows", async ({ page, watch }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "settings");
  const list = page.getByRole("navigation", { name: "Settings sections" });
  await expect(list).toBeVisible();
  await expect(page.locator("#hq-set-title")).toBeHidden();
  expect(await page.evaluate(wide)).toBe(true);

  await list.getByRole("link", { name: /^Appearance/ }).click();
  await expect(page).toHaveURL(/#\/settings\?tab=appearance$/);
  await expect(list).toBeHidden();
  await expect(page.locator("#hq-set-title")).toBeFocused();
  expect(await page.evaluate(wide)).toBe(true);

  await page.getByRole("link", { name: "Back to Settings" }).click();
  await expect(list).toBeVisible();
  await expect(list.getByRole("link", { name: /^Appearance/ })).toBeFocused();

  for (const s of SECTIONS) {
    await open(page, `settings?tab=${s}`);
    expect(await page.evaluate(wide), s).toBe(true);
  }
  expect(await problems(page, watch)).toEqual([]);
});

test("Appearance switches the theme, and the arrow keys move between the three", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "settings?tab=appearance");
  const group = page.getByRole("radiogroup", { name: "Theme" });
  await group.getByRole("radio", { name: /^Light/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(group.getByRole("radio", { name: /^Dark/ })).toBeFocused();
  expect(await problems(page, watch)).toEqual([]);
});

test("Slack and phone show what is not set up yet, fit a phone, and ask for Developer Unlock before a change", async ({ page, watch }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "settings?tab=notifications");
  const group = page.getByRole("region", { name: "Slack and phone" });
  await expect(group.getByText("Tokens not set up on jay-server (slack.env)")).toBeVisible();
  await expect(group.getByText("No ntfy topic in config.json")).toBeVisible();
  await expect(group.getByLabel("Quiet hours start")).toHaveValue("22:00");
  await expect(group.getByRole("button", { name: "Send a test" })).toBeDisabled();
  await expect(group.getByRole("group", { name: "Your Slack replies" }).getByRole("button", { name: "Answers only" }))
    .toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(wide)).toBe(true);
  await group.getByRole("group", { name: "Slack", exact: true }).getByRole("button", { name: "On" }).click();
  await expect(page.getByRole("dialog", { name: "Developer Unlock" })).toBeVisible();
  await page.keyboard.press("Escape");
  expect(watch.writes).toEqual([]);
  expect(await problems(page, watch)).toEqual([]);
});

test("Style: Professional has no faces; Childish puts them on Teams and My Office, phone included, and survives a reload", async ({ page, watch }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  for (const r of ["dashboard", "agents", "messages"]) {
    await open(page, r);
    await expect(page.locator("#main .hq-page")).toBeVisible();
    await expect(page.locator(".hq-face, .hq-fun")).toHaveCount(0);
  }
  await open(page, "settings?tab=appearance");
  await page.getByRole("group", { name: "Style" }).getByRole("button", { name: "Childish" }).click();
  await expect(page.locator(".hq-cast .hq-face")).toHaveCount(30);
  expect(await page.evaluate(wide)).toBe(true);

  await page.reload();
  await expect(page.getByRole("group", { name: "Style" }).getByRole("button", { name: "Childish" })).toHaveAttribute("aria-pressed", "true");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const r of ["agents", "dashboard"]) {
      await open(page, r);
      const cards = page.locator("#main .hq-sess.has-face");
      await expect(cards.first()).toBeVisible();
      // the face sits beside the card's text, never on top of it or pushing it out of the card
      const fit = await cards.evaluateAll((els) => els.every((el) => {
        const f = el.querySelector(".hq-face")!.getBoundingClientRect(), b = el.querySelector(".hq-sess-body")!.getBoundingClientRect(), c = el.getBoundingClientRect();
        return f.width === 36 && f.right <= b.left && b.right <= c.right + 0.5 && f.left >= c.left;
      }));
      expect(fit, `${r} at ${width}`).toBe(true);
      expect(await page.evaluate(wide), `${r} at ${width}`).toBe(true);
    }
  }
  expect(await problems(page, watch)).toEqual([]);
});

// A 1x1 PNG, served as ccd serves a logo: octet-stream, typed by the page from ccd's list. Buffer is reached through
// globalThis so the type check needs no @types/node (as env.ts does for process.env).
const DOT = (globalThis as unknown as { Buffer: { from(s: string, enc: "base64"): never } }).Buffer
  .from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

test("Project logos: shown from a blob beside the name on My Office, Teams and Settings, with no CSP violation", async ({ page, watch }) => {
  await page.route("**/api/projects/logos", (r) => r.fulfill({ json: { samvision: { mime: "image/png", sha256: "a".repeat(64), updatedAt: 1794549789 } } }));
  await page.route("**/api/projects/samvision/logo", (r) => r.fulfill({ body: DOT, contentType: "application/octet-stream",
    headers: { "content-disposition": "attachment", "x-content-type-options": "nosniff", "content-security-policy": "sandbox" } }));
  await page.setViewportSize({ width: 1280, height: 900 });
  for (const r of ["dashboard", "agents", "settings?tab=appearance"]) {
    await open(page, r);
    const logo = page.locator("#main img.hq-logo[data-project=samvision]").first();
    await expect(logo).toBeVisible();
    await expect(logo).toHaveAttribute("src", /^blob:/);
    // the picture really decoded: a blob of the wrong type, or one CSP refused, has no size
    expect(await logo.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth), r).toBe(1);
    expect(await page.evaluate(wide), r).toBe(true);
  }
  // locked: the row offers the change, and choosing opens Developer Unlock instead of the file dialog
  const row = page.locator("#set-logos .hq-set-row").filter({ hasText: "SamVision" });
  await expect(row).toContainText("PNG, added");
  await row.locator("label.hq-btn").click();
  await expect(page.getByRole("dialog", { name: "Developer Unlock" })).toBeVisible();
  await page.keyboard.press("Escape");
  expect(await problems(page, watch)).toEqual([]);
});
