import { Api, ApiError } from "../src/api/client";
import { setToken, clearToken, getToken, isRemembered } from "../src/api/auth";
import { jsonResponse } from "./helpers";

describe("API adapter", () => {
  beforeEach(() => { clearToken(); });
  it("sends the token in a header, never in the URL", async () => {
    setToken("a".repeat(43));
    const calls: [string, RequestInit][] = [];
    const api = new Api(async (u, init) => { calls.push([String(u), init!]); return jsonResponse({ tickets: [], projects: [], meta: {}, seq: 1 }); });
    await api.tasks();
    expect(calls[0][0]).toBe("/api/tasks");
    expect(calls[0][0]).not.toContain("token");
    expect((calls[0][1].headers as Record<string, string>)["X-CCD-Token"]).toBe("a".repeat(43));
    expect(calls[0][1].credentials).toBe("omit");
  });
  it("writes are JSON (ccd refuses anything else)", async () => {
    setToken("a".repeat(43));
    let init: RequestInit | undefined;
    const api = new Api(async (_u, i) => { init = i; return jsonResponse({ key: "CC-001" }, 201); });
    await api.updateTask("CC-001", { status: "DONE" });
    expect(init!.method).toBe("PATCH");
    expect((init!.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init!.body))).toEqual({ status: "DONE" });
  });
  it("maps ccd errors and network failure to ApiError", async () => {
    const api = new Api(async () => jsonResponse({ ok: false, error: "token required" }, 401));
    await expect(api.state()).rejects.toMatchObject({ status: 401, message: "token required" });
    const down = new Api(async () => { throw new TypeError("Failed to fetch"); });
    await expect(down.state()).rejects.toBeInstanceOf(ApiError);
    await expect(down.state()).rejects.toMatchObject({ status: 0 });
  });
  it("encodes keys and agent ids in paths", async () => {
    const urls: string[] = [];
    const api = new Api(async (u) => { urls.push(String(u)); return jsonResponse({}); });
    await api.tail("wE:p2", 40);
    await api.relate("CC-001", "blocked_by", "CC-002");
    expect(urls[0]).toBe("/api/agents/wE%3Ap2/tail?lines=40");
    expect(urls[1]).toBe("/api/tasks/CC-001/relations");
  });
});

describe("token storage", () => {
  beforeEach(() => clearToken());
  it("defaults to this tab only", () => {
    setToken(" b".repeat(1) + "b".repeat(42));
    expect(getToken()).toBe("b".repeat(43));
    expect(sessionStorage.getItem("ccd.token")).toBe("b".repeat(43));
    expect(localStorage.getItem("ccd.token")).toBeNull();
    expect(isRemembered()).toBe(false);
  });
  it("remember puts it in localStorage, forget clears both", () => {
    setToken("c".repeat(43), true);
    expect(localStorage.getItem("ccd.token")).toBe("c".repeat(43));
    clearToken();
    expect(getToken()).toBeNull();
    expect(localStorage.getItem("ccd.token")).toBeNull();
  });
});
