// Builds the design gallery page from e2e/gallery.mjs's manifest.json.
// Usage: node e2e/gallery-page.mjs <galleryDir> <out.html> [--ext webp|png] [--fragment] [--prototype URL] [--commit SHA]
//   --ext       image extension to link (the hosted gallery uses .webp copies; the ZIP keeps the .png originals)
//   --fragment  write the page without <!doctype>/<html>/<head>/<body> (for a host that wraps it)
import fs from "node:fs";
import path from "node:path";

const [dir, outFile, ...rest] = process.argv.slice(2);
const opt = (k, d) => { const i = rest.indexOf(k); return i >= 0 ? rest[i + 1] : d; };
const ext = opt("--ext", "png");
const fragment = rest.includes("--fragment");
const protoUrl = opt("--prototype", "");
const commit = opt("--commit", "");
const m = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
const swap = (p) => p.replace(/\.png$/, `.${ext}`);
const states = m.states.map((s) => ({ ...s, images: Object.fromEntries(Object.entries(s.images).map(([k, v]) => [k, swap(v)])) }));
const ORDER = ["My Office", "Shell and navigation", "Messages", "Decisions", "Teams", "Agents", "Operations Topology", "Engineering", "Revenue", "Budgets and usage", "Approvals",
  "New Agent onboarding", "New Project onboarding", "Settings", "Design system", "Pop-out windows"];
