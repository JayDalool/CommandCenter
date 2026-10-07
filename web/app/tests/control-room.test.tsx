/** The control room (plans/COMMAND-CENTER-CONTROL-ROOM.md): wall layout, rooms, panes, pop-out state,
 *  the dashboard, the tree, questions, gates, notifications' deep links and Developer Mode once. */
import { render, screen, within, fireEvent, waitFor, act } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { developer, devSession, restoreDevSession, setDevSession } from "../src/api/developer";
import { prefs } from "../src/lib/prefs";
import { stageOf, jayHref, taskHref } from "../src/lib/control";
import { jayQueue } from "../src/tickets/model";
import { Dashboard, newsText, projectPanels } from "../src/screens/Dashboard";
import { Workspace } from "../src/screens/Workspace";
import { QuestionsForm } from "../src/tickets/Questions";
import { GateCard } from "../src/tickets/GateCard";
import { works } from "../src/tickets/useWork";
import {
  MAX_ROOMS, addPane, closeRoom, detachPane, detachRoom, layout, openRoom, paneAreas, parseLayout, popPaneState, popRoomState,
  reattachPane, resetLayout, returnRoom, sessionName, toggleTool, wallShape,
} from "../src/workspace/rooms";
import { ev, state, tasks } from "./helpers";
import type { Question, Ticket, TicketWork } from "../src/api/types";

function work(over: Partial<TicketWork> = {}): TicketWork {
  return { key: "SV-071", status: "IN_PROGRESS", stage: "BUILD", stages: [], plan: { summary: "Rework the layout" }, planState: "accepted",
    policy: { plan: "auto", planReasons: [], merge: "owner", ui: false, deploy: false }, gate: null, gateReason: null, confirmed: [],
    branch: null, worktree: null, prs: [], roles: {}, review: { verdict: null, head: null, cycles: 0 }, verification: null, merge: null,
    handoff: null, blocked: null, findings: [], questions: [], openQuestions: 0, evidence: [], ...over } as TicketWork;
}
const q = (id: number, text: string, kind: Question["kind"] = "text", options: string[] = []): Question =>
  ({ id, batch: 1, position: id, text, kind, options, askedAt: 1, askedBy: "agent:coordinator", answer: null, answeredAt: null, answeredBy: null });

function ticket(over: Partial<Ticket>): Ticket {
  return { ...tasks().tickets[0], ...over } as Ticket;
}

beforeEach(() => {
  vi.restoreAllMocks();
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
  resetLayout();
  works.set({});
  location.hash = "";
  setDevSession(null);
  prefs.patch({ wsCollapsed: [], wsDetailOpen: true });
});

