import { vi } from "vitest";
import { Api, ApiError, IMPORT_PREVIEW_TIMEOUT_MS, READ_TIMEOUT_MS } from "../src/api/client";
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
  describe("a read ccd never answers", () => {
    afterEach(() => { vi.useRealTimers(); });
    // A stand-in fetch that never answers, but gives up when its request is aborted, as a browser's fetch does.
    const hang = (seen: RequestInit[] = []) => new Api((_u, init) => new Promise((_ok, fail) => {
      seen.push(init!);
      init?.signal?.addEventListener("abort", () => fail(new DOMException("The operation was aborted.", "AbortError")));
    }));

    it("fails after READ_TIMEOUT_MS as ccd not answering, so nothing waits on it for good", async () => {
      vi.useFakeTimers();
      const seen: RequestInit[] = [];
      const got = hang(seen).release().catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS - 1);
      expect(seen[0].signal?.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      const e = await got;
      expect(e).toBeInstanceOf(ApiError);
      expect(e).toMatchObject({ status: 0, message: "ccd did not answer within 30 s" });
      expect(seen[0].signal?.aborted).toBe(true);
    });

    it("a body that stops half way is not taken as an empty answer", async () => {
      vi.useFakeTimers();
      const api = new Api(async (_u, init) => ({ ok: true, status: 200, json: () => new Promise((_ok, fail) =>
        init!.signal!.addEventListener("abort", () => fail(new DOMException("aborted", "AbortError")))) }) as unknown as Response);
      const got = api.state().catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS);
      expect(await got).toMatchObject({ status: 0, message: "ccd did not answer within 30 s" });
    });

    it("a write is never cut off: it may still land, and a timeout would invite a second press", async () => {
      vi.useFakeTimers();
      const seen: RequestInit[] = [];
      let settled = false;
      void hang(seen).updateTask("CC-001", { status: "DONE" }).finally(() => { settled = true; });
      await vi.advanceTimersByTimeAsync(10 * READ_TIMEOUT_MS);
      expect(settled).toBe(false);
      expect(seen[0].signal).toBeUndefined();
      expect(vi.getTimerCount()).toBe(0);
    });

    it("the import preview gets longer: ccd asks GitHub once per project before it answers", async () => {
      vi.useFakeTimers();
      const seen: RequestInit[] = [];
      const got = hang(seen).importPreview().catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(IMPORT_PREVIEW_TIMEOUT_MS - 1);
      expect(seen[0].signal?.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(await got).toMatchObject({ status: 0, message: "ccd did not answer within 180 s" });
    });

    it("an answered read leaves no timer behind", async () => {
      vi.useFakeTimers();
      await new Api(async () => jsonResponse({ ok: true })).state();
      await new Api(async () => jsonResponse({ ok: false, error: "token required" }, 401)).state().catch(() => {});
      await new Api(async () => { throw new TypeError("Failed to fetch"); }).state().catch(() => {});
      expect(vi.getTimerCount()).toBe(0);
    });
  });
  it("encodes keys and agent ids in paths", async () => {
    const urls: string[] = [];
    const api = new Api(async (u) => { urls.push(String(u)); return jsonResponse({}); });
    await api.tail("wE:p2", 40);
    await api.relate("CC-001", "blocked_by", "CC-002");
    expect(urls[0]).toBe("/api/agents/wE%3Ap2/tail?lines=40");
    expect(urls[1]).toBe("/api/tasks/CC-001/relations");
  });
  it("milestones and the briefing: ccd's routes, and every write is JSON, a DELETE included", async () => {
    const calls: [string, string, string | undefined, unknown][] = [];
    const api = new Api(async (u, i) => {
      calls.push([i!.method!, String(u), (i!.headers as Record<string, string>)["Content-Type"], i!.body ? JSON.parse(String(i!.body)) : undefined]);
      return jsonResponse({});
    });
    await api.milestones();
    await api.milestoneAdd("samvision", { track: "business", title: "Contact the lawyer", due: null });
    await api.milestoneChange("samvision", "m_0123456789ab", { state: "done" });
    await api.milestoneRemove("samvision", "m_0123456789ab");
    await api.milestoneOrder("samvision", "technical", ["m_b", "m_a"], 7);
    await api.briefing();
    await api.briefing(1794505841.73);
    expect(calls).toEqual([
      ["GET", "/api/milestones", undefined, undefined],
      ["POST", "/api/milestones/samvision", "application/json", { track: "business", title: "Contact the lawyer", due: null }],
      ["PATCH", "/api/milestones/samvision/m_0123456789ab", "application/json", { state: "done" }],
      ["DELETE", "/api/milestones/samvision/m_0123456789ab", "application/json", {}],
      ["PUT", "/api/milestones/samvision/order", "application/json", { track: "technical", ids: ["m_b", "m_a"], revision: 7 }],
      ["GET", "/api/briefing", undefined, undefined],
      ["GET", "/api/briefing?since=1794505841", undefined, undefined],
    ]);
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
