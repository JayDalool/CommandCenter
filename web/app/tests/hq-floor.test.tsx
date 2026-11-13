// The office floor (hq/data/floor.ts, hq/pages/Floor.tsx): My Office's sessions as a place. A session is where its
// presence says and nowhere else, each once; a feed that is not live seats nobody and counts nothing; and a session
// whose state changes is moved to its new place with one CSS transition, unless the reader asked for less motion.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { parsePrefs, prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { buildFloor, buildTeams, evidence, type FloorView } from "../src/hq/data";
import { initials } from "../src/hq/pages/Floor";
import { castLeads, leadKeys } from "../src/hq/persona/assign";
import type { Agent, AgentStatus, State } from "../src/api/types";
import { fixture, state, tasks } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;
const WAIT = fixture.state.agents.find((a) => a.agent_name === "gauzemate")!.blockedSinceMs!;

const A = (id: string, name: string, project: string | null, status: string, extra: Partial<Agent> = {}): Agent => ({
  id, pane_id: id, agent_name: name, agent: "claude", label: name, project, role: "lane", status: status as AgentStatus, live: true, cwd: "/srv",
  workspace: "w", workspace_id: "w", tab_id: "t", session_id: `s-${id}`, blockedSinceMs: null, blockedForMin: null, context: null, ...extra });

/** The fixture's three sessions (the samvision lead idle, the gauzemate lead waiting, sv-056-impl working) and six
 *  more: one in every place, a team with no lead, and a session with no project. */
function crowd(): State {
  const st = state();
  st.agents.push(
    A("x1", "sv-071", "samvision", "idle"),
    A("x2", "sv-082-plan", "samvision", "blocked", { blockedSinceMs: WAIT - 600_000 }),
    A("x3", "gm-012-impl", "gauzemate", "working"),
    A("x4", "gy-003-impl", "gyst", "idle", { live: false }),
    A("x5", "scratch", null, "idle"),
    A("x6", "odd", "mfe", "resting"));
  return st;
}

function load(live = true, st = crowd()) {
  const t = tasks();
  const now = live ? SNAPSHOT + 10_000 : new Date("2026-10-27T15:00:00Z").getTime();
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: st, stateAt: now, tickets: t.tickets, ticketsLoaded: true, taskProjects: t.projects, meta: t.meta,
    conn: live ? { status: "live", lastMessageAt: now, attempt: 0 } : { status: "offline", lastMessageAt: null, attempt: 1 } });
}
const view = (): FloorView => { const src = app.store.get(), ev = evidence(src, Date.now() / 1000); return buildFloor(buildTeams(src, ev)); };

async function show() {
  location.hash = "#/dashboard";
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main [aria-labelledby='hq-office-sessions']")!;
}
const zone = (panel: HTMLElement, name: RegExp) => within(panel).getByRole("region", { name });
const who = (el: ParentNode) => [...el.querySelectorAll<HTMLElement>("[data-who]")];
const names = (el: ParentNode) => who(el).map((w) => w.querySelector("b")!.textContent);

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq", style: "professional", sessions: "floor" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional", sessions: "floor" }); });

describe("where each session is", () => {
  it("is one place, from its presence: a desk only while working, the door in the order the waits began", () => {
    load();
    const f = view();
    expect(f.teams.map((t) => [t.key, t.desks.map((m) => m.name)])).toEqual([
      ["samvision", ["samvision", "sv-056-impl", "sv-071", "sv-082-plan"]],   // the lead first, then by name
      ["gyst", ["gy-003-impl"]],                                              // a team with no lead still has its desks
      ["mfe", ["odd"]],
      ["gauzemate", ["gauzemate", "gm-012-impl"]],
      [null, ["scratch"]],
    ]);
    const spots = Object.fromEntries(f.teams.flatMap((t) => t.desks).map((m) => [m.name, m.spot]));
    expect(spots).toEqual({ samvision: "lounge", "sv-056-impl": "desk", "sv-071": "lounge", "sv-082-plan": "door", "gy-003-impl": "out",
      odd: "unseen", gauzemate: "door", "gm-012-impl": "desk", scratch: "lounge" });
    expect(f.door.map((m) => m.name)).toEqual(["sv-082-plan", "gauzemate"]);
    expect(f.lounge.map((m) => m.name)).toEqual(["samvision", "sv-071", "scratch"]);
    expect([f.out.map((m) => m.name), f.unseen.map((m) => m.name)]).toEqual([["gy-003-impl"], ["odd"]]);
    expect(f.total).toBe(app.store.get().state!.agents.length);
    expect(f.teams.at(-1)).toMatchObject({ name: "No project", desks: [{ project: null, projectName: null }] });
  });

  it("is nowhere when the session feed is not live: nobody at a desk, at the door or in the lounge", () => {
    load(false);
    const f = view();
    expect(f.unseen).toHaveLength(9);
    expect([f.door, f.lounge, f.out, f.teams.flatMap((t) => t.desks).filter((m) => m.spot === "desk")]).toEqual([[], [], [], []]);
  });

  it("has two letters for a session without a face", () => {
    expect(["sv-056-impl", "samvision", "gm 012 ui", "071", "é", ""].map(initials)).toEqual(["SI", "SA", "GU", "07", "É", "?"]);
  });
});

