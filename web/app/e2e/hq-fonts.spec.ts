// Geist in a real browser: HQ renders in it, and Classic never downloads it. tests/hq-fonts.test.ts checks the files.
import type { Page } from "@playwright/test";
import { test, expect, open, problems } from "./fixture";

const woff2 = (page: Page) => {
  const seen: string[] = [];
  page.on("request", (r) => { if (/\.woff2$/.test(new URL(r.url()).pathname)) seen.push(new URL(r.url()).pathname); });
  return seen;
};
const loaded = (page: Page) => page.evaluate(async () => {
  await document.fonts.ready;
  return [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family.replace(/"/g, "")).sort();
});

test.describe("Classic", () => {
  test("does not download Geist", async ({ page, watch }) => {
    const seen = woff2(page);
    for (const r of ["dashboard", "settings"]) await open(page, r);
    expect(await loaded(page)).toEqual([]);
    expect(seen).toEqual([]);
    expect(await problems(page, watch)).toEqual([]);
  });
});

test.describe("HQ", () => {
  test.use({ ui: "hq" });
  test("renders in Geist and Geist Mono from this server", async ({ page, watch }) => {
    const seen = woff2(page);
    await open(page, "dashboard");
    await expect.poll(() => loaded(page)).toContain("Geist");
    expect(seen.length).toBeGreaterThan(0);
    for (const p of seen) expect(p).toMatch(/^\/assets\/Geist(Mono)?-Variable-[A-Za-z0-9_-]{8}\.woff2$/);
    const body = await page.evaluate(() => getComputedStyle(document.querySelector(".hq-main") ?? document.body).fontFamily);
    expect(body.startsWith('Geist,') || body.startsWith('"Geist"')).toBe(true);
    expect(await problems(page, watch)).toEqual([]);
  });
});
