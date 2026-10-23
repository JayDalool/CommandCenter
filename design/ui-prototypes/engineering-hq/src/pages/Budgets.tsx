// BUDGETS (D-033) — agent, project and company budgets with alerts before the limit. At a hard limit only new
// billable work in that scope waits; running work checkpoints; one agent over its limit never stops its project;
// safety work is never held. MOCK DATA: the server's shadow report (GET /api/onboarding/budgets) holds nothing yet.
import { useState } from "react";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Pill, ProjIcon, cx } from "../components/ui";
import { Field, Modal, Money, Seg } from "../components/form";
import { PopButton } from "../windows/Detachable";
import { notify } from "../windows/manager";
import { useStore } from "../lib/store";
import { go } from "../lib/router";
import { AGENTS } from "../data/seed";
import {
  LOW_OVERRIDE_HOURS, LOW_OVERRIDE_SHARE, SAFETY_KINDS, SAFETY_LABEL, SAMPLE_WORK, SCENARIOS, TIER_LABEL, TIER_TONE, assess, budgetLines,
  effectiveLimit, gov, holdKey, requestOverride, setScenario, tierOf, wouldStart, type BudgetLine,
} from "../data/governance";

const ELAPSED = { month: 0.72, day: 0.58 };
const money = (n: number) => `$${n >= 100 ? Math.round(n).toLocaleString("en-US") : n.toFixed(2)}`;
const tokens = (n: number) => `${(n / 1_000_000).toFixed(1)}M tokens`;

export interface LineState { line: BudgetLine; usd: number | null; tokens: number | null; a: ReturnType<typeof assess>; overridden: boolean }

export function useBudgetState(now = Date.now()) {
  const g = useStore(gov);
  const lines: LineState[] = budgetLines(g.scenario).map((line) => {
    const o = g.overrides[holdKey(line.scope, line.key)];
    const lim = effectiveLimit(line.limit, o, now);
    return { line, usd: lim.usd, tokens: lim.tokens, a: assess(line.spentUsd, line.spentTokens, lim, line.alerts, ELAPSED[line.period]), overridden: lim.usd !== line.limit.usd };
  });
  const holds = new Set(lines.filter((l) => l.a.state === "hold").map((l) => holdKey(l.line.scope, l.line.key)));
  return { g, lines, holds };
}

function StatePill({ s }: { s: LineState }) {
  const { state, threshold } = s.a;
  if (state === "none") return <Pill>No limit</Pill>;
  if (state === "hold") return <Pill tone="bad" dot>Held</Pill>;
  if (state === "alert") return <Pill tone="warn" dot>Alert · {threshold}%</Pill>;
  return <Pill tone="ok" dot>{s.a.onCourseToHold ? "On course to limit" : "Within budget"}</Pill>;
}

function Bar({ s }: { s: LineState }) {
  const pct = Math.min(100, s.a.pct ?? 0);
  const tone = s.a.state === "hold" ? "bad" : s.a.state === "alert" ? "warn" : "ok";
  return <div className={cx("bud-bar", `t-${tone}`)} role="meter" aria-label={`${s.line.label} spend`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(s.a.pct ?? 0)}>
    <i style={{ width: `${pct}%` }} />{s.line.alerts.map((a) => <b key={a} style={{ left: `${a}%` }} title={`Alert at ${a}%`} />)}
  </div>;
}

function Row({ s, onOverride }: { s: LineState; onOverride?: (l: BudgetLine) => void }) {
  const l = s.line;
  const who = l.scope === "agent" ? <Avatar id={l.key} size={30} /> : l.scope === "project" ? <ProjIcon k={l.key} size={30} /> : <span className="bud-co"><Icon name="cube" size={17} /></span>;
  const spent = l.limit.tokens != null && l.spentTokens ? `${money(l.spentUsd)} · ${tokens(l.spentTokens)}` : money(l.spentUsd);
  const limit = [s.usd != null ? money(s.usd) : null, s.tokens != null ? tokens(s.tokens) : null].filter(Boolean).join(" or ");
  return <li className={cx("bud-row", s.a.state === "hold" && "is-held")} data-testid={`budget-${l.scope}-${l.key}`}>
    {who}
    <div className="bud-main">
      <div className="bud-top"><b>{l.label}</b><small className="muted">{l.period === "day" ? "today" : "this month"}</small><span className="sp" /><StatePill s={s} /></div>
      {s.a.state === "none" ? <p className="muted small">No limit set. Spend is still metered: {money(l.spentUsd)}.</p> : <>
        <Bar s={s} />
        <div className="bud-meta"><span>{spent} of {limit}</span>{s.overridden && <Pill tone="violet">Override active</Pill>}{l.note && <small className="muted">{l.note}</small>}</div>
      </>}
      {s.a.state === "hold" && <p className="bud-held"><Icon name="clock" size={14} /><span>New billable work for {l.scope === "company" ? "every project" : l.label} waits. Work in progress finishes its current step and checkpoints.</span>
        {onOverride && <button type="button" className="btn btn-sm" onClick={() => onOverride(l)}>Request override…</button>}</p>}
    </div>
  </li>;
}