describe("the floor on My Office", () => {
  it("is how sessions are shown first: the door, the desks, the lounge, then who is out, each session once", async () => {
    load();
    const panel = await show();
    expect(within(panel).getByRole("button", { name: "Floor" })).toHaveAttribute("aria-pressed", "true");
    expect(within(panel).queryByRole("group", { name: "Filter sessions" })).toBeNull();
    expect(within(panel).getAllByRole("region").map((r) => r.querySelector("h4")!.textContent)).toEqual([
      "At your door 2 waiting for you", "At their desks 2 working", "In the lounge 3 idle", "Out of the office 1 offline", "Not seen 1, status unknown"]);

    const ids = who(panel).map((w) => w.dataset.who);
    expect(ids.sort()).toEqual(app.store.get().state!.agents.map((a) => a.id).sort());
    expect(names(zone(panel, /^At your door/))).toEqual(["sv-082-plan", "gauzemate"]);
    expect(names(zone(panel, /^At their desks/))).toEqual(["sv-056-impl", "gm-012-impl"]);
    expect(names(zone(panel, /^In the lounge/))).toEqual(["samvision", "sv-071", "scratch"]);
    expect(names(zone(panel, /^Out of the office/))).toEqual(["gy-003-impl"]);
    expect(names(zone(panel, /^Not seen/))).toEqual(["odd"]);

    // who it is and what it is on, in words; away from its desk, whose team
    const door = who(zone(panel, /^At your door/));
    expect(door[0]).toHaveTextContent(/^SPsv-082-planSamVision · waiting 10m$/);
    expect(door[1]).toHaveTextContent(/^GAgauzemateGauzeMate lead · waiting \d+s$/);
    expect(within(panel).getByRole("link", { name: "Open Decisions" })).toHaveAttribute("href", "#/needs");
    // a session opens its task; one that waits with no task opens Decisions; any other opens Teams
    const f = view();
    for (const m of f.teams.flatMap((t) => t.desks)) {
      const el = panel.querySelector<HTMLElement>(`[data-who="${m.id}"]`)!;
      expect(el.getAttribute("href"), m.name).toBe(m.ticket ? `#/tasks/${m.ticket}` : m.spot === "door" ? "#/needs" : "#/agents");
    }
    expect(f.door.some((m) => !m.ticket)).toBe(true);
    expect(f.lounge.some((m) => !m.ticket)).toBe(true);

    // every session has a desk with its team; the desk of one that is elsewhere is an outline that says where it went
    const sv = within(panel).getByRole("list", { name: "SamVision desks" });
    expect([...sv.children].map((li) => [li.classList.contains("is-empty"), li.getAttribute("aria-hidden"), li.textContent])).toEqual([
      [true, "true", "samvisionin the lounge"], [false, null, "SIsv-056-implclaude"],
      [true, "true", "sv-071in the lounge"], [true, "true", "sv-082-planat your door"]]);
    // a team with nobody at a desk is not read out as an empty list
    const loose = panel.querySelector<HTMLElement>("ul[aria-label='No project desks']")!;
    expect(loose).toHaveTextContent("scratchin the lounge");
    expect(loose).toHaveAttribute("aria-hidden", "true");
    expect(sv).not.toHaveAttribute("aria-hidden");
    expect(within(panel).getAllByRole("list").map((l) => l.getAttribute("aria-label")).filter(Boolean)).toEqual(["SamVision desks", "GauzeMate desks"]);
  });

  it("Professional shows two letters and no face or emoji; Childish gives every session its own face", async () => {
    load();
    let panel = await show();
    expect(panel.querySelectorAll(".hq-face, .hq-fun")).toHaveLength(0);
    expect(who(panel).map((w) => w.querySelector(".hq-who-mono")!.textContent).sort()).toEqual(["GA", "GI", "GI", "OD", "SA", "SC", "SI", "SP", "SV"]);
    cleanup();

    prefs.patch({ style: "childish" });
    panel = await show();
    const faces = who(panel).map((w) => w.querySelector<SVGElement>(".hq-face")!.dataset.character);
    expect(new Set(faces).size).toBe(9);
    expect(panel.querySelectorAll(".hq-who-mono")).toHaveLength(0);
    const leads = castLeads(leadKeys(app.store.get()));
    expect(panel.querySelector<SVGElement>("[data-who='wE:p4'] .hq-face")!.dataset.character).toBe(leads.get("gauzemate")!.id);
    panel.querySelectorAll(".hq-face, .hq-fun").forEach((x) => expect(x).toHaveAttribute("aria-hidden", "true"));
  });

  it("switches to the list and back, and remembers the choice", async () => {
    load();
    const panel = await show();
    fireEvent.click(within(panel).getByRole("button", { name: "List" }));
    expect(prefs.get().sessions).toBe("list");
    expect(panel.querySelector(".hq-floor")).toBeNull();
    expect(panel.querySelectorAll(".hq-sess")).toHaveLength(9);
    expect(within(panel).getByRole("group", { name: "Filter sessions" })).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Floor" }));
    expect(panel.querySelectorAll(".hq-sess")).toHaveLength(0);
    expect(who(panel)).toHaveLength(9);
    // only exactly "list" is the list
    expect(["null", '"list"', '"grid"', "1", '"List"'].map((x) => parsePrefs(`{"sessions":${x}}`).sessions)).toEqual(["floor", "list", "floor", "floor", "floor"]);
  });

  it("seats nobody and counts nothing when the feed is not live", async () => {
    load(false);
    const panel = await show();
    expect(within(panel).getByRole("status")).toHaveTextContent("The session feed is not live, so nobody can be placed.");
    expect(panel.querySelectorAll(".hq-desk:not(.is-empty)")).toHaveLength(0);
    expect(who(zone(panel, /^Not seen/))).toHaveLength(9);
    expect(within(panel).getAllByRole("region").map((r) => r.querySelector("h4")!.textContent)).toEqual([
      "At your door not known", "At their desks not known", "In the lounge not known", "Not seen 9, status unknown"]);
    expect(zone(panel, /^At your door/)).toHaveTextContent("Not known while the feed is not live.");
    expect(panel.textContent).not.toMatch(/Nobody is|\d working|waiting for you/);
    expect(within(panel).queryByRole("link", { name: "Open Decisions" })).toBeNull();
  });

  it("says so when herdr reports no sessions", async () => {
    const st = state();
    st.agents = [];
    load(true, st);
    const panel = await show();
    expect(panel).toHaveTextContent("herdr reports no sessions.");
    expect(panel.querySelector(".hq-floor")).toBeNull();
  });
});

