import { getToken } from "./auth";
import type {
  Development, ImportPreview, State, Tail, TaskList, Ticket, TicketDetail, CcdEvent,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export type Fetch = typeof fetch;

/** The one place the UI talks HTTP to ccd. Same origin; the token goes in a header. */
export class Api {
  constructor(private fetchImpl: Fetch = (...a) => fetch(...a), private base = "") {}

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["X-CCD-Token"] = token;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await this.fetchImpl(this.base + path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store", credentials: "omit",
      });
    } catch (e) {
      throw new ApiError(0, "ccd unreachable");
    }
    let data: unknown = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (!res.ok) {
      const msg = (data && typeof data === "object" && "error" in data) ? String((data as { error: unknown }).error)
        : `HTTP ${res.status}`;
      throw new ApiError(res.status, msg);
    }
    return data as T;
  }

  state() { return this.req<State>("GET", "/api/state"); }
  activity(q: { limit?: number; before?: number; kind?: string; project?: string } = {}) {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
    return this.req<{ seq: number; events: CcdEvent[] }>("GET", `/api/activity?${p}`);
  }
  tail(agentId: string, lines = 40) {
    return this.req<Tail>("GET", `/api/agents/${encodeURIComponent(agentId)}/tail?lines=${lines}`);
  }
  focusAgent(agentId: string) { return this.req<{ ok: true }>("POST", "/api/action/focus", { agentId }); }
  focusWorkspace(workspaceId: string) { return this.req<{ ok: true }>("POST", "/api/action/focus", { workspaceId }); }
  focusTab(tabId: string) { return this.req<{ ok: true }>("POST", "/api/action/focus", { tabId }); }
  answer(agentId: string, text: string) { return this.req<{ ok: true }>("POST", "/api/action/answer", { agentId, text }); }
  ack(alertId: string) { return this.req<{ ok: true }>("POST", "/api/action/ack", { alertId }); }
  dispatch(project: string, taskId: string, verb: string, note = "") {
    return this.req<{ ok: true; coordinator: string }>("POST", "/api/action/dispatch", { project, taskId, verb, note });
  }

  development(project?: string) {
    return this.req<Development>("GET", `/api/development${project ? `?project=${encodeURIComponent(project)}` : ""}`);
  }
  tasks() { return this.req<TaskList>("GET", "/api/tasks"); }
  task(key: string) { return this.req<TicketDetail>("GET", `/api/tasks/${encodeURIComponent(key)}`); }
  createTask(body: { project: string; title: string } & Partial<Record<string, unknown>>) {
    return this.req<TicketDetail>("POST", "/api/tasks", body);
  }
  updateTask(key: string, fields: Partial<Record<string, unknown>>) {
    return this.req<TicketDetail>("PATCH", `/api/tasks/${encodeURIComponent(key)}`, fields);
  }
  comment(key: string, body: string) {
    return this.req<TicketDetail>("POST", `/api/tasks/${encodeURIComponent(key)}/comments`, { body });
  }
  relate(key: string, kind: string, target: string, remove = false) {
    return this.req<TicketDetail>("POST", `/api/tasks/${encodeURIComponent(key)}/relations`, { kind, target, remove });
  }
  link(key: string, body: { provider: string; kind: string; ref: string; url?: string; remove?: boolean }) {
    return this.req<TicketDetail>("POST", `/api/tasks/${encodeURIComponent(key)}/links`, body);
  }
  context(key: string) {
    return this.req<{ brief: string; dispatchable: boolean; ticket: TicketDetail }>(
      "GET", `/api/tasks/${encodeURIComponent(key)}/context`);
  }
  importPreview() { return this.req<ImportPreview>("GET", "/api/tasks/import-preview"); }
}

export type { Ticket };
export const api = new Api();
