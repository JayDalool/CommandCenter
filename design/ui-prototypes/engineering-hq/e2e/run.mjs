// Real-browser acceptance tests for pop-out windows (Chromium via Playwright, real popup windows).
// Usage: node e2e/run.mjs [baseUrl]   (serve the build first: npm run build && npm run preview)
import fs from "node:fs";
import { loadPlaywright } from "./pw.mjs";

const { chromium } = loadPlaywright();
const BASE = process.argv[2] ?? "http://127.0.0.1:5181/";
const OUT = "e2e/out"; fs.mkdirSync(OUT, { recursive: true });
const results = [];
const browser = await chromium.launch();

async function test(name, fn) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 950 } });
  const t0 = Date.now();
  try { await fn(ctx); results.push({ name, ok: true, ms: Date.now() - t0 }); console.log(`  ✓ ${name}`); }
  catch (e) { results.push({ name, ok: false, ms: Date.now() - t0, error: String(e?.message ?? e).split("\n")[0] }); console.log(`  ✗ ${name}\n      ${String(e?.message ?? e).split("\n")[0]}`); }
  finally { await ctx.close().catch(() => {}); }
}
const assert = (c, m) => { if (!c) throw new Error(m); };
async function main(ctx, route = "office", q = "?nofeed") { const p = await ctx.newPage(); await p.goto(`${BASE}${q}#/${route}`); await p.waitForSelector(".side"); return p; }
async function pop(page, testid) {
  const [w] = await Promise.all([page.waitForEvent("popup"), page.locator(`[data-testid="${testid}"]`).first().click()]);
  await w.waitForSelector('[data-testid="popout-window"]'); return w;
}
const shaded = (page, id) => page.locator(`[data-testid="tab-${id}"].is-out`).count();
const placeholder = (page, id) => page.locator(`[data-testid="placeholder-${id}"]`).count();
async function until(fn, ms = 8000, step = 150) { const end = Date.now() + ms; while (Date.now() < end) { if (await fn()) return true; await new Promise((r) => setTimeout(r, step)); } return false; }

console.log("Pop-out acceptance (real windows)");
const PAGES = ["office", "messages", "decisions", "teams", "topology", "engineering", "revenue"];

await test("each of the 7 pages pops out to a real window; original tab shaded; Return here reattaches and closes the window", async (ctx) => {
  const m = await main(ctx);
  for (const p of PAGES) {
    await m.goto(`${BASE}?nofeed#/${p}`);
    const w = await pop(m, `pop-page:${p}`);
    assert(w.url().endsWith(`#/pop/page%3A${p}`), `popup url ${w.url()}`);
    assert(await until(async () => (await shaded(m, `page:${p}`)) === 1), `${p}: tab not shaded`);
    assert(await placeholder(m, `page:${p}`) === 1, `${p}: no placeholder`);
    assert(await w.locator(".pop-body h1").count() >= 1, `${p}: popup empty`);
    if (p === "topology") { await m.screenshot({ path: `${OUT}/popout_shaded_main.png` }); await w.screenshot({ path: `${OUT}/popout_window_topology.png` }); }
    const closed = w.waitForEvent("close");
    await m.locator(`[data-testid="placeholder-page:${p}"] >> text=Return here`).click();
    await closed;
    assert(await until(async () => (await placeholder(m, `page:${p}`)) === 0), `${p}: not reattached`);
  }
});

await test("SamVision lead DM: pop out, switch conversations in main, send from the pop-out, no loss or duplicate", async (ctx) => {
  const m = await main(ctx, "messages/sv-lead");
  const w = await pop(m, "pop-dm:sv-lead");
  await m.goto(`${BASE}?nofeed#/messages/nova`);
  assert(await m.locator('section[aria-label="Conversation with Nova"]').count() === 1, "main could not switch conversation");
  const before = await w.locator(".msg").count();
  await w.getByLabel("Message Claude").fill("Status update on SV-025?");
  await w.getByRole("button", { name: "Send" }).click();
  await w.getByLabel("Message Claude").press("Enter");      // empty draft: must not send again
  assert(await until(async () => (await w.locator(".msg").count()) === before + 2), "expected exactly my message + one reply");
  await m.goto(`${BASE}?nofeed#/messages/sv-lead`);
  assert(await placeholder(m, "dm:sv-lead") === 1, "main should show the DM as open elsewhere");
  const closed = w.waitForEvent("close");
  await m.locator('[data-testid="placeholder-dm:sv-lead"] >> text=Return here').click(); await closed;
  assert(await until(async () => (await m.locator(".thread .msg").count()) === before + 2), "returned DM lost or duplicated messages");
});

