// The sealed browser for every spec: Classic's real build (served by e2e/serve.mjs with ccd's headers), the existing
// unit-test fixture (tests/fixture.json) as the API, a stubbed live-events socket and a dummy token. No ccd, no
// network: a request to anything but the test server is aborted and fails the test.
import { test as base, expect, type Page, type WebSocketRoute } from "@playwright/test";
import raw from "../tests/fixture.json" with { type: "json" };
import type { State, TaskList, TicketDetail, TicketWork } from "../src/api/types";
import { env } from "./env";

const fx = raw as unknown as { state: State; tasks: TaskList };

export const PORT = Number(env.E2E_PORT ?? 4317);
export const ORIGIN = `http://127.0.0.1:${PORT}`;
/** Right shape for auth.ts (TOKEN_SHAPE), not a credential: nothing here checks it. */
export const TOKEN = "e2e_dummy_token_not_a_secret_0000000000";
/** Five seconds after the fixture was taken, so every "updated … ago" reads the same on every run. */
export const NOW = Math.round(fx.state.at * 1000) + 5_000;

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

/** One honest answer per endpoint the screens read on load. Anything else is "unanswered" and fails the test. */
function answer(path: string): unknown {
  const seq = fx.state.seq;
  switch (path) {
    case "/api/state": return clone(fx.state);
    case "/api/tasks": return clone(fx.tasks);
    case "/api/activity": return { seq, events: [] };
    case "/api/development":
      return { rows: [], seq, gitAsOf: null, stages: ["branch", "commits", "pr", "ci", "review", "merge", "verify", "deploy"],
        notes: [] };
    case "/api/night-shift": return { projects: {} };
    case "/api/inbox": return { available: false, items: {}, orphans: [], counts: {} };
    case "/api/workspace/projects":
      return { projects: fx.state.projectsConfig.map((p) => ({ key: p.key, name: p.name, prefix: p.prefix ?? p.key.toUpperCase(),
        root: null, exists: false, branch: null, github: null, coordinator: null })) };
    case "/api/profiles": return { fingerprint: "", problems: [], projects: {}, decisions: {} };
    case "/api/autonomy":
      return { mode: "shadow", engine: 1, available: false, total: 0, agree: 0, disagree: 0, counts: {}, missing: {},
        disagreements: [] };
    case "/api/decisions": return { available: false, decisions: [], approvals: [], counts: {} };
    case "/api/workers": return { available: false, nodes: [], events: [] };
    case "/api/audit": return { available: false, events: [], summary: {}, chain: {} };
    case "/api/actors": return { available: false, tokens: [] };
    case "/api/usage": return { available: false };
    case "/api/ui-tests": return { projects: {} };
    case "/api/jay/merge": return { projects: {} };
    case "/api/desktop/launcher": return { available: false };
    case "/api/developer": return { active: false, expiresIn: null };
    case "/api/pty": return { sessions: [], enabled: false };
    case "/api/attachments": return { attachments: [] };
  }
  const task = /^\/api\/tasks\/([^/]+)(\/work)?$/.exec(path);
  const t = task && fx.tasks.tickets.find((x) => x.key === decodeURIComponent(task[1]));
  if (t && !task[2]) {
    const detail: TicketDetail = { ...clone(t), description: "", subtaskList: [], comments: [], timeline: [],
      relations: { blocks: [], blocked_by: [], related: [], duplicates: [], duplicated_by: [] } };
    return detail;
  }
  if (t) {
    // A ticket with no pipeline record yet: nothing planned, nothing gated.
    const work: TicketWork = { key: t.key, status: t.status, stage: null, stages: [], plan: {}, planState: "none",
      policy: { plan: "auto", planReasons: [], merge: "owner", ui: false, deploy: false }, gate: null, gateReason: null,
      confirmed: [], branch: t.branch, worktree: null, prs: [], roles: {}, review: { verdict: null, head: null, cycles: 0 },
      verification: null, merge: null, handoff: null, blocked: null, findings: [] };
    return work;
  }
  return undefined;
}

/** What went wrong in one page, collected as it happens. */
export interface Watch {
  console: string[];       // console.error and console.warn
  pageErrors: string[];    // uncaught exceptions
  blocked: string[];       // requests to anything but the test server
  unanswered: string[];    // /api requests the fixture has no answer for
  writes: string[];        // non-GET /api requests: the suite only looks
  badAuth: string[];       // /api requests without the token header
  tokenInUrl: string[];    // any URL that carries the token
  sockets: string[];       // WebSocket URLs the page opened
}

