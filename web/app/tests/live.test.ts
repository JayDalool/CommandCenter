import { Live } from "../src/api/live";
import { FakeSocket, ev } from "./helpers";

function make(token = "t".repeat(43)) {
  const seen: number[] = [], lost: string[] = [], statuses: string[] = [];
  const live = new Live({ onEvent: (e) => seen.push(e.seq), onLost: (r) => lost.push(r), onStatus: (s) => statuses.push(s) },
    { token: () => token, WebSocketImpl: FakeSocket as unknown as typeof WebSocket, url: "ws://127.0.0.1:7777/api/events" });
  return { live, seen, lost, statuses };
}

describe("live event stream", () => {
  beforeEach(() => { FakeSocket.reset(); vi.useFakeTimers(); });
  afterEach(() => vi.useRealTimers());

  it("offers the token as a subprotocol and resumes from seq", () => {
    const { live } = make();
    live.start(41);
    const s = FakeSocket.last();
    expect(s.url).toBe("ws://127.0.0.1:7777/api/events?since=41");
    expect(s.url).not.toContain("token");
    expect(s.protocols).toEqual(["ccd.v1", `ccd-token.${"t".repeat(43)}`]);
    live.stop();
  });

  it("applies replayed events in order once, then goes live", () => {
    const { live, seen, statuses } = make();
    live.start(10);
    const s = FakeSocket.last();
    s.open();
    s.msg({ type: "event", event: ev(11, "agent.started") });
    s.msg({ type: "event", event: ev(12, "pr.opened") });
    s.msg({ type: "event", event: ev(12, "pr.opened") });  // overlap from replay + live
    s.msg({ type: "replay_done", seq: 12 });
    expect(seen).toEqual([11, 12]);
    expect(statuses.at(-1)).toBe("live");
    expect(live.lastSeq).toBe(12);
    live.stop();
  });

  it("events_lost asks the app to refetch state", () => {
    const { live, lost } = make();
    live.start(5);
    FakeSocket.last().msg({ type: "events_lost", seq: 99, reason: "since is outside the retained log" });
    expect(lost).toHaveLength(1);
    live.stop();
  });

  it("reconnects after a drop, resuming from the last seq", () => {
    const { live, statuses } = make();
    live.start(1);
    const s = FakeSocket.last();
    s.open(); s.msg({ type: "hello", seq: 1 }); s.msg({ type: "event", event: ev(2, "agent.blocked") });
    s.drop();
    expect(statuses.at(-1)).toBe("offline");
    vi.advanceTimersByTime(1500);
    expect(FakeSocket.all).toHaveLength(2);
    expect(FakeSocket.last().url).toMatch(/since=2$/);
    live.stop();
  });

  it("a silent socket is treated as dead", () => {
    let now = 1_000_000;
    const live = new Live({ onEvent() {}, onLost() {}, onStatus() {} },
      { token: () => "x".repeat(40), WebSocketImpl: FakeSocket as unknown as typeof WebSocket, url: "ws://x/api/events",
        now: () => now, staleAfterMs: 45_000 });
    live.start(0);
    const s = FakeSocket.last();
    s.open(); s.msg({ type: "hello", seq: 0 });
    now += 60_000;
    vi.advanceTimersByTime(5_000);
    expect(s.closed).toBe(true);
    live.stop();
  });
});

describe("live stream review fixes", () => {
  beforeEach(() => { FakeSocket.reset(); });
  it("a second start replaces the first socket instead of leaking it", () => {
    const seen: number[] = [];
    const live = new Live({ onEvent: (e) => seen.push(e.seq), onLost() {}, onStatus() {} },
      { token: () => "x".repeat(40), WebSocketImpl: FakeSocket as unknown as typeof WebSocket, url: "ws://x/api/events" });
    live.start(1);
    const first = FakeSocket.last();
    live.start(1);
    expect(first.closed).toBe(true);
    first.msg({ type: "event", event: ev(2, "agent.started") });  // the orphan must be deaf
    expect(seen).toEqual([]);
    live.stop();
  });
});
