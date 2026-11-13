// QA sweep: every gallery state (pages, modals, menus, popovers, wizards) and every pop-out view, in Dark and Light,
// at 1920×1080, 1366×768, 1280×720 and phone. Each one is checked in the real browser for:
//   page errors and console errors · sideways scroll · clipped text (cut off with no ellipsis) · text that spills out of
//   its own box · low text contrast (WCAG AA: 4.5:1, 3:1 for large text; any CSS colour, including color-mix; text over a
//   gradient or image is skipped) · a dark slab in Light or a white slab in Dark ·
//   controls with no accessible name · duplicate ids · positive tabindex.
// Then three focused passes: keyboard (Tab walks every page; each stop must be visible and show a focus ring),
// reduced motion (no animation keeps running), and System theme (follows the OS live).
// Usage: npm run build && npm run preview &   then   node e2e/qa.mjs [baseUrl] [report.json] [only-state-ids]
// QA_THEMES=dark or QA_VP=1920,phone narrow a run. Exit code 1 when anything is found.
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./pw.mjs";
import { VIEWPORTS, S, POPS } from "./states.mjs";

const { chromium } = loadPlaywright();
const BASE = process.argv[2] ?? "http://127.0.0.1:5181/";
const OUT = process.argv[3] ?? "e2e/out/qa-report.json";
const ONLY = process.argv[4] ? new Set(process.argv[4].split(",")) : null;
const THEMES = (process.env.QA_THEMES ?? "dark,light").split(",");
const ONLY_VP = process.env.QA_VP ? new Set(process.env.QA_VP.split(",")) : null;
const CONCURRENCY = Math.max(1, Math.floor(Number(process.env.QA_JOBS ?? 3)) || 3);

