// Classic must look as it did before this change. The base build is run first
// with --update-snapshots=all, which writes e2e/.parity/, then this build, which must match. Run on its own it is
// skipped: there is nothing to compare with. See e2e/README.md.
//
// Two checks, because screenshots alone are not exact (playwright.config.ts, toHaveScreenshot):
// - every screen, the whole page and the end of every scrolling panel, in pixels;
// - every one of Classic's design tokens (CSS custom properties), as text, exactly.
// What this branch adds on purpose (routes.ts, ADDED) is hidden first, and everything else must match.
import { test, expect, open, settle, type Theme } from "./fixture";
import type { Page, TestInfo } from "@playwright/test";
import { ADDED, PARITY, isBare, slug } from "./routes";
import { env } from "./env";

test.skip(!env.E2E_PARITY, "parity needs a base build: see e2e/README.md");

/** Scrolls every panel that has more than it shows to its end. Returns how many it scrolled. */
const scrollPanels = (page: Page) => page.evaluate(() => {
  let n = 0;
  for (const el of document.querySelectorAll<HTMLElement>("body *")) {
    if (/(auto|scroll)/.test(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1) {
      el.scrollTop = el.scrollHeight;
      n++;
    }
  }
  return n;
});

/** Every custom property any stylesheet declares, with its value on <html> and on #main. Empty values are left out,
 *  so a token that only exists under another mode (HQ's --hq-*, inert in Classic) is not one of Classic's. HQ's own
 *  are left out by name too, so Classic's can be compared while HQ's are switched on. */
const tokens = (page: Page) => page.evaluate(() => {
  const names = new Set<string>();
  const walk = (rules: CSSRuleList) => {
    for (const r of rules) {
      if (r instanceof CSSStyleRule) for (const n of r.style) if (n.startsWith("--") && !n.startsWith("--hq-")) names.add(n);
      if ("cssRules" in r && (r as CSSGroupingRule).cssRules) walk((r as CSSGroupingRule).cssRules);
    }
  };
  for (const sheet of document.styleSheets) walk(sheet.cssRules);
  const at = (el: Element | null) => {
    const cs = el ? getComputedStyle(el) : null;
    return Object.fromEntries([...names].sort().map((n) => [n, cs?.getPropertyValue(n).trim() ?? ""]).filter(([, v]) => v));
  };
  return JSON.stringify({ html: at(document.documentElement), main: at(document.getElementById("main")) }, null, 1);
});

/** The HQ preview tests compare with the base screenshots, so they never write any. */
const writing = (info: TestInfo) => ["all", "changed"].includes(info.config.updateSnapshots);

/** Hides what this branch added on purpose (routes.ts). Each selector must match, so a stale entry fails. Not on the
 *  base side, which has none of it. */
async function hideAdded(page: Page, selectors: string[]) {
  for (const sel of selectors) {
    const n = await page.evaluate((s) => {
      const found = [...document.querySelectorAll<HTMLElement>(s)];
      for (const el of found) el.style.setProperty("display", "none", "important");
      return found.length;
    }, sel);
    expect(n, `${sel} (routes.ts, ADDED) is on the page`).toBeGreaterThan(0);
  }
  await settle(page);
}

const hq = (page: Page) => expect(page.locator("html"), "the HQ preview is on").toHaveAttribute("data-ui", "hq");

async function shoot(page: Page, route: string, theme: Theme) {
  await expect(page).toHaveScreenshot(`${slug(route)}-${theme}.png`, { fullPage: true });
  if (await scrollPanels(page)) {
    await settle(page);
    await expect(page, "with every scrolling panel at its end").toHaveScreenshot(`${slug(route)}-${theme}-end.png`, { fullPage: true });
  }
}

for (const theme of ["dark", "light"] as Theme[]) {
  test.describe(`Classic, ${theme}`, () => {
    test.use({ theme, ui: "classic" });

    test("design tokens are unchanged", { tag: "@parity" }, async ({ page }) => {
      await open(page, "dashboard");
      expect(await tokens(page)).toMatchSnapshot(`tokens-${theme}.json`);
    });

    for (const route of PARITY) {
      test(`#/${route} looks unchanged`, { tag: "@parity" }, async ({ page }, info) => {
        await open(page, route);
        if (!writing(info)) await hideAdded(page, ADDED[route] ?? []);
        await shoot(page, route, theme);
      });
    }
  });

  // The HQ preview: <html data-ui="hq"> switches HQ's tokens on, and they must not change one of Classic's. Its frame
  // (sidebar, top bar, tabs) is HQ's own look, so a framed screen is not compared with Classic's pixels; the screen
  // inside it is Classic's markup (tests/routes-both-modes.test.tsx). The pop-outs have no frame in either mode and
  // must still match Classic pixel for pixel.
  test.describe(`HQ preview, ${theme}`, () => {
    test.use({ theme, ui: "hq" });

    test("design tokens are unchanged", { tag: "@parity" }, async ({ page }, info) => {
      test.skip(writing(info), "compares with the base tokens from Classic");
      await open(page, "dashboard");
      await hq(page);
      expect(await tokens(page)).toMatchSnapshot(`tokens-${theme}.json`);
    });

    for (const route of PARITY.filter(isBare)) {
      test(`#/${route} looks unchanged`, { tag: "@parity" }, async ({ page }, info) => {
        test.skip(writing(info), "compares with the base screenshots from Classic");
        await open(page, route);
        await hq(page);
        await hideAdded(page, ADDED[route] ?? []);
        await shoot(page, route, theme);
        await hq(page);
      });
    }
  });
}
