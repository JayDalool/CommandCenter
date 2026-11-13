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
    // A ccd with the notifier and nothing set up yet: no Slack tokens, no member ID, no ntfy topic, everything off, and
    // Slack replies limited to answers (ccd's default until Jay chooses).
    case "/api/notify":
      return { settings: { slack: false, ntfy: false, quietStart: "22:00", quietEnd: "07:00", summaryAt: "07:00",
        timezone: "America/Winnipeg", replyScope: "answers" },
        status: { slack: "off", socket: "off", ntfy: "off", lastError: null, lastSentAt: null },
        configured: { slackTokens: false, slackTokensError: null, jayMemberId: false, ntfy: false },
        channels: { cto: "cto" }, clientProjects: ["gauzemate"], slackGates: ["failure", "ui"], quietNow: false, held: 0 };
    case "/api/ui-tests": return { projects: {} };
    case "/api/jay/merge": return { projects: {} };
    case "/api/desktop/launcher": return { available: false };
    case "/api/developer": return { active: false, expiresIn: null };
    case "/api/pty": return { sessions: [], enabled: false };
    case "/api/attachments": return { attachments: [] };
    case "/api/chat": return { conversations: [], canStart: false, unread: 0, limits: { text: 16000, fileBytes: 20971520, filesPerMessage: 10 } };
    // A ccd that has the HQ store and nothing in it: every task project with no milestones, and a quiet window.
    case "/api/milestones":
      return { projects: Object.fromEntries(fx.tasks.projects.map((p) => [p.key, { technical: [], business: [], revision: 0 }])) };
    case "/api/projects/logos": return {};
    case "/api/briefing": {
      const zero = { merged: 0, done: 0, failedChecks: 0, opened: 0, questionsAsked: 0, questionsAnswered: 0, deploys: 0, needsYou: 0 };
      return { since: Math.floor(NOW / 1000) - 12 * 3600, until: Math.floor(NOW / 1000), totals: zero, quiet: true,
        projects: fx.tasks.projects.map((p) => ({ key: p.key, name: p.name, ...zero, mainChecks: "unknown", spendUsd: null, highlights: [] })) };
    }
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

/** Routes a server with its switch off answers 404, as ccd does: /api/onboarding/* while the onboarding groundwork is off
 *  (config.json "onboarding_groundwork"). The page is expected to say Not enabled; the browser's own console line for
 *  that 404 is not a problem. */
const OFF = new Set(["/api/onboarding/budgets"]);

/** What went wrong in the browser context (every page, pop-outs and popups included), collected as it happens. */
export interface Watch {
  console: string[];       // console.error and console.warn
  pageErrors: string[];    // uncaught exceptions
  blocked: string[];       // requests and workers that are not the test server's
  unanswered: string[];    // /api requests the fixture has no answer for
  writes: string[];        // non-GET /api requests: the suite only looks
  badAuth: string[];       // /api requests without the token header
  tokenInUrl: string[];    // any URL that carries the token
  sockets: string[];       // WebSocket URLs a page opened
  popups: string[];        // windows a page opened itself (window.open, target=_blank); a spec's own newPage is not one
}

export type Theme = "dark" | "light";
/** Classic or the HQ preview, as the Interface preference (cc.prefs) says on first load. */
export type Ui = "classic" | "hq";

