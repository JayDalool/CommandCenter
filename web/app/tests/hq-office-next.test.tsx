// My Office's Briefing and Where we are panels (hq/pages/Briefing.tsx, Milestones.tsx) against ccd's shapes
// (GET /api/briefing, /api/milestones). The panels show what ccd answered and nothing else: no count, state or spend
// is made up while loading, after a failure, or on a server that has no such route yet.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { ApiError } from "../src/api/client";
import { dueLabel, isoDay, trackSummary } from "../src/hq/data";
import type { Briefing, BriefingProject, Milestone, MilestonesView } from "../src/api/types";
import { ev, state, tasks } from "./helpers";

const NOW = new Date("2026-11-13T09:30:00");
const at = (h: number, m = 0, day = 13) => new Date(2026, 10, day, h, m).getTime() / 1000;
const ms = (id: string, title: string, o: Partial<Milestone> = {}): Milestone =>
  ({ id, title, state: "todo", due: null, note: null, doneAt: null, by: "jay", ...o });
const proj = (key: string, name: string, o: Partial<BriefingProject> = {}): BriefingProject =>
  ({ key, name, merged: 0, done: 0, failedChecks: 0, opened: 0, questionsAsked: 0, questionsAnswered: 0, deploys: 0, needsYou: 0,
    mainChecks: "unknown", spendUsd: null, highlights: [], ...o });

const TICKET = tasks().tickets[0].key;
const BRIEF: Briefing = {
  since: at(21, 30, 12), until: at(9, 30),
  totals: { merged: 2, done: 1, failedChecks: 1, opened: 3, questionsAsked: 2, questionsAnswered: 0, deploys: 0, needsYou: 5 },
  projects: [
    proj("samvision", "SamVision", { merged: 2, done: 1, opened: 2, questionsAsked: 2, needsYou: 3, mainChecks: "passing", spendUsd: 4.2,
      highlights: [
        { at: at(5, 12), kind: "pipeline.merged", text: `${TICKET} merged`, ref: TICKET },
        { at: at(3, 40), kind: "pr.opened", text: "PR #92 opened", ref: "#92" },
        { at: at(23, 5, 12), kind: "pipeline.question", text: "asked 2 questions", ref: "SV-999" },
        { at: at(22, 1, 12), kind: "pr.opened", text: "PR #91 opened", ref: "#91" },
        { at: at(21, 45, 12), kind: "milestone.done", text: "samvision: technical milestone done", ref: null },
      ] }),
    proj("gyst", "GYST", { opened: 1, failedChecks: 1, mainChecks: "failing", spendUsd: 0 }),
    proj("mfe", "MFE"),
    proj("gauzemate", "GauzeMate", { needsYou: 2, mainChecks: "passing", highlights: [{ at: at(4, 0), kind: "pipeline.merged", text: "GM-9 · merged", ref: "GM-9" }] }),
  ],
  quiet: false,
};
const QUIET: Briefing = { since: at(21, 30, 12), until: at(9, 30), quiet: true,
  totals: { merged: 0, done: 0, failedChecks: 0, opened: 0, questionsAsked: 0, questionsAnswered: 0, deploys: 0, needsYou: 4 },
  projects: [proj("samvision", "SamVision", { needsYou: 4 }), proj("gyst", "GYST")] };

const stones = (): MilestonesView => ({ projects: {
  samvision: { revision: 7,
    technical: [ms("m_a", "Set up the back end", { state: "done", doneAt: at(8, 0) }), ms("m_b", "Set up the front end", { state: "doing", due: "2026-11-20" }),
      ms("m_c", "Ship the mobile layout", { by: "agent:lead-samvision" })],
    business: [ms("m_d", "Contact the lawyer", { due: "2026-11-10", note: "Ask about the licence wording" }), ms("m_e", "Send the demo email")] },
  gyst: { revision: 0, technical: [], business: [] },
  mfe: { revision: 2, technical: [ms("m_f", "Cut the release", { state: "done", doneAt: at(7, 0) })], business: [] },
  gauzemate: { revision: 0, technical: [], business: [] },
  commandcenter: { revision: 0, technical: [], business: [] },
} });

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: NOW.getTime(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}
const settle = async () => { for (let i = 0; i < 4; i++) await act(async () => {}); };
async function show() {
  location.hash = "#/dashboard";
  await loadHqFrame();
  render(<App />);
  await settle();
  return document.querySelector<HTMLElement>("#main > .hq-office")!;
}
const brief = (page: HTMLElement) => within(page).getByRole("region", { name: /^Briefing/ });
const where = (page: HTMLElement) => within(page).getByRole("region", { name: /^Where we are/ });
const row = (page: HTMLElement, name: string) =>
  [...where(page).querySelectorAll<HTMLElement>(".hq-ms-proj")].find((li) => li.querySelector(".hq-ms-name")?.textContent === name)!;

