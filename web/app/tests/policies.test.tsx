/** Settings → Policies: the Project Operating Profiles, read-only (v2 Phase 1). */
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { Policies } from "../src/components/Policies";
import type { AutonomyState, PolicyState } from "../src/api/types";

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

const shadow: AutonomyState = {
  mode: "shadow", engine: 1, available: true, total: 3, agree: 2, disagree: 1,
  counts: { samvision: { plan: { total: 3, agree: 2, pairs: { "auto->auto": 2, "auto->jay": 1 } } } },
  missing: { "api change": 1 },
  disagreements: [{ id: 3, at: 1792000000, key: "SV-101", project: "samvision", action: "plan", observed: "auto", engine: "jay",
    rule: "target.plan_approval:unknown", reasons: ["a plan trigger cannot be checked yet"], missing: ["api change"] }],
};

beforeEach(() => { vi.spyOn(app.api, "autonomy").mockResolvedValue(shadow); });

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

  it("shows the shadow engine's agreements and disagreements, and says it changes nothing", async () => {
    vi.spyOn(app.api, "profiles").mockResolvedValue(data);
    render(<Policies />);
    expect(await screen.findByText("Autonomy engine (shadow)")).toBeInTheDocument();
    expect(screen.getByText(/changes nothing/)).toBeInTheDocument();
    expect(screen.getByText("2 agree")).toBeInTheDocument();
    expect(screen.getByText(/Command Center acted on its own; target policy would have asked you/)).toBeInTheDocument();
    expect(screen.getByText("SV-101")).toBeInTheDocument();
  });

  it("lists problems when a file is broken or drifts", async () => {
    vi.spyOn(app.api, "profiles").mockResolvedValue({ ...data, problems: ["policy/projects/gyst.toml: cannot read"] });
    render(<Policies />);
    expect(await screen.findByText("policy/projects/gyst.toml: cannot read")).toBeInTheDocument();
  });
});
