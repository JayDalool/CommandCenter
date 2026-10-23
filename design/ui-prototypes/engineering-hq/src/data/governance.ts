// Budgets (D-033) and approvals (D-032), as the prototype shows them. MOCK DATA ONLY.
//
// The budget rules are a TypeScript copy of server/ccd/budgets.py (assess, wouldStart, effectiveLimit) so the page
// shows exactly what the server's shadow report would say. The approval rules are the tiers in the D-024 final
// proposal: Slack carries the request and a secure link; Jay approves on an authenticated CommandCenter screen;
// high-risk items need Developer Unlock and a typed confirmation there; in-Slack approval is a later, separate step.
// Nothing here talks to Slack or ccd.
import { SharedStore, isRecord } from "../lib/shared";

// ---------------------------------------------------------------- budgets (server/ccd/budgets.py)
export const DEFAULT_ALERTS = [50, 80, 95];   // D-033's proposed defaults; configurable per scope
/** Work the engine tags as safety work by action type. Never held by a budget. An agent cannot tag its own work. */
export const SAFETY_KINDS = ["health_check", "monitoring", "incident_response", "rollback", "restore", "backup_check", "recovery"] as const;
export const SAFETY_LABEL: Record<(typeof SAFETY_KINDS)[number], string> = {
  health_check: "Health checks", monitoring: "Monitoring", incident_response: "Incident response", rollback: "Rollback",
  restore: "Restore", backup_check: "Backup checks", recovery: "Recovery" };
export type Scope = "company" | "project" | "agent";
export interface Limit { usd: number | null; tokens: number | null }
export interface Assessment { state: "none" | "ok" | "alert" | "hold"; pct: number | null; threshold: number | null; onCourseToHold: boolean }

export function assess(spentUsd: number, spentTokens: number, limit: Limit, alerts: number[] = DEFAULT_ALERTS, elapsed?: number): Assessment {
  const pcts: number[] = [];
  for (const [spent, cap] of [[spentUsd, limit.usd], [spentTokens, limit.tokens]] as const) {
    if (cap == null) continue;
    pcts.push(cap <= 0 ? 100 : (100 * spent) / cap);
  }
  if (!pcts.length) return { state: "none", pct: null, threshold: null, onCourseToHold: false };
  const pct = Math.max(...pcts);
  const crossed = [...alerts].sort((a, b) => a - b).filter((a) => pct >= a);
  const state = pct >= 100 ? "hold" : crossed.length ? "alert" : "ok";
  const onCourseToHold = state !== "hold" && !!elapsed && elapsed > 0 && elapsed < 1 && pct / elapsed >= 100;
  return { state, pct: Math.round(pct * 10) / 10, threshold: crossed.length ? crossed[crossed.length - 1] : null, onCourseToHold };
}

export interface Override { usd: number; until: number; requestId: string }
/** A temporary override adds to a limit until it expires. It never lowers or removes a limit. */
export function effectiveLimit(limit: Limit, o: Override | undefined, now: number): Limit {
  if (!o || now >= o.until || !(o.usd > 0) || limit.usd == null) return limit;
  return { ...limit, usd: limit.usd + o.usd };
}

export interface Work { agent?: string; project?: string; kind: string; billable: boolean }
export interface StartVerdict { start: boolean; heldBy: { scope: Scope; key: string }[]; reason: string }
export const holdKey = (scope: Scope, key: string) => `${scope}:${key}`;
/** The scope rule: an agent's hold stops only that agent; a project's only that project; the company's all billable work. */
export function wouldStart(w: Work, holds: Set<string>): StartVerdict {
  if ((SAFETY_KINDS as readonly string[]).includes(w.kind)) return { start: true, heldBy: [], reason: "Safety work is never held by a budget." };
  if (!w.billable) return { start: true, heldBy: [], reason: "Costs nothing." };
  const mine: { scope: Scope; key: string }[] = [{ scope: "company", key: "*" }];
  if (w.project) mine.push({ scope: "project", key: w.project });
  if (w.agent) mine.push({ scope: "agent", key: w.agent });
  const heldBy = mine.filter((m) => holds.has(holdKey(m.scope, m.key)));
  return heldBy.length ? { start: false, heldBy, reason: `Waits: ${heldBy.map((h) => (h.scope === "company" ? "company budget" : `${h.key} budget`)).join(", ")}.` }
    : { start: true, heldBy: [], reason: "Within budget." };
}

