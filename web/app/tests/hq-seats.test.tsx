// Teams › Seats (hq/data/seats.ts, hq/pages/Seats.tsx, TicketFlow.tsx): Teams as a company: each project's seats, the tickets in
// flight with their row of stages, children under their parent, and one ticket opened in place. On the test fixture
// (a ccd from before the nine-stage flow) and on the same fixture as a ccd that runs it.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { href } from "../src/lib/router";
import { taskHref } from "../src/lib/control";
import { works } from "../src/tickets/useWork";
import type { Agent, FlowStage, State, Ticket, TicketWork } from "../src/api/types";
import { buildSeats, evidence, railOf, routeOf, stageOf, type SeatsTeam, type FlightRow } from "../src/hq/data";
import { ApiError } from "../src/api/client";
import { handoffText, stepsOf } from "../src/hq/pages/TicketFlow";
import { state, tasks, fixture } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;
const NOW = SNAPSHOT + 10_000, T = NOW / 1000;

/** The fixture with changes: `tickets` patches by key (a new key adds a ticket), `agents` adds SamVision sessions. */
function world(tickets: Record<string, Partial<Ticket>> = {}, agents: Record<string, string> = {}) {
  const st = state(), t = tasks();
  const lane = st.agents.find((a) => a.id === "wE:pA")!;
  for (const [id, name] of Object.entries(agents)) st.agents.push({ ...lane, id, pane_id: id, agent_name: name } as Agent);
  for (const [key, more] of Object.entries(tickets)) {
    const have = t.tickets.find((x) => x.key === key);
    if (have) Object.assign(have, more);
    else t.tickets.push({ ...t.tickets.find((x) => x.key === "SV-056")!, id: 900 + t.tickets.length, key, number: Number(key.split("-")[1]),
      agentRole: null, agentPaneId: null, assignee: null, parent: null, labels: [], flags: [], subtasks: { total: 0, done: 0 }, ...more });
  }
  return { state: st as State, tickets: t.tickets, projects: t.projects, meta: t.meta };
}
function build(w: ReturnType<typeof world>) {
  const src = { ...initial, state: w.state, stateAt: NOW, tickets: w.tickets, ticketsLoaded: true,
    conn: { status: "live" as const, lastMessageAt: NOW, attempt: 0 } };
  return buildSeats(src, evidence(src, T));
}
const team = (v: ReturnType<typeof build>, key = "samvision") => v.teams.find((t) => t.key === key)!;
const seatsOf = (t: SeatsTeam) => t.seats.map((s) => `${s.seat}:${s.who?.name ?? "free"}:${s.ticket?.key ?? "-"}`);
const keys = (rows: FlightRow[]): unknown[] => rows.map((r) => r.children.length ? [r.t.key, keys(r.children)] : r.t.key);
const rail = (t: Ticket, flow: boolean) => railOf(t, flow).map((s) => `${s.stage}:${s.state}`);
/** Every ticket carries a stage, as a ccd that runs the nine-stage flow sends it. */
const NINE: Record<string, Partial<Ticket>> = Object.fromEntries(tasks().tickets.map((t) => [t.key, { stage: stageOf(t), size: "standard" as const }]));