describe("the wall layout (spec §12, §17)", () => {
  it("holds 4 rooms per window, reuses an open room, and refuses a fifth", () => {
    const keys = ["SV-1", "SV-2", "SV-3", "SV-4"];
    keys.forEach((k) => expect(openRoom("1", { kind: "task", project: "samvision", key: k }).ok).toBe(true));
    expect(layout.get().walls["1"]).toHaveLength(MAX_ROOMS);
    const again = openRoom("1", { kind: "task", project: "samvision", key: "SV-2" });
    expect(again.ok && again.existed).toBe(true);
    expect(Object.keys(layout.get().rooms)).toHaveLength(4);       // never a duplicate room
    expect(openRoom("1", { kind: "task", project: "samvision", key: "SV-5" })).toEqual({ ok: false, full: true });
    closeRoom("t:SV-1");
    expect(openRoom("1", { kind: "project", project: "samvision", key: null }).ok).toBe(true);
  });

  it("shapes: 1 full, 2 side by side, 3 and 4 a 2×2; panes 1 · 2 · 1 over 2 · 2×2", () => {
    expect([1, 2, 3, 4].map((n) => wallShape(n).cells)).toEqual([1, 2, 4, 4]);
    expect(wallShape(2)).toMatchObject({ cols: 2, rows: 1 });
    expect([1, 2, 3, 4].map((n) => paneAreas(n).length)).toEqual([1, 2, 3, 4]);
  });

  it("names every pane's session after its task or project, so every window attaches to the same one", () => {
    const task = { kind: "task" as const, key: "SV-071" }, cons = { kind: "project" as const, key: null };
    expect(["claude", "codex", "project", "server"].map((t) => sessionName(task, t as never, "SV")))
      .toEqual(["claude:SV-071", "codex:SV-071", "repo:SV-071", "server"]);
    expect(["claude", "codex", "project"].map((t) => sessionName(cons, t as never, "SV"))).toEqual(["claude:SV", "codex:SV", "repo:SV"]);
  });

  it("toggles 1–4 panes cleanly and never more", () => {
    openRoom("1", { kind: "task", project: "samvision", key: "SV-071" });
    const r = () => layout.get().rooms["t:SV-071"];
    expect(r().slots).toEqual(["claude"]);
    toggleTool("t:SV-071", "project");
    toggleTool("t:SV-071", "codex");
    toggleTool("t:SV-071", "server");
    expect(r().slots).toEqual(["claude", "project", "codex", "server"]);
    toggleTool("t:SV-071", "codex");
    expect(r().slots).toEqual(["claude", "project", "server"]);
    toggleTool("t:SV-071", "claude");
    toggleTool("t:SV-071", "project");
    toggleTool("t:SV-071", "server");
    expect(r().slots).toEqual([]);
  });

  it("a popped pane frees its slot (+ Add Pane), detaches on window close, and reattaches into the room", () => {
    openRoom("1", { kind: "task", project: "samvision", key: "SV-071", tools: ["claude", "project"] });
    const r = () => layout.get().rooms["t:SV-071"];
    popPaneState("t:SV-071", "claude");
    expect(r().slots).toEqual([null, "project"]);
    expect(r().out).toEqual({ claude: "popped" });
    detachPane("t:SV-071", "claude");
    expect(r().out).toEqual({ claude: "detached" });
    addPane("t:SV-071", 0, "codex");                        // the freed slot takes another tool
    expect(r().slots).toEqual(["codex", "project"]);
    reattachPane("t:SV-071", "claude");
    expect(r().slots).toEqual(["codex", "project", "claude"]);
    expect(r().out).toEqual({});
  });

  it("a popped room frees its wall slot; closing its window detaches; it can come back", () => {
    ["SV-1", "SV-2", "SV-3", "SV-4"].forEach((k) => openRoom("1", { kind: "task", project: "samvision", key: k }));
    popRoomState("t:SV-2");
    expect(layout.get().walls["1"]).toEqual(["t:SV-1", "t:SV-3", "t:SV-4"]);
    expect(openRoom("1", { kind: "task", project: "samvision", key: "SV-9" }).ok).toBe(true);   // the slot is reusable
    detachRoom("t:SV-2");
    expect(layout.get().rooms["t:SV-2"].where).toBe("detached");
    expect(returnRoom("t:SV-2", "1")).toBe(false);          // full again
    expect(returnRoom("t:SV-2", "2")).toBe(true);           // a second Workspace window
    expect(layout.get().walls["2"]).toEqual(["t:SV-2"]);
  });

  it("parses stored layouts defensively", () => {
    expect(parseLayout("not json").walls).toEqual({ "1": [] });
    const l = parseLayout(JSON.stringify({ v: 1, rooms: { a: { id: "a", where: "wall" } }, walls: { "1": ["a", "ghost", "a"] } }));
    expect(l.walls["1"]).toEqual(["a"]);
  });
});

describe("stages and deep links", () => {
  it("maps tickets to the visible stages when ccd does not send one", () => {
    expect(stageOf(ticket({ status: "IN_PROGRESS", visibleStage: undefined, openQuestions: 2 }))).toBe("Needs Jay");
    expect(stageOf(ticket({ status: "IN_REVIEW", visibleStage: undefined, gate: null, openQuestions: 0, flags: [] }))).toBe("Reviewing");
    expect(stageOf(ticket({ status: "CANCELLED", visibleStage: undefined }))).toBe("Closed");
    expect(stageOf(ticket({ status: "IN_PROGRESS", visibleStage: "Blocked" }))).toBe("Blocked");
  });

  it("every Needs Jay item goes to the task, its room and the exact action", () => {
    expect(taskHref("SV-071", "questions")).toBe("#/workspace?task=SV-071&focus=questions&open=1");
    const st = state();
    st.needs = [{ project: "samvision", ref: "SV-071", text: "Claude needs 3 answers", kind: "questions", url: null, questions: 3 } as never,
      { project: "commandcenter", ref: "CC-031", text: "Deploy approval", kind: "gate", url: null, gate: "deploy" } as never];
    st.blocked = [];
    const items = jayQueue(st);
    expect(items.map((i) => [i.verb, jayHref(i)])).toEqual([
      ["Answer", "#/workspace?task=SV-071&focus=questions&open=1"],
      ["Deploy", "#/workspace?task=CC-031&focus=deploy&open=1"]]);
  });
});

