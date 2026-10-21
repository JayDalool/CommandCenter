/** Settings → Policies: the Project Operating Profiles, read-only (v2 Phase 1). */
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { Policies } from "../src/components/Policies";
import type { PolicyState } from "../src/api/types";

const data: PolicyState = {
  fingerprint: "ab".repeat(32), problems: [],
  projects: {
    samvision: { name: "SamVision", file: "policy/projects/samvision.toml", sha256: "cd".repeat(32), valid: true, errors: [], drift: [],
      mode: "controlled_production", decisions: ["D-004"], learning: "deep",
      enforced: { merge: "owner", night: "careful", paused: "", max_lanes: 2, ui_fix: "ask" },
      target: { release: { windows: ["Thu 01:00 America/Winnipeg"], unattended_requires: ["health_checks", "auto_rollback"] } },
      capabilities: { health_checks: false, auto_rollback: false } },
    gauzemate: { name: "GauzeMate", file: "policy/projects/gauzemate.toml", sha256: "ef".repeat(32), valid: true, errors: [], drift: [],
      mode: "paused", decisions: ["D-009"], learning: "off",
      enforced: { merge: "owner", night: "normal", paused: "Jay paused GauzeMate", max_lanes: 2, ui_fix: "ask" },
      target: {}, capabilities: { health_checks: false, auto_rollback: false } },
  },
  decisions: { "D-004": { id: "D-004", date: "2026-10-21", decided_by: "jay", projects: ["samvision"], question: "May SamVision deploy unattended at 01:00?",
    decision: "Only safe, low-risk releases, after health checks and rollback exist.", rationale: "x", rules: [], reconsider: "when rollback is rehearsed",
    supersedes: null, valid: true } },
};

describe("Policies", () => {
  it("shows today's rules, the agreed target as not enforced, and Jay's decisions", async () => {
    vi.spyOn(app.api, "profiles").mockResolvedValue(data);
    render(<Policies />);
    expect(await screen.findByText("Controlled production")).toBeInTheDocument();
    expect(screen.getByText(/not enforced yet/)).toBeInTheDocument();
    expect(screen.getByText(/All policy files are valid/)).toBeInTheDocument();
    expect(screen.getByText(/windows: Thu 01:00 America\/Winnipeg/)).toBeInTheDocument();
    expect(screen.getAllByText(/not built/).length).toBeGreaterThan(0);
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("none yet")).toBeInTheDocument();
    expect(screen.getByText("May SamVision deploy unattended at 01:00?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save|edit|apply/i })).toBeNull();          // read-only
  });

  it("lists problems when a file is broken or drifts", async () => {
    vi.spyOn(app.api, "profiles").mockResolvedValue({ ...data, problems: ["policy/projects/gyst.toml: cannot read"] });
    render(<Policies />);
    expect(await screen.findByText("policy/projects/gyst.toml: cannot read")).toBeInTheDocument();
  });
});