// Runs inside the page. Returns a list of findings for what is on screen now.
function audit() {
  const out = [];
  const vis = (el) => {
    const r = el.getBoundingClientRect(); if (r.width <= 1 || r.height <= 1) return false;   // 1 px: visually hidden, for screen readers
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden" || cs.visibility === "collapse") return false;
      if (Number(cs.opacity) < 0.05) return false;
      if (e.getAttribute("aria-hidden") === "true" || e.hasAttribute("inert")) return false;
    }
    return true;
  };
  const desc = (el) => {
    const cls = [...el.classList].slice(0, 3).join(".");
    const lab = el.getAttribute("aria-label");
    return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}${lab ? `[aria-label="${lab.slice(0, 40)}"]` : ""}`;
  };
  const own = (el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").replace(/\s+/g, " ").trim();
  // Any CSS colour to sRGB. rgb()/rgba() are read directly; anything else (color-mix gives oklab() or color(srgb …))
  // is painted on a 1×1 canvas and read back. Returns undefined when the browser cannot paint it, so the caller can
  // report it instead of skipping it.
  const cv = document.createElement("canvas"); cv.width = cv.height = 1; const g2 = cv.getContext("2d", { willReadFrequently: true });
  const seen = new Map();
  const parse = (c) => {
    if (!c || c === "transparent") return null;
    if (seen.has(c)) return seen.get(c);
    let v;
    const m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m) { const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); v = { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    else {
      g2.clearRect(0, 0, 1, 1); g2.fillStyle = "#010203"; g2.fillStyle = c;
      if (g2.fillStyle !== "#010203") { g2.fillRect(0, 0, 1, 1); const d = g2.getImageData(0, 0, 1, 1).data; v = { r: d[0], g: d[1], b: d[2], a: d[3] / 255 }; }
    }
    seen.set(c, v); return v;
  };
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const lum = (c) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const over = (top, under) => { const a = top.a + under.a * (1 - top.a); if (a <= 0) return { r: 0, g: 0, b: 0, a: 0 }; return { r: (top.r * top.a + under.r * under.a * (1 - top.a)) / a, g: (top.g * top.a + under.g * under.a * (1 - top.a)) / a, b: (top.b * top.a + under.b * under.a * (1 - top.a)) / a, a }; };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  // The colour behind an element: its own and its ancestors' backgrounds, composited. null when a gradient or image sits behind.
  const backdrop = (el) => {
    const layers = []; let op = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== "none" && !/^url\(/.test(cs.backgroundImage) && e !== document.documentElement && e !== document.body && !e.classList.contains("content")) return null;
      const c = parse(cs.backgroundColor); if (c === undefined) return undefined; if (c && c.a > 0) { layers.push(c); if (c.a >= 0.99) return { bg: layers.reverse().reduce((u, t) => over(t, u)), op }; }
      op *= Number(cs.opacity);
    }
    const root = parse(getComputedStyle(document.body).backgroundColor) ?? { r: 255, g: 255, b: 255, a: 1 };
    return { bg: [root, ...layers.reverse()].reduce((u, t) => over(t, u)), op };
  };
  const light = document.documentElement.dataset.hqTheme === "light";
  const ISLAND = ".term, .slack-phone, .theme-pick, .appearance-thumb, .ap-thumb, .kbd, kbd, .av, .avatar, [class*='thumb']";
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest("svg") || el.tagName === "SCRIPT" || el.tagName === "STYLE" || el.tagName === "NOSCRIPT") continue;
    const t = own(el);
    if (t && vis(el)) {
      const cs = getComputedStyle(el);
      // Clipped: content wider than the box, box clips it, and no ellipsis says so.
      const clips = /hidden|clip/.test(cs.overflowX) || /hidden|clip/.test(cs.overflow);
      if (el.scrollWidth > el.clientWidth + 2 && clips && cs.textOverflow !== "ellipsis" && cs.webkitLineClamp === "none" && el.clientWidth > 0)
        out.push({ kind: "clipped-text", el: desc(el), text: t.slice(0, 60), detail: `${el.scrollWidth}>${el.clientWidth}` });
      if (el.scrollWidth > el.clientWidth + 2 && cs.textOverflow === "ellipsis")
        out.push({ kind: "ellipsis", el: desc(el), text: t.slice(0, 60), detail: `${el.scrollWidth}>${el.clientWidth}` });
      // Spills: a text-only box (a chip, button or label) whose text runs past its edge.
      if (!el.children.length && cs.display !== "inline" && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 3 && !clips)
        out.push({ kind: "text-spills", el: desc(el), text: t.slice(0, 60), detail: `${el.scrollWidth}>${el.clientWidth}` });
      // Contrast.
      const disabled = el.closest(":disabled, [aria-disabled='true'], .is-disabled, [data-disabled]");
      const fg = parse(cs.color); const b = backdrop(el);
      if (!disabled && (fg === undefined || b === undefined)) out.push({ kind: "contrast-unmeasured", el: desc(el), text: t.slice(0, 60), detail: `${cs.color} on ${cs.backgroundColor}` });
      else if (fg && b && !disabled) {
        const eff = over({ ...fg, a: fg.a * b.op }, b.bg);
        const r = ratio(eff, b.bg);
        const px = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
        const need = px >= 24 || (px >= 18.66 && bold) ? 3 : 4.5;
        if (r < need) out.push({ kind: "contrast", el: desc(el), text: t.slice(0, 60), detail: `${r.toFixed(2)} < ${need} (${cs.color} on rgb(${b.bg.r | 0},${b.bg.g | 0},${b.bg.b | 0}), ${px}px)` });
      }
    }
    // A surface in the wrong theme: a large, near-neutral slab far from the theme's ground.
    const r = el.getBoundingClientRect();
    if (r.width * r.height > 6000 && !el.closest(ISLAND)) {
      const c = parse(getComputedStyle(el).backgroundColor);
      if (c && c.a > 0.6) {
        const L = lum(c), sat = Math.max(c.r, c.g, c.b) - Math.min(c.r, c.g, c.b);
        if (light && L < 0.06 && sat < 50 && vis(el)) out.push({ kind: "dark-slab-in-light", el: desc(el), text: own(el).slice(0, 40), detail: getComputedStyle(el).backgroundColor });
        if (!light && L > 0.6 && sat < 40 && vis(el)) out.push({ kind: "light-slab-in-dark", el: desc(el), text: own(el).slice(0, 40), detail: getComputedStyle(el).backgroundColor });
      }
    }
  }
  // Names for controls.
  const name = (el) => {
    const l = el.getAttribute("aria-label"); if (l && l.trim()) return l;
    const lb = el.getAttribute("aria-labelledby"); if (lb) { const s = lb.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim(); if (s) return s; }
    if (el.id) { const f = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (f?.textContent.trim()) return f.textContent; }
    const wrap = el.closest("label"); if (wrap && wrap.textContent.trim()) return wrap.textContent;
    const txt = (el.innerText ?? el.textContent ?? "").trim(); if (txt && !["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) return txt;
    if (el.getAttribute("title")) return el.getAttribute("title");
    if (el.tagName === "INPUT" && (el.type === "submit" || el.type === "button") && el.value) return el.value;
    return "";
  };
  for (const el of document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=menuitem], [role=radio], [role=checkbox], [role=switch], [role=option]"))
    if (vis(el) && !name(el)) out.push({ kind: "no-name", el: desc(el), text: "", detail: el.outerHTML.slice(0, 120) });
  const ids = new Map(); for (const el of document.querySelectorAll("[id]")) ids.set(el.id, (ids.get(el.id) ?? 0) + 1);
  for (const [id, n] of ids) if (n > 1) out.push({ kind: "duplicate-id", el: `#${id}`, text: "", detail: `${n} elements` });
  for (const el of document.querySelectorAll("[tabindex]")) if (Number(el.getAttribute("tabindex")) > 0) out.push({ kind: "positive-tabindex", el: desc(el), text: own(el).slice(0, 40), detail: el.getAttribute("tabindex") });
  const d = document.documentElement, m = document.querySelector("main.content");
  const side = Math.max(d.scrollWidth - d.clientWidth, m ? m.scrollWidth - m.clientWidth : 0);
  if (side > 2) out.push({ kind: "sideways-scroll", el: "page", text: "", detail: `${side}px` });
  return out;
}

