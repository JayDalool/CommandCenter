// Every Classic route loads in Dark and in Light with nothing wrong: no console error or warning, no uncaught
// exception, no CSP violation, no request off the test server, no API call the fixture cannot answer, no write, the
// token only ever in its header, and live events connected.
import { test, expect, open, problems, type Theme } from "./fixture";
import { LOAD } from "./routes";

for (const theme of ["dark", "light"] as Theme[]) {
  test.describe(`Classic, ${theme}`, () => {
    test.use({ theme });
    for (const route of LOAD) {
      test(`#/${route} loads clean`, async ({ page, watch }) => {
        await open(page, route);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        expect(await problems(page, watch)).toEqual([]);
      });
    }
  });
}
