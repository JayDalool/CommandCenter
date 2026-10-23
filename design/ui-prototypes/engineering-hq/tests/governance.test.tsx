// Budgets (D-033) and approvals (D-032), Jay 2026-10-23. The budget rules mirror server/ccd/budgets.py; the approval
// tiers follow the D-024 final proposal. Mock data only: nothing talks to Slack or ccd.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { App, renderView } from "../src/App";
import { owners } from "../src/windows/manager";
import { viewState } from "../src/data/live";
import { viewById } from "../src/windows/views";
import {
  SAFETY_KINDS, SAMPLE_WORK, amendRequest, approvableIn, assess, budgetLines, canApprove, decide, effectiveLimit, gov, holdKey, reqHash, requestOverride,
  seedGov, tierOf, wouldStart,
} from "../src/data/governance";

const go = (h: string) => act(() => { location.hash = h; window.dispatchEvent(new HashChangeEvent("hashchange")); });
const H = 3600_000;

beforeEach(() => {
  gov.set(seedGov()); owners.set({}); viewState.set({}); sessionStorage.clear();
  vi.stubGlobal("open", vi.fn(() => ({ closed: false, focus: vi.fn(), close: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn()); vi.stubGlobal("WebSocket", vi.fn());
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("budget rules (same as server/ccd/budgets.py)", () => {
  it("alerts at each threshold before the limit and holds at the limit", () => {
    const lim = { usd: 100, tokens: null };
    expect(assess(10, 0, lim).state).toBe("ok");
    expect(assess(50, 0, lim)).toMatchObject({ state: "alert", threshold: 50 });
    expect(assess(81, 0, lim)).toMatchObject({ state: "alert", threshold: 80 });
    expect(assess(96, 0, lim)).toMatchObject({ state: "alert", threshold: 95 });
    expect(assess(100, 0, lim).state).toBe("hold");
    expect(assess(5, 0, { usd: null, tokens: null }).state).toBe("none");
    expect(assess(0, 0, { usd: 0, tokens: null }).state).toBe("hold");              // a zero limit allows no billable work
    expect(assess(30, 0, lim, [25, 60]).threshold).toBe(25);                         // configurable thresholds
  });

  it("a token limit counts too (Codex has no price), and the run-rate warns early", () => {
    expect(assess(1, 41_000_000, { usd: 300, tokens: 40_000_000 }).state).toBe("hold");
    expect(assess(40, 0, { usd: 100, tokens: null }, undefined, 0.3).onCourseToHold).toBe(true);
    expect(assess(20, 0, { usd: 100, tokens: null }, undefined, 0.3).onCourseToHold).toBe(false);
  });

  it("an override adds to the limit until it expires and never lowers it", () => {
    const now = 1_000_000;
    expect(effectiveLimit({ usd: 20, tokens: null }, { usd: 5, until: now + H, requestId: "r" }, now).usd).toBe(25);
    expect(effectiveLimit({ usd: 20, tokens: null }, { usd: 5, until: now - 1, requestId: "r" }, now).usd).toBe(20);
    expect(effectiveLimit({ usd: 20, tokens: null }, { usd: -5, until: now + H, requestId: "r" }, now).usd).toBe(20);
  });

  it("an agent over its limit does not stop its project; a project hold stops only that project", () => {
    const agentHeld = new Set([holdKey("agent", "nova")]);
    expect(wouldStart({ agent: "nova", project: "samvision", kind: "build", billable: true }, agentHeld).start).toBe(false);
    expect(wouldStart({ agent: "atlas", project: "samvision", kind: "review", billable: true }, agentHeld).start).toBe(true);
    const projectHeld = new Set([holdKey("project", "gyst")]);
    expect(wouldStart({ agent: "pixel", project: "gyst", kind: "ui_test", billable: true }, projectHeld).start).toBe(false);
    expect(wouldStart({ agent: "nova", project: "samvision", kind: "build", billable: true }, projectHeld).start).toBe(true);
    const companyHeld = new Set([holdKey("company", "*")]);
    expect(wouldStart({ agent: "atlas", project: "mfe", kind: "review", billable: true }, companyHeld).start).toBe(false);
    expect(wouldStart({ agent: "atlas", project: "mfe", kind: "review", billable: false }, companyHeld).start).toBe(true);
  });

  it("safety monitoring, rollback and recovery are never held, even at the company limit", () => {
    const all = new Set([holdKey("company", "*"), holdKey("project", "gyst"), holdKey("agent", "orion")]);
    for (const k of SAFETY_KINDS) expect(wouldStart({ agent: "orion", project: "gyst", kind: k, billable: true }, all).start).toBe(true);
    expect(SAFETY_KINDS).toEqual(expect.arrayContaining(["monitoring", "rollback", "recovery", "restore", "health_check", "incident_response"]));
  });
});

describe("approval tiers (D-032)", () => {
  it("registration is low, read-only activation standard, repository, policy and production high", () => {
    expect(tierOf({ kind: "register_agent" })).toBe("low");
    expect(tierOf({ kind: "activate_readonly" })).toBe("standard");
    for (const k of ["repo_access", "policy_change", "raise_limit"] as const) expect(tierOf({ kind: k })).toBe("high");
  });

  it("a small, short override is low risk; a larger or longer one is high", () => {
    const o = (usd: number, hours: number) => tierOf({ kind: "budget_override", override: { scope: "agent", key: "nova", usd, hours } }, 20);
    expect(o(5, 24)).toBe("low");
    expect(o(6, 24)).toBe("high");
    expect(o(5, 72)).toBe("high");
    expect(tierOf({ kind: "budget_override", override: { scope: "agent", key: "x", usd: 1, hours: 1 } }, null)).toBe("high");
  });

  it("nothing is approvable inside Slack yet; high risk needs Developer Unlock and the typed ID; expired never", () => {
    for (const t of ["low", "standard", "high"] as const) { expect(approvableIn(t, "slack")).toBe(false); expect(approvableIn(t, "screen")).toBe(true); }
    const ctx = { unlocked: false, typed: "", expected: "agent:pixel", expired: false };
    expect(canApprove("low", ctx)).toBe(true);
    expect(canApprove("high", ctx)).toBe(false);
    expect(canApprove("high", { ...ctx, unlocked: true })).toBe(false);
    expect(canApprove("high", { ...ctx, typed: "agent:pixel" })).toBe(false);
    expect(canApprove("high", { ...ctx, unlocked: true, typed: "agent:pixel" })).toBe(true);
    expect(canApprove("low", { ...ctx, expired: true })).toBe(false);
  });

  it("an approval is bound to the request's hash; a changed request has a new hash", () => {
    const before = reqHash(gov.get().requests.find((r) => r.id === "r-7f3a91")!);
    amendRequest("r-7f3a91");
    expect(reqHash(gov.get().requests.find((r) => r.id === "r-7f3a91")!)).not.toBe(before);
    decide("r-7f3a91", "approved", "screen");
    const rec = gov.get().decisions["r-7f3a91"];
    expect(rec.hash).toBe(reqHash(gov.get().requests.find((r) => r.id === "r-7f3a91")!));
    decide("r-7f3a91", "declined", "screen");                                        // recorded once
    expect(gov.get().decisions["r-7f3a91"].decision).toBe("approved");
  });

  it("approving an override request applies a temporary override to that line only", () => {
    const nova = budgetLines("agent").find((l) => l.key === "nova")!;
    const r = requestOverride(nova, 5, 24);
    expect(gov.get().requests[0].id).toBe(r.id);
    expect(gov.get().overrides).toEqual({});
    decide(r.id, "approved", "screen");
    expect(Object.keys(gov.get().overrides)).toEqual([holdKey("agent", "nova")]);
  });
});

describe("Budgets page", () => {
  it("shows Nova held while SamVision keeps running, and which new work would start", () => {
    go("#/budgets"); render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Budgets" })).toBeInTheDocument();
    expect(screen.getByText(/Shadow mode: nothing is held yet/)).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-agent-nova")).getByText("Held")).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-project-samvision")).queryByText("Held")).toBeNull();
    expect(within(screen.getByTestId("budget-project-samvision")).getByText(/Alert/)).toBeInTheDocument();
    expect(within(screen.getByTestId("budget-agent-iris")).getByText("No limit")).toBeInTheDocument();
    expect(within(screen.getByTestId("work-w1")).getByText("Waits")).toBeInTheDocument();
    expect(within(screen.getByTestId("work-w2")).getByText("Starts")).toBeInTheDocument();
    expect(SAMPLE_WORK.length).toBe(5);
  });

  it("at the company limit all billable work waits but safety work still starts", () => {
    go("#/budgets"); render(<App />);
    fireEvent.click(screen.getByRole("radio", { name: "Company over limit" }));
    expect(within(screen.getByTestId("budget-company-*")).getByText("Held")).toBeInTheDocument();
    for (const w of ["w1", "w2", "w3"]) expect(within(screen.getByTestId(`work-${w}`)).getByText("Waits")).toBeInTheDocument();
    for (const w of ["w4", "w5"]) expect(within(screen.getByTestId(`work-${w}`)).getByText("Starts")).toBeInTheDocument();
  });

  it("the override dialog shows its tier and files a request on the Approvals page", () => {
    go("#/budgets"); render(<App />);
    fireEvent.click(within(screen.getByTestId("budget-agent-nova")).getByRole("button", { name: /Request override/ }));
    const dlg = screen.getByRole("dialog");
    expect(within(dlg).getByTestId("override-tier")).toHaveTextContent("Low risk");
    fireEvent.click(within(dlg).getByRole("radio", { name: "72 h" }));
    expect(within(dlg).getByTestId("override-tier")).toHaveTextContent("High risk");
    const n = gov.get().requests.length;
    fireEvent.click(within(dlg).getByRole("button", { name: "Request override" }));
    expect(gov.get().requests.length).toBe(n + 1);
    expect(gov.get().requests[0].override).toMatchObject({ scope: "agent", key: "nova", hours: 72 });
    expect(within(screen.getByTestId("budget-agent-nova")).getByText("Held")).toBeInTheDocument();   // nothing applies until approved
  });

  it("an approved override lifts Nova's hold", () => {
    const r = requestOverride(budgetLines("agent").find((l) => l.key === "nova")!, 5, 24);
    decide(r.id, "approved", "screen");
    go("#/budgets"); render(<App />);
    const row = screen.getByTestId("budget-agent-nova");
    expect(within(row).queryByText("Held")).toBeNull();
    expect(within(row).getByText("Override active")).toBeInTheDocument();
    expect(within(screen.getByTestId("work-w1")).getByText("Starts")).toBeInTheDocument();
  });
});

describe("Approvals page", () => {
  it("lists requests with tiers, shows the Slack preview with a link that is not a credential, and says Slack is off", () => {
    go("#/approvals"); render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Approvals" })).toBeInTheDocument();
    expect(screen.getByText("Slack is not connected")).toBeInTheDocument();
    expect(within(screen.getByTestId("req-r-7f3a91")).getByText("Low risk")).toBeInTheDocument();
    expect(within(screen.getByTestId("req-r-2c8d40")).getByText("Standard")).toBeInTheDocument();
    expect(within(screen.getByTestId("req-r-b41e07")).getByText("High risk")).toBeInTheDocument();
    expect(within(screen.getByTestId("req-r-0e93cc")).getByText("Expired")).toBeInTheDocument();
    const phone = screen.getByLabelText("Slack message preview");
    expect(phone).toHaveTextContent("…/approve/r-7f3a91");
    expect(phone).toHaveTextContent(/not a credential/);
    expect(within(phone).getByRole("button", { name: "Approve" })).toBeDisabled();             // in-Slack approval is off
  });

  it("a low-risk request is approved on the screen and recorded with its hash", () => {
    go("#/approvals/r-7f3a91"); render(<App />);
    const s = screen.getByTestId("approval-screen");
    expect(within(s).queryByTestId("strong-confirm")).toBeNull();
    fireEvent.click(within(s).getByRole("button", { name: "Approve" }));
    expect(within(s).getByTestId("approval-recorded")).toHaveTextContent("Approved");
    expect(gov.get().decisions["r-7f3a91"]).toMatchObject({ decision: "approved", via: "screen" });
  });

  it("a high-risk request needs Developer Unlock and the typed ID before Approve is enabled", () => {
    go("#/approvals/r-b41e07"); render(<App />);
    const s = screen.getByTestId("approval-screen");
    const approve = within(s).getByRole("button", { name: "Approve" });
    expect(within(s).getByTestId("strong-confirm")).toBeInTheDocument();
    expect(approve).toBeDisabled();
    fireEvent.change(within(s).getByLabelText("Type agent:pixel to confirm"), { target: { value: "agent:pixel" } });
    expect(approve).toBeDisabled();
    fireEvent.click(within(s).getByRole("button", { name: /Use Developer Unlock/ }));
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(gov.get().decisions["r-b41e07"]).toMatchObject({ decision: "approved", via: "screen + Developer Unlock" });
  });

  it("a request that changes after it was opened cannot be approved", () => {
    go("#/approvals/r-7f3a91"); render(<App />);
    const s = screen.getByTestId("approval-screen");
    fireEvent.click(within(s).getByRole("button", { name: "Simulate a change (demo)" }));
    expect(within(s).getByRole("alert")).toHaveTextContent(/changed after you opened it/);
    expect(within(s).getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(gov.get().decisions["r-7f3a91"]).toBeUndefined();
  });

  it("an expired request offers no approval", () => {
    go("#/approvals/r-0e93cc"); render(<App />);
    const s = screen.getByTestId("approval-screen");
    expect(s).toHaveTextContent(/expired/);
    expect(within(s).queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

describe("navigation and pop-outs", () => {
  it("the sidebar has Approvals with a pending count, and Budgets", () => {
    go("#/office"); render(<App />);
    const more = screen.getByRole("navigation", { name: "More" });
    const nav = within(more).getByRole("link", { name: /Approvals/ });
    expect(nav).toHaveAttribute("href", "#/approvals");
    expect(nav).toHaveTextContent("3");
    expect(within(more).getByRole("link", { name: /Budgets/ })).toHaveAttribute("href", "#/budgets");
  });

  it("both pages pop out to another monitor", () => {
    for (const id of ["page:budgets", "page:approvals"]) {
      expect(viewById(id)?.title).toBeTruthy();
      const { unmount } = render(<>{renderView(id)}</>);
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(id === "page:budgets" ? "Budgets" : "Approvals");
      unmount();
    }
  });
});
