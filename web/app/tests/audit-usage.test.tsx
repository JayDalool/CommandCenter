/** Settings → Audit and Usage (PR 7): recorded, not enforced; tokens shown once; costs are estimates. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { Audit } from "../src/components/Audit";
import { Usage, tokens, usd } from "../src/components/Usage";
import { setDevSession } from "../src/api/developer";
import type { AuditState, ActorsState, UsageState } from "../src/api/types";

const now = Date.now() / 1000;
const audit: AuditState = {
  available: true, chain: { ok: true, checked: 3, brokenAt: null },
  summary: { total: 3, byVia: { none: 2, developer: 1 }, unverifiedJay: 1, agentUnverified: 1, mismatch: 0, wouldRefuse: 2 },
  events: [
    { id: 3, at: now - 5, actor: "agent:coder", verified: false, via: "none", tokenActor: null, method: "POST",
      path: "/api/tasks/SAM-1/comments", status: 201, project: "samvision", ref: "SAM-1", bodyKeys: ["body"], summary: "", profileHash: null },
    { id: 2, at: now - 50, actor: "jay", verified: true, via: "developer", tokenActor: null, method: "POST",
      path: "/api/workers/approve", status: 200, project: null, ref: null, bodyKeys: ["id"], summary: "", profileHash: null },
  ],
};
const actors: ActorsState = { available: true, header: "X-CCD-Actor-Token", tokens: [
  { id: 1, actor: "agent:reviewer", fingerprint: "ab12-cd34", issuedAt: now - 99, expiresAt: now + 9999, revokedAt: null, note: "", status: "active" }] };

describe("Audit", () => {
  afterEach(() => { vi.restoreAllMocks(); setDevSession(null); });

  it("shows who did what and how far it is proven; issuing without Developer Mode asks to unlock", async () => {
    vi.spyOn(app.api, "audit").mockResolvedValue(audit);
    vi.spyOn(app.api, "actors").mockResolvedValue(actors);
    const issue = vi.spyOn(app.api, "actorIssue");
    render(<Audit />);
    expect(await screen.findByText("agent:coder")).toBeInTheDocument();
    expect(screen.getByText(/intact \(3 rows\)/)).toBeInTheDocument();
    expect(screen.getAllByText("Developer Unlock").length).toBeGreaterThan(0);
    expect(screen.getByText("ab12-cd34")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Issue a token" }));
    expect(issue).not.toHaveBeenCalled();
  });

  it("with Developer Mode, issues a token and shows it once", async () => {
    setDevSession("s".repeat(43), 3600);
    vi.spyOn(app.api, "audit").mockResolvedValue(audit);
    vi.spyOn(app.api, "actors").mockResolvedValue(actors);
    vi.spyOn(window, "prompt").mockReturnValue("agent:coordinator");
    const issue = vi.spyOn(app.api, "actorIssue").mockResolvedValue({ ...actors.tokens[0], actor: "agent:coordinator", token: "cca_SECRET" });
    render(<Audit />);
    await screen.findByText("agent:coder");
    fireEvent.click(screen.getByRole("button", { name: "Issue a token" }));
    await waitFor(() => expect(issue).toHaveBeenCalledWith("agent:coordinator", 30, ""));
    expect(await screen.findByText("cca_SECRET")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText("cca_SECRET")).not.toBeInTheDocument();
  });

  it("walks the whole chain on request", async () => {
    const get = vi.spyOn(app.api, "audit").mockImplementation(async (q = "") =>
      q.includes("full=1") ? { ...audit, chain: { ok: true, checked: 9, brokenAt: null, full: true } } : audit);
    vi.spyOn(app.api, "actors").mockResolvedValue(actors);
    render(<Audit />);
    fireEvent.click(await screen.findByRole("button", { name: "Check whole chain" }));
    expect(await screen.findByText(/intact \(9 rows, whole chain\)/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("?full=1&limit=1");
  });

  it("says when the chain is broken", async () => {
    vi.spyOn(app.api, "audit").mockResolvedValue({ ...audit, chain: { ok: false, checked: 1, brokenAt: 2 } });
    vi.spyOn(app.api, "actors").mockResolvedValue(actors);
    render(<Audit />);
    expect(await screen.findByText("broken at row 2")).toBeInTheDocument();
  });
});

const row = (key: string, cost: number, unpriced = 0) => ({ key, replies: 3, input: 1500, output: 200, cacheRead: 2_000_000, cacheWrite: 0, costUsd: cost, unpriced });
const usage: UsageState = {
  available: true, days: 14, pricesAsOf: "2026-10-06", note: "Estimate at Anthropic list prices; subscription plans are not billed per token.",
  total: { replies: 6, input: 3000, output: 400, cacheRead: 4_000_000, cacheWrite: 0, costUsd: 12.5, unpriced: 1 },
  byProject: [row("samvision", 12.5)], byModel: [row("claude-opus-5-5", 12.5), row("gpt-5-codex", 0, 3)], byDay: [], byTicket: [row("SAM-7", 4)],
  bySource: [], budgets: [{ project: "samvision", monthlyUsd: 10, monthlyTokens: null, spentUsd: 12.5, spentTokens: 4_003_400 }],
};

describe("Usage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("formats", () => {
    expect([tokens(999), tokens(1500), tokens(2_000_000), tokens(3e9)]).toEqual(["999", "1.5k", "2.0M", "3.0B"]);
    expect([usd(0.1234), usd(250.4)]).toEqual(["$0.12", "$250"]);
  });

  it("shows the estimate, budgets (shown only) and unpriced models; changing the window re-reads", async () => {
    const get = vi.spyOn(app.api, "usage").mockResolvedValue(usage);
    render(<Usage />);
    expect(await screen.findByText(/not billed per token/)).toBeInTheDocument();
    expect(screen.getByText(/over \(shown only\)/)).toBeInTheDocument();
    expect(screen.getByText("SAM-7")).toBeInTheDocument();
    expect(screen.getByText("$0.00*")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith(30));
  });
});
