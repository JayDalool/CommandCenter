// The app's one data controller: bootstrap over REST, live over WebSocket, and
// never blank the screen. Every screen reads from `app` through selectors.
import { Api, ApiError, api as defaultApi } from "../api/client";
import { getToken, setToken, clearToken } from "../api/auth";
import { Live, type LiveStatus } from "../api/live";
import type { CcdEvent, State, TaskMeta, TaskProject, Ticket, TicketDetail } from "../api/types";
import { Store } from "../lib/store";

export interface AppData {
  auth: "checking" | "needed" | "ok";
  authError: string | null;
  state: State | null;
  /** browser time (ms) of the last successful /api/state */
  stateAt: number | null;
  conn: { status: LiveStatus; lastMessageAt: number | null; attempt: number };
  error: string | null;
  tickets: Ticket[];
  ticketsLoaded: boolean;
  taskProjects: TaskProject[];
  meta: TaskMeta | null;
  details: Record<string, TicketDetail>;
  activity: CcdEvent[];
  toast: { text: string; tone: "ok" | "bad" } | null;
}

export const initial: AppData = {
  auth: "checking", authError: null, state: null, stateAt: null,
  conn: { status: "offline", lastMessageAt: null, attempt: 0 }, error: null,
  tickets: [], ticketsLoaded: false, taskProjects: [], meta: null, details: {}, activity: [], toast: null,
};

const ACTIVITY_CAP = 300;
// State changes without an event (host numbers every 120 s) still need a refresh.
const IDLE_REFRESH_MS = 60_000;

export class App {
  store = new Store<AppData>(initial);
  live: Live;
  private stateTimer: ReturnType<typeof setTimeout> | null = null;
  private lastStateFetch = 0;
  private stateReq = 0;
  private ticketTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private idle: ReturnType<typeof setInterval> | null = null;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(public api: Api = defaultApi, WebSocketImpl?: typeof WebSocket) {
    this.live = new Live({
      onEvent: (ev) => this.onEvent(ev),
      onLost: () => this.resync(),
      onStatus: (status, info) => this.store.patch({ conn: { status, lastMessageAt: info.lastMessageAt, attempt: info.attempt } }),
      onAuthFailed: () => this.recheckAuth(),
    }, { token: getToken, WebSocketImpl });
  }

  get data() { return this.store.get(); }

  async boot() {
    if (!getToken()) { this.store.patch({ auth: "needed" }); return; }
    try {
      await this.loadAll();
      this.store.patch({ auth: "ok", authError: null });
      this.live.start(this.data.state?.seq ?? 0);
      this.startIdleRefresh();
    } catch (e) {
      this.handleBootError(e);
    }
  }

  private handleBootError(e: unknown) {
    if (e instanceof ApiError && e.status === 401) {
      this.store.patch({ auth: "needed", authError: "ccd refused that token." });
    } else if (e instanceof ApiError && e.status === 503) {
      // ccd warming up: retry shortly, keep whatever is on screen
      this.store.patch({ auth: "ok", error: "ccd is warming up…" });
      setTimeout(() => this.boot(), 2000);
    } else {
      this.store.patch({ auth: this.data.state ? "ok" : "needed",
        authError: this.data.state ? null : `Cannot reach ccd (${(e as Error).message}). Is the tunnel up?`,
        error: (e as Error).message });
      if (this.data.state) setTimeout(() => this.boot(), 5000);
    }
  }

  async login(token: string, remember: boolean) {
    setToken(token, remember);
    this.store.patch({ auth: "checking", authError: null });
    await this.boot();
  }

  logout() {
    clearToken();
    this.live.stop();
    if (this.idle) clearInterval(this.idle);
    this.idle = null;
    this.store.set({ ...initial, auth: "needed" });
  }

  private async recheckAuth() {
    try { await this.api.state(); } catch (e) {
      if (e instanceof ApiError && e.status === 401) { this.live.stop(); this.store.patch({ auth: "needed",
        authError: "ccd refused the token (was it rotated?)." }); }
    }
  }