// ---------------------------------------------------------------- mock budget lines
export interface BudgetLine { scope: Scope; key: string; label: string; period: "month" | "day"; limit: Limit; spentUsd: number; spentTokens: number; alerts: number[]; note?: string }
export type Scenario = "normal" | "agent" | "project" | "company";
export const SCENARIOS: { id: Scenario; label: string; hint: string }[] = [
  { id: "normal", label: "Normal", hint: "Two alerts, nothing held." },
  { id: "agent", label: "Agent over limit", hint: "Nova is held; SamVision keeps running." },
  { id: "project", label: "Project over limit", hint: "GYST is held; other projects keep running." },
  { id: "company", label: "Company over limit", hint: "All billable work waits; safety work still runs." },
];
/** Demo spend for a scenario. Month 72% elapsed. Numbers are mock, not metered. */
export function budgetLines(s: Scenario): BudgetLine[] {
  const company: BudgetLine = { scope: "company", key: "*", label: "CommandCenter (company)", period: "month", limit: { usd: 1500, tokens: null }, spentUsd: s === "company" ? 1512 : 1046, spentTokens: 0, alerts: DEFAULT_ALERTS };
  const projects: BudgetLine[] = [
    { scope: "project", key: "samvision", label: "SamVision", period: "month", limit: { usd: 600, tokens: null }, spentUsd: s === "agent" ? 498 : 462, spentTokens: 0, alerts: DEFAULT_ALERTS },
    { scope: "project", key: "gyst", label: "GYST / LifeOps", period: "month", limit: { usd: 300, tokens: 40_000_000 }, spentUsd: s === "project" ? 301 : 231, spentTokens: 22_400_000, alerts: DEFAULT_ALERTS,
      note: "Includes Codex, counted in tokens (no price)." },
    { scope: "project", key: "mfe", label: "MyFamilyExpenses", period: "month", limit: { usd: 150, tokens: null }, spentUsd: 41, spentTokens: 0, alerts: DEFAULT_ALERTS },
  ];
  const agents: BudgetLine[] = [
    { scope: "agent", key: "nova", label: "Nova", period: "day", limit: { usd: 20, tokens: null }, spentUsd: s === "agent" ? 20.4 : 11.2, spentTokens: 0, alerts: DEFAULT_ALERTS },
    { scope: "agent", key: "atlas", label: "Atlas", period: "day", limit: { usd: 15, tokens: null }, spentUsd: 6.1, spentTokens: 0, alerts: DEFAULT_ALERTS },
    { scope: "agent", key: "pixel", label: "Pixel", period: "day", limit: { usd: 12, tokens: null }, spentUsd: 9.4, spentTokens: 0, alerts: DEFAULT_ALERTS },
    { scope: "agent", key: "iris", label: "Iris", period: "day", limit: { usd: null, tokens: null }, spentUsd: 3.2, spentTokens: 0, alerts: DEFAULT_ALERTS },
  ];
  return [company, ...projects, ...agents];
}

export interface WorkItem extends Work { id: string; label: string }
export const SAMPLE_WORK: WorkItem[] = [
  { id: "w1", label: "Nova · build SV-031 on SamVision", agent: "nova", project: "samvision", kind: "build", billable: true },
  { id: "w2", label: "Atlas · review SV-029 on SamVision", agent: "atlas", project: "samvision", kind: "review", billable: true },
  { id: "w3", label: "Pixel · UI test run on GYST", agent: "pixel", project: "gyst", kind: "ui_test", billable: true },
  { id: "w4", label: "Orion · health check on SamVision", agent: "orion", project: "samvision", kind: "health_check", billable: true },
  { id: "w5", label: "Orion · rollback rehearsal on GYST", agent: "orion", project: "gyst", kind: "rollback", billable: true },
];

