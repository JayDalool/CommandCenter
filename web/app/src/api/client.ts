import { getToken } from "./auth";
import { devExpired, devSession } from "./developer";
import type { AnswersResult, CoordinatorState, GoLiveResult, MergeReady, MergeResult, NightShiftState, UiTestsState, TaskCheckResult, TaskRecord, TicketWork,
  Attachment, DevCommits, PtySession, ScmDiff, ScmStatus, SearchResult, FileList, FileRead, LauncherInfo, SaveResult, UploadResult, WorkspaceProject,
  Development, ImportPreview, State, Tail, TaskList, Ticket, TicketDetail, CcdEvent, PolicyState, AutonomyState, LedgerState } from "./types";

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
    const dev = devSession();
    if (dev) headers["X-CCD-Developer"] = dev;
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
      if (res.status === 403 && data && typeof data === "object" && "error" in data &&
        String((data as { error: unknown }).error).startsWith("Developer Unlock")) devExpired();
      if (res.status === 409 && data && typeof data === "object") {
        throw Object.assign(new ApiError(409, String((data as { error?: unknown }).error ?? "conflict")), { data });
      }
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
  tasks(archived = false) { return this.req<TaskList>("GET", `/api/tasks${archived ? "?archived=1" : ""}`); }
  task(key: string) { return this.req<TicketDetail>("GET", `/api/tasks/${encodeURIComponent(key)}`); }
  createTask(body: { project: string; title: string } & Partial<Record<string, unknown>>) {
    return this.req<TicketDetail>("POST", "/api/tasks", body);
  }
  taskWork(key: string) { return this.req<TicketWork>("GET", `/api/tasks/${encodeURIComponent(key)}/work`); }
  /** Owner step from the UI: close a gate (needs Developer Unlock; ccd also checks it is Jay). */
  confirmGate(key: string, gate: string) {
    return this.req<TicketWork>("POST", `/api/tasks/${encodeURIComponent(key)}/work/confirm`, { gate });
  }
  /** One pipeline step from the UI (rework, replan, confirm …), recorded as Jay. */
  workOp(key: string, op: string, body: Record<string, unknown>) {
    return this.req<TicketWork>("POST", `/api/tasks/${encodeURIComponent(key)}/work/${encodeURIComponent(op)}`, body);
  }
  /** The task check (Developer Unlock): the project's idle coordinator Claude proposes stale tasks and adds missing ones. */
  taskCheck(project: string, copy = false) {
    return this.req<TaskCheckResult>("POST", "/api/tasks/check", copy ? { project, copy: true } : { project });
  }
  /** Night shift (Developer Unlock): the project's idle coordinator works its open tasks until morning; never deploys. */
  nightShift(project: string, copy = false) {
    return this.req<TaskCheckResult>("POST", "/api/tasks/night-shift", copy ? { project, copy: true } : { project });
  }
  /** Every project's night shift: running?, coordinator, the newest morning report. */
  nightShiftState() {
    return this.req<NightShiftState>("GET", "/api/night-shift");
  }
  /** End a night shift (Developer Unlock): no more reminders; the coordinator is told to stop safely. */
  nightShiftEnd(project: string) {
    return this.req<{ ok: boolean; told: boolean }>("POST", "/api/night-shift/end", { project });
  }
  /** A UI test run, when Jay asks (Developer Unlock): the coordinator tests the UI merged since its last run. */
  uiTest(project: string, copy = false) {
    return this.req<TaskCheckResult>("POST", "/api/tasks/ui-test", copy ? { project, copy: true } : { project });
  }
  /** Every project's latest UI test run and Jay's decisions. */
  uiTests() {
    return this.req<UiTestsState>("GET", "/api/ui-tests");
  }
  /** Project Operating Profiles and Jay's decisions (policy/): read-only. */
  profiles() {
    return this.req<PolicyState>("GET", "/api/profiles");
  }

  autonomy() {
    return this.req<AutonomyState>("GET", "/api/autonomy");
  }

  decisions() {
    return this.req<LedgerState>("GET", "/api/decisions");
  }
  /** Jay decides one finding: fix (a ui-finding task enters the pipeline) or skip. */
  uiDecide(project: string, run: string, finding: string, decision: "fix" | "skip") {
    return this.req<{ ok: boolean; finding: string; decision: string; ticket: string | null }>("POST", "/api/ui-tests/decide",
      { project, run, finding, decision });
  }
  /** What each project can merge now (reviewed head, PR open and green), in merge order. */
  mergeReady() {
    return this.req<MergeReady>("GET", "/api/jay/merge");
  }
  /** Merge (Developer Unlock): approve exactly those heads; the coordinator merges them one at a time. */
  merge(project: string, items: { key: string; head: string }[]) {
    return this.req<MergeResult>("POST", "/api/jay/merge", { project, items });
  }
  /** Go Live (Developer Unlock): approves the open live-deploy gates and asks the coordinator to PREPARE the deploy; Jay confirms it in its pane. */
  goLive(project: string, keys: string[]) {
    return this.req<GoLiveResult>("POST", "/api/jay/go-live", { project, keys });
  }
  /** Jay answers Claude's questions (Developer Unlock). The last answer resumes the same task session. */
  answers(key: string, answers: { id: number; answer: string }[], scopeChange = false) {
    return this.req<AnswersResult>("POST", `/api/tasks/${encodeURIComponent(key)}/answers`, { answers, scopeChange });
  }
  record(key: string) { return this.req<TaskRecord>("GET", `/api/tasks/${encodeURIComponent(key)}/record`); }
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

  devCommits(key: string) { return this.req<DevCommits>("GET", `/api/development/${encodeURIComponent(key)}/commits`); }

  // ---------- workspace ----------
  workspaceProjects() { return this.req<{ projects: WorkspaceProject[] }>("GET", "/api/workspace/projects"); }
  listDir(project: string, path: string, git = false) {
    return this.req<FileList>("GET", `/api/files/list?${new URLSearchParams({ project, path, ...(git ? { git: "1" } : {}) })}`);
  }
  readFile(project: string, path: string) {
    return this.req<FileRead>("GET", `/api/files/read?${new URLSearchParams({ project, path })}`);
  }
  saveFile(project: string, path: string, text: string, baseSha: string | null) {
    return this.req<SaveResult>("POST", "/api/files/save", { project, path, text, baseSha });
  }
  attachments(owner: "ticket" | "project", key: string) {
    return this.req<{ attachments: Attachment[] }>("GET", `/api/attachments?${new URLSearchParams({ owner, key })}`);
  }
  removeAttachment(id: string) { return this.req<{ ok: true }>("DELETE", `/api/attachments/${encodeURIComponent(id)}`, {}); }
  developerStatus() { return this.req<{ active: boolean; expiresIn: number | null; tokenFile?: string | null }>("GET", "/api/developer"); }
  unlock(token: string) {
    return this.req<{ ok: true; session: string; expiresIn: number }>("POST", "/api/developer/unlock", { token });
  }
  lock() { return this.req<{ ok: true }>("POST", "/api/developer/lock", {}); }
  launcher() { return this.req<LauncherInfo>("GET", "/api/desktop/launcher"); }

  // ---------- explorer operations (Developer Mode) ----------
  mkdir(project: string, dir: string, name: string) { return this.req<{ path: string }>("POST", "/api/files/mkdir", { project, dir, name }); }
  renamePath(project: string, path: string, name: string) { return this.req<{ path: string }>("POST", "/api/files/rename", { project, path, name }); }
  duplicate(project: string, path: string) { return this.req<{ path: string; name: string }>("POST", "/api/files/duplicate", { project, path }); }
  removePath(project: string, path: string) { return this.req<{ path: string; deleted: string }>("POST", "/api/files/remove", { project, path }); }

  // ---------- search ----------
  searchFiles(project: string, signal?: AbortSignal) {
    return this.reqAbortable<{ files: string[]; truncated: boolean }>(`/api/search/files?${new URLSearchParams({ project })}`, signal);
  }
  searchText(project: string, q: string, opts: { regex?: boolean; caseSensitive?: boolean; glob?: string }, signal?: AbortSignal) {
    const p = new URLSearchParams({ project, q });
    if (opts.regex) p.set("regex", "1");
    if (opts.caseSensitive) p.set("case", "1");
    if (opts.glob) p.set("glob", opts.glob);
    return this.reqAbortable<SearchResult>(`/api/search/text?${p}`, signal);
  }

  // ---------- source control ----------
  scmStatus(project: string) { return this.req<ScmStatus>("GET", `/api/scm/status?${new URLSearchParams({ project })}`); }
  scmDiff(project: string, path: string, staged: boolean) {
    return this.req<ScmDiff>("GET", `/api/scm/diff?${new URLSearchParams({ project, path, ...(staged ? { staged: "1" } : {}) })}`);
  }
  scmTicketBranch(ticket: string) { return this.req<{ ticket: string; existing: string | null; suggested: string }>("GET", `/api/scm/ticket-branch?${new URLSearchParams({ ticket })}`); }
  scm(op: "stage" | "unstage" | "stage-all" | "discard" | "commit" | "branch", body: Record<string, unknown>) {
    return this.req<Record<string, unknown>>("POST", `/api/scm/${op}`, body);
  }

  // ---------- Claude input (Developer Mode) and terminals ----------
  prompt(agentId: string, text: string) { return this.req<{ ok: true }>("POST", "/api/action/prompt", { agentId, text }); }
  key(agentId: string, key: "esc" | "enter") { return this.req<{ ok: true }>("POST", "/api/action/key", { agentId, key }); }
  ptyList() { return this.req<{ sessions: PtySession[]; enabled: boolean }>("GET", "/api/pty"); }
  adoptCoordinator(project: string, sessionId: string) {
    return this.req<{ ok: true; coordinator: CoordinatorState & { paneId: string | null } }>("POST", "/api/coordinators/adopt", { project, sessionId });
  }
  ptyClose(name: string) { return this.req<{ ok: true }>("POST", "/api/pty/close", { name }); }

  private async reqAbortable<T>(path: string, signal?: AbortSignal): Promise<T> {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["X-CCD-Token"] = token;
    const res = await this.fetchImpl(this.base + path, { headers, cache: "no-store", credentials: "omit", signal });
    let data: unknown = null;
    try { data = await res.json(); } catch { /* empty */ }
    if (!res.ok) throw new ApiError(res.status, data && typeof data === "object" && "error" in data ? String((data as { error: unknown }).error) : `HTTP ${res.status}`);
    return data as T;
  }

  /** GET a file with the token header and hand it to the browser as a download. */
  async download(path: string, fallbackName: string) {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["X-CCD-Token"] = token;
    const res = await this.fetchImpl(this.base + path, { headers, cache: "no-store", credentials: "omit" });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { msg = String((await res.json()).error ?? msg); } catch { /* not json */ }
      throw new ApiError(res.status, msg);
    }
    const cd = res.headers.get("content-disposition") ?? "";
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : fallbackName;
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = name; a.rel = "noopener";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
}

/** A raw-bytes upload with progress (fetch has no upload progress). */
export function uploadBytes(path: string, file: Blob, onProgress: (fraction: number) => void): Promise<UploadResult & Attachment> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    const token = getToken();
    if (token) xhr.setRequestHeader("X-CCD-Token", token);
    const dev = devSession();
    if (dev) xhr.setRequestHeader("X-CCD-Developer", dev);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onerror = () => reject(new ApiError(0, "ccd unreachable"));
    xhr.onload = () => {
      let data: Record<string, unknown> = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* empty */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data as unknown as UploadResult & Attachment);
      if (xhr.status === 403 && String(data.error ?? "").startsWith("Developer Unlock")) devExpired();
      reject(Object.assign(new ApiError(xhr.status, String(data.error ?? `HTTP ${xhr.status}`)), { data }));
    };
    xhr.send(file);
  });
}

export type { Ticket };
export const api = new Api();