const groups = [...new Set([...ORDER.filter((g) => states.some((s) => s.group === g)), ...states.map((s) => s.group)])];
const count = states.reduce((a, s) => a + Object.keys(s.images).length, 0);
const data = { groups, states, viewports: m.viewports, generated: m.generated, protoUrl, commit, count };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const body = `<title>Engineering HQ Gallery</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* Layout: a sticky control bar over a page map of sections; each section is a grid of screenshot cards; a lightbox compares sizes.
   One deliberate look: the same deep navy and purple as Engineering HQ, so the screenshots sit on their own ground. */
[hidden] { display: none !important; } /* the lightbox and buttons hide with the attribute, also when opened as a file */
:root {
  color-scheme: dark;
  --bg: #070b17; --panel: #0b1224; --raise: #121b35; --line: #19233f; --line-2: #243154;
  --text: #e9edf8; --text-2: #b4bdd6; --muted: #7c88a6; --accent: #6d5cff; --accent-2: #3f7bff; --focus: #8fa2ff; --warn: #ffb020; --ok: #2fe08c;
  --font: "Inter", "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif; --mono: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
  --r: 12px; --r-lg: 16px; --e1: inset 0 1px 0 rgba(255,255,255,.035), 0 1px 2px rgba(0,0,0,.28), 0 4px 14px rgba(0,0,0,.16);
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 var(--font); -webkit-font-smoothing: antialiased; }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--bg); }
a { color: var(--focus); }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 6px; }
.wrap { max-width: 1680px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
header.hero { padding-block: 28px 18px; display: grid; gap: 10px; }
.eyebrow { font: 600 11.5px var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1 { margin: 0; font: 700 clamp(26px, 4vw, 38px)/1.1 var(--font); letter-spacing: -.02em; text-wrap: balance; }
h1 em { font-style: normal; background: linear-gradient(90deg, #8b6bff, #5b8bff); -webkit-background-clip: text; background-clip: text; color: transparent; }
.lede { margin: 0; color: var(--text-2); max-width: 70ch; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; }
.fact { display: inline-flex; gap: 6px; align-items: center; padding: 4px 10px; border-radius: 999px; background: var(--panel); border: 1px solid var(--line); font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
.fact b { color: var(--text); }
.fact.is-warn { border-color: rgba(255,176,32,.35); color: var(--warn); }
.bar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: rgba(7,11,23,.94); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
.bar .wrap { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; padding-block: 10px; }
.seg { display: inline-flex; padding: 3px; gap: 2px; border-radius: 10px; background: var(--panel); border: 1px solid var(--line); flex-wrap: wrap; }
.seg button { border: 0; background: none; color: var(--text-2); font: 500 13px var(--font); padding: 6px 11px; border-radius: 8px; cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--raise); color: #fff; box-shadow: inset 0 0 0 1px rgba(111,123,255,.3); }
.search { flex: 1 1 220px; min-width: 0; height: 34px; border-radius: 10px; border: 1px solid var(--line-2); background: var(--panel); color: var(--text); padding: 0 12px; font: 13.5px var(--font); }
.map { display: flex; flex-wrap: wrap; gap: 6px; padding-block: 14px 4px; }
.map a { text-decoration: none; font-size: 12.5px; color: var(--text-2); padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line); background: var(--panel); }
.map a:hover { color: #fff; border-color: var(--line-2); }
.map a span { color: var(--muted); font-variant-numeric: tabular-nums; margin-left: 4px; }
section.grp { padding-block: 22px 6px; scroll-margin-top: 70px; }
section.grp h2 { margin: 0 0 12px; font: 650 19px var(--font); letter-spacing: -.01em; display: flex; gap: 10px; align-items: baseline; }
section.grp h2 small { font: 500 12.5px var(--font); color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); gap: 16px; }
.grid.is-phone { grid-template-columns: repeat(auto-fill, minmax(min(100%, 200px), 1fr)); }
.card { display: grid; gap: 0; border-radius: var(--r-lg); background: var(--panel); border: 1px solid var(--line); box-shadow: var(--e1); overflow: hidden; text-align: left; padding: 0; color: inherit; font: inherit; cursor: zoom-in; }
.card:hover { border-color: var(--line-2); }
.shot { aspect-ratio: 16 / 9; background: #050812; overflow: hidden; display: block; width: 100%; max-width: 100%; }
.shot.is-phone { aspect-ratio: 390 / 844; }
.shot.is-win { aspect-ratio: 4 / 3; }
.shot img { width: 100%; height: 100%; object-fit: cover; object-position: top left; display: block; }
.shot.is-win img { object-fit: contain; object-position: center; }
.cap { padding: 10px 12px 12px; display: grid; gap: 3px; min-width: 0; }
.cap b { font-weight: 600; font-size: 13.5px; }
.cap small { color: var(--muted); font-size: 12px; }
.cap code { font: 11.5px var(--mono); color: var(--muted); overflow-wrap: anywhere; }
.sizes { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
.sizes i { font: 600 10.5px var(--mono); font-style: normal; color: var(--text-2); padding: 1px 6px; border-radius: 999px; background: var(--raise); }
.empty { color: var(--muted); padding: 30px 0; }
footer.foot { padding-block: 30px 40px; color: var(--muted); font-size: 12.5px; display: grid; gap: 6px; }
.lb { position: fixed; inset: 0; z-index: 20; background: rgba(3,5,12,.92); display: grid; grid-template-rows: auto minmax(0, 1fr); padding: max(10px, env(safe-area-inset-top, 0px)) max(16px, env(safe-area-inset-right, 0px)) max(10px, env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-left, 0px)); }
.lb-top { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; padding-bottom: 10px; }
.lb-top h3 { margin: 0; font: 650 16px var(--font); flex: 1 1 260px; min-width: 0; }
.lb-top h3 small { display: block; font: 400 12.5px var(--font); color: var(--muted); }
.btn { border: 1px solid var(--line-2); background: var(--panel); color: var(--text); font: 500 13px var(--font); height: 32px; padding: 0 12px; border-radius: 9px; cursor: pointer; }
.btn:hover { border-color: var(--focus); }
.lb-view { overflow: auto; display: grid; place-items: start center; gap: 16px; min-height: 0; }
.lb-view img { max-width: 100%; height: auto; border-radius: 10px; box-shadow: 0 20px 60px rgba(0,0,0,.6); border: 1px solid var(--line); }
.lb-view.is-cmp { grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); align-items: start; place-items: start stretch; }
.lb-view figure { margin: 0; display: grid; gap: 6px; }
.lb-view figcaption { font: 600 11.5px var(--mono); color: var(--muted); }
@media (max-width: 600px) { .bar .wrap { gap: 8px; } .seg button { padding: 5px 8px; font-size: 12px; } }
@media (prefers-reduced-motion: no-preference) { .card { transition: border-color .15s ease, transform .2s cubic-bezier(.2,.8,.2,1); } .card:hover { transform: translateY(-2px); } }
</style>
<header class="hero wrap">
  <span class="eyebrow">CommandCenter · design reference</span>
  <h1>Engineering HQ <em>gallery</em></h1>
  <p class="lede">Every page and its important states, captured from the interactive prototype with mock data only. Pick a size, open any screenshot, and compare the same screen across sizes.</p>
  <div class="facts" id="facts"></div>
</header>
<div class="bar"><div class="wrap">
  <div class="seg" role="group" aria-label="Screen size" id="vps"></div>
  <input class="search" id="q" type="search" placeholder="Filter screens, for example budgets, wizard, pop-out" aria-label="Filter screens">
</div></div>
<main class="wrap">
  <nav class="map" id="map" aria-label="Page map"></nav>
  <div id="groups"></div>
</main>
<footer class="foot wrap" id="foot"></footer>
<div class="lb" id="lb" hidden role="dialog" aria-modal="true" aria-label="Screenshot">
  <div class="lb-top"><h3 id="lbt"></h3><div class="seg" role="group" aria-label="Size" id="lbs"></div>
    <button class="btn" type="button" id="lbc" aria-pressed="false">Compare sizes</button>
    <button class="btn" type="button" id="lbp" aria-label="Previous screenshot">←</button><button class="btn" type="button" id="lbn" aria-label="Next screenshot">→</button>
    <button class="btn" type="button" id="lbx">Close</button></div>
  <div class="lb-view" id="lbv"></div>
</div>
<script type="application/json" id="data">${JSON.stringify(data).replace(/</g, "\\u003c")}</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById("data").textContent);
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const VP = [...D.viewports.map((v) => ({ id: v.id, label: v.label })), { id: "all", label: "All sizes" }];
  const label = (k) => k === "window" ? "Own window" : k.endsWith("-full") ? (D.viewports.find((v) => v.id === k.replace("-full", ""))?.label ?? k) + ", whole page" : (D.viewports.find((v) => v.id === k)?.label ?? k);
  let vp = "1920", q = "", open = null, cmp = false, lbKey = null;
  try { vp = localStorage.getItem("hq-gallery-vp") || vp; } catch (e) {}
  const date = new Date(D.generated);
  $("facts").innerHTML = [
    '<span class="fact"><b>' + D.states.length + '</b> screens and states</span>',
    '<span class="fact"><b>' + D.count + '</b> screenshots</span>',
    '<span class="fact">Captured <b>' + date.toISOString().slice(0, 10) + '</b></span>',
    D.commit ? '<span class="fact">Prototype <b>' + esc(D.commit) + '</b></span>' : "",
    '<span class="fact is-warn">Mock data · not connected to ccd</span>',
    D.protoUrl ? '<a class="fact" href="' + esc(D.protoUrl) + '" target="_blank" rel="noopener">Open the interactive prototype ↗</a>' : "",
  ].join("");
  $("foot").innerHTML = "<span>Engineering HQ is an isolated design prototype (PR #64, a draft). Every figure, agent, task and conversation in these screenshots is mock data.</span>" +
    "<span>Regenerate: <code>node e2e/gallery.mjs</code>, then <code>node e2e/gallery-page.mjs</code>, in design/ui-prototypes/engineering-hq.</span>";
  function pick(s) {
    if (vp === "all") return s.images["1920"] ? "1920" : Object.keys(s.images)[0];
    if (s.images[vp]) return vp;
    return s.images.window ? "window" : null;
  }
  function render() {
    const s0 = q.toLowerCase();
    const vis = D.states.filter((s) => (!s0 || (s.title + " " + s.group + " " + s.note + " " + s.route + " " + s.id).toLowerCase().includes(s0)) && pick(s));
    $("vps").innerHTML = VP.map((v) => '<button type="button" aria-pressed="' + (v.id === vp) + '" data-vp="' + v.id + '">' + esc(v.label) + "</button>").join("");
    $("map").innerHTML = D.groups.map((g) => { const n = vis.filter((s) => s.group === g).length; return n ? '<a href="#g-' + g.toLowerCase().replace(/[^a-z0-9]+/g, "-") + '">' + esc(g) + "<span>" + n + "</span></a>" : ""; }).join("");
    $("groups").innerHTML = D.groups.map((g) => {
      const list = vis.filter((s) => s.group === g); if (!list.length) return "";
      const phone = vp === "phone";
      return '<section class="grp" id="g-' + g.toLowerCase().replace(/[^a-z0-9]+/g, "-") + '"><h2>' + esc(g) + "<small>" + list.length + " " + (list.length === 1 ? "screen" : "screens") + '</small></h2><div class="grid' + (phone ? " is-phone" : "") + '">' +
        list.map((s) => { const k = pick(s); const cls = k === "phone" ? " is-phone" : k === "window" ? " is-win" : "";
          return '<button type="button" class="card" id="' + esc(s.id) + '" data-id="' + esc(s.id) + '"><span class="shot' + cls + '"><img loading="lazy" decoding="async" src="' + esc(s.images[k]) + '" alt="' + esc(s.title) + '"></span>' +
            '<span class="cap"><b>' + esc(s.title) + "</b>" + (s.note ? "<small>" + esc(s.note) + "</small>" : "") + "<code>" + esc(s.route) + '</code><span class="sizes">' +
            Object.keys(s.images).map((x) => "<i>" + esc(x === "window" ? "window" : x) + "</i>").join("") + "</span></span></button>"; }).join("") + "</div></section>";
    }).join("") || '<p class="empty">No screens match “' + esc(q) + '”.</p>';
  }
  function show() {
    const s = D.states.find((x) => x.id === open); if (!s) return;
    const keys = Object.keys(s.images);
    if (!lbKey || !s.images[lbKey]) lbKey = s.images[vp] ? vp : keys[0];
    $("lbt").innerHTML = esc(s.title) + "<small>" + esc(s.group) + " · " + esc(s.route) + (s.note ? " · " + esc(s.note) : "") + "</small>";
    $("lbs").innerHTML = keys.map((k) => '<button type="button" data-k="' + k + '" aria-pressed="' + (!cmp && k === lbKey) + '">' + esc(label(k)) + "</button>").join("");
    $("lbc").setAttribute("aria-pressed", String(cmp)); $("lbc").hidden = keys.length < 2;
    const v = $("lbv"); v.classList.toggle("is-cmp", cmp);
    v.innerHTML = cmp ? keys.filter((k) => !k.endsWith("-full")).map((k) => '<figure><figcaption>' + esc(label(k)) + '</figcaption><img src="' + esc(s.images[k]) + '" alt="' + esc(s.title + ", " + label(k)) + '"></figure>').join("")
      : '<img src="' + esc(s.images[lbKey]) + '" alt="' + esc(s.title + ", " + label(lbKey)) + '">';
    v.scrollTop = 0;
  }
  function openId(id) { open = id; lbKey = null; cmp = false; $("lb").hidden = false; show(); $("lbx").focus(); try { history.replaceState(null, "", "#" + id); } catch (e) {} }
  function close() { const id = open; open = null; $("lb").hidden = true; try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {} const c = id && document.querySelector('[data-id="' + id + '"]'); if (c) c.focus(); }
  function step(d) { const vis = [...document.querySelectorAll(".card")].map((c) => c.dataset.id); const i = vis.indexOf(open); if (i < 0) return; open = vis[(i + d + vis.length) % vis.length]; lbKey = null; show(); }
  $("vps").addEventListener("click", (e) => { const b = e.target.closest("button[data-vp]"); if (!b) return; vp = b.dataset.vp; try { localStorage.setItem("hq-gallery-vp", vp); } catch (e2) {} render(); });
  $("q").addEventListener("input", (e) => { q = e.target.value; render(); });
  $("groups").addEventListener("click", (e) => { const c = e.target.closest(".card"); if (c) openId(c.dataset.id); });
  $("lbs").addEventListener("click", (e) => { const b = e.target.closest("button[data-k]"); if (!b) return; lbKey = b.dataset.k; cmp = false; show(); });
  $("lbc").addEventListener("click", () => { cmp = !cmp; show(); });
  $("lbp").addEventListener("click", () => step(-1)); $("lbn").addEventListener("click", () => step(1)); $("lbx").addEventListener("click", close);
  $("lb").addEventListener("click", (e) => { if (e.target === $("lb")) close(); });
  document.addEventListener("keydown", (e) => { if (!open) return; if (e.key === "Escape") close(); else if (e.key === "ArrowRight") step(1); else if (e.key === "ArrowLeft") step(-1); });
  render();
  const h = location.hash.slice(1); if (h && D.states.some((s) => s.id === h)) openId(h);
})();
</script>`;

const page = fragment ? body : `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n${body.replace("<header", "</head>\n<body>\n<header")}\n</body>\n</html>\n`;
fs.writeFileSync(outFile, page);
console.log(`wrote ${outFile}: ${states.length} states, ${count} images (.${ext})`);
void esc;
