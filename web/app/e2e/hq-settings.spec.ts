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
