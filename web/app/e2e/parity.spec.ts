// Classic must look as it did before this change. The CI job first runs this file against the base build with
// --update-snapshots=all, which writes e2e/.parity/, then against this build, which must match. Run on its own it is
// skipped: there is nothing to compare with. See e2e/README.md.
//
// Two checks, because screenshots alone are not exact (playwright.config.ts, toHaveScreenshot):
// - every screen, the whole page and the end of every scrolling panel, in pixels;
// - every one of Classic's design tokens (CSS custom properties), as text, exactly.
import { test, expect, open, settle, type Theme } from "./fixture";
import type { Page } from "@playwright/test";
import { PARITY, slug } from "./routes";
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
 *  so a token that only exists under another mode (HQ's --hq-*, inert in Classic) is not one of Classic's. */
const tokens = (page: Page) => page.evaluate(() => {
  const names = new Set<string>();
  const walk = (rules: CSSRuleList) => {
    for (const r of rules) {
      if (r instanceof CSSStyleRule) for (const n of r.style) if (n.startsWith("--")) names.add(n);
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

for (const theme of ["dark", "light"] as Theme[]) {
  test.describe(`Classic, ${theme}`, () => {
    test.use({ theme });

    test("design tokens are unchanged", { tag: "@parity" }, async ({ page }) => {
      await open(page, "dashboard");
      expect(await tokens(page)).toMatchSnapshot(`tokens-${theme}.json`);
    });

    for (const route of PARITY) {
      test(`#/${route} looks unchanged`, { tag: "@parity" }, async ({ page }) => {
        await open(page, route);
        await expect(page).toHaveScreenshot(`${slug(route)}-${theme}.png`, { fullPage: true });
        if (await scrollPanels(page)) {
          await settle(page);
          await expect(page, "with every scrolling panel at its end").toHaveScreenshot(`${slug(route)}-${theme}-end.png`, { fullPage: true });
        }
      });
    }
  });
}