describe("dashboard (spec §4)", () => {
  it("one panel per project with latest update, Needs Jay and counts — no KPIs", () => {
    const st = state();
    st.needs = [{ project: "samvision", ref: "SV-071", text: "x", kind: "questions", url: null, questions: 3 } as never];
    st.blocked = [];
    app.store.patch({ state: st, activity: [ev(9, "task.updated", { ref: "SV-042", data: { kind: "status", to: "READY_TO_MERGE" } })] });
    render(<Dashboard />);
    const panels = screen.getAllByRole("region").filter((r) => r.classList.contains("dash-card"));
    // Every registered project with a polled repository or active tickets: SV, GZ, CC, GYST, MFE.
    expect(panels.map((p) => p.getAttribute("aria-label"))).toEqual(["SamVision", "GauzeMate", "Command Center", "GYST", "MFE"]);
    const sv = screen.getByRole("region", { name: "SamVision" });
    expect(within(sv).getByText("SV-042 ready to merge")).toBeInTheDocument();
    expect(within(sv).getByRole("link", { name: "Answer 3 questions on SV-071" })).toHaveAttribute("href",
      "#/workspace?task=SV-071&focus=questions&open=1");
    for (const word of ["commits", "files", "KPI"]) expect(screen.queryByText(new RegExp(word, "i"))).toBeNull();
  });

  it("counts by stage and shows blockers only when there are some", () => {
    const t = [ticket({ key: "SV-1", project: "samvision", status: "IN_REVIEW", archived: false, visibleStage: "Reviewing" }),
      ticket({ key: "SV-2", project: "samvision", status: "BLOCKED", archived: false, visibleStage: "Blocked", gateReason: "mobile overlap" }),
      ticket({ key: "SV-3", project: "samvision", status: "DONE", archived: false, visibleStage: "Closed" })];
    const [p] = projectPanels([{ key: "samvision", name: "SamVision", prefix: "SV" }], t, [], []);
    expect(p.active.map((x) => x.key)).toEqual(["SV-1", "SV-2"]);
    expect(p.counts).toMatchObject({ review: 1, merge: 0 });
    expect(p.blocked.map((x) => x.key)).toEqual(["SV-2"]);
    expect(newsText(ev(1, "task.updated", { ref: "SV-1", data: { kind: "status", to: "VERIFYING" } }))).toBe("SV-1 merged — verifying");
  });
});

describe("workspace (spec §5, §12)", () => {
  it("the tree lists active tasks only; double-click opens the Task Room; a fifth room offers pop-out or a new window", async () => {
    vi.spyOn(app.api, "workspaceProjects").mockResolvedValue({ projects: [] });
    vi.spyOn(app.api, "task").mockImplementation(async (k) => ({ ...tasks().tickets.find((t) => t.key === k)!, description: "", relations:
      { blocks: [], blocked_by: [], related: [], duplicates: [], duplicated_by: [] }, subtaskList: [], comments: [], timeline: [] }));
    vi.spyOn(app.api, "taskWork").mockResolvedValue(work());
    const all = app.data.tickets.map((t, i) => (i === 0 ? { ...t, status: "DONE" as const } : t));
    app.store.patch({ tickets: all });
    location.hash = "#/workspace";
    render(<Workspace />);
    const tree = screen.getByRole("navigation", { name: "Projects and tasks" });
    expect(within(tree).queryByText(all[0].key)).toBeNull();                 // closed: gone from the tree
    const open = all.filter((t) => !t.archived && !["DONE", "DENIED", "CANCELLED"].includes(t.status));
    expect(within(tree).getByText(open[0].key)).toBeInTheDocument();
    for (const t of open.slice(0, 4)) fireEvent.doubleClick(within(tree).getByText(t.key));
    expect(layout.get().walls["1"]).toHaveLength(4);
    expect(screen.getByText("Active Rooms: 4/4")).toBeInTheDocument();
    fireEvent.doubleClick(within(tree).getByText(open[4].key));
    const dlg = await screen.findByRole("dialog", { name: /Workspace is full \(4\/4\)/ });
    expect(within(dlg).getByRole("button", { name: "Open New Workspace Window" })).toBeInTheDocument();
    expect(within(dlg).getAllByRole("button", { name: /^Pop Out / })).toHaveLength(4);
  });
});

