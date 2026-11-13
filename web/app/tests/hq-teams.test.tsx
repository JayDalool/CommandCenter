// Teams (hq/pages/Teams.tsx) on the test fixture: every session herdr reports, once, under its project; a lead only
// where the coordinator is a session; each session opens Classic's Agents screen; presence only from evidence. Both
// views: the org chart (the default on a desktop) and the list of team panels (the default on a phone).
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
/** Switch the page to its list of team panels. */
function list(page: HTMLElement) {
  fireEvent.click(within(within(page).getByRole("group", { name: "View" })).getByRole("button", { name: "List" }));
}

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
    const chart = within(page).getByRole("region", { name: "Org chart" });
    expect(within(chart).getByRole("link", { name: /^Jay Directs/ })).toHaveAttribute("href", href("needs"));
    const branches = [...chart.querySelectorAll<HTMLElement>(".hq-org-branch")];
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
    expect(chart.querySelectorAll(".hq-org-loose a.hq-sess")).toHaveLength(v.unassigned.length);
  });

  it("opens as the list on a phone-width window", async () => {
    load(true);
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("max-width: 760px"), media: q, addEventListener() {},
      removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false }));
    const page = (await show())!;
    expect(page.querySelector(".hq-org")).toBeNull();
    expect(within(page).getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
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
    expect(page.querySelectorAll("a.hq-sess").length).toBeGreaterThan(0);
    expect(within(page).queryAllByText("Working")).toHaveLength(0);
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