let view: MilestonesView;
beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  view = stones();
  vi.spyOn(app.api, "briefing").mockResolvedValue(BRIEF);
  vi.spyOn(app.api, "milestones").mockImplementation(async () => JSON.parse(JSON.stringify(view)));
  prefs.patch({ ui: "hq" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("where a track stands", () => {
  it("counts what is done and names the one in hand", () => {
    const list = stones().projects.samvision;
    expect(trackSummary(list.technical, "2026-11-13")).toMatchObject({ total: 3, done: 1, label: "Now", overdue: false, current: { id: "m_b" } });
    expect(trackSummary(list.business, "2026-11-13")).toMatchObject({ total: 2, done: 0, label: "Next", overdue: true, current: { id: "m_d" } });
    expect(trackSummary(list.business, "2026-11-10").overdue).toBe(false);
    expect(trackSummary([], "2026-11-13")).toEqual({ total: 0, done: 0, current: null, label: null, overdue: false });
    expect(trackSummary([ms("x", "A", { state: "done" })], "2026-11-13")).toMatchObject({ total: 1, done: 1, current: null, label: null });
  });

  it("reads a due date as a local day", () => {
    expect(isoDay(new Date(2026, 10, 3, 23, 59))).toBe("2026-11-03");
    expect(dueLabel("2026-11-20")).toBe(new Date(2026, 10, 20).toLocaleDateString(undefined, { month: "short", day: "numeric" }));
  });
});

describe("My Office › Briefing", () => {
  it("shows ccd's totals and, per project, what was counted, main's checks and what waits on Jay", async () => {
    load();
    const b = brief(await show());
    expect(b.querySelector("h3")).toHaveTextContent("since Thu 21:30");
    const totals = within(b).getByRole("list", { name: "Totals for the last 12 hours" });
    expect([...totals.querySelectorAll("li")].map((li) => li.textContent)).toEqual(
      ["2Merged", "1Done", "3PRs opened", "1Checks failed", "0Deploys", "2Questions asked", "0Answered"]);
    expect(totals.querySelector("li:nth-child(4) b")).toHaveClass("t-bad");

    const rows = [...b.querySelectorAll<HTMLElement>(".hq-brief-proj")];
    expect(rows.map((r) => r.querySelector(".hq-brief-name")!.textContent)).toEqual(["SamVision", "GYST", "GauzeMate"]);
    expect(rows[0]).toHaveTextContent("Main passing");
    expect(rows[0].querySelector(".hq-brief-counts")).toHaveTextContent("2 merged · 1 done · 2 PRs opened · 2 questions asked");
    expect(within(rows[0]).getByRole("link", { name: "3 waiting on you" })).toHaveAttribute("href", "#/needs");
    expect(rows[0]).toHaveTextContent("$4.20 spent");
    expect(rows[1]).toHaveTextContent("Main failing");
    expect(rows[1].querySelector(".hq-brief-counts")).toHaveTextContent("1 PR opened · 1 check failed");
    // a measured zero and "no data" both say nothing about spend
    expect(rows[1]).not.toHaveTextContent("spent");
    expect(rows[2].querySelector(".hq-brief-counts")).toHaveTextContent("Nothing counted");
    expect(rows[2]).not.toHaveTextContent("spent");
    expect(b).toHaveTextContent("No activity: MFE");
  });

  it("lists the newest three events, opens the task when there is one, and shows the rest on request", async () => {
    load();
    const b = brief(await show());
    const sv = b.querySelector<HTMLElement>(".hq-brief-proj")!;
    const items = () => [...sv.querySelectorAll(".hq-brief-hl li")];
    expect(items().map((li) => li.textContent)).toEqual([`05:12${TICKET} merged`, "03:40PR #92 opened", "Thu 23:05SV-999 asked 2 questions"]);
    expect(within(items()[0] as HTMLElement).getByRole("link")).toHaveAttribute("href", `#/tasks/${TICKET}`);
    // a ticket this browser does not know, and a PR, are not links
    expect(items()[1].querySelector("a")).toBeNull();
    expect(items()[2].querySelector("a")).toBeNull();
    const more = within(sv).getByRole("button", { name: "Show 2 more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    expect(items()).toHaveLength(5);
    expect(within(sv).getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
    // a client project's line is ccd's own short form, shown as it came
    expect(b.querySelectorAll(".hq-brief-proj")[2].querySelector(".hq-brief-hl")).toHaveTextContent("04:00GM-9 · merged");
  });

  it("asks ccd again for a longer window", async () => {
    load();
    const b = brief(await show());
    expect(app.api.briefing).toHaveBeenLastCalledWith(NOW.getTime() / 1000 - 12 * 3600);
    // until ccd answers for the new window, the figures on screen are still named for the window they belong to
    let answer!: (b: Briefing) => void;
    vi.mocked(app.api.briefing).mockImplementationOnce(() => new Promise((r) => { answer = r; }));
    fireEvent.click(within(within(b).getByRole("group", { name: "Briefing window" })).getByRole("button", { name: "3 days" }));
    await settle();
    expect(app.api.briefing).toHaveBeenLastCalledWith(NOW.getTime() / 1000 - 72 * 3600);
    expect(within(b).getByRole("list", { name: "Totals for the last 12 hours" })).toBeInTheDocument();
    expect(within(b).getByRole("status")).toHaveTextContent("Loading the last 3 days…");
    expect(b).toHaveAttribute("aria-busy", "true");
    await act(async () => answer({ ...QUIET, quiet: true }));
    await settle();
    expect(within(b).getByRole("list", { name: "Totals for the last 3 days" })).toBeInTheDocument();
    expect(b).toHaveTextContent("Nothing happened in the last 3 days.");
    expect(within(b).queryByRole("status")).toBeNull();
    expect(b).not.toHaveAttribute("aria-busy");
  });

  it("keeps the last answer and says so when a later refresh fails", async () => {
    load();
    const page = await show();
    vi.mocked(app.api.briefing).mockRejectedValueOnce(new ApiError(0, "ccd unreachable"));
    vi.mocked(app.api.milestones).mockRejectedValueOnce(new ApiError(0, "ccd unreachable"));
    act(() => app.store.set((d) => ({ ...d, activity: [ev(960, "milestone.done"), ...d.activity] })));
    await settle();
    expect(within(brief(page)).getByRole("status")).toHaveTextContent("Not updated just now (ccd unreachable). Showing ccd's last answer, for the last 12 hours.");
    expect(brief(page).querySelectorAll(".hq-brief-proj")).toHaveLength(3);
    expect(within(where(page)).getByRole("status")).toHaveTextContent("Not updated just now (ccd unreachable). Showing ccd's last answer.");
    expect(where(page).querySelectorAll(".hq-ms-proj")).toHaveLength(5);
    // the next good answer clears it
    act(() => app.store.set((d) => ({ ...d, activity: [ev(961, "milestone.done"), ...d.activity] })));
    await settle();
    expect(within(brief(page)).queryByRole("status")).toBeNull();
    expect(within(where(page)).queryByRole("status")).toBeNull();
  });

  it("says so when nothing happened, and still shows the zeros ccd sent", async () => {
    vi.mocked(app.api.briefing).mockResolvedValue(QUIET);
    load();
    const b = brief(await show());
    expect(b).toHaveTextContent("Nothing happened in the last 12 hours.");
    expect(b.querySelectorAll(".hq-brief-proj")).toHaveLength(0);
    expect(b.querySelectorAll(".hq-brief-stats .is-zero")).toHaveLength(7);
    expect(b).not.toHaveTextContent("No activity");
  });

  it("shows no figure at all on a server without the route, or when ccd fails", async () => {
    vi.mocked(app.api.briefing).mockRejectedValue(new ApiError(404, "not found"));
    load();
    let b = brief(await show());
    expect(b).toHaveTextContent("This server does not have the briefing yet. It arrives with the next server update.");
    expect(b.querySelector("[role=alert]")).toBeNull();
    expect(b.querySelector(".hq-brief-stats")).toBeNull();
    cleanup();

    vi.mocked(app.api.briefing).mockRejectedValue(new ApiError(500, "event log is locked"));
    b = brief(await show());
    expect(within(b).getByRole("alert")).toHaveTextContent("event log is locked");
    expect(b.querySelector(".hq-brief-stats")).toBeNull();
  });

  it("reloads when something countable happens", async () => {
    load();
    await show();
    expect(app.api.briefing).toHaveBeenCalledTimes(1);
    act(() => app.store.set((d) => ({ ...d, activity: [ev(900, "agent.status"), ...d.activity] })));
    await settle();
    expect(app.api.briefing).toHaveBeenCalledTimes(1);
    act(() => app.store.set((d) => ({ ...d, activity: [ev(901, "pr.opened"), ...d.activity] })));
    await settle();
    expect(app.api.briefing).toHaveBeenCalledTimes(2);
  });
});

describe("My Office › Where we are", () => {
  it("gives every project one line per track: how far along, and what is in hand", async () => {
    load();
    const page = await show();
    const names = [...where(page).querySelectorAll(".hq-ms-name")].map((n) => n.textContent);
    expect(names).toHaveLength(5);
    expect(new Set(names)).toEqual(new Set(["SamVision", "GYST", "MFE", "GauzeMate", "Command Center"]));
    const [tech, life] = [...row(page, "SamVision").querySelectorAll<HTMLElement>(".hq-ms-track")];
    expect(within(tech).getByRole("img", { name: "1 of 3 done" })).toBeInTheDocument();
    expect(tech).toHaveTextContent(`Technical1 of 3Now Set up the front end · due ${dueLabel("2026-11-20")}`);
    expect(life).toHaveTextContent(`Real life0 of 2Next Contact the lawyer · overdue ${dueLabel("2026-11-10")}`);
    expect(life.querySelector(".t-bad")).toHaveTextContent("overdue");
    expect(row(page, "MFE").querySelector(".hq-ms-track")).toHaveTextContent("Technical1 of 1All done");
    expect(row(page, "GYST")).toHaveTextContent("TechnicalNo milestones yetReal lifeNo milestones yet");
    expect(within(row(page, "GYST")).getByRole("button", { name: "Add GYST milestones" })).toHaveAttribute("aria-expanded", "false");
  });

  it("Edit opens both lists; a state change goes to ccd and the line follows ccd's answer", async () => {
    load();
    const page = await show();
    fireEvent.click(within(row(page, "SamVision")).getByRole("button", { name: "Edit SamVision milestones" }));
    const tech = within(row(page, "SamVision")).getByRole("region", { name: "Technical milestones" });
    expect([...tech.querySelectorAll(".hq-ms-item b")].map((b) => b.textContent)).toEqual(["Set up the back end", "Set up the front end", "Ship the mobile layout"]);
    expect(tech).toHaveTextContent("Added by the lead");
    expect(tech.querySelector(".hq-ms-item.is-done small")).toHaveTextContent("Done 1h ago");
    expect(within(row(page, "SamVision")).getByRole("region", { name: "Real life milestones" })).toHaveTextContent("Ask about the licence wording");

    const change = vi.spyOn(app.api, "milestoneChange").mockImplementation(async (_p, id, m) => {
      const it = view.projects.samvision.technical.find((x) => x.id === id)!;
      Object.assign(it, m, m.state === "done" ? { doneAt: at(9, 30) } : {});
      return { milestone: it, revision: ++view.projects.samvision.revision };
    });
    const sel = within(tech).getByRole("combobox", { name: "State of Set up the front end" });
    sel.focus();
    fireEvent.change(sel, { target: { value: "done" } });
    // while ccd answers, the control is off for screen readers but is not disabled, so focus stays on it
    expect(sel).toHaveAttribute("aria-disabled", "true");
    expect(sel).not.toBeDisabled();
    await settle();
    expect(change).toHaveBeenCalledWith("samvision", "m_b", { state: "done" });
    expect(document.activeElement).toBe(sel);
    expect(sel).not.toHaveAttribute("aria-disabled");
    expect(row(page, "SamVision").querySelector(".hq-ms-track")).toHaveTextContent("Technical2 of 3Next Ship the mobile layout");
  });

  it("adds to the right track, and keeps what was typed when ccd refuses", async () => {
    load();
    const page = await show();
    fireEvent.click(within(row(page, "GYST")).getByRole("button", { name: "Add GYST milestones" }));
    const life = within(row(page, "GYST")).getByRole("region", { name: "Real life milestones" });
    const input = within(life).getByRole("textbox", { name: "New real life milestone" });
    const add = vi.spyOn(app.api, "milestoneAdd").mockRejectedValueOnce(new ApiError(400, "that looks like a secret"));
    expect(within(life).getByRole("button", { name: "Add" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "  Contact the lawyer  " } });
    fireEvent.change(within(life).getByLabelText("Due date (optional)"), { target: { value: "2026-12-01" } });
    fireEvent.click(within(life).getByRole("button", { name: "Add" }));
    await settle();
    expect(add).toHaveBeenCalledWith("gyst", { track: "business", title: "Contact the lawyer", due: "2026-12-01" });
    expect(within(life).getByRole("alert")).toHaveTextContent("that looks like a secret");
    expect(input).toHaveValue("  Contact the lawyer  ");
    expect(life).toHaveTextContent("None yet.");

    add.mockImplementationOnce(async (_p, m) => {
      const it = ms("m_new", m.title, { due: m.due ?? null });
      view.projects.gyst.business.push(it);
      return { milestone: it, revision: 1 };
    });
    fireEvent.click(within(life).getByRole("button", { name: "Add" }));
    await settle();
    expect(input).toHaveValue("");
    expect(document.activeElement).toBe(input);
    expect(within(life).queryByRole("alert")).toBeNull();
    expect(row(page, "GYST")).toHaveTextContent(`Real life0 of 1Next Contact the lawyer · due ${dueLabel("2026-12-01")}`);
  });

  it("moves, renames and removes through ccd, and says when the list changed somewhere else", async () => {
    load();
    const page = await show();
    fireEvent.click(within(row(page, "SamVision")).getByRole("button", { name: "Edit SamVision milestones" }));
    const tech = () => within(row(page, "SamVision")).getByRole("region", { name: "Technical milestones" });
    // at the ends a move button is switched off for screen readers but stays focusable, and pressing it sends nothing
    const top = within(tech()).getByRole("button", { name: "Move Set up the back end up" });
    expect(top).toHaveAttribute("aria-disabled", "true");
    expect(top).not.toBeDisabled();
    expect(within(tech()).getByRole("button", { name: "Move Ship the mobile layout down" })).toHaveAttribute("aria-disabled", "true");
    expect(within(tech()).getByRole("button", { name: "Move Set up the front end up" })).not.toHaveAttribute("aria-disabled");

    const order = vi.spyOn(app.api, "milestoneOrder").mockRejectedValueOnce(Object.assign(new ApiError(409, "stale revision"), { data: {} }));
    fireEvent.click(top);
    expect(order).not.toHaveBeenCalled();
    fireEvent.click(within(tech()).getByRole("button", { name: "Move Ship the mobile layout up" }));
    await settle();
    expect(order).toHaveBeenCalledWith("samvision", "technical", ["m_a", "m_c", "m_b"], 7);
    expect(within(tech()).getByRole("alert")).toHaveTextContent("This list changed somewhere else. It has been reloaded; try again.");
    expect(app.api.milestones).toHaveBeenCalledTimes(2);

    // a move that works: the row changes place and the keyboard stays on the button that was pressed
    order.mockImplementationOnce(async (_p, track, ids) => {
      const t = view.projects.samvision[track];
      view.projects.samvision[track] = ids.map((id) => t.find((x) => x.id === id)!);
      return { revision: ++view.projects.samvision.revision };
    });
    const down = within(tech()).getByRole("button", { name: "Move Set up the front end down" });
    down.focus();
    fireEvent.click(down);
    await settle();
    expect([...tech().querySelectorAll(".hq-ms-item b")].map((b) => b.textContent)).toEqual(["Set up the back end", "Ship the mobile layout", "Set up the front end"]);
    expect(document.activeElement).toBe(within(tech()).getByRole("button", { name: "Move Set up the front end down" }));
    expect(document.activeElement).toHaveAttribute("aria-disabled", "true");

    const change = vi.spyOn(app.api, "milestoneChange").mockImplementation(async (_p, id, m) => {
      const it = view.projects.samvision.technical.find((x) => x.id === id)!;
      Object.assign(it, m);
      return { milestone: it, revision: 8 };
    });
    fireEvent.click(within(tech()).getByRole("button", { name: "Edit Ship the mobile layout" }));
    // meanwhile the lead adds a note; Jay only renames, so only the title is sent and the note survives
    view.projects.samvision.technical.find((x) => x.id === "m_c")!.note = "The lead's note";
    fireEvent.change(within(tech()).getByRole("textbox", { name: "Title" }), { target: { value: "Ship the phone layout" } });
    fireEvent.click(within(tech()).getByRole("button", { name: "Save" }));
    await settle();
    expect(change).toHaveBeenCalledWith("samvision", "m_c", { title: "Ship the phone layout" });
    expect(tech()).toHaveTextContent("Ship the phone layout");
    expect(tech()).toHaveTextContent("The lead's note");
    // the form closes and focus is back on the pencil it was opened with
    expect(document.activeElement).toBe(within(tech()).getByRole("button", { name: "Edit Ship the phone layout" }));

    // nothing changed: Save closes the form and sends nothing; a cleared note and a new date go as just those two
    change.mockClear();
    fireEvent.click(within(tech()).getByRole("button", { name: "Edit Ship the phone layout" }));
    fireEvent.click(within(tech()).getByRole("button", { name: "Save" }));
    await settle();
    expect(change).not.toHaveBeenCalled();
    fireEvent.click(within(tech()).getByRole("button", { name: "Edit Ship the phone layout" }));
    fireEvent.change(within(tech()).getByRole("textbox", { name: "Note" }), { target: { value: " " } });
    fireEvent.change(within(tech()).getByLabelText("Due date"), { target: { value: "2026-12-24" } });
    fireEvent.click(within(tech()).getByRole("button", { name: "Save" }));
    await settle();
    expect(change).toHaveBeenCalledWith("samvision", "m_c", { due: "2026-12-24", note: null });

    const remove = vi.spyOn(app.api, "milestoneRemove").mockImplementation(async (_p, id) => {
      view.projects.samvision.technical = view.projects.samvision.technical.filter((x) => x.id !== id);
      return { ok: true, revision: 9 };
    });
    // remove asks once more on the same button, which says what it is about to remove
    const bin = within(tech()).getByRole("button", { name: "Remove Ship the phone layout" });
    bin.focus();
    fireEvent.click(bin);
    expect(remove).not.toHaveBeenCalled();
    expect(bin).toHaveAccessibleName("Confirm: remove Ship the phone layout");
    expect(bin).toHaveTextContent("Remove?");
    expect(document.activeElement).toBe(bin);
    fireEvent.click(bin);
    await settle();
    expect(remove).toHaveBeenCalledWith("samvision", "m_c");
    expect(tech()).not.toHaveTextContent("Ship the phone layout");
    // the row is gone, so focus goes to the field for the next one, not to the top of the page
    expect(document.activeElement).toBe(within(tech()).getByRole("textbox", { name: "New technical milestone" }));
  });

  it("shows what a lead added when its event arrives, and nothing on a server without the route", async () => {
    load();
    const page = await show();
    view.projects.gyst.technical.push(ms("m_g", "Wire the importer", { by: "agent:lead-gyst" }));
    act(() => app.store.set((d) => ({ ...d, activity: [ev(950, "milestone.added"), ...d.activity] })));
    await settle();
    expect(row(page, "GYST").querySelector(".hq-ms-track")).toHaveTextContent("Technical0 of 1Next Wire the importer");
    cleanup();

    vi.mocked(app.api.milestones).mockRejectedValue(new ApiError(404, "not found"));
    const w = where(await show());
    expect(w).toHaveTextContent("This server does not have milestones yet. It arrives with the next server update.");
    expect(w.querySelector(".hq-ms-proj, [role=alert]")).toBeNull();
  });
});