describe("walking", () => {
  /** jsdom lays nothing out, so the floor gets a layout here: each room at its own place, people 108px apart. */
  const ROOM: Record<string, [number, number]> = { "is-door": [700, 0], "is-desks": [0, 0], "is-lounge": [700, 200], "is-out": [0, 400], "is-unseen": [0, 500] };
  function layout() {
    const at = (el: HTMLElement): [number, number] => {
      if (!el.matches("[data-who]")) return [0, 0];
      const room = ROOM[[...el.closest(".hq-zone")!.classList].find((c) => c in ROOM)!];
      const slot = el.closest("li")!, row = [...slot.parentElement!.children].indexOf(slot);
      const team = el.closest(".hq-floor-team"), teamRow = team ? [...team.parentElement!.children].indexOf(team) : 0;
      return [room[0] + row * 108, room[1] + teamRow * 120];
    };
    vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) { return at(this)[0]; });
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (this: HTMLElement) { return at(this)[1]; });
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1000);
  }
  const set = async (id: string, change: Partial<Agent>) => {
    const st = JSON.parse(JSON.stringify(app.store.get().state)) as State;
    Object.assign(st.agents.find((a) => a.id === id)!, change);
    await act(async () => { app.store.patch({ state: st }); });
  };
  const walking = (panel: HTMLElement) => who(panel).filter((w) => w.classList.contains("is-walking")).map((w) => w.dataset.who);

  it("moves a session that changed state to its new place with one transition, and nobody else", async () => {
    layout();
    load();
    const panel = await show();
    expect(walking(panel)).toEqual([]);   // nobody walks in when the floor is first drawn

    await set("wE:pA", { status: "blocked", blockedSinceMs: Date.now() });   // sv-056-impl now needs Jay
    const el = panel.querySelector<HTMLElement>("[data-who='wE:pA']")!;
    expect(el.closest(".hq-zone")).toBe(zone(panel, /^At your door/));
    expect(walking(panel)).toEqual(["wE:pA"]);
    // let go from where it was (its desk, 108px into the desks) towards where it is (third at the door)
    expect(el.style.transition).toMatch(/^transform \d+ms /);
    expect(el.style.transform).toBe("");
    expect(Number(/(\d+)ms/.exec(el.style.transition)![1])).toBeGreaterThan(1000);

    fireEvent.transitionEnd(el);
    expect(walking(panel)).toEqual([]);
    expect(el.style.transition).toBe("");

    // a keyboard that is on a session stays on it when it changes rooms, and stays put when someone else does
    el.focus();
    await set("wE:pA", { status: "idle", blockedSinceMs: null });
    const moved = panel.querySelector<HTMLElement>("[data-who='wE:pA']")!;
    expect(moved).not.toBe(el);
    expect(moved.closest(".hq-zone")).toBe(zone(panel, /^In the lounge/));
    expect(document.activeElement).toBe(moved);
    await set("x3", { status: "idle" });
    expect(document.activeElement).toBe(moved);
    moved.blur();
    await set("wE:pA", { status: "working" });
    expect(document.activeElement).toBe(document.body);   // focus is not taken by a session nobody was on
    for (const w of who(panel)) fireEvent.transitionEnd(w);

    // someone leaving the middle of a row: the ones after it close the gap, and all of them are seen moving
    await set("x1", { status: "working" });   // sv-071 leaves the lounge for its desk; gm-012-impl and scratch move up
    expect(walking(panel).sort()).toEqual(["x1", "x3", "x5"]);
  });

  it("a second walk of the same session replaces the first: the first one's timer does not cut it short", async () => {
    layout();
    load();
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"], now: Date.now() });
    const panel = await show();
    const scratch = () => panel.querySelector<HTMLElement>("[data-who='x5']")!;
    await set("x1", { status: "working" });      // scratch moves up one place in the lounge: 450 + 108 * 1.6 = 623 ms
    const el = scratch();
    expect(el.style.transition).toBe("transform 623ms cubic-bezier(.45, .05, .25, 1)");
    vi.advanceTimersByTime(600);
    await set("wE:p2", { status: "working" });   // and again before it arrived
    expect(scratch()).toBe(el);
    vi.advanceTimersByTime(300);                 // the first walk's timer (at 773 ms) would have ended it here
    expect(el.classList.contains("is-walking")).toBe(true);
    expect(el.style.transition).toMatch(/^transform /);
    // something inside it finishing a transition is not its arrival
    fireEvent.transitionEnd(el.querySelector("b")!);
    expect(el.classList.contains("is-walking")).toBe(true);
    vi.advanceTimersByTime(600);
    expect(el.classList.contains("is-walking")).toBe(false);
    expect(el.style.transition).toBe("");
  });

  it("moves nobody when the reader asked for less motion, or when the floor was resized", async () => {
    layout();
    load();
    const panel = await show();
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("prefers-reduced-motion"), addEventListener() {}, removeEventListener() {} }));
    await set("wE:pA", { status: "idle" });
    expect(panel.querySelector("[data-who='wE:pA']")!.closest(".hq-zone")).toBe(zone(panel, /^In the lounge/));
    expect(walking(panel)).toEqual([]);

    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    vi.mocked(Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth")!.get!).mockReturnValue(600);
    await set("wE:pA", { status: "working" });
    expect(walking(panel)).toEqual([]);
    await set("wE:pA", { status: "idle" });   // the same width as last time: walking again
    expect(walking(panel)).toContain("wE:pA");
  });
});
