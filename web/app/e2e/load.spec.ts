// Every route loads in Dark and in Light, in Classic and in the HQ preview, shows the screen it names, and has nothing
// wrong: no console error or warning, no uncaught exception, no CSP violation, no request off the test server, no API
// call the fixture cannot answer, no write, the token only ever in its header, no window or worker it should not
// open, and live events live.
import { test, expect, open, problems, shown, type Theme, type Ui } from "./fixture";
import { LOAD, SHOWS, isBare } from "./routes";

for (const ui of ["classic", "hq"] as Ui[]) {
  for (const theme of ["dark", "light"] as Theme[]) {
    test.describe(`${ui === "hq" ? "HQ preview" : "Classic"}, ${theme}`, () => {
      test.use({ theme, ui });
      for (const route of LOAD) {
        test(`#/${route} loads clean`, async ({ page, watch }) => {
          await open(page, route);
          expect(await shown(page)).toBe(SHOWS[route]);
          const html = page.locator("html");
          await expect(html).toHaveAttribute("data-theme", theme);
          // HQ's attribute only in the HQ preview: in Classic its tokens stay inert.
          if (ui === "hq") await expect(html).toHaveAttribute("data-ui", "hq");
          else await expect(html).not.toHaveAttribute("data-ui", /.*/);
          // The label: only in the HQ preview, at the foot of the rail, so never in a pop-out (no rail).
          await expect(page.locator(".rail .hq-tag")).toHaveCount(ui === "hq" && !isBare(route) ? 1 : 0);
          await expect(page.locator(".hq-tag")).toHaveCount(ui === "hq" && !isBare(route) ? 1 : 0);
          expect(await problems(page, watch)).toEqual([]);
        });
      }
    });
  }
}
