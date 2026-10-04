import { freshness } from "../src/lib/freshness";
import { state } from "./helpers";

const live = { status: "live" as const, lastMessageAt: 0 };
describe("source freshness", () => {
  it("is live when every source is recent", () => {
    const st = state();
    const now = Math.max(st.sources.host.asOf!, ...Object.values(st.sources.github).map((g) => g.asOf!)) + 5;
    st.sources.herdr.lastEventAt = now - 1;
    const rows = freshness(st, { ...live, lastMessageAt: now * 1000 - 200 }, now);
    expect(rows.map((r) => r.label)).toEqual(["HERDR", "GITHUB", "HOST", "TASKS", "CCD"]);
    expect(rows.every((r) => r.state === "live")).toBe(true);
  });
  it("names a stale GitHub with its age", () => {
    const st = state();
    const oldest = Math.min(...Object.values(st.sources.github).map((g) => g.asOf!));
    const rows = freshness(st, live, oldest + 312);
    const gh = rows.find((r) => r.id === "github")!;
    expect(gh.state).toBe("stale");
    expect(Math.round(gh.ageS!)).toBe(312);
  });
  it("herdr down is down, not stale", () => {
    const st = state();
    st.sources.herdr.ok = false;
    st.sources.herdr.error = "No such file";
    expect(freshness(st, live, st.sources.host.asOf!).find((r) => r.id === "herdr")!.state).toBe("down");
  });
  it("when the stream is offline nothing is shown as live", () => {
    const st = state();
    const rows = freshness(st, { status: "offline", lastMessageAt: null }, st.sources.host.asOf!);
    expect(rows.find((r) => r.id === "ccd")!.state).toBe("down");
    expect(rows.some((r) => r.state === "live")).toBe(false);
  });
  it("tasks off when the ccd has no task system", () => {
    const st = state();
    delete st.sources.tasks;
    expect(freshness(st, live, st.sources.host.asOf!).find((r) => r.id === "tasks")!.state).toBe("off");
  });
});
