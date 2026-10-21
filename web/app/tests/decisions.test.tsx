/** Settings → Decisions: Decision and Approval records, read-only (v2 Phase 1). */
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { Decisions } from "../src/components/Decisions";
import type { LedgerState } from "../src/api/types";

const data: LedgerState = {
  available: true, counts: { pending: 1, consumed: 1 },
  approvals: [
    { id: 2, project: "gyst", key: "GYST-12", subject: "merge", subjectHash: "ab".repeat(20), action: "close the merge gate",
      state: "pending", reason: "PR approved and green", requestedAt: 1792000000, requestedBy: "system:pipeline",
      expiresAt: 1792259200, overdue: false, decidedAt: null, decidedBy: null, via: null, consumedAt: null, voidedAt: null, voidReason: null },
    { id: 1, project: "samvision", key: "SV-80", subject: "plan", subjectHash: "cd".repeat(32), action: "close the plan gate",
      state: "consumed", reason: "migration", requestedAt: 1791990000, requestedBy: "system:pipeline", expiresAt: 1792249200,
      overdue: false, decidedAt: 1791995000, decidedBy: "jay", via: "ui", consumedAt: 1791995000, voidedAt: null, voidReason: null },
  ],
  decisions: [
    { id: 3, ref: null, project: "gyst", key: "GYST-12", question: "Keep the old export?", options: [], decision: "no",
      rationale: "yesno question", decidedBy: "jay", via: "answer", reconsider: null, decidedAt: 1792000100, supersedes: null,
      source: "question", sourceRef: "41", sha256: "ef".repeat(32), current: true },
    { id: 1, ref: "D-004", project: "samvision", key: null, question: "May SamVision deploy unattended at 01:00?",
      options: [], decision: "Only low-risk releases, after health checks and rollback exist.", rationale: "x", decidedBy: "jay",
      via: "policy-file", reconsider: null, decidedAt: 1792000000, supersedes: null, source: "policy", sourceRef: "D-004",
      sha256: "12".repeat(32), current: true },
  ],
};

describe("Decisions", () => {
  it("lists approvals with what they are bound to, and decisions, without any action", async () => {
    vi.spyOn(app.api, "decisions").mockResolvedValue(data);
    render(<Decisions />);
    expect(await screen.findByText("GYST-12", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("waiting for you")).toBeInTheDocument();
    expect(screen.getByText("approved and used")).toBeInTheDocument();
    expect(screen.getByText("abababab".padEnd(10, "ab"))).toBeInTheDocument();
    expect(screen.getByText("Keep the old export?")).toBeInTheDocument();
    expect(screen.getByText("May SamVision deploy unattended at 01:00?")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says when the task system is off", async () => {
    vi.spyOn(app.api, "decisions").mockResolvedValue({ available: false, decisions: [], approvals: [], counts: {} });
    render(<Decisions />);
    expect(await screen.findByText("No records")).toBeInTheDocument();
  });
});
