// The design gallery: every page and its important states, at 1920×1080, 1366×768, 1280×720 and phone (390×844 @2x),
// plus pop-out windows at their own sizes. Writes PNGs and manifest.json, which e2e/gallery-page.mjs turns into the gallery.
// Usage: npm run build && npm run preview &   then   node e2e/gallery.mjs [baseUrl] [outDir] [only-state-ids,comma-separated]
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./pw.mjs";
import { VIEWPORTS, S, POPS, wait, click } from "./states.mjs";

const { chromium } = loadPlaywright();
const BASE = process.argv[2] ?? "http://127.0.0.1:5181/";
const OUT = process.argv[3] ?? "e2e/out/gallery";
const ONLY = process.argv[4] ? new Set(process.argv[4].split(",")) : null;
// GALLERY_VP=phone (or 1920,1366) retakes only those sizes and keeps the others from the existing manifest.
const ONLY_VP = process.env.GALLERY_VP ? new Set(process.env.GALLERY_VP.split(",")) : null;
fs.mkdirSync(OUT, { recursive: true });


const errors = [];
const warnings = [];
async function fresh(ctx, route, query = "?nofeed") {
  const p = await ctx.newPage();
  p.on("pageerror", (e) => errors.push(`${route}: ${e}`));
  await p.goto(`${BASE}${query}#/office`);
  await p.evaluate(() => { try { localStorage.clear(); sessionStorage.clear(); } catch { /* none */ } });
  await p.goto(`${BASE}${query}#/${route}`); await p.reload(); await p.waitForSelector(".app, .pop-body", { timeout: 8000 }); await wait(p, 450);
  return p;
}
const file = (group, id, vp) => `${group.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}/${id}__${vp}.png`;
const manifest = { generated: new Date().toISOString(), viewports: VIEWPORTS, states: [] };
const browser = await chromium.launch();
for (const st of S) {
  if (ONLY && !ONLY.has(st.id)) continue;
  const entry = { id: st.id, group: st.group, title: st.title, note: st.note, route: `#/${st.route}`, images: {} };
  for (const vp of VIEWPORTS) {
    if (st.only ? !st.only.includes(vp.id) : vp.id === "phone" && !st.phone) continue;
    if (ONLY_VP && !ONLY_VP.has(vp.id)) continue;
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: vp.scale });
    try {
      const p = await fresh(ctx, st.route, st.query);
      if (st.run) await st.run(p);
      const rel = file(st.group, st.id, vp.id); fs.mkdirSync(path.dirname(path.join(OUT, rel)), { recursive: true });
      await p.screenshot({ path: path.join(OUT, rel) }); entry.images[vp.id] = rel;
      const over = await p.evaluate(() => { const d = document.documentElement; const m = document.querySelector("main.content"); return Math.max(d.scrollWidth - d.clientWidth, m ? m.scrollWidth - m.clientWidth : 0); });
      if (over > 2) { (entry.overflow ??= []).push(vp.id); warnings.push(`${st.id} @ ${vp.id}: page scrolls sideways by ${over}px`); }
      if (st.full && (vp.id === "1920" || vp.id === "phone")) {
        const extra = await p.evaluate(() => { const m = document.querySelector("main.content"); return m ? Math.max(0, m.scrollHeight - m.clientHeight) : 0; });
        if (extra > 40) {
          await p.setViewportSize({ width: vp.width, height: Math.min(vp.height + extra, 6000) }); await wait(p, 300);
          const relF = file(st.group, `${st.id}-full`, vp.id); await p.screenshot({ path: path.join(OUT, relF) }); entry.images[`${vp.id}-full`] = relF;
        }
      }
    } catch (e) { errors.push(`${st.id} @ ${vp.id}: ${String(e.message).split("\n")[0]}`); }
    await ctx.close();
  }
  manifest.states.push(entry); process.stdout.write(".");
}
// Pop-out windows, plus the main window showing a popped tab as shaded with Focus window / Return here.
for (const [id, title, view, w, h] of POPS) {
  if ((ONLY && !ONLY.has(id)) || ONLY_VP) continue;
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  try {
    if (view === "panel:agent") { const p0 = await fresh(ctx, "agents"); await p0.getByRole("button", { name: /^Nova, / }).first().click(); await wait(p0, 300); await p0.close(); }
    const p = await ctx.newPage(); p.on("pageerror", (e) => errors.push(`${id}: ${e}`));
    await p.goto(`${BASE}?nofeed#/pop/${encodeURIComponent(view)}`); await wait(p, 600);
    const rel = file("Pop-out windows", id, `${w}x${h}`); fs.mkdirSync(path.dirname(path.join(OUT, rel)), { recursive: true });
    await p.screenshot({ path: path.join(OUT, rel) });
    manifest.states.push({ id, group: "Pop-out windows", title, note: `${w}×${h}, the size it opens at. Drag it to any monitor.`, route: `#/pop/${view}`, images: { window: rel } });
  } catch (e) { errors.push(`${id}: ${String(e.message).split("\n")[0]}`); }
  await ctx.close(); process.stdout.write(".");
}
if ((!ONLY || ONLY.has("pop-main-shaded")) && !ONLY_VP) {
  const entry = { id: "pop-main-shaded", group: "Pop-out windows", title: "Main window while Topology is popped out", note: "The tab stays, shaded with ↗; the page offers Focus window and Return here.", route: "#/topology", images: {} };
  for (const vp of VIEWPORTS.filter((v) => v.id !== "phone")) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    try {
      const m = await fresh(ctx, "topology");
      const [w] = await Promise.all([m.waitForEvent("popup"), m.locator('[data-testid="pop-page:topology"]:visible').first().click()]);
      await w.waitForSelector('[data-testid="popout-window"]'); await wait(m, 600);
      const rel = file("Pop-out windows", "pop-main-shaded", vp.id); await m.screenshot({ path: path.join(OUT, rel) }); entry.images[vp.id] = rel;
    } catch (e) { errors.push(`pop-main-shaded @ ${vp.id}: ${String(e.message).split("\n")[0]}`); }
    await ctx.close();
  }
  manifest.states.push(entry);
}
await browser.close();
const prev = (ONLY || ONLY_VP) && fs.existsSync(path.join(OUT, "manifest.json")) ? JSON.parse(fs.readFileSync(path.join(OUT, "manifest.json"), "utf8")) : null;
if (prev) {
  const old = new Map(prev.states.map((s) => [s.id, s]));
  // A partial run keeps the sizes it did not retake.
  for (const s of manifest.states) { const o = old.get(s.id); if (o && ONLY_VP) s.images = { ...o.images, ...s.images }; }
  const ids = new Set(manifest.states.map((s) => s.id)); manifest.states = [...prev.states.filter((s) => !ids.has(s.id)), ...manifest.states];
}
// Keep the order the states are defined in, however many partial re-runs merged into the manifest.
const ORDER_IDS = [...S.map((s) => s.id), ...POPS.map((p) => p[0]), "pop-main-shaded"];
const rank = (id) => { const i = ORDER_IDS.indexOf(id); return i < 0 ? ORDER_IDS.length : i; };
manifest.states.sort((a, b) => rank(a.id) - rank(b.id));
fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 1));
const n = manifest.states.reduce((a, s) => a + Object.keys(s.images).length, 0);
console.log(`\n${manifest.states.length} states, ${n} screenshots in ${OUT}`);
if (warnings.length) console.log(`WARNINGS (${warnings.length}):\n${warnings.join("\n")}`);
if (errors.length) { console.log(`PROBLEMS (${errors.length}):\n${errors.join("\n")}`); process.exitCode = 1; }