export type Theme = "dark" | "light";

export const test = base.extend<{ theme: Theme; watch: Watch }>({
  theme: ["dark", { option: true }],
  colorScheme: async ({ theme }, use) => { await use(theme); },
  watch: [async ({ page, theme }, use) => {
    const w: Watch = { console: [], pageErrors: [], blocked: [], unanswered: [], writes: [], badAuth: [], tokenInUrl: [],
      sockets: [] };
    page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") w.console.push(`${m.type()}: ${m.text()}`); });
    page.on("pageerror", (e) => w.pageErrors.push(String(e)));
    page.on("request", (r) => { if (r.url().includes(TOKEN)) w.tokenInUrl.push(r.url()); });

    await page.clock.setFixedTime(NOW);
    await page.addInitScript(({ token, theme }) => {
      sessionStorage.setItem("ccd.token", token);
      // First load only, so a spec that changes a preference keeps it across reloads.
      if (localStorage.getItem("cc.prefs") === null) localStorage.setItem("cc.prefs", JSON.stringify({ theme }));
      const seen: string[] = [];
      Object.defineProperty(window, "__e2eCsp", { value: seen });
      document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
    }, { token: TOKEN, theme });

    await page.route(() => true, async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      if (url.origin !== ORIGIN) { w.blocked.push(req.url()); return route.abort("blockedbyclient"); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (req.headers()["x-ccd-token"] !== TOKEN) w.badAuth.push(`${req.method()} ${url.pathname}`);
      if (req.method() !== "GET") { w.writes.push(`${req.method()} ${url.pathname}`); return route.fulfill({ status: 405, json: { ok: false, error: "read-only test" } }); }
      const body = answer(url.pathname);
      if (body === undefined) { w.unanswered.push(`GET ${url.pathname}`); return route.fulfill({ status: 404, json: { ok: false, error: "no fixture" } }); }
      return route.fulfill({ json: body, headers: { "cache-control": "no-store" } });
    });

    await page.routeWebSocket(() => true, (ws: WebSocketRoute) => {
      const url = ws.url();
      w.sockets.push(url);
      if (url.includes(TOKEN)) w.tokenInUrl.push(url);
      if (new URL(url).origin !== ORIGIN.replace("http:", "ws:")) { w.blocked.push(url); return ws.close(); }
      if (new URL(url).pathname !== "/api/events") { w.unanswered.push(`WS ${new URL(url).pathname}`); return ws.close(); }
      // The server's greeting and an empty replay: the page is live and up to date at the fixture's seq.
      ws.send(JSON.stringify({ type: "hello", seq: fx.state.seq }));
      ws.send(JSON.stringify({ type: "replay_done", seq: fx.state.seq }));
    });

    await use(w);
  }, { auto: true }],
});

export { expect };

/** Opens a Classic route (`dashboard`, `settings?tab=audit`, …) and waits until it has settled. */
export async function open(page: Page, route: string) {
  await page.goto(`${ORIGIN}/#/${route}`);
  await settle(page);
}

/** No request in flight, fonts loaded, two frames painted. */
export async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.locator("#main").waitFor();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
}

/** Everything a clean page must not have. An empty list means clean. */
export async function problems(page: Page, w: Watch): Promise<string[]> {
  const csp = await page.evaluate(() => (window as unknown as { __e2eCsp: string[] }).__e2eCsp.slice());
  const live = w.sockets.some((u) => new URL(u).pathname === "/api/events");
  return [
    ...w.console.map((x) => `console ${x}`),
    ...w.pageErrors.map((x) => `page error: ${x}`),
    ...csp.map((x) => `CSP violation: ${x}`),
    ...w.blocked.map((x) => `left the test server: ${x}`),
    ...w.unanswered.map((x) => `no fixture for ${x}`),
    ...w.writes.map((x) => `wrote: ${x}`),
    ...w.badAuth.map((x) => `no token header: ${x}`),
    ...w.tokenInUrl.map((x) => `token in a URL: ${x}`),
    ...(live ? [] : ["live events never connected"]),
  ];
}
