// Budgets (roadmap P4.1): model spend against limits, read-only. Two sources, both the server's own:
// - GET /api/usage?days=30: spend estimated at list prices, and the monthly limits project profiles set (Classic's
//   Settings › Usage shows the same). Shown whenever metering is on.
// - GET /api/onboarding/budgets: D-033's budgets in shadow (company, project and agent; day and month) with their alert
//   levels. Shadow means nothing is held or stopped, and the page says so on every line. The route answers 404 while
//   the onboarding groundwork is off, and the page says Not enabled.
import { useEffect, useMemo, useState } from "react";
import "./office.css";
import "./decisions.css";
import "./governance.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { ApiError } from "../../api/client";
import type { BudgetLine, BudgetsState, UsageState } from "../../api/types";
import { tokens, usd } from "../../components/Usage";
import { Kpi, Pill, cx, plural } from "./ui";

type Shadow = { s: "loading" } | { s: "off" } | { s: "failed"; error: string } | { s: "on"; data: BudgetsState };

/** Both reads, again every minute. A failure keeps what was last read. */
function useBudgets() {
  const [usage, setUsage] = useState<UsageState | null>(null);
  const [usageErr, setUsageErr] = useState<string | null>(null);
  const [shadow, setShadow] = useState<Shadow>({ s: "loading" });
  useEffect(() => {
    let live = true;
    const load = () => {
      app.api.usage(30).then((d) => { if (live) { setUsage(d); setUsageErr(null); } })
        .catch((e) => { if (live) setUsageErr((e as Error).message); });
      app.api.budgets().then((d) => { if (live) setShadow({ s: "on", data: d }); })
        .catch((e) => { if (live) setShadow(e instanceof ApiError && e.status === 404 ? { s: "off" } : { s: "failed", error: (e as Error).message }); });
    };
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  return { usage, usageErr, shadow };
}

/** Spend as a share of a limit, with the alert levels marked. Past 100 % the bar stays full. */
function Bar({ pct, tone, marks = [] }: { pct: number; tone: string; marks?: number[] }) {
  return <span className={`hq-bud-bar t-${tone}`} aria-hidden>
    <i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    {marks.filter((m) => m > 0 && m < 100).map((m) => <b key={m} style={{ left: `${m}%` }} />)}</span>;
}

const STATE: Record<BudgetLine["state"], [string, string]> = {
  none: ["No limit", "idle"], ok: ["Within limit", "ok"], alert: ["Alert", "warn"], unknown: ["Unknown", "idle"], hold: ["Would hold", "bad"],
};

function ShadowLine({ l, name }: { l: BudgetLine; name: string }) {
  const [label, tone] = STATE[l.state];
  const limit = l.limitUsd != null ? usd(l.limitUsd) : l.limitTokens != null ? `${tokens(l.limitTokens)} tokens` : "no limit";
  const spent = l.limitUsd == null && l.limitTokens != null ? `${tokens(l.spentTokens)} tokens` : usd(l.assessedUsd);
  return <li className="hq-bud-line">
    <span className="hq-bud-name"><b className="hq-ellip" title={name}>{name}</b><small>{l.period === "day" ? "Today" : "This month"}</small></span>
    {l.pct != null ? <Bar pct={l.pct} tone={tone} marks={l.alerts} /> : <span className="hq-bud-bar is-none" aria-hidden />}
    <span className="hq-bud-fig">{spent} of {limit}{l.pct != null ? ` · ${Math.round(l.pct)}%` : ""}</span>
    <Pill tone={tone} title={l.holdReason === "stale-meter" ? "No fresh meter reading: spend is unknown" : undefined}>
      {l.state === "alert" && l.threshold != null ? `Alert ${l.threshold}%` : label}</Pill>
    {(l.onCourseToHold || l.unpricedReplies > 0) && <small className="hq-bud-flags">
      {l.onCourseToHold && <span className="t-warn">On course to reach the limit</span>}
      {l.unpricedReplies > 0 && <span>{plural(l.unpricedReplies, "reply", "replies")} with no list price, counted at the highest</span>}
    </small>}
  </li>;
}

const SCOPES: { k: BudgetLine["scope"]; title: string }[] = [
  { k: "company", title: "Company" }, { k: "project", title: "Projects" }, { k: "agent", title: "Agents" },
];

export function Budgets() {
  const { usage, usageErr, shadow } = useBudgets();
  const names = useProjectNames();
  const limits = usage?.budgets ?? [];
  const over = limits.filter((b) => (b.monthlyUsd != null && b.spentUsd > b.monthlyUsd)
    || (b.monthlyTokens != null && b.spentTokens > b.monthlyTokens)).length;
  const t = usage?.available ? usage.total : undefined;

  return <div className="hq-page hq-budgets">
    <header className="hq-hero"><div><h2>Budgets</h2>
      <p>Model spend against the limits you set, estimated at list prices. Not a bill, and nothing here stops work.</p></div></header>

    <section className="hq-kpis" aria-label="Summary">
      <Kpi label="Estimated spend" value={t ? usd(t.costUsd) : "—"} sub={t ? `last 30 days · ${plural(t.replies, "model reply", "model replies")}` : "metering off or not read yet"} />
      <Kpi label="Projects with a monthly limit" value={usage?.available ? limits.length : "—"} sub="from project profiles" />
      <Kpi label="Over a limit" value={usage?.available ? over : "—"} sub="this month, shown only" tone={over ? "bad" : undefined} />
      <Kpi label="Shadow budgets" value={shadow.s === "on" ? "On" : shadow.s === "off" ? "Not enabled" : shadow.s === "failed" ? "Unknown" : "—"}
        sub={shadow.s === "on" ? `${plural(shadow.data.wouldHold.length, "line")} would hold` : "company, project and agent limits"} />
    </section>

    <div className="hq-office-grid">
      <section className="hq-panel" aria-labelledby="hq-bud-shadow">
        <header><h3 id="hq-bud-shadow">Company, project and agent budgets</h3>
          {shadow.s === "on" ? <Pill tone="info">Shadow: nothing is held</Pill> : shadow.s === "off" ? <Pill tone="idle">Not enabled</Pill> : null}</header>
        {shadow.s === "loading" && <p className="hq-empty">Loading…</p>}
        {shadow.s === "failed" && <p className="hq-note">Could not read the shadow budgets: {shadow.error}</p>}
        {shadow.s === "off" && <div className="hq-off-body">
          <p>Budgets per company, project and agent, with alerts at 50, 80 and 95 % and a hold at 100 %, are built but switched off on
            this server. They run in shadow first: they show what would be held and hold nothing.</p>
          <p className="hq-note">They come on with the onboarding groundwork switch in the server's config.json, which is a separate
            approval of yours. The project limits on the right already apply as shown-only figures.</p>
        </div>}
        {shadow.s === "on" && <>
          {SCOPES.map(({ k, title }) => {
            const lines = shadow.data.lines.filter((l) => l.scope === k);
            return lines.length ? <div key={k} className="hq-bud-group"><h4>{title}</h4>
              <ul className="hq-bud-lines">{lines.map((l) => <ShadowLine key={`${l.scope}:${l.key}:${l.period}`} l={l}
                name={k === "company" ? "Whole company" : k === "project" ? names.get(l.key) ?? l.key : l.key} />)}</ul></div> : null;
          })}
          {!shadow.data.lines.length && <p className="hq-empty">No budget is set yet.</p>}
          {shadow.data.meter.stale && <p className="hq-note t-warn">No meter reading in the last {Math.round(shadow.data.meter.staleAfterSeconds / 60)} minutes:
            spend is Unknown, and lines at 80 % or more would hold.</p>}
          {!!shadow.data.dataAlerts.length && <ul className="hq-bud-alerts">{shadow.data.dataAlerts.map((a) =>
            <li key={a.kind}><b>{a.kind.replace(/-/g, " ")}</b>: {a.detail}</li>)}</ul>}
        </>}
      </section>

      <div className="hq-office-side">
        <section className="hq-panel" aria-labelledby="hq-bud-limits">
          <header><h3 id="hq-bud-limits">Project limits this month <small>{limits.length}</small></h3></header>
          {usageErr && !usage && <p className="hq-note">Could not read usage: {usageErr}</p>}
          {usage && !usage.available && <p className="hq-empty">Metering is off, or the task system is off.</p>}
          {usage?.available && (limits.length ? <ul className="hq-bud-lines">{limits.map((b) => {
            const pct = b.monthlyUsd ? 100 * b.spentUsd / b.monthlyUsd : b.monthlyTokens ? 100 * b.spentTokens / b.monthlyTokens : 0;
            const tone = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "ok";
            return <li key={b.project} className="hq-bud-line is-compact">
              <span className="hq-bud-name"><b className="hq-ellip">{names.get(b.project) ?? b.project}</b></span>
              <Bar pct={pct} tone={tone} />
              <span className={cx("hq-bud-fig", pct >= 100 && "t-bad")}>
                {b.monthlyUsd != null ? `${usd(b.spentUsd)} of ${usd(b.monthlyUsd)}` : `${tokens(b.spentTokens)} of ${tokens(b.monthlyTokens ?? 0)} tokens`}
                {pct >= 100 ? " · over" : ""}</span>
            </li>;
          })}</ul> : <p className="hq-empty">No project profile sets a monthly limit.</p>)}
          {usage?.available && <p className="hq-note">Estimated from the agents' own session logs on this machine. Subscription plans
            are not charged per token. Prices as of {usage.pricesAsOf}.</p>}
        </section>
      </div>
    </div>
  </div>;
}

/** Project keys to names, from the live state and the task system. */
function useProjectNames(): Map<string, string> {
  const o = useSelector(app.store, (d) => Object.fromEntries([...(d.state?.projects ?? []).map((p) => [p.key, p.name]),
    ...d.taskProjects.map((p) => [p.key, p.name])]) as Record<string, string>, (a, b) => JSON.stringify(a) === JSON.stringify(b));
  return useMemo(() => new Map(Object.entries(o)), [o]);
}
