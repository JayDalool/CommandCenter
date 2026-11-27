/** CC-100: the criteria editor. Save sends only what changed, asks for Developer Unlock past investigation (and to
 *  lower a risky size), explains a refusal without losing the edits, and shows the saved criteria at once. */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { ApiError } from "../src/api/client";
import { developer } from "../src/api/developer";
import { works } from "../src/tickets/useWork";
import { ScopeEditor } from "../src/tickets/ScopeEditor";
import { unlockDialogGone } from "../src/components/DevMode";
import { state, tasks } from "./helpers";
import type { TicketDetail, TicketWork } from "../src/api/types";

const crit = (id: string, text: string, st = "open") => ({ id, text, state: st, by: null, at: null, head: null });
const T = { key: "SV-056", project: "samvision", title: "Valuation", updatedAt: 1, dueAt: null } as unknown as TicketDetail;

function work(over: Partial<TicketWork> = {}): TicketWork {
  return { key: "SV-056", status: "IN_PROGRESS", stage: "BUILD", stages: [], plan: {}, planState: "accepted",
    policy: { plan: "auto", planReasons: [], merge: "owner", ui: false, deploy: false }, gate: null, gateReason: null,
    confirmed: [], branch: null, worktree: null, prs: [], roles: {}, review: { verdict: null, head: null, cycles: 0 },
    verification: null, merge: null, handoff: null, blocked: null, findings: [], size: "standard", requirements: ["keep the URL"],
    criteria: [crit("c1", "First", "pass"), crit("c2", "Second"), crit("c3", "Third")],
    flow: { size: "standard", stage: "build" }, ...over } as unknown as TicketWork;
}

let refresh: ReturnType<typeof vi.fn>;
function mount(w: TicketWork) {
  works.set({ "SV-056": w });
  vi.spyOn(app.api, "taskWork").mockResolvedValue(w);
  return render(<ScopeEditor t={T} />);
}
const edit = () => fireEvent.click(screen.getByRole("button", { name: "Edit" }));
const type = (name: string, v: string) => fireEvent.change(screen.getByRole("textbox", { name }), { target: { value: v } });

beforeEach(() => {
  vi.restoreAllMocks();
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true, taskProjects: t.projects, meta: t.meta });
  developer.set({ active: true } as never);
  refresh = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(app, "refreshTicket").mockImplementation(refresh as never);
});
afterEach(() => { cleanup(); unlockDialogGone(); works.set({}); });

it("reads: each criterion with its id and state, then Edit", () => {
  mount(work());
  const list = screen.getByRole("list", { name: "Criteria" });
  expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["c1FirstPassed", "c2SecondNot checked", "c3ThirdNot checked"]);
  expect(screen.getByText("keep the URL")).toBeInTheDocument();
});

it("is hidden on a closed ticket", () => {
  mount(work({ status: "DONE" }));
  expect(screen.queryByRole("region", { name: "Acceptance criteria" })).toBeNull();
});

it("Save sends kept criteria as {id,text}, new ones as text, and only the fields that changed", async () => {
  const op = vi.spyOn(app.api, "workOp").mockResolvedValue(work());
  mount(work());
  edit();
  type("Criterion c1", "First, reworded");
  fireEvent.click(screen.getByRole("button", { name: "Remove Criterion c2" }));
  fireEvent.click(screen.getByRole("button", { name: "Add criterion" }));
  type("New criterion 3", "Fourth");
  fireEvent.click(screen.getByRole("button", { name: "Add requirement" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Requirement 2" }), { target: { value: "no new route" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Size" }), { target: { value: "risky" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(op).toHaveBeenCalledTimes(1));
  expect(op).toHaveBeenCalledWith("SV-056", "criteria", {
    criteria: [{ id: "c1", text: "First, reworded" }, { id: "c3", text: "Third" }, "Fourth"],
    requirements: ["keep the URL", "no new route"], size: "risky" });
});

it("a save with nothing changed sends nothing", () => {
  const op = vi.spyOn(app.api, "workOp");
  mount(work());
  edit();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(op).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
});

it("past investigation without Unlock: explains, sends nothing, opens the dialog; after Unlock the same body is sent once", async () => {
  const op = vi.spyOn(app.api, "workOp").mockResolvedValue(work());
  developer.set({ active: false } as never);
  const dialog = vi.fn();
  window.addEventListener("cc:dev-unlock", dialog);
  mount(work());
  edit();
  type("Criterion c2", "Second, reworded");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("status")).toHaveTextContent("past investigation. Only you change its scope now, with Developer Unlock. Nothing was saved.");
  expect(dialog).toHaveBeenCalled();
  expect(op).not.toHaveBeenCalled();
  developer.set({ active: true } as never);
  // The dialog (mounted by the shell in the app) settles with ok: here the shell is absent, so press the button.
  fireEvent.click(screen.getByRole("button", { name: "Developer Unlock" }));
  await waitFor(() => expect(op).toHaveBeenCalledTimes(1));
  expect(op).toHaveBeenCalledWith("SV-056", "criteria", { criteria: [{ id: "c1", text: "First" }, { id: "c2", text: "Second, reworded" }, { id: "c3", text: "Third" }] });
  window.removeEventListener("cc:dev-unlock", dialog);
});

it("a 403 from ccd explains why, keeps the edits and leaves the works store alone", async () => {
  const w = work();
  vi.spyOn(app.api, "workOp").mockRejectedValue(new ApiError(403, "Developer Unlock required: changing a ticket past investigation is Jay's"));
  mount(w);
  edit();
  type("Criterion c1", "Kept edit");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Nothing was saved."));
  expect(screen.getByRole("textbox", { name: "Criterion c1" })).toHaveValue("Kept edit");
  expect(works.get()["SV-056"]).toBe(w);
  expect(refresh).not.toHaveBeenCalled();
});

it("a 409 shows ccd's own words and keeps the edits", async () => {
  vi.spyOn(app.api, "workOp").mockRejectedValue(new ApiError(409, "SV-056 is past investigation; only Jay edits its criteria now"));
  mount(work());
  edit();
  type("Criterion c1", "Kept");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("only Jay edits its criteria now"));
  expect(screen.getByRole("textbox", { name: "Criterion c1" })).toHaveValue("Kept");
});