// ---------------------------------------------------------------- approvals (D-032)
export type Tier = "low" | "standard" | "high";
export const TIER_LABEL: Record<Tier, string> = { low: "Low risk", standard: "Standard", high: "High risk" };
export const TIER_TONE: Record<Tier, string> = { low: "ok", standard: "info", high: "bad" };
export type ReqKind = "register_agent" | "activate_readonly" | "repo_access" | "policy_change" | "budget_override" | "raise_limit";
export interface Change { field: string; from: string; to: string }
export interface Req { id: string; kind: ReqKind; title: string; agent?: string; project?: string; requestedBy: string; at: number; expires: number; changes: Change[]; does: string[]; doesNot: string[]; override?: { scope: Scope; key: string; usd: number; hours: number }; rev: number }

/** The ceiling for a low-risk temporary override: at most a quarter of the limit, for at most 24 hours (proposed). */
export const LOW_OVERRIDE_SHARE = 0.25;
export const LOW_OVERRIDE_HOURS = 24;
export function tierOf(r: Pick<Req, "kind" | "override">, limitUsd?: number | null): Tier {
  switch (r.kind) {
    case "register_agent": return "low";
    case "activate_readonly": return "standard";
    case "budget_override": {
      const o = r.override;
      return o && limitUsd && o.usd <= limitUsd * LOW_OVERRIDE_SHARE && o.hours <= LOW_OVERRIDE_HOURS ? "low" : "high";
    }
    default: return "high";      // repository access, policy, production capabilities, permission widening, raising a hard limit
  }
}
/** Where a tier can be approved. In-Slack approval is step 2 of D-032 and is off. */
export const SLACK_STEP_2 = false;
export function approvableIn(tier: Tier, surface: "slack" | "screen"): boolean {
  return surface === "screen" ? true : SLACK_STEP_2 && tier === "low";
}
/** High tier: Developer Unlock and the typed ID. Everything else: the signed-in screen. */
export function canApprove(tier: Tier, ctx: { unlocked: boolean; typed: string; expected: string; expired: boolean }): boolean {
  if (ctx.expired) return false;
  return tier !== "high" || (ctx.unlocked && ctx.typed.trim() === ctx.expected);
}
/** A short, stable fingerprint of what is being approved (FNV-1a; a demo stand-in for the server's SHA-256). */
export function reqHash(r: Pick<Req, "kind" | "agent" | "project" | "changes" | "override" | "rev">): string {
  const s = JSON.stringify([r.kind, r.agent ?? "", r.project ?? "", r.changes, r.override ?? null, r.rev]);
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, "0");
}
export const confirmText = (r: Req) => (r.agent ? `agent:${r.agent}` : r.project ?? r.id);

const H = 3600_000;
export function seedRequests(now = Date.now()): Req[] {
  return [
    { id: "r-7f3a91", kind: "register_agent", title: "Register agent Mira", agent: "mira", project: "samvision", requestedBy: "claude", at: now - 0.4 * H, expires: now + 23 * H, rev: 1,
      changes: [{ field: "ID", from: "none", to: "agent:mira" }, { field: "Role", from: "none", to: "Implementation Agent" }, { field: "Model", from: "none", to: "claude-sonnet-5-5" }, { field: "Requested", from: "none", to: "repo.read allow · repo.push allow · prod.deploy approval" }],
      does: ["Writes Mira's identity record and configuration version 1."], doesNot: ["Issue a credential or actor token.", "Start Mira or grant any permission.", "Reserve anything beyond the ID."] },
    { id: "r-2c8d40", kind: "activate_readonly", title: "Activate Atlas on GYST, read-only", agent: "atlas", project: "gyst", requestedBy: "claude", at: now - 2 * H, expires: now + 22 * H, rev: 1,
      changes: [{ field: "GYST membership", from: "none", to: "Reviewer" }, { field: "Grants", from: "none", to: "repo.read allow" }],
      does: ["Lets Atlas read GYST's code to review it."], doesNot: ["Allow writes, pushes or pull requests.", "Touch production or personal data."] },
    { id: "r-b41e07", kind: "repo_access", title: "Let Pixel push branches to SamVisionAI", agent: "pixel", project: "samvision", requestedBy: "claude", at: now - 5 * H, expires: now + 19 * H, rev: 1,
      changes: [{ field: "Repository", from: "none", to: "JayDalool/SamVisionAI" }, { field: "repo.push", from: "deny", to: "allow (own feature branches)" }],
      does: ["Lets Pixel push its own feature branches for UI test fixes."], doesNot: ["Allow merging (hard ceiling: deny).", "Allow deploys or CI changes."] },
    { id: "r-0e93cc", kind: "policy_change", title: "GYST profile: allow merges without Jay", project: "gyst", requestedBy: "claude", at: now - 26 * H, expires: now - 2 * H, rev: 1,
      changes: [{ field: "merge", from: "owner", to: "low-risk" }],
      does: ["Would change policy/projects/gyst.toml through a PR for Jay."], doesNot: ["Apply without Jay merging the profile PR (D-007)."] },
  ];
}