describe("questions (spec §9)", () => {
  it("one field per question; submitting sends every answer and the scope tick; never without Developer Mode", async () => {
    const w = work({ questions: [q(1, "Same layout on mobile?"), q(2, "Keep the colours?", "yesno"), q(3, "Which option?", "choice", ["A", "B"])],
      openQuestions: 3 });
    const answers = vi.spyOn(app.api, "answers").mockResolvedValue({ work: work(), complete: true, delivered: true, reason: null });
    const unlock = vi.fn();
    window.addEventListener("cc:dev-unlock", unlock);
    const done = vi.fn();
    render(<QuestionsForm ticketKey="SV-071" work={w} onDone={done} />);
    expect(screen.getByText("Claude needs 3 answers")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Same layout on mobile/), { target: { value: "Yes, same" } });
    fireEvent.click(screen.getByRole("radio", { name: "No" }));
    fireEvent.change(screen.getByLabelText(/Which option/), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit Answers" }));
    expect(unlock).toHaveBeenCalled();                       // locked: asks for Developer Mode, sends nothing
    expect(answers).not.toHaveBeenCalled();
    act(() => developer.set({ active: true, expiresAt: null, error: null }));
    fireEvent.click(screen.getByRole("checkbox", { name: /change the approved scope/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit Answers" }));
    await waitFor(() => expect(answers).toHaveBeenCalledWith("SV-071",
      [{ id: 1, answer: "Yes, same" }, { id: 2, answer: "No" }, { id: 3, answer: "B" }], true));
    expect(done).toHaveBeenCalled();
    window.removeEventListener("cc:dev-unlock", unlock);
  });
});

describe("gates in manager words (spec §11, §22)", () => {
  beforeEach(() => developer.set({ active: true, expiresAt: null, error: null }));

  it("a live deployment waits for Jay: Deploy Live closes the deploy gate", async () => {
    const op = vi.spyOn(app.api, "workOp").mockResolvedValue(work({ deploy: { approvedAt: 2 } as never }));
    render(<GateCard ticketKey="CC-031" work={work({ status: "VERIFYING", gate: "deploy", deploy: { env: "live", what: "The new Dashboard",
      verification: "UI tests 14/14", requestedAt: 1, requestedBy: "agent:coordinator", approvedAt: null, result: null } })} onDone={() => {}} />);
    const card = screen.getByRole("region", { name: "Ready for live deployment" });
    expect(within(card).getByText("The new Dashboard")).toBeInTheDocument();
    expect(within(card).getByText("UI tests 14/14")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Deploy Live" }));
    await waitFor(() => expect(op).toHaveBeenCalledWith("CC-031", "confirm", { gate: "deploy" }));
  });

  it("a blocker explains first, offers Fix and continue / Re-plan, and keeps technical details folded", async () => {
    const op = vi.spyOn(app.api, "workOp").mockResolvedValue(work());
    vi.spyOn(window, "prompt").mockReturnValue("fix the mobile layout");
    render(<GateCard ticketKey="SV-079" work={work({ status: "BLOCKED", gate: "failure", blocked: { stage: "REVIEW", reason: "mobile UI test failed",
      at: 1, what: "Buttons overlap on narrow screens.", why: "A visible mobile regression.", action: "Fix the mobile layout.", impact: "Small.",
      technical: "spec.ts:42" } })} onDone={() => {}} />);
    const card = screen.getByRole("region", { name: "SV-079 is blocked" });
    expect(within(card).getByText("Buttons overlap on narrow screens.")).toBeInTheDocument();
    expect(within(card).queryByText("spec.ts:42")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Show technical details" }));
    expect(within(card).getByText("spec.ts:42")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Fix and continue" }));
    await waitFor(() => expect(op).toHaveBeenCalledWith("SV-079", "rework", { reason: "fix the mobile layout" }));
  });
});

describe("Developer Mode once per app session (spec §27)", () => {
  it("survives a reload of this tab from sessionStorage, and Lock clears it", async () => {
    setDevSession("s".repeat(43), 3600);
    // a reload: memory is gone, sessionStorage is not
    const saved = sessionStorage.getItem("ccd.dev");
    setDevSession(null);
    sessionStorage.setItem("ccd.dev", saved!);
    await restoreDevSession();
    expect(devSession()).toBe("s".repeat(43));
    expect(developer.get().active).toBe(true);
    setDevSession(null);
    expect(sessionStorage.getItem("ccd.dev")).toBeNull();
    expect(JSON.stringify({ ...localStorage })).not.toContain("s".repeat(43));
  });
});
