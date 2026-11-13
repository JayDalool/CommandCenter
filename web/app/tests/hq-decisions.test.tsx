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
import { developer } from "../src/api/developer";
import { works } from "../src/tickets/useWork";
import type { TicketWork } from "../src/api/types";

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
    // Nothing on the page approves or merges: with no ticket questions in the queue, its only buttons filter the list.
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

  describe("answering in place", () => {
    const q = (id: number, extra: object) => ({ id, batch: 1, position: id, text: `Question ${id}?`, kind: "text", options: [],
      askedAt: 1, askedBy: "agent:coordinator", answer: null, answeredAt: null, answeredBy: null, purpose: null, ...extra });
    const work = (questions: object[]) => ({ key: "SV-056", questions, openQuestions: questions.length } as unknown as TicketWork);

    function withQuestions(questions: object[]) {
      load();
      const st = app.store.get().state!;
      st.needs = [{ project: "samvision", ref: "SV-056", text: "Claude needs answers: Export", kind: "questions",
        questions: questions.length, url: null } as unknown as (typeof st.needs)[number], ...st.needs];
      app.store.set({ ...app.store.get(), state: { ...st } });
      works.set({});
      vi.spyOn(app.api, "inbox").mockReturnValue(new Promise(() => {}));
      vi.spyOn(app.api, "taskWork").mockResolvedValue(work(questions));
    }
    const row = (page: HTMLElement) => rows(page).find((r) => r.textContent!.includes("SV-056"))!;
    afterEach(() => developer.set({ active: false, expiresAt: null, error: null }));

    it("shows the recommended option picked, with why, and sends it in one press", async () => {
      withQuestions([q(1, { kind: "choice", options: ["CSV", "XLSX", "Both"], recommended: 1, why: "Clients use Excel" })]);
      developer.set({ active: true, expiresAt: null, error: null });
      const answers = vi.spyOn(app.api, "answers").mockResolvedValue({ work: work([]), complete: true, delivered: true,
        reason: null, deliveredTo: "lead" } as never);
      const page = await show();
      const r = row(page);
      expect(r.querySelector("a")!.textContent).toBe("Open task");
      fireEvent.click(within(r).getByRole("button", { name: "Answer here" }));
      await act(async () => {});
      const group = within(r).getByRole("radiogroup", { name: "Question 1?" });
      const radios = within(group).getAllByRole("radio");
      expect(radios.map((x) => x.closest("label")!.querySelector("b")!.textContent))
        .toEqual(["CSV", "XLSX", "Both", "Something else", "Talk it through"]);
      expect(radios[1]).toBeChecked();
      expect(radios[1].closest("label")).toHaveTextContent("Recommended");
      expect(radios[1].closest("label")).toHaveTextContent("Clients use Excel");
      fireEvent.click(within(r).getByRole("button", { name: "Send answer" }));
      await act(async () => {});
      expect(answers).toHaveBeenCalledWith("SV-056", [{ id: 1, answer: "XLSX" }]);
      expect(r).toHaveTextContent("Sent to the SamVision lead in Messages");
    });

    it("takes Jay's own words with Something else, and Other: … on a yes / no question", async () => {
      withQuestions([q(1, { kind: "choice", options: ["A", "B"] }), q(2, { kind: "yesno" }), q(3, {})]);
      developer.set({ active: true, expiresAt: null, error: null });
      const answers = vi.spyOn(app.api, "answers").mockResolvedValue({ work: work([]), complete: true, delivered: true,
        reason: null, deliveredTo: "task" } as never);
      const page = await show();
      const r = row(page);
      fireEvent.click(within(r).getByRole("button", { name: "Answer here" }));
      await act(async () => {});
      expect(within(r).getByRole("button", { name: "Send answers" })).toBeDisabled();
      const pickIn = (name: string, label: string) => fireEvent.click(within(within(r).getByRole("radiogroup", { name }))
        .getAllByRole("radio").find((x) => x.closest("label")!.querySelector("b")!.textContent === label)!);
      pickIn("Question 1?", "Something else");
      fireEvent.change(within(r).getByLabelText("Your answer to: Question 1?"), { target: { value: "Neither, use C" } });
      pickIn("Question 2?", "Something else");
      fireEvent.change(within(r).getByLabelText("Your answer to: Question 2?"), { target: { value: "only on mobile" } });
      fireEvent.change(within(r).getByLabelText("Your answer to: Question 3?"), { target: { value: "Admins first" } });
      fireEvent.click(within(r).getByRole("button", { name: "Send answers" }));
      await act(async () => {});
      expect(answers).toHaveBeenCalledWith("SV-056", [{ id: 1, answer: "Neither, use C" }, { id: 2, answer: "Other: only on mobile" },
        { id: 3, answer: "Admins first" }]);
      expect(r).toHaveTextContent("Sent to the task's Claude session.");
    });

    it("Talk it through messages the lead with the question quoted, answers nothing, and opens Messages", async () => {
      withQuestions([q(1, { kind: "choice", options: ["CSV", "XLSX"], recommended: 0, why: "simple" })]);
      const answers = vi.spyOn(app.api, "answers");
      const chat = vi.spyOn(app.api, "chatSend").mockResolvedValue({ ok: true } as never);
      const page = await show();
      const r = row(page);
      fireEvent.click(within(r).getByRole("button", { name: "Answer here" }));
      await act(async () => {});
      fireEvent.click(within(r).getAllByRole("radio").find((x) => x.closest("label")!.textContent!.startsWith("Talk it through"))!);
      fireEvent.change(within(r).getByLabelText("Talk through: Question 1?"), { target: { value: "What about Google Sheets?" } });
      fireEvent.click(within(r).getByRole("button", { name: "Send to the lead and open Messages" }));
      await act(async () => {});
      expect(chat).toHaveBeenCalledWith("samvision", "About SV-056: “Question 1?”\nOptions: 1. CSV (recommended)  2. XLSX\n\nWhat about Google Sheets?");
      expect(answers).not.toHaveBeenCalled();
      expect(location.hash).toBe("#/messages?c=samvision");
    });

    it("asks for Developer Unlock instead of sending when it is locked", async () => {
      withQuestions([q(1, { kind: "choice", options: ["A", "B"], recommended: 0, why: "w" })]);
      const answers = vi.spyOn(app.api, "answers");
      const unlock = vi.fn();
      window.addEventListener("cc:dev-unlock", unlock);
      const page = await show();
      const r = row(page);
      fireEvent.click(within(r).getByRole("button", { name: "Answer here" }));
      await act(async () => {});
      expect(r).toHaveTextContent("Sending answers needs Developer Unlock");
      fireEvent.click(within(r).getByRole("button", { name: "Send answer" }));
      expect(unlock).toHaveBeenCalled();
      expect(answers).not.toHaveBeenCalled();
      window.removeEventListener("cc:dev-unlock", unlock);
    });
  });
});
