/** Ticket WORK: compact stages, one owner action per open gate, and gates in the one Needs Jay queue. */
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { WorkPanel } from "../src/tickets/WorkPanel";
import { jayQueue } from "../src/tickets/model";
import { developer } from "../src/api/developer";
import { state, tasks } from "./helpers";
import type { TicketDetail, TicketWork } from "../src/api/types";

const T = { key: "SV-056", project: "samvision", title: "Valuation", updatedAt: 1, prUrl: "https://github.com/JayDalool/SamVisionAI/pull/94" } as unknown as TicketDetail;

function work(over: Partial<TicketWork> = {}): TicketWork {
  return { key: "SV-056", status: "IN_REVIEW", stage: "REVIEW",
    stages: [{ stage: "PLAN", state: "done" }, { stage: "BUILD", state: "done" }, { stage: "REVIEW", state: "active" },
      { stage: "MERGE", state: "todo" }, { stage: "VERIFY", state: "todo" }],
    plan: { summary: "Show the comparison" }, planState: "accepted",
    policy: { plan: "auto", planReasons: [], merge: "owner", ui: false, deploy: false },
    gate: null, gateReason: null, confirmed: [], branch: "SV-056-valuation", worktree: "/srv/w/SV-056", prs: ["JayDalool/SamVisionAI#94"],
    roles: { implementer: { model: "sonnet", session: "sv-056", at: 1 } }, review: { verdict: null, head: null, cycles: 0 },
    verification: null, merge: null, handoff: null, blocked: null, findings: [], ...over } as TicketWork;
}

beforeEach(() => {
  vi.restoreAllMocks();
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true, taskProjects: t.projects, meta: t.meta });
  developer.set({ active: true } as never);
});

it("shows PLAN · BUILD · REVIEW · MERGE · VERIFY with the current stage, and no action when nothing waits on Jay", async () => {
  vi.spyOn(app.api, "taskWork").mockResolvedValue(work());
  render(<WorkPanel t={T} />);
  const pipe = await screen.findByRole("list", { name: "Pipeline" });
  expect(within(pipe).getAllByRole("listitem").map((li) => li.textContent?.replace(/[✓●■—]/g, "").replace(/(done|active|todo|blocked)$/, "")))
    .toEqual(["PLAN", "BUILD", "REVIEW", "MERGE", "VERIFY"]);
  expect(within(pipe).getByText("REVIEW").closest("li")).toHaveAttribute("aria-current", "step");
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryAllByRole("button")).toHaveLength(0);
  expect(screen.getByText("SV-056-valuation")).toBeInTheDocument();
});

it("merge gate: one action, Open PR, to GitHub", async () => {
  vi.spyOn(app.api, "taskWork").mockResolvedValue(work({ status: "READY_TO_MERGE", stage: "MERGE", gate: "merge",
    gateReason: "PR approved and green", review: { verdict: "APPROVE", head: "abcdef1234", cycles: 0 } }));
  render(<WorkPanel t={T} />);
  const gate = await screen.findByRole("status");
  expect(gate).toHaveTextContent("Ready to merge");
  const actions = within(gate).getAllByRole("link");
  expect(actions.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([["Open PR ↗", T.prUrl]]);
  expect(screen.getByText(/approved at abcdef1/)).toBeInTheDocument();
});

it("plan gate: Approve plan closes it through ccd; locked asks to unlock first", async () => {
  vi.spyOn(app.api, "taskWork").mockResolvedValue(work({ status: "RESEARCHING", stage: "PLAN", gate: "plan", planState: "proposed",
    gateReason: "migration" }));
  const confirm = vi.spyOn(app.api, "confirmGate").mockResolvedValue(work({ status: "READY_TO_IMPLEMENT", stage: "PLAN" }));
  developer.set({ active: false } as never);
  const unlock = vi.fn();
  window.addEventListener("cc:dev-unlock", unlock);
  const { unmount } = render(<WorkPanel t={T} />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve plan" }));
  expect(unlock).toHaveBeenCalled();
  expect(confirm).not.toHaveBeenCalled();
  window.removeEventListener("cc:dev-unlock", unlock);
  unmount();
  developer.set({ active: true } as never);
  render(<WorkPanel t={T} />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve plan" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledWith("SV-056", "plan"));
});

it("blocked shows the stage and reason once, with Resume", async () => {
  vi.spyOn(app.api, "taskWork").mockResolvedValue(work({ status: "BLOCKED", stage: "REVIEW", gate: "failure",
    gateReason: "2 review cycles requested changes", blocked: { stage: "REVIEW", reason: "2 review cycles requested changes", at: 1 },
    stages: [{ stage: "PLAN", state: "done" }, { stage: "BUILD", state: "done" }, { stage: "REVIEW", state: "blocked" },
      { stage: "MERGE", state: "todo" }, { stage: "VERIFY", state: "todo" }] }));
  render(<WorkPanel t={T} />);
  expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
  expect(screen.getByText(/REVIEW: 2 review cycles/)).toBeInTheDocument();
});

it("every pipeline event reads as its recorded sentence, including safety signals", async () => {
  const { describe: describeEvent } = await import("../src/screens/TicketDetail");
  const ev = (kind: string, trigger: string | null) => ({ id: 1, at: 1, actor: "system:automation", kind, field: null, from: null, to: null, trigger, data: {} });
  expect(describeEvent(ev("pipeline.unreviewed_merge", "JayDalool/SamVisionAI#94 merged without a recorded approval")))
    .toBe("JayDalool/SamVisionAI#94 merged without a recorded approval");
  expect(describeEvent(ev("pipeline.not_ready", "back to review: checks are not green"))).toBe("back to review: checks are not green");
  expect(describeEvent(ev("pipeline.some_future_step", null))).toBe("some future step");
});

it("merge gate without a ticket prUrl links the reviewed PR", async () => {
  vi.spyOn(app.api, "taskWork").mockResolvedValue(work({ status: "READY_TO_MERGE", stage: "MERGE", gate: "merge",
    review: { verdict: "APPROVE", head: "a".repeat(40), cycles: 0, pr: "JayDalool/SamVisionAI#94" } }));
  render(<WorkPanel t={{ ...T, prUrl: null } as unknown as TicketDetail} />);
  const link = await screen.findByRole("link", { name: "Open PR ↗" });
  expect(link).toHaveAttribute("href", "https://github.com/JayDalool/SamVisionAI/pull/94");
});

it("Needs Jay: a gate is one item with its verb, and replaces a flag item for the same ticket", () => {
  const st = state();
  st.needs = [
    { project: "samvision", ref: "SV-056", text: "UI review: verified; owner check left", kind: "gate", gate: "ui", url: null, flags: ["gate:ui"], since: 1 },
    { project: "samvision", ref: "SV-056", text: "Valuation", kind: "ticket", url: null, flags: ["needs_ui_review"], since: 1 },
    { project: "gyst", ref: "GYST-001", text: "Plan needs approval: migration", kind: "gate", gate: "plan", url: null, flags: ["gate:plan"], since: 2 },
  ] as never;
  st.blocked = [];
  const q = jayQueue(st);
  expect(q.map((j) => [j.ref, j.kind, j.verb])).toEqual([["SV-056", "gate", "Review UI"], ["GYST-001", "gate", "Approve plan"]]);
});