it("lowering a risky size asks for Unlock first, even during investigation", () => {
  const op = vi.spyOn(app.api, "workOp");
  developer.set({ active: false } as never);
  mount(work({ status: "RESEARCHING", size: "risky", flow: { size: "risky", stage: "investigate" } } as never));
  edit();
  fireEvent.change(screen.getByRole("combobox", { name: "Size" }), { target: { value: "standard" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("status")).toHaveTextContent("Lowering a risky ticket needs Developer Unlock");
  expect(op).not.toHaveBeenCalled();
});

it("during investigation a scope edit needs no Unlock", async () => {
  const op = vi.spyOn(app.api, "workOp").mockResolvedValue(work());
  developer.set({ active: false } as never);
  mount(work({ status: "RESEARCHING", flow: { size: "standard", stage: "investigate" } } as never));
  edit();
  type("Criterion c1", "Early edit");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(op).toHaveBeenCalledTimes(1));
});

it("small is offered only before investigation; the due date has a minimum of today and cannot be cleared", () => {
  const { unmount } = mount(work());
  edit();
  expect(within(screen.getByRole("combobox", { name: "Size" })).queryByRole("option", { name: "small" })).toBeNull();
  expect(screen.getByLabelText("Due date")).toHaveAttribute("min", new Date().toLocaleDateString("en-CA"));
  unmount();
  mount(work({ status: "INBOX", flow: { size: "standard", stage: "intake" } } as never));
  edit();
  expect(within(screen.getByRole("combobox", { name: "Size" })).getByRole("option", { name: "small" })).toBeInTheDocument();
});

it("a past or cleared due date is not sent", () => {
  const op = vi.spyOn(app.api, "workOp");
  mount(work({ status: "INBOX", flow: { size: "standard", stage: "intake" } } as never));
  edit();
  fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2000-01-01" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("status")).toHaveTextContent("cannot be in the past");
  fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));      // cleared: nothing to send
  expect(op).not.toHaveBeenCalled();
});

it("after a resolved save the section shows the returned criteria and the ticket is refreshed", async () => {
  const saved = work({ criteria: [crit("c1", "First, reworded"), crit("c4", "Fresh")] } as never);
  vi.spyOn(app.api, "workOp").mockResolvedValue(saved);
  mount(work());
  edit();
  type("Criterion c1", "First, reworded");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByText("Fresh")).toBeInTheDocument());
  expect(refresh).toHaveBeenCalledWith("SV-056");
  expect(screen.queryByText("Third")).toBeNull();
});

it("a draft made for one ticket is never sent for another (CC-100 user check)", async () => {
  const op = vi.spyOn(app.api, "workOp").mockResolvedValue(work());
  const other = { ...T, key: "CC-032" } as TicketDetail;
  const first = work();
  const second = { ...work(), key: "CC-032" } as TicketWork;
  works.set({ "SV-056": first, "CC-032": second });
  vi.spyOn(app.api, "taskWork").mockImplementation(async (k: string) => (k === "CC-032" ? second : first));
  // Without a key on the mount, the same component instance is reused, as the pane did before the fix.
  const view = render(<ScopeEditor t={T} />);
  edit();
  type("Criterion c1", "SV-056 draft");
  view.rerender(<ScopeEditor t={other} />);
  fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("another ticket"));
  expect(op).not.toHaveBeenCalled();
  // Keyed (as the pane mounts it): the draft is dropped and the editor is closed.
  view.rerender(<ScopeEditor key="CC-032" t={other} />);
  expect(screen.queryByRole("textbox", { name: "Criterion c1" })).toBeNull();
});