describe("buildSeats", () => {
  it("on a ccd from before the flow: five seats, seven stages, and nobody seated without a ticket", () => {
    const v = build(world());
    expect(v.flow).toBe(false);
    const sv = team(v);
    expect(seatsOf(sv)).toEqual(["lead:samvision:-", "investigator:free:-", "developer:free:-", "codeReviewer:free:-", "verifier:free:-"]);
    expect(sv.loose.map((m) => m.name)).toEqual(["sv-056-impl"]);
    expect(keys(sv.flight)).toEqual(["SV-031", "SV-042", "SV-056", "SV-011", "SV-014"]);   // closest to done first
    expect([sv.inFlight, sv.atIntake]).toEqual([5, 1]);
    const by = Object.fromEntries(sv.flight.map((r) => [r.t.key, r]));
    expect(by["SV-056"].rail.map((s) => s.stage)).toEqual(["intake", "investigate", "build", "codeReview", "merge", "release", "done"]);
    expect(by["SV-056"].rail.find((s) => s.state === "active")!.stage).toBe("codeReview");
    // a blocked ticket has no stage this ccd can name, so nothing on its row is marked as where it is
    expect([by["SV-014"].blocked, by["SV-014"].stage, by["SV-014"].rail.some((s) => s.state === "active")]).toEqual([true, null, false]);
    // a project with no coordinator session has an empty lead seat that says why
    expect([team(v, "gyst").seats[0].who, team(v, "gyst").leadWhy]).toEqual([null, "No coordinator session"]);
  });

  it("seats a session by the role its ticket records, and guesses only for the stages one session does alone", () => {
    const v = build(world({
      "SV-011": { agentPaneId: "wE:pB", agentRole: "PLANNER" },             // recorded: investigator
      "SV-056": { assignee: "agent:sv-056-impl" },                          // in review, no role recorded: no seat
      "SV-070": { status: "IN_PROGRESS", assignee: "agent:sv-070-impl" },   // in build, no role recorded: developer
      "SV-071": { status: "IN_PROGRESS", agentPaneId: "wE:pE", agentRole: "IMPLEMENTER" },
    }, { "wE:pB": "sv-011-plan", "wE:pD": "sv-070-impl", "wE:pE": "sv-071-impl" }));
    const sv = team(v);
    expect(seatsOf(sv)).toEqual(["lead:samvision:-", "investigator:sv-011-plan:SV-011", "developer:sv-070-impl:SV-070",
      "developer:sv-071-impl:SV-071", "codeReviewer:free:-", "verifier:free:-"]);
    const row = sv.flight.find((r) => r.t.key === "SV-056")!;
    expect(row.on.map((x) => [x.who.name, x.seat])).toEqual([["sv-056-impl", null]]);
    expect(sv.loose.map((m) => [m.name, m.ticket])).toEqual([["sv-056-impl", "SV-056"]]);
    // the lead's seat is the team's lead and nobody else's: another session recorded as a coordinator sits nowhere
    const two = team(build(world({ "SV-011": { agentPaneId: "wE:pB", agentRole: "COORDINATOR" } }, { "wE:pB": "sv-second-lead" })));
    expect(two.seats.filter((s) => s.seat === "lead").map((s) => s.who?.name)).toEqual(["samvision"]);
    expect(two.loose.map((m) => m.name)).toContain("sv-second-lead");
  });

  it("on a ccd that runs the flow: all eight seats, and a reviewer sits in the review its ticket is at", () => {
    const v = build(world({ ...NINE,
      "SV-011": { stage: "techReview", size: "risky", agentPaneId: "wE:pB", agentRole: "REVIEWER" },
      "SV-056": { stage: "userCheck", size: "standard", agentPaneId: "wE:pA", agentRole: "REVIEWER" },
      "SV-042": { stage: "codeReview", size: "standard", agentPaneId: "wE:pD", agentRole: "REVIEWER" },
    }, { "wE:pB": "sv-011-tech", "wE:pD": "sv-042-review" }));
    expect(v.flow).toBe(true);
    expect(seatsOf(team(v))).toEqual(["lead:samvision:-", "investigator:free:-", "techReviewer:sv-011-tech:SV-011", "developer:free:-",
      "userReviewer:sv-056-impl:SV-056", "designReviewer:free:-", "codeReviewer:sv-042-review:SV-042", "verifier:free:-"]);
    expect(team(v).loose).toEqual([]);
    expect(team(v).flight.find((r) => r.t.key === "SV-011")!.rail).toHaveLength(9);
    // a ticket nobody has sized keeps the seven stages it had before the flow, and says so
    const plain = build(world({ ...NINE, "SV-031": { stage: "release", size: null } }));
    const row = team(plain).flight.find((r) => r.t.key === "SV-031")!;
    expect(row.rail).toHaveLength(9);   // drawn on the same nine places as every other ticket, two of them skipped
    expect([row.notSized, row.rail.filter((s) => s.state !== "skipped").map((s) => s.stage).join()])
      .toEqual([true, "intake,investigate,build,codeReview,merge,release,done"]);
    expect(team(plain).flight.find((r) => r.t.key === "SV-042")!.notSized).toBe(false);
    expect(team(build(world())).flight.every((r) => !r.notSized)).toBe(true);   // before the flow nothing is sized, and nothing says so
  });

  it("a small ticket skips the investigation and the technical review, and the user check unless a screen changes", () => {
    const t = tasks().tickets.find((x) => x.key === "SV-056")!;
    const small = { ...t, size: "small" as const, labels: [], flags: [], type: "BUG" };
    const at = (stage: FlowStage, more: Partial<Ticket> = {}) => rail({ ...small, stage, ...more }, true);
    expect(at("build")).toEqual(["intake:done", "investigate:skipped", "techReview:skipped", "build:active", "userCheck:skipped",
      "codeReview:todo", "merge:todo", "release:todo", "done:todo"]);
    expect(at("build", { labels: ["ui"] })[4]).toBe("userCheck:todo");
    expect(at("codeReview", { labels: ["ui"] })[4]).toBe("userCheck:done");
    // where the ticket is always shows, even on a stage its size would skip
    expect(at("techReview")[2]).toBe("techReview:active");
    expect(rail({ ...small, stage: "build", size: "standard" }, true).filter((s) => s.endsWith(":skipped"))).toEqual([]);
    // the route ccd sends wins over the size: a ticket nobody sized that the policy makes risky still runs seven stages
    const legacy: FlowStage[] = ["intake", "investigate", "build", "codeReview", "merge", "release", "done"];
    const risky = { ...t, size: "risky" as const, stage: "build" as const, route: legacy };
    expect(routeOf(risky, true)).toEqual(legacy);
    expect(rail(risky, true).filter((s) => s.endsWith(":skipped"))).toEqual(["techReview:skipped", "userCheck:skipped"]);
    expect(routeOf({ ...risky, route: [] }, true)).toHaveLength(9);          // an empty or unknown route is not one
    expect(routeOf({ ...risky, route: ["later" as FlowStage] }, true)).toHaveLength(9);
    // the stage ccd sends wins over the status; an unknown one falls back to the status
    expect(stageOf({ ...t, status: "RESEARCHING", stage: "techReview" })).toBe("techReview");
    expect(stageOf({ ...t, status: "RESEARCHING", stage: "later" as FlowStage })).toBe("investigate");
  });

  it("nests every open child under its parent, and a child in flight brings its parent along", () => {
    const v = build(world({
      "SV-056": { subtasks: { total: 3, done: 1 } },
      "SV-057": { parent: "SV-056", status: "IN_PROGRESS" },
      "SV-058": { parent: "SV-056", status: "INBOX" },          // at intake, still listed under its parent
      "SV-059": { parent: "SV-056", status: "DONE" },           // done: counted, not listed
      "SV-010": { subtasks: { total: 1, done: 0 } },            // a parent at intake…
      "SV-012": { parent: "SV-010", status: "IN_REVIEW" },      // …with a child in review
    }));
    const sv = team(v);
    expect(keys(sv.flight)).toEqual(["SV-031", "SV-042", ["SV-056", ["SV-057", "SV-058"]], "SV-011", ["SV-010", ["SV-012"]], "SV-014"]);
    expect([sv.inFlight, sv.atIntake]).toEqual([9, 0]);   // the counts are of what the list holds: SV-058 and SV-010 are in it
  });

  it("puts what needs Jay first, and two sessions in the same seat side by side", () => {
    const v = build(world({
      "SV-011": { gate: "plan" },
      "SV-070": { status: "IN_PROGRESS", agentPaneId: "wE:pD", agentRole: "IMPLEMENTER" },
      "SV-071": { status: "IN_PROGRESS", agentPaneId: "wE:pE", agentRole: "IMPLEMENTER" },
    }, { "wE:pD": "sv-070-impl", "wE:pE": "sv-071-impl" }));
    const sv = team(v);
    expect(sv.flight[0].t.key).toBe("SV-011");
    expect(sv.flight[0].needsJay).toBe(true);
    expect(sv.seats.filter((s) => s.seat === "developer").map((s) => s.who?.name)).toEqual(["sv-070-impl", "sv-071-impl"]);
  });
});