await test("Task Room, terminal, Topology and Revenue popped out together; resized narrow without horizontal overflow", async (ctx) => {
  const m = await main(ctx, "task/SV-025");
  const ws = [await pop(m, "pop-task:SV-025")];
  await m.locator(".tab", { hasText: "SV-025 Task Room" }).locator('[data-testid="pop-task:SV-025"]').count();
  await m.goto(`${BASE}?nofeed#/topology`); ws.push(await pop(m, "pop-page:topology"));
  await m.goto(`${BASE}?nofeed#/revenue`); ws.push(await pop(m, "pop-page:revenue"));
  // the terminal pane lives inside the popped Task Room: pop it out of that window
  ws.push(await pop(ws[0], "pop-term:SV-025"));
  assert(await until(async () => (await m.locator(".tab.is-out").count()) === 4), "expected 4 shaded tabs");
  for (const [i, w] of ws.entries()) {
    for (const [wd, ht] of [[1280, 800], [820, 640]]) {
      await w.setViewportSize({ width: wd, height: ht }); await w.waitForTimeout(150);
      const over = await w.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      assert(over <= 1, `window ${i} overflows by ${over}px at ${wd}px`);
    }
    if (i === 1) await w.screenshot({ path: `${OUT}/pop_topology_820x640.png` });
  }
});

await test("re-popping an already popped tab focuses the existing window (no second window, one owner)", async (ctx) => {
  const m = await main(ctx, "teams");
  await pop(m, "pop-page:teams");
  const pagesBefore = ctx.pages().length;
  await m.locator('[data-testid="tab-page:teams"] a').click();       // clicking the shaded tab focuses
  await m.locator('[data-testid="placeholder-page:teams"] >> text=Focus window').click();
  await m.keyboard.press("Alt+Shift+O");
  await m.waitForTimeout(400);
  assert(ctx.pages().length === pagesBefore, `a second window opened (${ctx.pages().length} vs ${pagesBefore})`);
});

await test("closing the pop-out with the OS close button restores the tab (and stops nothing)", async (ctx) => {
  const m = await main(ctx, "engineering");
  const w = await pop(m, "pop-page:engineering");
  await w.close({ runBeforeUnload: true });
  assert(await until(async () => (await placeholder(m, "page:engineering")) === 0, 6000), "tab still shaded after close");
  assert(await m.getByText("is back in this window").count() >= 1, "no notice that the view came back");
});

await test("pop-out dies without saying goodbye (crash: no pagehide) is recovered via its Web Lock; no permanent shaded tab", async (ctx) => {
  const m = await main(ctx, "revenue");
  const w = await pop(m, "pop-page:revenue");
  // Swallow pagehide so the window cannot mark itself closing, like a renderer crash or a killed process.
  await w.evaluate(() => window.addEventListener("pagehide", (e) => e.stopImmediatePropagation(), true));
  await w.close();
  assert(await until(async () => (await placeholder(m, "page:revenue")) === 0, 9000), "crashed window left the tab shaded");
});

await test("reloading the pop-out keeps it the owner", async (ctx) => {
  const m = await main(ctx, "decisions");
  const w = await pop(m, "pop-page:decisions");
  await w.reload(); await w.waitForSelector('[data-testid="popout-window"]');
  await m.waitForTimeout(3500);
  assert(await placeholder(m, "page:decisions") === 1, "main took the view back during a reload");
  assert(await w.locator(".pop-body h1").count() >= 1, "reloaded pop-out lost its view");
});

await test("pop-up blocked: state rolls back and the message explains how to allow pop-ups", async (ctx) => {
  await ctx.addInitScript(() => { window.open = () => null; });
  const m = await main(ctx, "revenue");
  await m.locator('[data-testid="pop-page:revenue"]').first().click();
  assert(await m.getByText(/blocked the pop-out window/).count() === 1, "no blocked message");
  assert(await placeholder(m, "page:revenue") === 0, "view stuck shaded after a blocked pop-up");
});

await test("main window closes: the pop-out keeps working and can become the main window", async (ctx) => {
  const m = await main(ctx, "topology");
  const w = await pop(m, "pop-page:topology");
  await m.close();
  assert(await until(async () => (await w.getByText("main CommandCenter window is closed").count()) === 1, 7000), "no orphan banner");
  await w.getByRole("button", { name: "Make this the main window" }).click();
  await w.waitForSelector(".side");
  assert(await w.locator(".page-topology").count() === 1, "did not become main on the same view");
  assert(await placeholder(w, "page:topology") === 0, "new main window shows its own view as elsewhere");
});

