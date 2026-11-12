// Decisions (hq/pages/Decisions.tsx) on the test fixture: Classic's Needs You queue, in Classic's order, with the same
// read-only inbox details, and every item opening the place Jay acts today.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { jayQueue } from "../src/tickets/model";
import { jayHref } from "../src/lib/control";
import type { InboxState } from "../src/api/types";
import { state, tasks } from "./helpers";

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}

async function show() {
  location.hash = "#/needs";
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-decisions")!;
}

const queue = () => jayQueue(app.store.get().state, undefined, app.store.get().tickets);
const rows = (page: HTMLElement) => [...page.querySelectorAll<HTMLElement>(".hq-dec")];

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("Decisions", () => {
  it("shows every item in Classic's queue, each opening the place Jay acts today", async () => {
    load();
    vi.spyOn(app.api, "inbox").mockReturnValue(new Promise(() => {}));
    const page = await show();
    const q = queue();
    expect(q.length).toBeGreaterThan(0);
    expect(rows(page)).toHaveLength(q.length);
    const links = rows(page).map((r) => r.querySelector("a")!.getAttribute("href"));
    expect(links.sort()).toEqual(q.map(jayHref).sort());
    // Nothing on the page answers, approves or merges: its only buttons filter the list.
    expect(within(page).getAllByRole("button").filter((b) => !b.closest("[aria-label='Filter by kind']"))).toEqual([]);
  });

  it("filters by kind, and Show all brings every item back", async () => {
    load();
    vi.spyOn(app.api, "inbox").mockReturnValue(new Promise(() => {}));
    const page = await show();
    const all = rows(page).length;
    const kinds = within(page).getByRole("group", { name: "Filter by kind" });
    const btn = within(kinds).getAllByRole("button").find((b) => Number(b.querySelector("b")!.textContent) > 0
      && Number(b.querySelector("b")!.textContent) < all)!;
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(rows(page)).toHaveLength(Number(btn.querySelector("b")!.textContent));
    fireEvent.click(within(page).getByRole("button", { name: "Show all" }));
    expect(rows(page)).toHaveLength(all);
  });

  it("puts an overdue approval first and shows the inbox details, as Classic does", async () => {
    load();
    const q = queue();
    const last = q[q.length - 1];
    const now = Date.now() / 1000;
    const inbox: InboxState = { available: true, orphans: [], counts: { approvals: 1, precedentHits: 1 }, items: {
      [last.id]: {
        approval: { id: 7, project: last.project, gate: "plan", subjectHash: "abcdef1234567890", requestedAt: now - 7200, expiresAt: now - 60, overdue: true },
        precedents: [{ questionId: 3, question: "Keep initials?", precedents: [
          { id: 1, project: last.project, key: null, question: "Keep initials?", decision: "yes", decidedAt: now - 86400, decidedBy: "jay", reconsider: null }] }],
      } } };
    vi.spyOn(app.api, "inbox").mockResolvedValue(inbox);
    const page = await show();
    await act(async () => {});
    const first = rows(page)[0];
    expect(first).toHaveClass("is-late");
    expect(first.querySelector("a")!.getAttribute("href")).toBe(jayHref(last));
    expect(first).toHaveTextContent("Approval #7 · bound to abcdef12 · overdue");
    expect(first).toHaveTextContent("Asked before: “Keep initials?” → yes");
    const sum = within(page).getByRole("region", { name: "Summary" });
    expect(within(sum).getByText("Overdue").nextElementSibling).toHaveTextContent("1");
  });

  it("says the list is still complete when the inbox details cannot be read", async () => {
    load();
    vi.spyOn(app.api, "inbox").mockRejectedValue(new Error("down"));
    const page = await show();
    await act(async () => {});
    expect(rows(page)).toHaveLength(queue().length);
    expect(page).toHaveTextContent("Could not read the approval and engine details; the list is still complete.");
  });
});