describe("a ticket's stages and history", () => {
  const base = { stages: [], roles: {}, merge: null } as unknown as TicketWork;
  const r = (t: Ticket) => railOf(t, false);
  const sv056 = () => tasks().tickets.find((x) => x.key === "SV-056")!;

  it("before the flow: five stages in the new words, who and when from the roles, and the status when nothing is recorded", () => {
    expect(stepsOf(base, r(sv056())).map((s) => `${s.label}:${s.state}`)).toEqual(["Investigate:done", "Build:done", "Code review:active",
      "Merge:todo", "Release:todo"]);
    const w = { ...base, stages: [{ stage: "PLAN", state: "done" }, { stage: "BUILD", state: "blocked" }],
      roles: { planner: { model: null, session: "sv-056-plan", at: 100 }, implementer: { model: null, session: null, at: 200 } },
      merge: { pr: "#1", sha: null, at: 300 } } as unknown as TicketWork;
    expect(stepsOf(w, r(sv056())).slice(0, 4)).toEqual([
      { label: "Investigate", state: "done", who: "Investigator · sv-056-plan", at: 100 },
      { label: "Build", state: "blocked", who: "Developer", at: 200 },
      { label: "Code review", state: "active", who: null, at: null },
      { label: "Merge", state: "todo", who: null, at: 300 }]);
  });

  it("with the flow: the stages ccd sends, the merge as yours, and each handoff in words", () => {
    const w = { ...base, flow: { stages: [
      { stage: "build", state: "done", seat: "developer", by: "agent:a", session: "sv-056-impl", at: 10 },
      { stage: "merge", state: "active", seat: "jay", by: null, session: null, at: null },
      { stage: "done", state: "todo", seat: null, by: null, session: null, at: null }] } } as unknown as TicketWork;
    expect(stepsOf(w, [])).toEqual([{ label: "Build", state: "done", who: "Developer · sv-056-impl", at: 10 },
      { label: "Merge", state: "active", who: "You", at: null }, { label: "Done", state: "todo", who: null, at: null }]);
    const h = { at: 1, by: "agent:a", note: null };
    expect(handoffText({ ...h, stage: "investigate", kind: "advanced", from: "investigator", to: "techReviewer" })).toBe("Investigator to Technical reviewer");
    expect(handoffText({ ...h, stage: "techReview", kind: "sentBack", from: "techReviewer", to: "investigator", note: "Name the files" }))
      .toBe("Technical reviewer sent it back to Investigator · Name the files");
    expect(handoffText({ ...h, stage: "codeReview", kind: "advanced", from: "codeReviewer", to: "jay" })).toBe("Code reviewer to You");
    expect(handoffText({ ...h, stage: "build", kind: "blocked", from: "developer", to: null })).toBe("Blocked at Build");
    expect(handoffText({ ...h, stage: "build", kind: "resumed", from: null, to: "developer" })).toBe("Resumed at Build");
    expect(handoffText({ ...h, stage: "intake", kind: "advanced", from: null, to: null })).toBe("Start to Intake");
    // a stage or seat from a newer ccd shows as ccd names it
    const newer = { ...base, flow: { stages: [{ stage: "audit", state: "active", seat: "auditor", by: null, session: null, at: null }] } } as unknown as TicketWork;
    expect(stepsOf(newer, [])).toEqual([{ label: "audit", state: "active", who: "auditor", at: null }]);
  });
});