const findings = [];
const add = (state, theme, vp, f) => findings.push({ state, theme, vp, ...f });
async function open(browser, vp, theme, route, query = "?nofeed", opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1, ...opts });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(`pageerror: ${String(e).slice(0, 160)}`));
  p.on("console", (m) => { if (m.type() === "error") errs.push(`console: ${m.text().slice(0, 160)}`); });
  await p.goto(`${BASE}${query}#/office`);
  await p.evaluate((t) => { try { localStorage.clear(); sessionStorage.clear(); localStorage.setItem("hq.theme", JSON.stringify(t)); } catch { /* none */ } }, theme);
  await p.goto(`${BASE}${query}#/${route}`); await p.reload();
  await p.waitForSelector(".app, .pop-body", { timeout: 8000 }); await p.waitForTimeout(450);
  return { ctx, p, errs };
}

const jobs = [];
for (const st of S) {
  if (st.group.startsWith("Light theme")) continue;          // the same pages are swept in Light below
  if (ONLY && !ONLY.has(st.id)) continue;
  for (const vp of VIEWPORTS) {
    if (st.only ? !st.only.includes(vp.id) : vp.id === "phone" && !st.phone) continue;
    if (ONLY_VP && !ONLY_VP.has(vp.id)) continue;
    for (const theme of THEMES) jobs.push({ kind: "state", st, vp, theme });
  }
}
for (const [id, , view, w, h] of POPS) {
  if (ONLY && !ONLY.has(id)) continue;
  for (const theme of THEMES) jobs.push({ kind: "pop", id, view, vp: { id: `${w}x${h}`, width: w, height: h }, theme });
}

