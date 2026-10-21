/** Needs You v2: the same queue as the dashboard and the bell, grouped, one action per card, with the pending
 *  Approval, the shadow engine's verdict and earlier answers from GET /api/inbox. Read-only. */
import { render, screen, fireEvent, within } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { NeedsYou, typeOf } from "../src/screens/NeedsYou";
import { jayQueue } from "../src/tickets/model";
import type { InboxState } from "../src/api/types";
import { state } from "./helpers";

const now = Date.now() / 1000;

function setup() {
  try { localStorage.clear(); } catch { /* none */ }
  const st = state();
  st.blocked = [];
  st.needs = [
    { project: "gyst", ref: "GYST-7", text: "Ready to merge: approved and green", kind: "gate", gate: "merge", url: null, flags: ["gate:merge"], since: now - 3600 },
    { project: "gyst", ref: "GYST-9", text: "Claude needs 1 answer: Export", kind: "questions", questions: 1, url: null, flags: [], since: now - 60 },
    { project: "samvision", ref: "SV-3", text: "Blocked: the API key is missing", kind: "gate", gate: "failure", url: null, flags: ["gate:failure"], since: now - 30 },
  ] as never;
  app.store.patch({ state: st, tickets: [] });
  const inbox: InboxState = {
    available: true, orphans: [],
    counts: { approvals: 2, overdue: 1, precedentHits: 1, orphans: 0 },
    items: {
      "gate:gyst:GYST-7": { approval: { id: 4, project: "gyst", gate: "merge", subjectHash: "ab".repeat(20), requestedAt: now - 3600, expiresAt: now - 5, overdue: true },
        engine: { engine: "jay", observed: "jay", rule: "merge: target policy needs Jay", agree: true, at: now } },
      "questions:gyst:GYST-9": { precedents: [{ questionId: 2, question: "Keep the old export?", precedents: [
        { id: 8, project: "gyst", key: "GYST-2", question: "Keep the old export?", decision: "no", decidedAt: now - 86400, decidedBy: "jay", reconsider: null }] }] },
    },
  };
  vi.spyOn(app.api, "inbox").mockResolvedValue(inbox);
  return st;
}

describe("Needs You", () => {
  it("shows the dashboard's queue grouped by project, with approval, engine verdict and precedent; one action each", async () => {
    const st = setup();
    render(<NeedsYou />);
    expect(await screen.findByText(/1 overdue/)).toBeInTheDocument();
    expect(screen.getByText(/3 things need you/)).toBeInTheDocument();
    expect(jayQueue(st).length).toBe(3);                                         // the same list the bell counts
    expect(screen.getByText(/bound to abababab/)).toBeInTheDocument();
    expect(screen.getByText("ask you")).toBeInTheDocument();
    expect(screen.getByText("no")).toBeInTheDocument();                          // asked before → its answer
    const merge = screen.getByText("Merge acceptance").closest("li")!;
    expect(within(merge).getAllByRole("link")).toHaveLength(1);                   // one action per card
    expect(within(merge).getByRole("link", { name: "Review merge" }).getAttribute("href")).toContain("GYST-7");
    expect(screen.getByRole("link", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Resolve" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();          // nothing approves from here
  });

  it("groups by type, blockers first, and still lists everything when the details are unavailable", async () => {
    setup();
    vi.spyOn(app.api, "inbox").mockResolvedValue({ available: false, error: "the Needs You details could not be read", items: {}, orphans: [], counts: {} });
    render(<NeedsYou />);
    fireEvent.click(screen.getByRole("button", { name: "By type" }));
    expect(await screen.findByText(/the list below is still complete/)).toBeInTheDocument();
    const titles = screen.getAllByRole("heading").map((h) => h.textContent ?? "");
    expect(titles.findIndex((t) => t.startsWith("Blocker"))).toBeLessThan(titles.findIndex((t) => t.startsWith("Question")));
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });

  it("says so when the details cannot be read, and keeps the list", async () => {
    setup();
    vi.spyOn(app.api, "inbox").mockRejectedValue(new Error("down"));
    render(<NeedsYou />);
    expect(await screen.findByText(/Could not read the approval and engine details/)).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });

  it("puts a project with an overdue approval first, even when its name sorts later", async () => {
    setup();
    vi.spyOn(app.api, "inbox").mockResolvedValue({ available: true, orphans: [], counts: { approvals: 1, overdue: 1 },
      items: { "gate:samvision:SV-3": { approval: { id: 9, project: "samvision", gate: "failure", subjectHash: "cd".repeat(32),
        requestedAt: now - 9000, expiresAt: now - 1, overdue: true } } } });
    render(<NeedsYou />);
    await screen.findByText(/1 overdue/);
    const titles = screen.getAllByRole("heading").map((h) => h.textContent ?? "");
    expect(titles[0]).toMatch(/samvision/i);
  });

  it("names each kind of ask", () => {
    expect(typeOf({ kind: "gate", gate: "plan" } as never)).toBe("Plan approval");
    expect(typeOf({ kind: "answer" } as never)).toBe("Blocked agent");
  });
});
