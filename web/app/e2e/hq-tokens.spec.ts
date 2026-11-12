// HQ's tokens in a real browser: they resolve only under <html data-ui="hq"> and follow Classic's theme (dark, light,
// system). tests/hq-tokens.test.ts checks the file itself, and parity.spec.ts proves Classic's pixels and every one of
// its variables stay the same with the attribute on or off.
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
  expect(await read()).toEqual({ hq: "#0f1012", pj: "#4fbf8f", classic: classicDark });

  await set("data-theme", "light");
  const classicLight = (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()));
  expect(await read()).toEqual({ hq: "#f5f5f3", pj: "#4fbf8f", classic: classicLight });

  await set("data-theme", "system");
  await page.emulateMedia({ colorScheme: "light" });
  expect((await read()).hq).toBe("#f5f5f3");
  await page.emulateMedia({ colorScheme: "dark" });
  expect((await read()).hq).toBe("#0f1012");

  // Classic Dark stays dark on a computer in light mode, and Light stays light on one in dark mode.
  await set("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  expect((await read()).hq).toBe("#0f1012");
  await set("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  expect((await read()).hq).toBe("#f5f5f3");

  await set("data-ui", null);
  expect((await read()).hq).toBe("");
});