const browser = await chromium.launch();
let done = 0;
async function run(job) {
  const label = job.kind === "pop" ? job.id : job.st.id;
  let h;
  try {
    if (job.kind === "pop") {
      h = await open(browser, job.vp, job.theme, "office");
      if (job.view === "panel:agent") { await h.p.goto(`${BASE}?nofeed#/agents`); await h.p.waitForTimeout(300); await h.p.getByRole("button", { name: /^Nova, / }).first().click(); await h.p.waitForTimeout(300); }
      await h.p.goto(`${BASE}?nofeed#/pop/${encodeURIComponent(job.view)}`); await h.p.waitForTimeout(700);
    } else {
      h = await open(browser, job.vp, job.theme, job.st.route, job.st.query);
      if (job.st.run) await job.st.run(h.p);
      await h.p.waitForTimeout(200);
    }
    const got = await h.p.evaluate(() => document.documentElement.dataset.hqTheme);
    if (got !== job.theme) add(label, job.theme, job.vp.id, { kind: "theme-not-applied", el: "html", text: "", detail: `data-hq-theme=${got}` });
    for (const f of await h.p.evaluate(audit)) add(label, job.theme, job.vp.id, f);
    for (const e of h.errs) add(label, job.theme, job.vp.id, { kind: "error", el: "", text: "", detail: e });
  } catch (e) {
    add(label, job.theme, job.vp.id, { kind: "setup-failed", el: "", text: "", detail: String(e.message).split("\n")[0] });
  }
  await h?.ctx.close().catch(() => {});
  done++; if (done % 25 === 0) process.stdout.write(`${done}/${jobs.length} `);
}
const queue = [...jobs];
await Promise.all(Array.from({ length: CONCURRENCY }, async () => { while (queue.length) await run(queue.shift()); }));

// Keyboard: Tab through each page (first 70 stops); every stop must be on screen and show a focus ring. Runs with
// reduced motion, so the ring is read after its transition, not halfway through it. The ring check blurs and
// re-focuses each stop, which also fires the page's focus handlers (tooltips); that is harmless here.
const PAGES = ["office", "messages/sv-lead", "decisions", "decisions/sv-025", "teams/samvision", "agents", "topology", "engineering", "task/SV-025", "revenue", "budgets", "approvals", "settings/appearance", "design"];
if (!ONLY) for (const route of PAGES) for (const theme of THEMES) {
  const vp = VIEWPORTS[1];
  let h;
  try {
  h = await open(browser, vp, theme, route, "?nofeed", { reducedMotion: "reduce" });
  const seen = new Set(); let lost = 0;
  for (let i = 0; i < 70; i++) {
    await h.p.keyboard.press("Tab");
    const s = await h.p.evaluate(() => {
      const el = document.activeElement; if (!el || el === document.body) return { body: true };
      const r = el.getBoundingClientRect();
      // A focus ring may sit on the element, on a wrapper (a search field) or on a child (a theme thumbnail): compare
      // outline, box-shadow and border colour of all three while focused and after a blur.
      const near = [el, el.parentElement, el.parentElement?.parentElement, ...el.children].filter(Boolean);
      const look = () => near.map((n) => { const c = getComputedStyle(n); return `${c.outlineStyle} ${c.outlineWidth} ${c.outlineColor}|${c.boxShadow}|${c.borderColor}`; }).join(";");
      const focused = look(); el.blur(); const blurred = look(); el.focus();
      const ring = focused !== blurred;
      const cls = [...el.classList].slice(0, 3).join(".");
      return { key: `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}|${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40)}`,
        ring, onScreen: r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth, fv: el.matches(":focus-visible") };
    });
    if (s.body) { lost++; continue; }
    if (seen.has(s.key)) continue; seen.add(s.key);
    if (!s.onScreen) add(route, theme, vp.id, { kind: "focus-offscreen", el: s.key, text: "", detail: "focused element not visible" });
    if (!s.ring) add(route, theme, vp.id, { kind: "focus-no-ring", el: s.key, text: "", detail: s.fv ? ":focus-visible but no outline/box-shadow" : "not :focus-visible" });
  }
  if (seen.size < 5) add(route, theme, vp.id, { kind: "focus-few-stops", el: "", text: "", detail: `${seen.size} distinct stops, ${lost} on body` });
  } catch (e) { add(route, theme, vp.id, { kind: "setup-failed", el: "keyboard", text: "", detail: String(e.message).split("\n")[0] }); }
  await h?.ctx.close().catch(() => {});
}

