// Screenshots of every page at 1920×1080 (and 1366×768 / a narrow pop-out size) for comparison with references/.
// Usage: node e2e/shots.mjs [baseUrl] [outDir]
import fs from "node:fs";
import { loadPlaywright } from "./pw.mjs";

const { chromium } = loadPlaywright();
const base = process.argv[2] ?? "http://127.0.0.1:5181/";
const out = process.argv[3] ?? "e2e/out";
fs.mkdirSync(out, { recursive: true });
const pages = [["topology", "00_topology"], ["office", "01_office"], ["messages/sv-lead", "02_messages"], ["decisions", "03_decisions"], ["teams/samvision", "04_teams"],
  ["engineering", "06_engineering"], ["revenue", "07_revenue_not_connected"], ["task/SV-025", "08_task_room"]];
const browser = await chromium.launch();
for (const [vw, vh, tag] of [[1920, 1080, ""], [1366, 768, "_1366"]]) {
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  for (const [route, name] of pages) {
    await page.goto(`${base}?nofeed#/${route}`);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${out}/${name}${tag}.png` });
  }
  await page.goto(`${base}?nofeed#/revenue`); await page.getByLabel("Fictional demo").check(); await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/07_revenue_demo${tag}.png` });
  await page.getByLabel("Fictional demo").uncheck();
  await ctx.close();
}
// Detached-window sizes.
const ctx = await browser.newContext({ viewport: { width: 980, height: 820 } });
const p = await ctx.newPage();
await p.goto(`${base}?nofeed#/pop/dm:sv-lead`); await p.waitForTimeout(500); await p.screenshot({ path: `${out}/pop_dm_980x820.png` });
await p.goto(`${base}?nofeed#/pop/panel:topology-inspector`); await p.setViewportSize({ width: 520, height: 860 }); await p.waitForTimeout(400); await p.screenshot({ path: `${out}/pop_inspector_520x860.png` });
await browser.close();
console.log("screenshots in", out);
