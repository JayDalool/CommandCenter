// Teams (hq/pages/Teams.tsx) on the test fixture: every session herdr reports, once, under its project; a lead only
// where the coordinator is a session; each session opens Classic's Agents screen; presence only from evidence.
import { act, cleanup, render, within } from "@testing-library/react";
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

const view = () => buildTeams(app.store.get(), evidence(app.store.get(), Date.now() / 1000));

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("Teams", () => {
  it("shows every session once, each opening Classic's Agents screen, and has no buttons", async () => {
    load(true);
    const page = (await show())!;
    const ids = app.store.get().state!.agents.map((a) => a.id);
    const links = [...page.querySelectorAll<HTMLAnchorElement>("a.hq-sess")];
    expect(links.map((a) => a.getAttribute("href")).sort()).toEqual(ids.map((id) => href("agents", id)).sort());
    expect(page.querySelectorAll("button")).toHaveLength(0);
  });

  it("names a lead only where the coordinator is a session, and says why otherwise", async () => {
    load(true);
    const page = (await show())!;
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