// Reduced motion: with the OS asking for less motion, nothing keeps animating (one-shot fades of ≤ 10 ms are fine).
if (!ONLY) for (const route of ["office", "topology", "teams/samvision", "messages/sv-lead", "task/SV-025", "engineering"]) {
  let h;
  try {
  h = await open(browser, VIEWPORTS[0], "dark", route, "?nofeed", { reducedMotion: "reduce" });
  await h.p.waitForTimeout(600);
  const anim = await h.p.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").map((a) => {
    const t = a.effect?.getComputedTiming?.(); const tgt = a.effect?.target;
    return { name: a.animationName ?? a.transitionProperty ?? "anim", dur: t?.duration, it: t?.iterations, el: tgt ? `${tgt.tagName?.toLowerCase()}.${[...(tgt.classList ?? [])].slice(0, 2).join(".")}` : "" };
  }).filter((a) => (typeof a.dur === "number" ? a.dur : 0) > 10));
  for (const a of anim) add(route, "dark", "1920", { kind: "motion-under-reduce", el: a.el, text: a.name, detail: `${a.dur}ms × ${a.it}` });
  } catch (e) { add(route, "dark", "1920", { kind: "setup-failed", el: "reduced motion", text: "", detail: String(e.message).split("\n")[0] }); }
  await h?.ctx.close().catch(() => {});
}

// System theme: follows the OS, and switches live when the OS does.
if (!ONLY) {
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, colorScheme: "light" });
  try {
  const p = await ctx.newPage();
  await p.goto(`${BASE}?nofeed&theme=system#/office`); await p.waitForSelector(".app");
  const a = await p.evaluate(() => document.documentElement.dataset.hqTheme);
  await p.emulateMedia({ colorScheme: "dark" }); await p.waitForTimeout(300);
  const b = await p.evaluate(() => document.documentElement.dataset.hqTheme);
  await p.emulateMedia({ colorScheme: "light" }); await p.waitForTimeout(300);
  const c = await p.evaluate(() => document.documentElement.dataset.hqTheme);
  if (a !== "light" || b !== "dark" || c !== "light") add("system-theme", "system", "1366", { kind: "system-theme", el: "html", text: "", detail: `light OS→${a}, dark OS→${b}, light again→${c}` });
  } catch (e) { add("system-theme", "system", "1366", { kind: "setup-failed", el: "system theme", text: "", detail: String(e.message).split("\n")[0] }); }
  await ctx.close().catch(() => {});
}
await browser.close();

// Summary: the same finding on many states is one row.
const groups = new Map();
for (const f of findings) {
  if (f.kind === "ellipsis") continue;
  const k = `${f.kind}|${f.el}|${f.text}`;
  const g = groups.get(k) ?? { kind: f.kind, el: f.el, text: f.text, detail: f.detail, where: new Set() };
  g.where.add(`${f.state}@${f.vp}/${f.theme}`); groups.set(k, g);
}
const rows = [...groups.values()].map((g) => ({ ...g, where: [...g.where] })).sort((a, b) => a.kind.localeCompare(b.kind) || b.where.length - a.where.length);
const ellipsis = findings.filter((f) => f.kind === "ellipsis" && f.vp === "1920");
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ when: new Date().toISOString(), jobs: jobs.length, rows, ellipsisAt1920: ellipsis }, null, 1));
const byKind = {}; for (const r of rows) byKind[r.kind] = (byKind[r.kind] ?? 0) + 1;
console.log(`\n${jobs.length} state × theme × size checks${ONLY ? "" : `, ${PAGES.length * THEMES.length} keyboard walks, reduced motion and System theme passes`}.`);
console.log(rows.length ? `FINDINGS (distinct): ${JSON.stringify(byKind)}` : "No findings.");
for (const r of rows.slice(0, 80)) console.log(`  ${r.kind}  ${r.el}  "${r.text}"  ${r.detail}  ×${r.where.length} e.g. ${r.where.slice(0, 2).join(", ")}`);
console.log(`Ellipsis truncations at 1920 (for review, not failures): ${ellipsis.length}. Report: ${OUT}`);
process.exit(rows.length ? 1 : 0);
