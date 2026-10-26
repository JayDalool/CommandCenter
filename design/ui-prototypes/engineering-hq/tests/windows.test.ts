import { beforeEach, describe, expect, it, vi } from "vitest";
import { BEAT_MS, GRACE_MS, PENDING_MS, STALE_MS, claimAsPopout, deadOwners, notices, owners, popOut, returnHere, windowName } from "../src/windows/manager";
import { viewById } from "../src/windows/views";
import { SharedStore, WIN_ID, isRecord } from "../src/lib/shared";
import { appendMessage, chat } from "../src/data/live";

const fakeWin = () => ({ closed: false, focus: vi.fn(), close: vi.fn() }) as unknown as Window;

beforeEach(() => { owners.set({}); notices.set([]); sessionStorage.clear(); });

describe("pop out", () => {
  it("opens a real window for the view, from the same origin path, with only the view id in the address", () => {
    const open = vi.fn(() => fakeWin());
    expect(popOut("page:topology", open)).toBe("opened");
    const [url, name, features] = open.mock.calls[0] as unknown as [string, string, string];
    expect(url).toMatch(/#\/pop\/page%3Atopology$/);
    expect(url).not.toMatch(/token|session|dev|key=/i);       // no credential ever rides in the URL
    expect(name).toBe(windowName("page:topology"));
    expect(features).toContain("popup=yes");
    expect(owners.get()["page:topology"]).toMatchObject({ state: "popped", win: null });
  });

  it("a blocked pop-up rolls the view back and tells Jay how to allow pop-ups", () => {
    expect(popOut("page:revenue", () => null)).toBe("blocked");
    expect(owners.get()["page:revenue"]).toBeUndefined();
    expect(notices.get().at(-1)?.text).toMatch(/blocked.*Allow pop-ups/);
  });

  it("popping out a view that is already out focuses it instead of making a second owner", () => {
    const open = vi.fn(() => fakeWin());
    popOut("dm:sv-lead", open);
    expect(popOut("dm:sv-lead", open)).toBe("focused");
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("return here takes ownership back and closes the window", () => {
    const w = fakeWin();
    popOut("task:SV-025", () => w);
    returnHere("task:SV-025");
    expect(owners.get()["task:SV-025"]).toBeUndefined();
    expect(w.close).toHaveBeenCalled();
  });

  it("refuses ids that are not a known view", () => {
    for (const bad of ["page:../../etc", "javascript:alert(1)", "dm:nope", "page:office?token=x", "x"]) expect(popOut(bad, vi.fn())).toBe("invalid");
    expect(viewById("page:office")?.title).toBe("My Office");
  });
});

describe("pop-out window lifecycle", () => {
  it("claims the view, beats, and marks itself closing on pagehide (OS close button)", () => {
    vi.useFakeTimers();
    popOut("page:office", () => fakeWin());
    const stop = claimAsPopout("page:office", vi.fn());
    expect(owners.get()["page:office"].win).toBe(WIN_ID);
    const first = owners.get()["page:office"].beat;
    vi.advanceTimersByTime(BEAT_MS + 5);
    expect(owners.get()["page:office"].beat).toBeGreaterThanOrEqual(first);
    window.dispatchEvent(new Event("pagehide"));
    expect(owners.get()["page:office"].state).toBe("closing");
    stop(); vi.useRealTimers();
  });

  it("closes itself when another window takes the view back", () => {
    const lost = vi.fn();
    const stop = claimAsPopout("page:teams", lost);
    returnHere("page:teams");
    expect(lost).toHaveBeenCalled();
    stop();
  });

  it("a reload after the view was returned does not steal it back", () => {
    const stop = claimAsPopout("page:decisions", vi.fn());
    returnHere("page:decisions");
    stop();
    const lost = vi.fn();
    claimAsPopout("page:decisions", lost)();       // same window reloads: its session flag says it had claimed before
    expect(lost).toHaveBeenCalled();
    expect(owners.get()["page:decisions"]).toBeUndefined();
  });
});

describe("recovery never leaves a view shaded forever", () => {
  const now = 1_000_000;
  it("heartbeat mode (no Web Locks)", () => {
    const o = {
      "page:office": { state: "popped" as const, win: "w1", beat: now - 1000, since: now - 9999 },        // alive
      "page:revenue": { state: "popped" as const, win: "w2", beat: now - STALE_MS - 1, since: 0 },        // crashed
      "page:teams": { state: "closing" as const, win: "w3", beat: now - GRACE_MS - 1, since: 0 },        // closed with X
      "page:messages": { state: "closing" as const, win: "w4", beat: now - 100, since: 0 },              // maybe reloading
      "dm:nova": { state: "popped" as const, win: null, beat: now - PENDING_MS - 1, since: now - PENDING_MS - 1 },  // never opened
    };
    expect(deadOwners(o, now, null).sort()).toEqual(["dm:nova", "page:revenue", "page:teams"]);
  });
  it("Web Locks mode: a held lock is alive even if timers were throttled", () => {
    const o = { "page:office": { state: "popped" as const, win: "w1", beat: now - 60_000, since: 0 },
      "page:revenue": { state: "popped" as const, win: "w2", beat: now - GRACE_MS - 1, since: 0 } };
    expect(deadOwners(o, now, new Set(["hq-view:page:office"]))).toEqual(["page:revenue"]);
  });
});

describe("shared state is validated and idempotent", () => {
  it("ignores values that fail the store's guard", () => {
    const s = new SharedStore<Record<string, number>>("t-guard", {}, (v): v is Record<string, number> => isRecord(v) && Object.values(v).every((x) => typeof x === "number"));
    s.receive({ a: "<script>" });
    expect(s.get()).toEqual({});
    s.receive({ a: 1 });
    expect(s.get()).toEqual({ a: 1 });
  });
  it("a replayed chat message is not duplicated", () => {
    const m = { cid: "same-id", from: "jay", at: "now", text: "hello" };
    const before = chat.get()["nova"].length;
    appendMessage("nova", m); appendMessage("nova", m); appendMessage("nova", { ...m });
    expect(chat.get()["nova"].length).toBe(before + 1);
  });
});
