import { App } from "../src/store/app";
import { Api } from "../src/api/client";
import { setToken, clearToken } from "../src/api/auth";
import { FakeSocket, state, tasks, ev, jsonResponse } from "./helpers";

function setup(over: Partial<Record<string, (u: string, i?: RequestInit) => Response | Promise<Response>>> = {}) {
  const calls: string[] = [];
  let up = true;
  const fetchImpl = async (u: RequestInfo | URL, init?: RequestInit) => {
    const url = String(u);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (!up) throw new TypeError("Failed to fetch");
    const path = url.split("?")[0];
    if (over[path]) return over[path]!(url, init);
    if (path === "/api/state") return jsonResponse(state());
    if (path === "/api/tasks") return jsonResponse(tasks());
    if (path === "/api/activity") return jsonResponse({ seq: 5, events: [ev(5, "agent.started"), ev(4, "pr.opened")] });
    if (path.startsWith("/api/tasks/")) {
      const key = decodeURIComponent(path.split("/")[3]);
      const t = tasks().tickets.find((x) => x.key === key)!;
      return jsonResponse({ ...t, title: "fresh " + t.title, description: "", relations: { blocks: [], blocked_by: [], related: [], duplicates: [], duplicated_by: [] },
        subtaskList: [], comments: [], timeline: [] });
    }
    return jsonResponse({ ok: false, error: "nope" }, 404);
  };
  const app = new App(new Api(fetchImpl), FakeSocket as unknown as typeof WebSocket);
  return { app, calls, setUp: (v: boolean) => { up = v; } };
}

describe("app controller", () => {
  beforeEach(() => { FakeSocket.reset(); clearToken(); setToken("t".repeat(43)); });
  afterEach(() => vi.useRealTimers());

  it("asks for a token when there is none", async () => {
    clearToken();
    const { app } = setup();
    await app.boot();
    expect(app.data.auth).toBe("needed");
  });

  it("boots from REST, then opens the stream at the state's seq", async () => {
    const { app } = setup();
    await app.boot();
    expect(app.data.auth).toBe("ok");
    expect(app.data.tickets.length).toBe(18);
    expect(app.data.activity.map((e) => e.seq)).toEqual([5, 4]);
    expect(FakeSocket.last().url).toMatch(new RegExp(`since=${state().seq}$`));
    app.live.stop();
  });

  it("a 401 sends Jay back to the token screen", async () => {
    const { app } = setup({ "/api/state": () => jsonResponse({ ok: false, error: "token required" }, 401) });
    await app.boot();
    expect(app.data.auth).toBe("needed");
    expect(app.data.authError).toMatch(/refused/);
  });

  it("offline keeps the last data on screen", async () => {
    const { app, setUp } = setup();
    await app.boot();
    const before = app.data.state;
    setUp(false);
    FakeSocket.last().drop();
    await app.refreshState();
    expect(app.data.conn.status).toBe("offline");
    expect(app.data.state).toBe(before);
    expect(app.data.error).toMatch(/unreachable/);
    app.live.stop();
  });

  it("events_lost refetches everything and resumes from the fresh seq", async () => {
    const { app, calls } = setup();
    await app.boot();
    const n = calls.filter((c) => c === "GET /api/state").length;
    FakeSocket.last().msg({ type: "events_lost", seq: 999 });
    await vi.waitFor(() => expect(calls.filter((c) => c === "GET /api/state").length).toBe(n + 1));
    await vi.waitFor(() => expect(FakeSocket.all.length).toBe(2));
    app.live.stop();
  });

  it("a task event refreshes just that ticket", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { app, calls } = setup();
    await app.boot();
    app.onEvent(ev(50, "task.updated", { ref: "SV-056", data: { kind: "status" } }));
    await vi.advanceTimersByTimeAsync(200);
    expect(calls).toContain("GET /api/tasks/SV-056");
    await vi.waitFor(() => expect(app.data.tickets.find((t) => t.key === "SV-056")!.title).toMatch(/^fresh /));
    expect(app.data.activity[0].seq).toBe(50);
    app.live.stop();
  });

  it("a burst of agent events costs one state refetch", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { app, calls } = setup();
    await app.boot();
    const n = calls.filter((c) => c === "GET /api/state").length;
    for (let i = 0; i < 20; i++) app.onEvent(ev(100 + i, "agent.state_changed"));
    await vi.advanceTimersByTimeAsync(2000);
    expect(calls.filter((c) => c === "GET /api/state").length).toBe(n + 1);
    app.live.stop();
  });
});