function load(w = world()) {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  app.store.set({ ...initial, auth: "ok", state: w.state, stateAt: NOW, tickets: w.tickets, ticketsLoaded: true,
    taskProjects: w.projects, meta: w.meta, conn: { status: "live", lastMessageAt: NOW, attempt: 0 } });
}
async function show() {
  location.hash = "#/agents";
  await loadHqFrame();
  render(<App />);
  for (let i = 0; i < 4; i++) await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-teams")!;
}

describe("Teams › Seats", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    vi.spyOn(app, "boot").mockResolvedValue(undefined);
    works.set({});
    prefs.patch({ ui: "hq", style: "professional" });
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional" }); });

  it("opens on the seats: one panel per project, a free seat says Free, and it says the nine stages are not here yet", async () => {
    load();
    const page = await show();
    expect(within(page).getByRole("button", { name: "Seats" })).toHaveAttribute("aria-pressed", "true");
    expect(within(page).getByText(/does not run the nine-stage flow yet/)).toBeInTheDocument();
    const sv = within(page).getByRole("region", { name: /^SamVision/ });
    expect(sv).toHaveTextContent("5 tickets in flight · 1 more at intake");
    const seats = within(within(sv).getByRole("list", { name: "SamVision seats" })).getAllByRole("listitem");
    expect(seats.map((s) => s.querySelector("b")!.textContent)).toEqual(["Lead", "Investigator", "Developer", "Code reviewer", "Verifier"]);
    expect(within(seats[0]).getByRole("link", { name: "samvision" })).toHaveAttribute("href", href("agents", "wE:p2"));
    expect(seats.slice(1).every((s) => s.classList.contains("is-free") && /Free$/.test(s.textContent!))).toBe(true);
    // Professional: a monogram per seat, no face, no emoji
    expect(seats.map((s) => s.querySelector(".hq-seat-mono")!.textContent)).toEqual(["LD", "IN", "DV", "CR", "VF"]);
    expect(page.querySelectorAll(".hq-face, .hq-fun")).toHaveLength(0);
    // a project with no lead session says why in the lead's seat
    expect(within(page).getByRole("list", { name: "GYST seats" }).firstElementChild).toHaveTextContent("LeadNo coordinator session");
    expect(within(sv).getByRole("list", { name: "SamVision sessions not in a seat" })).toHaveTextContent("sv-056-impl");
  });

  it("shows who sits where, each ticket's row of stages, and children under their parent", async () => {
    load(world({ ...NINE,
      "SV-011": { stage: "investigate", size: "standard", agentPaneId: "wE:pB", agentRole: "PLANNER" },
      "SV-056": { stage: "build", status: "IN_PROGRESS", size: "standard", agentPaneId: "wE:pA", agentRole: "IMPLEMENTER", subtasks: { total: 2, done: 0 } },
      "SV-057": { parent: "SV-056", stage: "codeReview", status: "IN_REVIEW", size: "small" },
      "SV-058": { parent: "SV-056", stage: "intake", status: "INBOX", size: "small" },
      "SV-042": { stage: "merge", size: "risky", visibleStage: "Needs Jay" },
      "SV-060": { stage: "techReview", status: "RESEARCHING", size: "risky", stale: true },
      "SV-031": { stage: "release", size: null },
    }, { "wE:pB": "sv-011-investigate" }));
    const page = await show();
    expect(within(page).queryByText(/does not run the nine-stage flow yet/)).toBeNull();
    const sv = within(page).getByRole("region", { name: /^SamVision/ });
    const seats = within(within(sv).getByRole("list", { name: "SamVision seats" })).getAllByRole("listitem");
    expect(seats.map((s) => s.querySelector("b")!.textContent)).toEqual(["Lead", "Investigator", "Technical reviewer", "Developer",
      "User reviewer", "Design reviewer", "Code reviewer", "Verifier"]);
    expect(seats[1]).toHaveTextContent("InvestigatorWorkingsv-011-investigateOn SV-011 · Investigate");
    expect(within(seats[1]).getByRole("link", { name: "SV-011" })).toHaveAttribute("href", href("tasks", "SV-011"));
    expect(seats[3]).toHaveTextContent("DeveloperWorkingsv-056-implOn SV-056 · Build");

    const flight = within(sv).getByRole("list", { name: "SamVision tickets in flight" });
    const rows = [...flight.children] as HTMLElement[];
    expect(rows[0]).toHaveTextContent("SV-042");                       // what needs Jay comes first
    expect(within(rows[0]).getByRole("link", { name: "Needs you" })).toHaveAttribute("href", href("needs"));
    expect(within(rows[0]).getByRole("img", { name: "Stage 7 of 9" })).toBeInTheDocument();
    const parent = rows.find((r) => r.textContent!.includes("SV-056"))!;
    expect(parent).toHaveTextContent("Developer · sv-056-impl0 of 2 children done");
    const kids = within(parent).getByRole("list", { name: "Children of SV-056" });
    expect([...kids.children].map((k) => k.querySelector("code")!.textContent)).toEqual(["SV-057", "SV-058"]);
    // a small ticket that changes no screen skips three stages, drawn as skipped and not counted; its size and a stale
    // ticket are in words
    expect(within(kids).getByRole("img", { name: "Stage 3 of 6" }).querySelectorAll("i.is-skipped")).toHaveLength(3);
    expect(kids.children[0]).toHaveTextContent("Small");
    const stale = rows.find((r) => r.textContent!.includes("SV-060"))!;
    expect(stale).toHaveTextContent("StaleRisky");
    const plain = rows.find((r) => r.textContent!.includes("SV-031"))!;
    expect(plain).toHaveTextContent("Not sized");
    expect(within(plain).getByRole("img", { name: "Stage 6 of 7" }).children).toHaveLength(9);
    expect(within(stale).getByText("Nobody on it")).toBeInTheDocument();
  });

  it("opens a ticket in place: the stages with who and when, the criteria, the history and the way to its session", async () => {
    load(world({ ...NINE, "SV-056": { stage: "build", status: "IN_PROGRESS", size: "standard", agentPaneId: "wE:pA", agentRole: "IMPLEMENTER" } }));
    const step = (stage: FlowStage, st: string, seat: string | null, session: string | null, at: number | null) => ({ stage, state: st, seat, by: null, session, at });
    const work = { key: "SV-056", stages: [], roles: {}, merge: null, criteria: [
      { id: "c1", text: "Markers closer than 40 px join one cluster", state: "pass", by: null, at: null, head: null },
      { id: "c2", text: "Zooming in splits a cluster", state: "open", by: null, at: null, head: null }],
      flow: { size: "standard", rounds: 1, idleSince: T, stale: false, waitingOn: null, holder: null, next: null, stages: [
        step("intake", "done", "lead", "samvision", T - 7300), step("investigate", "done", "investigator", "sv-056-plan", T - 3700),
        step("build", "active", "developer", "sv-056-impl", T - 650), step("merge", "todo", "jay", null, null)] },
      handoffs: [{ at: T - 3600, stage: "investigate", kind: "advanced", from: "investigator", to: "developer", by: "agent:x", note: "Plan approved" }],
    } as unknown as TicketWork;
    let give!: (w: TicketWork) => void;
    const asked = vi.spyOn(app.api, "taskWork").mockReturnValue(new Promise((r) => { give = r; }));
    const page = await show();
    const open = within(page).getByRole("button", { name: /^SV-056/ });
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(asked).not.toHaveBeenCalled();                     // nothing is fetched until a ticket is opened
    fireEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(asked).toHaveBeenCalledWith("SV-056");
    const panel = document.getElementById(open.getAttribute("aria-controls")!)!;
    expect(panel).toHaveTextContent("Loading the stages…");
    expect(within(panel).getByRole("list", { name: "On SV-056 now" })).toHaveTextContent("Developer sv-056-implWorking");
    await act(async () => { give(work); });
    const steps = within(within(panel).getByRole("list", { name: "Stages of SV-056" })).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual(["IntakeDone · Lead · samvision · 2h", "InvestigateDone · Investigator · sv-056-plan · 1h",
      "BuildNow · Developer · sv-056-impl · 10m", "MergeNot started · You"]);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(panel).toHaveTextContent("Markers closer than 40 px join one clusterPassed");
    expect(panel).toHaveTextContent("Zooming in splits a clusterNot checked");
    expect(panel).toHaveTextContent("Investigator to Developer · Plan approved");
    expect(within(panel).getByRole("link", { name: "Watch the live session" })).toHaveAttribute("href", taskHref("SV-056"));
    expect(within(panel).getByRole("link", { name: "Open ticket" })).toHaveAttribute("href", href("tasks", "SV-056"));
    // the page only looks: its buttons are the view switch and the tickets' open-and-close
    expect([...page.querySelectorAll("button")].every((b) => b.closest(".hq-seg") || b.classList.contains("hq-fl-btn"))).toBe(true);
    fireEvent.click(open);
    expect(document.getElementById(panel.id)).toBeNull();
  });

  it("says so when a ticket has no work recorded, and who it waits for when nobody is on it", async () => {
    load(world({ "SV-042": { gate: "merge" } }));
    works.set({ "SV-031": "missing", "SV-042": { stages: [], roles: {}, merge: null } as unknown as TicketWork });
    vi.spyOn(app.api, "taskWork").mockReturnValue(new Promise(() => {}));
    const page = await show();
    fireEvent.click(within(page).getByRole("button", { name: /^SV-031/ }));
    expect(page.querySelector(".hq-tf")).toHaveTextContent("No work is recorded for this ticket yet");
    fireEvent.click(within(page).getByRole("button", { name: /^SV-031/ }));
    fireEvent.click(within(page).getByRole("button", { name: /^SV-042/ }));
    const panel = page.querySelector<HTMLElement>(".hq-tf")!;
    expect(panel).toHaveTextContent("Nobody is on it: it is waiting for you.");
    expect(within(panel).getByRole("link", { name: "Open Decisions" })).toHaveAttribute("href", href("needs"));
  });

  it("says so when the stages cannot be loaded, and tries again when asked", async () => {
    load();
    const asked = vi.spyOn(app.api, "taskWork").mockRejectedValue(new ApiError(500, "boom"));
    const page = await show();
    fireEvent.click(within(page).getByRole("button", { name: /^SV-056/ }));
    await act(async () => {});
    const panel = page.querySelector<HTMLElement>(".hq-tf")!;
    expect(within(panel).getByRole("alert")).toHaveTextContent("Could not load the stages.");
    expect(within(panel).getByRole("link", { name: "Open ticket" })).toBeInTheDocument();
    asked.mockResolvedValue({ stages: [], roles: {}, merge: null } as unknown as TicketWork);
    fireEvent.click(within(panel).getByRole("button", { name: "Try again" }));
    await act(async () => {});
    expect(asked).toHaveBeenCalledTimes(2);
    expect(within(panel).queryByRole("alert")).toBeNull();
    expect(within(panel).getByRole("list", { name: "Stages of SV-056" })).toBeInTheDocument();
  });

  it("says nothing about the flow when no ticket is open to tell by", async () => {
    const w = world();
    w.tickets.length = 0;
    load(w);
    const page = await show();
    expect(page.querySelector(".hq-seats")).not.toBeNull();
    expect(within(page).queryByText(/does not run the nine-stage flow yet/)).toBeNull();
  });

  it("Childish gives each seat a face that stays the seat's, and the lead's seat the lead's own", async () => {
    load();
    prefs.patch({ style: "childish" });
    const page = await show();
    const seats = [...page.querySelectorAll<HTMLElement>(".hq-seat")];
    expect(seats.length).toBeGreaterThan(0);
    expect(seats.every((s) => s.querySelectorAll(".hq-face").length === 1 && !s.querySelector(".hq-seat-mono"))).toBe(true);
    const title = (s: Element) => s.querySelector(".hq-face title")?.textContent ?? s.querySelector(".hq-face")?.getAttribute("aria-label") ?? "";
    const sv = [...within(page).getByRole("list", { name: "SamVision seats" }).children];
    expect(title(sv[0])).toMatch(/the face of the samvision lead$/);
    expect(title(sv[1])).toMatch(/the face of the investigator seat$/);
  });
});