await test("live status updates reach the pop-out; a feed outage shows Stale, never Working", async (ctx) => {
  const m = await main(ctx, "office", "?stalems=2500");
  const w = await pop(m, "pop-page:office");
  const read = () => w.locator(".agent-cards").innerText();
  const first = await read();
  assert(await until(async () => (await read()) !== first, 13000), "no live update arrived in the pop-out");
  await m.goto(`${BASE}?stalems=2500#/more`);
  await m.getByLabel(/Simulate a status-feed outage/).check();
  assert(await until(async () => (await w.getByText(/Stale/).count()) > 0, 8000), "pop-out did not show stale state");
  assert(await w.locator(".agent-card .pres.t-ok").count() === 0, "an agent still shows Working during an outage");
});

await test("agent inspector: pops out to its own window; agent clicks in the main window follow it there; drawers stay in their own window", async (ctx) => {
  const m = await main(ctx, "teams/samvision");
  await m.getByRole("button", { name: /^Atlas, / }).click();
  const d = m.getByRole("dialog", { name: "Agent details" });
  assert(await d.count() === 1, "drawer did not open");
  assert((await d.textContent()).includes("gpt-5-codex"), "drawer has no model id");
  const w = await pop(m, "pop-panel:agent");
  assert(await until(async () => (await m.getByRole("dialog", { name: "Agent details" }).count()) === 0), "main still shows the drawer while popped out");
  assert(await until(async () => (await w.locator(".agent-insp h2").textContent()) === "Atlas"), "pop-out does not show Atlas");
  await m.getByRole("button", { name: /^Pixel, / }).click();
  assert(await until(async () => (await w.locator(".agent-insp h2").textContent()) === "Pixel"), "pop-out did not follow the click in main");
  assert(await m.getByRole("dialog", { name: "Agent details" }).count() === 0, "a drawer opened in main although the inspector is popped out");
  assert((await w.locator(".agent-insp").textContent()).includes("MFE-014"), "Pixel's task missing");
  const closed = w.waitForEvent("close");
  await w.getByRole("button", { name: /Return to main window/ }).click(); await closed;
  await m.getByRole("button", { name: /^Nova, / }).click();
  assert(await until(async () => (await m.getByRole("dialog", { name: "Agent details" }).count()) === 1), "drawer did not come back after return");
});

await test("onboarding wizards: pop out, keep the draft across reload, approve in the pop-out, and the main window updates", async (ctx) => {
  const m = await main(ctx, "onboard");
  await m.getByRole("button", { name: "Implementation Agent template" }).click();
  await m.getByRole("button", { name: /^Next:/ }).click();
  await m.getByLabel("Display name").fill("Mira");
  const w = await pop(m, "pop-page:onboard");
  assert(await until(async () => (await placeholder(m, "page:onboard")) === 1), "no placeholder for the agent wizard");
  assert(await w.getByLabel("Display name").inputValue() === "Mira", "draft did not move to the pop-out");
  await w.reload(); await w.waitForSelector('[data-testid="popout-window"]');
  assert(await w.getByLabel("Display name").inputValue() === "Mira", "draft lost on pop-out reload");
  await m.goto(`${BASE}?nofeed#/teams/samvision`);
  await w.getByRole("button", { name: /Review & activate/ }).click();
  await w.getByRole("button", { name: "Approve & Add Agent" }).click();
  await w.getByRole("dialog").getByRole("button", { name: "Approve & Add Agent" }).click();
  assert(await until(async () => (await m.getByRole("button", { name: /^Mira, Implementation Agent/ }).count()) === 1), "main window did not show the new agent");
  assert((await m.getByRole("button", { name: /^Mira, Implementation Agent/ }).textContent()).includes("Not started"), "new agent not shown as Not started");
  // project wizard: pop out, type, close with the OS button: it comes back with the draft intact
  await m.goto(`${BASE}?nofeed#/newproject`);
  const w2 = await pop(m, "pop-page:newproject");
  await w2.getByLabel("Project name").fill("Listing Scraper");
  await w2.close();
  assert(await until(async () => (await placeholder(m, "page:newproject")) === 0, 9000), "project wizard did not come back");
  assert(await m.getByLabel("Project name").inputValue() === "Listing Scraper", "project draft lost when its window closed");
});

