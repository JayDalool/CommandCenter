// My Office (hq/pages/Office.tsx) on the test fixture: the same counts as Classic, links to the Classic screens, and
// Unknown, never Working, when the session feed is not live.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { jayQueue } from "../src/tickets/model";
import { buildOffice, evidence } from "../src/hq/data";
import { fixture, state, tasks } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;

function load(live: boolean) {
  const t = tasks();
  // Live: the clock just after the fixture's snapshot and the event stream connected. Stale: 24 days later, offline.
  const now = live ? SNAPSHOT + 10_000 : new Date("2026-10-27T15:00:00Z").getTime();
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: now, tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta,
    conn: live ? { status: "live", lastMessageAt: now, attempt: 0 } : { status: "offline", lastMessageAt: null, attempt: 1 } });
}

async function show() {
  location.hash = "#/dashboard";
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-office")!;
}

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", sessions: "floor" }); });

const kpi = (page: HTMLElement, label: string) =>
  [...page.querySelectorAll<HTMLElement>(".hq-kpi")].find((k) => k.querySelector("small")?.textContent === label)!;

describe("My Office", () => {
  it("replaces the Dashboard in HQ, with Classic's Needs-you count and links into Classic", async () => {
    load(true);
    const page = await show();
    expect(page).not.toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("My Office");
    const needs = kpi(page, "Needs you");
    expect(needs.querySelector("b")).toHaveTextContent(String(jayQueue(app.store.get().state).length));
    expect(needs).toHaveAttribute("href", "#/needs");
    // Every project links to its Classic project screen.
    const view = buildOffice(app.store.get(), evidence(app.store.get(), Date.now() / 1000));
    const cards = [...page.querySelectorAll<HTMLAnchorElement>(".hq-proj")];
    expect(cards.map((a) => a.getAttribute("href"))).toEqual(view.projects.map((p) => `#/projects/${p.key}`));
    // The attention list is the top of the Needs-you queue, each row to its task or to Needs You.
    const rows = [...page.querySelectorAll<HTMLAnchorElement>(".hq-attn a")].filter((a) => a.closest("[aria-labelledby='hq-office-attn']"));
    expect(rows.length).toBe(Math.min(4, view.attention.length));
    rows.forEach((a, i) => expect(a.getAttribute("href")).toBe(view.attention[i].ticket ? `#/tasks/${view.attention[i].ticket}` : "#/needs"));
    // No lead updates: there is no source for them yet.
    expect(page.textContent).not.toMatch(/updates from leads/i);
  });

  it("says Unknown, never Working, when the feeds are not live", async () => {
    load(false);
    const page = await show();
    expect(kpi(page, "Sessions").querySelector("b")).toHaveTextContent("Unknown");
    expect(kpi(page, "Health").querySelector("b")).toHaveTextContent("Unknown");
    expect(kpi(page, "Health")).toHaveAttribute("href", "#/server");
    fireEvent.click(within(page).getByRole("button", { name: "List" }));
    expect(page.querySelector(".hq-sess .hq-pill")?.textContent).toBe("Unknown");
    expect(within(page).queryByText("Working")).toBeNull();
    expect(page.textContent).toMatch(/Feed not live/);
    // Counts from the last snapshot say so (review of #80).
    expect(page.querySelector("#hq-office-sessions")).toHaveTextContent("last reported by herdr");
    page.querySelectorAll(".hq-proj-foot").forEach((f) => expect(f).toHaveTextContent(/last reported/));
  });

  it("filters sessions by presence", async () => {
    load(true);
    const page = await show();
    fireEvent.click(within(page).getByRole("button", { name: "List" }));
    const group = within(page).getByRole("group", { name: "Filter sessions" });
    const all = page.querySelectorAll(".hq-sess").length;
    expect(all).toBe(app.store.get().state!.agents.length);
    const working = within(group).getByRole("button", { name: /^Working/ });
    fireEvent.click(working);
    expect(working).toHaveAttribute("aria-pressed", "true");
    const n = Number(/\((\d+)\)/.exec(working.textContent!)![1]);
    expect(page.querySelectorAll(".hq-sess").length).toBe(n);
    page.querySelectorAll(".hq-sess .hq-pill").forEach((p) => expect(p.textContent).toBe("Working"));
  });
});