  private startIdleRefresh() {
    if (this.idle) return;
    this.idle = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      if (this.data.conn.status === "live") this.scheduleState(0);
    }, IDLE_REFRESH_MS);
  }

  async loadAll() {
    const req = ++this.stateReq;
    const [st, tl, act] = await Promise.all([
      this.api.state(),
      this.api.tasks().catch((e) => (e instanceof ApiError && e.status === 404 ? null : Promise.reject(e))),
      this.api.activity({ limit: 150 }).catch(() => null),
    ]);
    this.lastStateFetch = Date.now();
    if (req !== this.stateReq) return;  // a newer fetch started meanwhile; its answer wins
    this.store.patch({
      state: st, stateAt: Date.now(), error: null,
      ...(tl ? { tickets: tl.tickets, taskProjects: tl.projects, meta: tl.meta, ticketsLoaded: true } : {}),
      ...(act ? { activity: mergeActivity(this.data.activity, act.events) } : {}),
    });
  }

  /** events_lost: the server could not replay. Refetch everything, then resume from the fresh seq. */
  async resync() {
    try {
      await this.loadAll();
      this.live.restart(this.data.state?.seq ?? 0);
    } catch (e) {
      this.store.patch({ error: (e as Error).message });
    }
  }

  async refreshState() {
    const req = ++this.stateReq;
    try {
      const st = await this.api.state();
      this.lastStateFetch = Date.now();
      if (req !== this.stateReq) return;
      this.store.patch({ state: st, stateAt: Date.now(), error: null });
    } catch (e) {
      // Keep the last good state. The banner says how old it is.
      this.store.patch({ error: (e as Error).message });
    }
  }

  /** Coalesce bursts: at most one /api/state per 1.5 s, 400 ms after the last event. */
  scheduleState(delay = 400) {
    if (this.stateTimer) return;
    const wait = Math.max(delay, 1500 - (Date.now() - this.lastStateFetch));
    this.stateTimer = setTimeout(() => { this.stateTimer = null; void this.refreshState(); }, wait);
  }

  onEvent(ev: CcdEvent) {
    this.store.set((d) => ({ ...d, activity: mergeActivity(d.activity, [ev]) }));
    if (ev.kind.startsWith("task.") && ev.ref) {
      this.scheduleTicket(ev.ref);
      if (ev.data && (ev.data as { kind?: string }).kind && String((ev.data as { kind?: string }).kind).startsWith("needs_")) {
        this.scheduleState();
      }
      return;
    }
    if (ev.kind === "action.answer" || ev.kind === "action.focus") return;  // our own echo
    this.scheduleState();
  }

  scheduleTicket(key: string) {
    if (this.ticketTimers.has(key)) return;
    this.ticketTimers.set(key, setTimeout(() => { this.ticketTimers.delete(key); void this.refreshTicket(key); }, 150));
  }

  async refreshTicket(key: string) {
    try {
      const t = await this.api.task(key);
      this.putTicket(t);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return;
      this.store.patch({ error: (e as Error).message });
    }
  }

  putTicket(t: TicketDetail) {
    this.store.set((d) => {
      const { description: _d, relations: _r, subtaskList: _s, comments: _c, timeline: _t, ...row } = t;
      const exists = d.tickets.some((x) => x.key === t.key);
      const tickets = exists ? d.tickets.map((x) => (x.key === t.key ? { ...x, ...row } : x)) : [{ ...row }, ...d.tickets];
      return { ...d, tickets, details: { ...d.details, [t.key]: t } };
    });
  }

  async loadTicket(key: string) {
    const t = await this.api.task(key);
    this.putTicket(t);
    return t;
  }

  /** A write: apply the server's answer immediately; the WS echo then refreshes others. */
  async mutate(fn: () => Promise<TicketDetail>, ok?: string) {
    try {
      const t = await fn();
      this.putTicket(t);
      if (ok) this.toast(ok, "ok");
      return t;
    } catch (e) {
      this.toast((e as Error).message, "bad");
      throw e;
    }
  }

  toast(text: string, tone: "ok" | "bad" = "ok") {
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.store.patch({ toast: { text, tone } });
    this.toastTimer = setTimeout(() => this.store.patch({ toast: null }), tone === "bad" ? 6000 : 2500);
  }

  async action<T>(fn: () => Promise<T>, ok: string): Promise<T | undefined> {
    try {
      const r = await fn();
      this.toast(ok, "ok");
      return r;
    } catch (e) {
      this.toast((e as Error).message, "bad");
      return undefined;
    }
  }
}

export function mergeActivity(cur: CcdEvent[], incoming: CcdEvent[], cap = ACTIVITY_CAP): CcdEvent[] {
  if (!incoming.length) return cur;
  const seen = new Set(cur.map((e) => e.seq));
  const add = incoming.filter((e) => !seen.has(e.seq));
  if (!add.length) return cur;
  return [...add, ...cur].sort((a, b) => b.seq - a.seq).slice(0, cap);
}

export const app = new App();