// ---------------------------------------------------------------- shared demo state (every window)
export interface DecisionRec { decision: "approved" | "declined"; at: number; hash: string; via: "screen" | "screen + Developer Unlock" }
export interface Gov { scenario: Scenario; requests: Req[]; decisions: Record<string, DecisionRec>; overrides: Record<string, Override>; seq: number }
const isGov = (v: unknown): v is Gov => isRecord(v) && typeof v.scenario === "string" && SCENARIOS.some((s) => s.id === v.scenario)
  && Array.isArray(v.requests) && v.requests.every((r) => isRecord(r) && typeof r.id === "string" && typeof r.kind === "string" && Array.isArray(r.changes))
  && isRecord(v.decisions) && isRecord(v.overrides) && typeof v.seq === "number";
export const seedGov = (): Gov => ({ scenario: "agent", requests: seedRequests(), decisions: {}, overrides: {}, seq: 1 });
export const gov = new SharedStore<Gov>("gov", seedGov(), isGov);

export function setScenario(s: Scenario) { gov.set((g) => ({ ...g, scenario: s })); }

export function requestOverride(line: BudgetLine, usd: number, hours: number, now = Date.now()): Req {
  const n = gov.get().seq + 1;
  const id = `r-ov${n.toString(16).padStart(4, "0")}`;
  const req: Req = { id, kind: "budget_override", title: `Temporary override: ${line.label} +$${usd} for ${hours} h`, agent: line.scope === "agent" ? line.key : undefined,
    project: line.scope === "project" ? line.key : undefined, requestedBy: "jay", at: now, expires: now + 24 * H, rev: 1,
    override: { scope: line.scope, key: line.key, usd, hours },
    changes: [{ field: `${line.label} ${line.period === "day" ? "daily" : "monthly"} limit`, from: `$${line.limit.usd}`, to: `$${(line.limit.usd ?? 0) + usd} until it expires` }],
    does: ["Raises this limit for the stated time; held work resumes from its checkpoint, one task at a time."], doesNot: ["Change the configured limit.", "Affect any other budget."] };
  gov.set((g) => ({ ...g, seq: n, requests: [req, ...g.requests] }));
  return req;
}

/** Record Jay's decision against the request's current hash. An approved override takes effect. */
export function decide(id: string, decision: "approved" | "declined", via: DecisionRec["via"], now = Date.now()) {
  gov.set((g) => {
    const r = g.requests.find((x) => x.id === id);
    if (!r || g.decisions[id]) return g;
    const rec: DecisionRec = { decision, at: now, hash: reqHash(r), via };
    const overrides = decision === "approved" && r.override
      ? { ...g.overrides, [holdKey(r.override.scope, r.override.key)]: { usd: r.override.usd, until: now + r.override.hours * H, requestId: id } } : g.overrides;
    return { ...g, decisions: { ...g.decisions, [id]: rec }, overrides };
  });
}

/** Demo: the request changes after it was sent. Its hash changes, so a link opened earlier cannot approve the old one. */
export function amendRequest(id: string) {
  gov.set((g) => ({ ...g, requests: g.requests.map((r) => (r.id === id ? { ...r, rev: r.rev + 1, changes: [...r.changes, { field: "Amended", from: "—", to: `revision ${r.rev + 1}` }] } : r)) }));
}
