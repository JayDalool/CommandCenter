// Classic must look exactly as it did before this change. The CI job first runs this file against the base build
// with --update-snapshots=all, which writes e2e/.parity/, then against this build, which must match pixel for pixel.
// Run on its own it is skipped: there is nothing to compare with. See e2e/README.md.
import { test, expect, open, type Theme } from "./fixture";
import { PARITY, slug } from "./routes";
import { env } from "./env";

test.skip(!env.E2E_PARITY, "parity needs a base build: see e2e/README.md");

for (const theme of ["dark", "light"] as Theme[]) {
  test.describe(`Classic, ${theme}`, () => {
    test.use({ theme });
    for (const route of PARITY) {
      test(`#/${route} looks unchanged`, { tag: "@parity" }, async ({ page }) => {
        await open(page, route);
        await expect(page).toHaveScreenshot(`${slug(route)}-${theme}.png`);
      });
    }
  });
}