export const test = base.extend<{ theme: Theme; ui: Ui; watch: Watch }>({
  theme: ["dark", { option: true }],
  ui: ["classic", { option: true }],
  colorScheme: async ({ theme }, use) => { await use(theme); },
  watch: [async ({ context, page, theme, ui }, use) => {
    const w: Watch = { console: [], pageErrors: [], blocked: [], unanswered: [], writes: [], badAuth: [], tokenInUrl: [],
      sockets: [], popups: [] };
    // Everything below is set on the browser context, so a pop-out or a popup is sealed and watched like the first page.
    context.on("console", (m) => {
      if (m.type() !== "error" && m.type() !== "warning") return;
      const at = m.location().url;
      if (at && OFF.has(new URL(at, ORIGIN).pathname) && m.text().startsWith("Failed to load resource")) return;
      w.console.push(`${m.type()}: ${m.text()}`);
    });
    context.on("weberror", (e) => w.pageErrors.push(String(e.error())));
    context.on("request", (r) => { if (r.url().includes(TOKEN)) w.tokenInUrl.push(r.url()); });
    const watchPage = (p: Page) => {
      // Playwright cannot route a worker's own WebSockets; ccd's CSP (connect-src) still holds them to this server.
      // Classic's only workers are Monaco's, from its own /assets/.
      p.on("worker", (wk) => { if (!wk.url().startsWith(`${ORIGIN}/`) && !wk.url().startsWith(`blob:${ORIGIN}/`)) w.blocked.push(`worker ${wk.url()}`); });
    };
    watchPage(page);
    context.on("page", async (p) => {
      watchPage(p);
      if (!(await p.opener())) return;
      const i = w.popups.push(p.url()) - 1;
      p.on("framenavigated", (f) => { if (f === p.mainFrame()) w.popups[i] = f.url(); });
    });

    await context.clock.setFixedTime(NOW);
    await context.addInitScript(({ origin, token, theme, ui }) => {
      // CSP violations are recorded on the window: a popup runs this script only in its first about:blank, then keeps
      // that window when it navigates to the app.
      if (!Object.hasOwn(window, "__e2eCsp")) {
        const seen: string[] = [];
        Object.defineProperty(window, "__e2eCsp", { value: seen });
        window.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
      }
      if (location.origin !== origin) return;  // about:blank, or a frame with an opaque origin: no storage of its own
      try {
        sessionStorage.setItem("ccd.token", token);
        // First load only, so a spec that changes a preference keeps it across reloads.
        if (localStorage.getItem("cc.prefs") === null) localStorage.setItem("cc.prefs", JSON.stringify({ theme, ui }));
      } catch { /* storage refused: the page shows Connect, and the spec fails on what it expected to see */ }
    }, { origin: ORIGIN, token: TOKEN, theme, ui });

    await context.route(() => true, async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      if (url.origin !== ORIGIN) { w.blocked.push(req.url()); return route.abort("blockedbyclient"); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (req.headers()["x-ccd-token"] !== TOKEN) w.badAuth.push(`${req.method()} ${url.pathname}`);
      if (req.method() !== "GET") { w.writes.push(`${req.method()} ${url.pathname}`); return route.fulfill({ status: 405, json: { ok: false, error: "read-only test" } }); }
      if (OFF.has(url.pathname)) return route.fulfill({ status: 404, json: { ok: false, error: "not found" } });
      const body = answer(url.pathname);
      if (body === undefined) { w.unanswered.push(`GET ${url.pathname}`); return route.fulfill({ status: 404, json: { ok: false, error: "no fixture" } }); }
      return route.fulfill({ json: body, headers: { "cache-control": "no-store" } });
    });

    // A routed socket never reaches the browser's own CSP check, so the origin check here stands in for connect-src.
    await context.routeWebSocket(() => true, (ws: WebSocketRoute) => {
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

/** Which screen the page shows: the top bar's title (with the Settings section; HQ's top bar in the HQ preview),
 *  "Dashboard", or "pop-out". */
export async function shown(page: Page): Promise<string> {
  return page.evaluate(() => {
    if (document.querySelector(".shell.is-bare")) return "pop-out";
    const hq = document.querySelector(".hq-top h1.page-title")?.textContent;   // the HQ frame's top bar, on every screen
    if (!hq && document.querySelector(".shell.is-dash .dash-top")) return "Dashboard";
    const title = hq ?? document.querySelector("h1.page-title")?.textContent ?? "(no title)";
    // Classic's Settings marks its section with a pressed button, HQ's with the current link in its section list.
    const section = document.querySelector('[aria-label="Settings section"] [aria-pressed="true"]')?.textContent
      ?? document.querySelector('[aria-label="Settings sections"] [aria-current="page"] b')?.textContent;
    return section ? `${title} › ${section}` : title;
  });
}

/** Everything a clean page must not have, across every page in its context. An empty list means clean. */
export async function problems(page: Page, w: Watch): Promise<string[]> {
  const csp: string[] = [];
  for (const p of page.context().pages()) {
    if (new URL(p.url()).origin !== ORIGIN) continue;
    csp.push(...await p.evaluate(() => (window as unknown as { __e2eCsp?: string[] }).__e2eCsp?.slice() ?? []));
  }
  const socket = w.sockets.some((u) => new URL(u).pathname === "/api/events");
  // The connection banner (Shell.tsx, OfflineBanner) shows whenever live events are not live.
  const notLive = await page.locator(".banner .caps").filter({ hasText: /^(Reconnecting|Offline)$/ }).count();
  return [
    ...w.console.map((x) => `console ${x}`),
    ...w.pageErrors.map((x) => `page error: ${x}`),
    ...csp.map((x) => `CSP violation: ${x}`),
    ...w.blocked.map((x) => `left the test server: ${x}`),
    ...w.unanswered.map((x) => `no fixture for ${x}`),
    ...w.writes.map((x) => `wrote: ${x}`),
    ...w.badAuth.map((x) => `no token header: ${x}`),
    ...w.tokenInUrl.map((x) => `token in a URL: ${x}`),
    ...w.popups.map((x) => `opened a window: ${x}`),
    ...(socket ? [] : ["live events never connected"]),
    ...(notLive ? ["live events connected but not live"] : []),
  ];
}