function OverrideDialog({ line, onClose }: { line: BudgetLine; onClose: () => void }) {
  const [usd, setUsd] = useState(Math.max(1, Math.round((line.limit.usd ?? 0) * 0.2)));
  const [hours, setHours] = useState<"4" | "24" | "72">("24");
  const ok = Number.isFinite(usd) && usd > 0;
  const tier = tierOf({ kind: "budget_override", override: { scope: line.scope, key: line.key, usd: ok ? usd : 0, hours: Number(hours) } }, line.limit.usd);
  return <Modal title={`Temporary override · ${line.label}`} onClose={onClose}
    footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn-primary" disabled={!ok} onClick={() => {
        const r = requestOverride(line, usd, Number(hours));
        notify(`Override requested. Approve it in Approvals (${TIER_LABEL[tier]}).`, "ok", { label: "Open", run: () => go("approvals", r.id) });
        onClose();
      }}>Request override</button></>}>
    <p className="muted">An override adds to the limit until it expires, then ends by itself. It never changes the configured limit or any other budget.</p>
    <div className="ds-form">
      <Field label="Extra amount">{(id) => <Money id={id} v={usd} onChange={setUsd} label="Extra amount in dollars" />}</Field>
      <Field label="Expires after">{() => <Seg label="Expires after" value={hours} onChange={setHours} options={[{ id: "4", label: "4 h" }, { id: "24", label: "24 h" }, { id: "72", label: "72 h" }]} />}</Field>
    </div>
    <div className={cx("tier-note", `t-${TIER_TONE[tier]}`)} data-testid="override-tier"><Pill tone={TIER_TONE[tier]} dot>{TIER_LABEL[tier]}</Pill>
      <span>{tier === "low" ? `Within the low-risk ceiling (up to ${LOW_OVERRIDE_SHARE * 100}% of the limit for up to ${LOW_OVERRIDE_HOURS} h): approve from the secure link; later also inside Slack.`
        : "Above the low-risk ceiling: approve in CommandCenter with Developer Unlock and a typed confirmation."}</span></div>
  </Modal>;
}

export function Budgets() {
  const { g, lines, holds } = useBudgetState();
  const [over, setOver] = useState<BudgetLine | null>(null);
  const by = (scope: string) => lines.filter((l) => l.line.scope === scope);
  const sc = SCENARIOS.find((s) => s.id === g.scenario)!;
  return <div className="page page-budgets">
    <div className="page-head"><div><h1>Budgets</h1><p>Alerts before each limit. At a hard limit, only new billable work in that scope waits, and one agent over its limit never stops its project.</p></div>
      <div className="row-gap"><Demo /><PopButton id="page:budgets" /></div></div>
    <div className="shadow-note" role="note"><Icon name="info" size={18} /><div><b>Shadow mode: nothing is held yet</b>
      <p>ccd reports where a hold would apply (budget report, D-033). Holding work waits for your approval after Phase 2. Spend is the usage meter’s estimate at list prices; Codex counts in tokens.</p></div></div>
    <div className="bud-scn"><span className="muted small">Demo scenario</span>
      <Seg label="Demo scenario" value={g.scenario} onChange={setScenario} options={SCENARIOS.map((s) => ({ id: s.id, label: s.label, title: s.hint }))} />
      <small className="muted">{sc.hint}</small></div>
    <div className="bud-grid">
      <section className="panel pad bud-col" aria-label="Company and project budgets">
        <h2><Icon name="cube" size={18} /> Company</h2><ul className="bud-list">{by("company").map((s) => <Row key={s.line.key} s={s} onOverride={setOver} />)}</ul>
        <h2><Icon name="layers" size={18} /> Projects</h2><ul className="bud-list">{by("project").map((s) => <Row key={s.line.key} s={s} onOverride={setOver} />)}</ul>
      </section>
      <section className="panel pad bud-col" aria-label="Agent budgets">
        <h2><Icon name="users" size={18} /> Agents</h2><ul className="bud-list">{by("agent").map((s) => <Row key={s.line.key} s={s} onOverride={setOver} />)}</ul>
      </section>
      <section className="panel pad bud-col" aria-label="Would new work start">
        <h2><Icon name="target" size={18} /> Would new work start?</h2>
        <ul className="bud-work">{SAMPLE_WORK.map((w) => { const v = wouldStart(w, holds); const a = AGENTS.find((x) => x.id === w.agent);
          return <li key={w.id} className={cx(!v.start && "is-held")} data-testid={`work-${w.id}`}>{a && <Avatar id={a.id} size={24} />}<span className="bud-wt"><b>{w.label}</b><small className="muted">{v.reason}</small></span>
            {v.start ? <Pill tone="ok" dot>Starts</Pill> : <Pill tone="warn" dot>Waits</Pill>}</li>; })}</ul>
        <h2><Icon name="shield" size={18} /> Never held by a budget</h2>
        <div className="chips">{SAFETY_KINDS.map((k) => <span key={k} className="chip">{SAFETY_LABEL[k]}</span>)}</div>
        <p className="muted small">The engine tags safety work by what it does; an agent cannot label its own work as safety. Its spend still shows on its own line. A budget hold is never a safety event: it does not change a project’s mode or open an incident.</p>
        <h2><Icon name="list" size={18} /> At the hard limit</h2>
        <ol className="bud-steps"><li>New billable work in that scope stops being scheduled.</li><li>Work in progress finishes its step and checkpoints; deploys, migrations, rollbacks and pushes already under way finish.</li>
          <li>You and the project’s lead are notified (Needs You; Slack once approved).</li><li>You raise the limit or grant a temporary override.</li><li>Held work resumes from its checkpoints, one task at a time.</li></ol>
      </section>
    </div>
    {over && <OverrideDialog line={over} onClose={() => setOver(null)} />}
  </div>;
}
