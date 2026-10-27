// HQ's tokens in a real browser: they resolve only under <html data-ui="hq">, follow Classic's theme (dark, light,
// system), and never change one of Classic's own variables. tests/hq-tokens.test.ts checks the file itself, and
// parity.spec.ts proves Classic's pixels do not move with the attribute on or off.
import { test, expect, open } from "./fixture";

test("HQ tokens exist only under data-ui=\"hq\" and follow Classic's theme", async ({ page }) => {
  await open(page, "dashboard");
  const read = () => page.evaluate(() => {
    const s = getComputedStyle(document.documentElement);
    return { hq: s.getPropertyValue("--hq-bg").trim(), pj: s.getPropertyValue("--hq-pj-samvision").trim(),
      classic: s.getPropertyValue("--bg").trim() };
  });
  const set = (name: string, value: string | null) => page.evaluate(([n, v]) => {
    if (v === null) document.documentElement.removeAttribute(n!); else document.documentElement.setAttribute(n!, v);
  }, [name, value]);

  const classicDark = (await read()).classic;
  expect(await read()).toEqual({ hq: "", pj: "", classic: classicDark });

  await set("data-ui", "hq");
  expect(await read()).toEqual({ hq: "#070b17", pj: "#2fe0a0", classic: classicDark });

  await set("data-theme", "light");
  const classicLight = (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()));
  expect(await read()).toEqual({ hq: "#f2f3f8", pj: "#2fe0a0", classic: classicLight });

  await set("data-theme", "system");
  await page.emulateMedia({ colorScheme: "light" });
  expect((await read()).hq).toBe("#f2f3f8");
  await page.emulateMedia({ colorScheme: "dark" });
  expect((await read()).hq).toBe("#070b17");

  await set("data-ui", null);
  expect((await read()).hq).toBe("");
});
