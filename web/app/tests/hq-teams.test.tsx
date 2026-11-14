// Teams (hq/pages/Teams.tsx) on the test fixture: every session herdr reports, once, under its project; a lead only
// where the coordinator is a session; each session opens Classic's Agents screen; presence only from evidence. The
// two views of sessions as cards: the org chart and the list of team panels. Seats, the view the page opens on, is
// in hq-seats.test.tsx.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { href } from "../src/lib/router";
import { buildTeams, evidence } from "../src/hq/data";
import { fixture, state, tasks } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;

function load(live: boolean) {
  const t = tasks();
  const now = live ? SNAPSHOT + 10_000 : new Date("2026-10-27T15:00:00Z").getTime();
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: now, tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta,
    conn: live ? { status: "live", lastMessageAt: now, attempt: 0 } : { status: "offline", lastMessageAt: null, attempt: 1 } });
}

async function show(hash = "#/agents") {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-teams");
}
const pick = (page: HTMLElement, name: string) =>
  fireEvent.click(within(within(page).getByRole("group", { name: "View" })).getByRole("button", { name }));
/** Switch the page to its list of team panels. */
const list = (page: HTMLElement) => pick(page, "List");
const chart = (page: HTMLElement) => pick(page, "Org chart");

const view = () => buildTeams(app.store.get(), evidence(app.store.get(), Date.now() / 1000));

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("Teams", () => {
  it("shows every session once in either view, each opening Classic's Agents screen, and has no actions", async () => {
    load(true);
    const page = (await show())!;
    const ids = app.store.get().state!.agents.map((a) => a.id);
    const sessions = () => [...page.querySelectorAll<HTMLAnchorElement>("a.hq-sess")].map((a) => a.getAttribute("href")).sort();
    const actions = () => [...page.querySelectorAll("button")].filter((b) => !b.closest(".hq-seg"));
    chart(page);
    expect(page.querySelector(".hq-org")).not.toBeNull();
    expect(sessions()).toEqual(ids.map((id) => href("agents", id)).sort());
    expect(actions()).toHaveLength(0);
    list(page);
    expect(page.querySelector(".hq-org")).toBeNull();
    expect(sessions()).toEqual(ids.map((id) => href("agents", id)).sort());
    expect(actions()).toHaveLength(0);
  });

  it("draws Jay, then each project's lead, then the sessions working with it", async () => {
    load(true);
    const page = (await show())!;
    const v = view();
    chart(page);
    const org = within(page).getByRole("region", { name: "Org chart" });
    expect(within(org).getByRole("link", { name: /^Jay Directs/ })).toHaveAttribute("href", href("needs"));
    const branches = [...org.querySelectorAll<HTMLElement>(".hq-org-branch")];
    expect(branches.map((b) => b.querySelector(".hq-org-proj b")!.textContent)).toEqual(v.teams.map((t) => t.name));
    v.teams.forEach((t, i) => {
      const b = branches[i];
      const lead = b.querySelector(".hq-org-proj + *")!;
      if (t.lead) { expect(lead).toHaveClass("is-lead"); expect(lead).toHaveAttribute("href", href("agents", t.lead.id)); }
      else expect(lead.textContent).toBe(`No lead${t.leadWhy}`);
      const reports = [...b.querySelectorAll<HTMLAnchorElement>(".hq-org-reports a.hq-sess")].map((a) => a.getAttribute("href"));
      expect(reports).toEqual(t.members.map((m) => href("agents", m.id)));
      const defined = b.querySelector(".hq-org-defined");
      if (t.defined.length) { for (const d of t.defined) expect(defined).toHaveTextContent(d.name); }
      else expect(defined).toBeNull();
    });
    expect(org.querySelectorAll(".hq-org-loose a.hq-sess")).toHaveLength(v.unassigned.length);
  });

  it("opens on Seats at any width, with the chart and the list one press away", async () => {
    load(true);
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("max-width: 760px"), media: q, addEventListener() {},
      removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false }));
    const page = (await show())!;
    const pressed = () => within(within(page).getByRole("group", { name: "View" })).getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);
    expect(pressed()).toEqual(["Seats"]);
    expect(page.querySelector(".hq-org, a.hq-sess")).toBeNull();
    chart(page);
    expect(pressed()).toEqual(["Org chart"]);
    list(page);
    expect(pressed()).toEqual(["List"]);
    expect(page.querySelector(".hq-seats")).toBeNull();
  });

  it("names a lead only where the coordinator is a session, and says why otherwise", async () => {
    load(true);
    const page = (await show())!;
    list(page);
    const v = view();
    expect(v.teams.some((t) => t.lead) && v.teams.some((t) => !t.lead)).toBe(true);   // the fixture has both
    for (const t of v.teams) {
      const panel = within(page).getByRole("region", { name: new RegExp(`^${t.name}`) });
      if (t.lead) expect(within(panel).getByRole("link", { name: new RegExp(`^${t.lead.name}`) }).className).toContain("is-lead");
      else expect(panel.querySelector(".hq-sess.is-empty")!.textContent).toBe(`No lead${t.leadWhy}`);
      expect(within(panel).getByRole("link", { name: "Tasks" })).toHaveAttribute("href", href("tasks", null, { project: t.key }));
    }
  });

  it("lists the subagents a lead can call, with no status", async () => {
    load(true);
    const page = (await show())!;
    list(page);
    const t = view().teams.find((x) => x.defined.length)!;
    const panel = within(page).getByRole("region", { name: new RegExp(`^${t.name}`) });
    for (const d of t.defined) expect(panel.querySelector(".hq-note")!.textContent).toContain(d.name);
  });

  it("shows no session as Working when the feed is not live", async () => {
    load(false);
    const page = (await show())!;
    for (const [view, sessions] of [["Seats", ".hq-seating a[href^='#/agents/']"], ["Org chart", "a.hq-sess"], ["List", "a.hq-sess"]]) {
      pick(page, view);
      expect(page.querySelectorAll(sessions).length, view).toBeGreaterThan(0);
      expect(within(page).queryAllByText("Working"), view).toHaveLength(0);
    }
    expect(within(page).getByText(/Feed not live/)).toBeInTheDocument();
    // The Sessions figure reads Unknown, as on My Office, with the last count beside it.
    const kpi = within(page).getByText("Sessions").closest(".hq-kpi")!;
    expect(kpi).toHaveTextContent(`Unknown${app.store.get().state!.agents.length} last reported by herdr`);
  });

  it("keeps Classic's Agents screen for one session", async () => {
    load(true);
    const id = app.store.get().state!.agents[0].id;
    expect(await show(href("agents", id))).toBeNull();
    expect(document.querySelector("#main .hq-page")).toBeNull();
  });
});