await test("security: no credential in any window URL or shared storage; only same-origin windows", async (ctx) => {
  const m = await main(ctx, "messages/sv-lead");
  const w = await pop(m, "pop-dm:sv-lead");
  for (const p of [m, w]) assert(!/token|session=|dev=|key=|signin/i.test(p.url()), `credential-like URL ${p.url()}`);
  const stored = await w.evaluate(() => Object.entries(localStorage).map(([k, v]) => k + v).join(""));
  assert(!/ccd\.token|ccd\.dev|bearer/i.test(stored), "credential-like value in shared storage");
  assert(new URL(w.url()).origin === new URL(m.url()).origin, "pop-out on another origin");
});

await test("reduced motion: graph edges do not animate", async (ctx) => {
  const p = await ctx.newPage(); await p.emulateMedia({ reducedMotion: "reduce" });
  await p.goto(`${BASE}?nofeed#/topology`); await p.waitForSelector(".edge");
  const anim = await p.evaluate(() => getComputedStyle(document.querySelector(".ek-flow .edge-line")).animationName);
  assert(anim === "none", `animation ${anim}`);
});

console.log("Refinement layer (menus, tooltips, popovers, motion, loading)");
const SHOT = process.env.SHOTS; if (SHOT) fs.mkdirSync(SHOT, { recursive: true });
const shot = async (p, name) => { if (SHOT) await p.screenshot({ path: `${SHOT}/${name}.png` }); };

await test("context menus: right-click and Shift+F10 open them, arrows move, Escape closes and restores focus; they work in pop-outs too", async (ctx) => {
  const m = await main(ctx, "office");
  await m.locator(".agent-card").first().click({ button: "right" });
  const menu = m.getByRole("menu");
  assert(await menu.isVisible(), "no menu on right-click");
  assert(await menu.getByRole("menuitem", { name: "Open details", exact: true }).count() === 1, "agent menu items missing");
  await m.waitForTimeout(150); await shot(m, "r4_context_menu_agent");
  const first = await m.evaluate(() => document.activeElement?.textContent);
  await m.keyboard.press("ArrowDown");
  const second = await m.evaluate(() => document.activeElement?.textContent);
  assert(first !== second, "arrow keys don't move");
  await m.keyboard.press("Escape");
  assert(await menu.count() === 0, "Escape didn't close");
  assert(await m.evaluate(() => !!document.activeElement?.closest(".agent-card")), "focus not restored");
  await m.locator('[data-testid="tab-page:office"] a').focus(); await m.keyboard.press("Shift+F10");
  assert(await m.getByRole("menuitem", { name: "Pop out to new window" }).count() === 1, "tab menu via keyboard");
  await m.mouse.click(5, 900); assert(await m.getByRole("menu").count() === 0, "outside click didn't close");
  const w = await pop(m, "pop-page:agents");
  await w.locator(".dir tbody tr").first().click({ button: "right" });
  assert(await w.getByRole("menu").isVisible(), "no menu in pop-out");
  await shot(w, "r4_context_menu_popout");
  await w.getByRole("menuitem", { name: "Open details", exact: true }).click();
  assert(await w.getByRole("menu").count() === 0, "menu stayed open after choosing");
});

await test("context menu action: Pause from a pop-out changes the shared store in every window and is audited", async (ctx) => {
  const m = await main(ctx, "agents");
  await m.evaluate(() => localStorage.clear()); await m.reload(); await m.waitForSelector(".dir");
  const w = await pop(m, "pop-page:agents");
  await m.goto(`${BASE}?nofeed#/office`); await m.waitForSelector(".agent-card");
  await w.locator(".dir tbody tr", { hasText: "Iris" }).click({ button: "right" });
  await w.getByRole("menuitem", { name: "Pause", exact: true }).click();
  assert(await until(async () => (await m.locator(".agent-card", { hasText: "Iris" }).locator(".pres", { hasText: "Paused" }).count()) === 1), "main window didn't see the pause");
  assert(await w.locator(".audit li", { hasText: /Iris/ }).count() >= 1, "not audited");
  await w.locator(".dir tbody tr", { hasText: "Iris" }).first().click({ button: "right" }).catch(() => {});
});

await test("tooltips: styled tooltip after a pause, native title parked while shown and restored after", async (ctx) => {
  const m = await main(ctx, "office");
  const btn = m.locator('[data-testid="pop-page:topology"]').first();
  const title = await btn.getAttribute("title");
  await btn.hover();
  assert(await until(async () => (await m.locator(".tip").count()) === 1, 2000), "no tooltip");
  assert((await m.locator(".tip").textContent()) === title, "tooltip text differs from title");
  assert(await btn.getAttribute("title") === null, "native title not parked");
  await shot(m, "r4_tooltip");
  await m.mouse.move(5, 5);
  assert(await until(async () => (await m.locator(".tip").count()) === 0, 1000), "tooltip stuck");
  assert(await btn.getAttribute("title") === title, "title not restored");
});

