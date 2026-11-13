// The office floor (My Office › Sessions) in a real browser, on the fixture's three sessions: everyone has a place and
// the floor fits a desktop and a phone; a session that starts waiting is seen crossing from its desk to Jay's door;
// and with reduced motion it is simply at the door. The spec plays ccd here: it serves the state and sends the one
// live event that makes the page read it again.
import raw from "../tests/fixture.json" with { type: "json" };
import type { Locator, Page, WebSocketRoute } from "@playwright/test";
import type { State } from "../src/api/types";
import { test, expect, open, problems, settle, NOW, type Watch } from "./fixture";

test.use({ ui: "hq" });

const fx = (raw as unknown as { state: State }).state;
const LANE = "wE:pA";   // sv-056-impl: working in the fixture
const wide = () => document.documentElement.scrollWidth <= window.innerWidth;
const box = async (l: Locator) => (await l.boundingBox())!;
const drawn = (page: Page) => page.evaluate((id) => {
  const el = document.querySelector<HTMLElement>(`[data-who="${id}"]`)!;
  return { walking: el.classList.contains("is-walking"), shifted: getComputedStyle(el).transform !== "none" };
}, LANE);

/** ccd for this page. `knock()` makes sv-056-impl wait for Jay, and says so with one live event. */
async function stage(page: Page, watch: Watch) {
  let waiting = false, seq = fx.seq, sock: WebSocketRoute | null = null;
  await page.route("**/api/state", (r) => {
    const st = JSON.parse(JSON.stringify(fx)) as State;
    if (waiting) Object.assign(st.agents.find((a) => a.id === LANE)!, { status: "blocked", blockedSinceMs: NOW - 30_000 });
    return r.fulfill({ json: st, headers: { "cache-control": "no-store" } });
  });
  await page.routeWebSocket((u) => u.pathname === "/api/events", (ws) => {
    watch.sockets.push(ws.url());
    sock = ws;
    ws.send(JSON.stringify({ type: "hello", seq }));
    ws.send(JSON.stringify({ type: "replay_done", seq }));
  });
  return { knock() {
    waiting = true;
    sock!.send(JSON.stringify({ type: "event", event: { seq: ++seq, at: NOW / 1000, source: "herdr", kind: "agent.status", severity: "info",
      project: "samvision", agentId: LANE, ref: null, text: "sv-056-impl is waiting", data: {} } }));
  } };
}

test("everyone has a place; a session that starts waiting walks from its desk to the door", async ({ page, watch }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });   // the suite runs with reduced motion (playwright.config.ts)
  const ccd = await stage(page, watch);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "dashboard");
  const panel = page.getByRole("region", { name: /^Sessions/ });
  await expect(panel.getByRole("button", { name: "Floor" })).toHaveAttribute("aria-pressed", "true");
  const desks = panel.getByRole("region", { name: /^At their desks/ }), door = panel.getByRole("region", { name: /^At your door/ });
  await expect(panel.locator("[data-who]")).toHaveCount(3);
  await expect(desks.locator("[data-who]")).toHaveCount(1);
  await expect(door).toContainText("1 waiting for you");
  await expect(panel.getByRole("region", { name: /^In the lounge/ })).toContainText("1 idle");
  // wide: the desks are drawn left of the door, though the door comes first for a keyboard and a screen reader
  const d = await box(desks), r = await box(door);
  expect(d.x + d.width).toBeLessThanOrEqual(r.x);
  const me = panel.locator(`[data-who="${LANE}"]`);
  const from = await box(me);
  await me.focus();

  ccd.knock();
  // In the page's structure it is at the door at once; on the screen it is still on its way there.
  await expect(door.locator(`[data-who="${LANE}"]`)).toHaveCount(1);
  expect(await drawn(page)).toEqual({ walking: true, shifted: true });
  await expect(me).toBeFocused();   // a keyboard that was on it is still on it
  await expect(me).not.toHaveClass(/is-walking/, { timeout: 6000 });
  expect(await drawn(page)).toEqual({ walking: false, shifted: false });
  const to = await box(me), room = await box(door);
  expect(to.x).toBeGreaterThan(from.x + 200);
  expect(to.x >= room.x && to.x + to.width <= room.x + room.width && to.y >= room.y && to.y + to.height <= room.y + room.height).toBe(true);
  await expect(door).toContainText("2 waiting for you");
  await expect(desks).toContainText("0 working");
  await expect(desks.locator(".hq-desk.is-empty", { hasText: "sv-056-impl" })).toContainText("at your door");
  expect(await page.evaluate(wide)).toBe(true);
  expect(await problems(page, watch)).toEqual([]);
});

test("on a phone the door comes first and everything fits; with reduced motion a session is simply at its new place", async ({ page, watch }) => {
  const ccd = await stage(page, watch);   // reduced motion, as the whole suite runs (playwright.config.ts)
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "dashboard");
  const panel = page.getByRole("region", { name: /^Sessions/ });
  const desks = panel.getByRole("region", { name: /^At their desks/ }), door = panel.getByRole("region", { name: /^At your door/ });
  expect((await box(door)).y).toBeLessThan((await box(desks)).y);
  const inside = () => panel.locator(".hq-floor").evaluate((floor) => {
    const f = floor.getBoundingClientRect();
    return [...floor.querySelectorAll(".hq-who, .hq-desk")].every((el) => { const b = el.getBoundingClientRect(); return b.left >= f.left - 0.5 && b.right <= f.right + 0.5; });
  });
  expect(await inside()).toBe(true);
  expect(await page.evaluate(wide)).toBe(true);

  ccd.knock();
  await expect(door.locator(`[data-who="${LANE}"]`)).toHaveCount(1);
  expect(await drawn(page)).toEqual({ walking: false, shifted: false });
  expect(await inside()).toBe(true);

  // the list is one press away, and the choice survives a reload
  await panel.getByRole("button", { name: "List" }).click();
  await expect(panel.locator(".hq-sess")).toHaveCount(3);
  await page.reload();
  await settle(page);
  await expect(panel.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
  await expect(panel.locator(".hq-floor")).toHaveCount(0);
  expect(await page.evaluate(wide)).toBe(true);
  expect(await problems(page, watch)).toEqual([]);
});
