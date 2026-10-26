// Look closer at one QA finding: open a gallery state (or pop-out) in a theme and size, screenshot it, and describe
// the elements matching a selector (box, overflow, colours). Usage: node e2e/qa-shot.mjs <state-id> <theme> <vp-id|WxH> <selector> <out.png>
import { loadPlaywright } from "./pw.mjs";
import { VIEWPORTS, S, POPS } from "./states.mjs";
const { chromium } = loadPlaywright();
const [id, theme = "dark", vpId = "1920", sel = "body", out = "/tmp/qa-shot.png"] = process.argv.slice(2);
const BASE = process.env.BASE ?? "http://127.0.0.1:5181/";
const pop = POPS.find((x) => x[0] === id);
const st = S.find((x) => x.id === id);
const vp = pop ? { width: pop[3], height: pop[4] } : vpId.includes("x") ? { width: +vpId.split("x")[0], height: +vpId.split("x")[1] } : VIEWPORTS.find((v) => v.id === vpId);
if (!vp) { console.error(`Unknown size "${vpId}". Use ${VIEWPORTS.map((v) => v.id).join(", ")} or WxH.`); process.exit(2); }
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: vp.width, height: vp.height } });
const p = await ctx.newPage();
await p.goto(`${BASE}?nofeed#/office`);
await p.evaluate((t) => { localStorage.clear(); localStorage.setItem("hq.theme", JSON.stringify(t)); }, theme);
if (pop) {
  if (pop[2] === "panel:agent") { await p.goto(`${BASE}?nofeed#/agents`); await p.waitForTimeout(400); await p.getByRole("button", { name: /^Nova, / }).first().click(); await p.waitForTimeout(300); }
  await p.goto(`${BASE}?nofeed#/pop/${encodeURIComponent(pop[2])}`); await p.reload(); await p.waitForTimeout(800);
} else {
  await p.goto(`${BASE}${st?.query ?? "?nofeed"}#/${st?.route ?? id}`); await p.reload(); await p.waitForSelector(".app, .pop-body"); await p.waitForTimeout(450);
  if (st?.run) await st.run(p); await p.waitForTimeout(250);
}
await p.screenshot({ path: out });
const info = await p.evaluate(([sel, n]) => [...document.querySelectorAll(sel)].slice(0, n).map((el) => {
  const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  return { tag: el.tagName.toLowerCase(), cls: el.className?.baseVal ?? el.className, text: (el.textContent ?? "").trim().slice(0, 50), box: [r.x | 0, r.y | 0, r.width | 0, r.height | 0], sw: el.scrollWidth, cw: el.clientWidth, color: cs.color, bg: cs.backgroundColor, font: `${cs.fontSize} ${cs.fontWeight}` };
}), [sel, Number(process.env.N ?? 12)]);
const doc = await p.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
for (const e of info) console.log(`${e.tag}.${String(e.cls).split(" ").join(".")}  "${e.text}"  box=${e.box.join(",")}  scroll ${e.sw}/${e.cw}  ${e.color} on ${e.bg}  ${e.font}`);
console.log(`page scrollWidth/clientWidth: ${doc.join("/")}`);
await b.close();
