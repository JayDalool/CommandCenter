// Every Classic route loads in Dark and in Light, shows the screen it names, and has nothing wrong: no console error
// or warning, no uncaught exception, no CSP violation, no request off the test server, no API call the fixture cannot
// answer, no write, the token only ever in its header, no window or worker it should not open, and live events live.
import { test, expect, open, problems, shown, type Theme } from "./fixture";
import { LOAD, SHOWS } from "./routes";

for (const theme of ["dark", "light"] as Theme[]) {
  test.describe(`Classic, ${theme}`, () => {
    test.use({ theme });
    for (const route of LOAD) {
      test(`#/${route} loads clean`, async ({ page, watch }) => {
        await open(page, route);
        expect(await shown(page)).toBe(SHOWS[route]);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        expect(await problems(page, watch)).toEqual([]);
      });
    }
  });
}