await test("Jay's menu and notifications popover; reduce-motion setting stops animation app-wide", async (ctx) => {
  const m = await main(ctx, "office");
  await m.locator(".bell").click();
  assert(await m.getByRole("dialog", { name: "Notifications" }).isVisible(), "no notifications popover");
  await m.waitForTimeout(250); await shot(m, "r4_popover_notifications");
  await m.keyboard.press("Escape");
  assert(await m.getByRole("dialog", { name: "Notifications" }).count() === 0, "popover didn't close");
  await m.locator("button.me").click();
  await m.waitForTimeout(150); await shot(m, "r4_menu_jay");
  await m.getByRole("menuitemcheckbox", { name: "Reduce motion" }).click();
  assert(await m.evaluate(() => document.documentElement.dataset.motion) === "reduce", "data-motion not set");
  const d = await m.evaluate(() => getComputedStyle(document.querySelector(".btn")).transitionDuration);
  assert(/^0\.00001s|^1e-05s|^0s/.test(d) || parseFloat(d) < 0.001, `transitions still run: ${d}`);
  await m.locator("button.me").click(); await m.getByRole("menuitemcheckbox", { name: "Motion: follow system" }).click();
  assert(await m.evaluate(() => document.documentElement.dataset.motion) === "system", "not back to system");
});

await test("segmented controls: the thumb sits under the selected segment and follows it", async (ctx) => {
  const m = await main(ctx, "office");
  const seg = m.locator(".agents-strip .seg").first();
  assert(await until(async () => (await seg.getAttribute("class")).includes("has-thumb")), "no thumb");
  const at = async () => m.evaluate((el) => [parseFloat(el.style.getPropertyValue("--th-x")), parseFloat(el.style.getPropertyValue("--th-w"))], await seg.elementHandle());
  const [x0, w0] = await at();
  await seg.getByRole("tab", { name: /^Working/ }).click(); await m.waitForTimeout(80);
  const [x1] = await at();
  const sel = await seg.getByRole("tab", { name: /^Working/ }).evaluate((b) => b.offsetLeft);
  assert(w0 > 0 && x1 > x0 && Math.abs(x1 - sel) < 1, `thumb ${x0}→${x1}, selected at ${sel}`);
});

await test("command palette: arrow keys choose, Enter opens the chosen result", async (ctx) => {
  const m = await main(ctx, "office");
  await m.keyboard.press("Control+k");
  await m.keyboard.press("ArrowDown"); await m.keyboard.press("ArrowDown");
  const chosen = await m.locator('.palette [aria-selected="true"] span').first().textContent();
  await shot(m, "r4_palette");
  await m.keyboard.press("Enter");
  assert(chosen === "Decisions" && /#\/decisions$/.test(m.url()), `chose ${chosen}, at ${m.url()}`);
});

await test("loading: simulated slow loading shows a skeleton, then the page; design system page renders in a pop-out", async (ctx) => {
  const m = await main(ctx, "office", "?nofeed&slow");
  await m.locator('.nav a[href="#/decisions"]').click();
  assert(await m.locator(".page-skel").count() === 1, "no skeleton");
  await shot(m, "r4_skeleton");
  assert(await until(async () => (await m.locator(".page-skel").count()) === 0 && (await m.locator(".page h1").count()) > 0, 3000), "never loaded");
  await m.goto(`${BASE}?nofeed#/design`); await m.waitForSelector(".page-design"); await m.waitForTimeout(400);
  await shot(m, "r4_design_system");
  const w = await pop(m, "pop-page:design");
  assert(await w.locator(".page-design h1").count() === 1, "design page not in pop-out");
  await w.locator(".ds-card").click({ button: "right" });
  assert(await w.getByRole("menu").isVisible(), "menu missing in pop-out design page");
});

await browser.close();
const pass = results.filter((r) => r.ok).length;
fs.writeFileSync(`${OUT}/e2e-results.json`, JSON.stringify({ when: new Date().toISOString(), base: BASE, pass, total: results.length, results }, null, 2));
console.log(`\n${pass}/${results.length} passed`);
process.exit(pass === results.length ? 0 : 1);
