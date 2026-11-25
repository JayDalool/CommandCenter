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
import "./budgets.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { ApiError } from "../../api/client";
import type { BudgetLine, BudgetsState, BudgetWeek, BudgetWeekLine, UsageState } from "../../api/types";
import { tokens, usd } from "../../components/Usage";
import { devOr, unlockDialogOpen, useDevActive } from "../../components/DevMode";
import { Kpi, Pill, cx, plural } from "./ui";
import { amountCents, centsText, evenShares, rebalance, shareCents } from "./budgetShares";

/** on: the last good reading, with the error of a later read that failed, if one did. */
type Shadow = { s: "loading" } | { s: "off" } | { s: "failed"; error: string } | { s: "on"; data: BudgetsState; error?: string };

/** Both reads, again every minute. A failed read keeps what was last read and says it failed; a 404 means the shadow
 *  budgets are switched off, so it replaces them. */
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
        .catch((e) => {
          if (!live) return;
          const error = (e as Error).message;
          setShadow((was) => e instanceof ApiError && e.status === 404 ? { s: "off" }
            : was.s === "on" ? { s: "on", data: was.data, error } : { s: "failed", error });
        });
    };
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  /** A saved weekly budget replaces what was read, without waiting for the next minute. */
  const setWeek = (budgetWeek: BudgetWeek) => setUsage((u) => ({ ...(u ?? { available: false }), budgetWeek }));
  return { usage, usageErr, shadow, setWeek };
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
  const { usage, usageErr, shadow, setWeek } = useBudgets();
  const names = useProjectNames();
  const limits = usage?.budgets ?? [];
  const over = limits.filter((b) => (b.monthlyUsd != null && b.spentUsd > b.monthlyUsd)
    || (b.monthlyTokens != null && b.spentTokens > b.monthlyTokens)).length;
  const t = usage?.available ? usage.total : undefined;

  return <div className="hq-page hq-budgets">
    <header className="hq-hero"><div><h2>Budgets</h2>
      <p>Model spend against your limits, at list prices. Not a bill; nothing here stops work.</p></div></header>

    <section className="hq-kpis" aria-label="Summary">
      <Kpi label="Estimated spend" value={t ? usd(t.costUsd) : "—"} sub={t ? `last 30 days · ${plural(t.replies, "model reply", "model replies")}` : "metering off or not read yet"} />
      <Kpi label="Projects with a monthly limit" value={usage?.available ? limits.length : "—"} sub="from project profiles" />
      <Kpi label="Over a limit" value={usage?.available ? over : "—"} sub="this month, shown only" tone={over ? "bad" : undefined} />
      <Kpi label="Shadow budgets" value={shadow.s === "on" ? "On" : shadow.s === "off" ? "Not enabled" : shadow.s === "failed" ? "Unknown" : "—"}
        sub={shadow.s === "on" ? `${plural(shadow.data.wouldHold.length, "line")} would hold` : "company, project and agent limits"} />
    </section>

    {usage?.budgetWeek && <WeeklyBudget week={usage.budgetWeek} onSaved={setWeek} />}

    <div className="hq-office-grid">
      <section className="hq-panel" aria-labelledby="hq-bud-shadow">
        <header><h3 id="hq-bud-shadow">Company, project and agent budgets</h3>
          {shadow.s === "on" ? <Pill tone="info">Shadow: nothing is held</Pill> : shadow.s === "off" ? <Pill tone="idle">Not enabled</Pill> : null}</header>
        {shadow.s === "loading" && <p className="hq-empty">Loading…</p>}
        {shadow.s === "failed" && <p className="hq-note">Could not read the shadow budgets: {shadow.error}</p>}
        {shadow.s === "off" && <div className="hq-off-body">
          <p>Company, project and agent budgets (alerts at 50, 80 and 95 %, hold at 100 %) are built but off on this server.
            When on, they run in shadow first and hold nothing.</p>
          <p className="hq-note">Turned on by the onboarding groundwork switch in config.json, a separate approval of yours.</p>
        </div>}
        {shadow.s === "on" && <>
          {SCOPES.map(({ k, title }) => {
            const lines = shadow.data.lines.filter((l) => l.scope === k);
            return lines.length ? <div key={k} className="hq-bud-group"><h4>{title}</h4>
              <ul className="hq-bud-lines">{lines.map((l) => <ShadowLine key={`${l.scope}:${l.key}:${l.period}`} l={l}
                name={k === "company" ? "Whole company" : k === "project" ? names.get(l.key) ?? l.key : l.key} />)}</ul></div> : null;
          })}
          {!shadow.data.lines.length && <p className="hq-empty">No budget is set yet.</p>}
          {shadow.error && <p className="hq-note t-warn">Could not re-read the shadow budgets ({shadow.error}). Showing the last reading.</p>}
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

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const LEVEL_TONE: Record<number, string> = { 0: "ok", 50: "info", 80: "warn", 95: "warn", 100: "bad" };

/** One weekly line: spend against its limit, the alert levels marked, and the level reached. */
function WeekLine({ l, stale }: { l: BudgetWeekLine; stale: boolean }) {
  const none = l.pct == null;
  return <li className="hq-bud-line">
    <span className="hq-bud-name"><b className="hq-ellip" title={l.name}>{l.name}</b>
      <small>{l.scope === "account" ? "Whole budget" : `${l.share ?? 0}% share`}</small></span>
    {none ? <span className="hq-bud-bar is-none" aria-hidden /> : <Bar pct={l.pct ?? 0} tone={LEVEL_TONE[l.level]} marks={[50, 80, 95]} />}
    <span className="hq-bud-fig">{none ? "no budget (0% share)" : `${usd(l.spentUsd)} of ${usd(l.limitUsd)} · ${Math.round(l.pct ?? 0)}%`}</span>
    <Pill tone={stale ? "idle" : LEVEL_TONE[l.level]}>{none ? "No budget" : stale ? "Meter not read" : l.level >= 100 ? "Reached 100%" : l.level ? `Alert ${l.level}%` : "Within budget"}</Pill>
  </li>;
}

/** The weekly budget (CC-064 a): one estimated-dollar amount for all apps and a slider per app for its share. The
 *  sliders always add up to 100: moving one moves the others in proportion, by keyboard too. Saving is Jay's and needs
 *  Developer Unlock (ccd checks both). Nothing here holds or stops work; it sets the alerts at 50, 80, 95 and 100 %. */
function WeeklyBudget({ week, onSaved }: { week: BudgetWeek; onSaved: (w: BudgetWeek) => void }) {
  const active = useDevActive();
  const apps = week.apps ?? [];
  const keys = apps.map((a) => a.key);
  const reset = week.settings?.week ?? week.defaultWeek ?? { weekday: 1, hour: 0, tz: "America/Winnipeg" };
  const saved = week.settings;
  // Every field starts from what is saved and follows a newer save (another tab, the CTO later), unless Jay is editing.
  const base = useMemo(() => ({ amount: saved?.weekUsd ?? "", shares: { ...evenShares(keys), ...(saved?.shares ?? {}) },
    weekday: reset.weekday, hour: reset.hour }), [week.changedAt, keys.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps
  const [form, setForm] = useState(base);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ tone: string; text: string } | null>(null);
  useEffect(() => { if (!dirty) setForm(base); }, [base, dirty]);
  const edit = (patch: Partial<typeof form>) => { setForm((f) => ({ ...f, ...patch })); setDirty(true); setNote(null); };
  const cents = amountCents(form.amount);
  const total = Object.values(form.shares).reduce((n, x) => n + x, 0);
  const save = () => {
    if (cents == null || total !== 100) return;
    if (!devOr(save)) return;
    setBusy(true); setNote(null);
    app.api.saveBudgetWeek({ weekUsd: centsText(cents), shares: form.shares, week: { weekday: form.weekday, hour: form.hour, tz: reset.tz } })
      .then((w) => { onSaved(w); setDirty(false); setNote({ tone: "ok", text: "Saved. Alerts follow this budget from the next meter reading." }); })
      .catch((e: unknown) => setNote({ tone: "bad", text: e instanceof Error ? e.message : String(e) }))
      .finally(() => setBusy(false));
  };
  const lines = week.lines;
  return <section className="hq-panel hq-bud-week" aria-labelledby="hq-bud-week">
    <header><h3 id="hq-bud-week">Weekly budget</h3><Pill tone="info" title="List-price estimate of the usage ccd can see on this server">Estimate · not your bill</Pill></header>
    <p className="hq-note">{week.enabled
      ? "One estimated amount for all apps, split by share. You get a Messages alert at 50, 80, 95 and 100 % of each line. Nothing is held or stopped."
      : "No weekly budget is set, so there are no alerts. Set an amount and the shares below. Nothing is held or stopped."}</p>
    {week.enabled && <>
      <ul className="hq-bud-lines">{lines.map((l) => <WeekLine key={`${l.scope}:${l.key}`} l={l} stale={week.stale} />)}</ul>
      {week.stale && <p className="hq-note t-warn">Meter not read in the last {Math.round(week.meter.staleAfterSeconds / 60)} minutes: spend is
        not known, so no alert is sent until it is read.</p>}
    </>}
    <form className="hq-bud-form" onSubmit={(e) => { e.preventDefault(); save(); }} aria-label="Weekly budget settings">
      <div className="hq-bud-fields">
        <label className="hq-bud-field"><span>Weekly amount (US dollars, estimate)</span>
          <input type="text" inputMode="decimal" autoComplete="off" value={form.amount} placeholder="for example 250.00"
            aria-invalid={form.amount !== "" && cents == null} onChange={(e) => edit({ amount: e.target.value })} /></label>
        <label className="hq-bud-field"><span>Week starts on</span>
          <select value={form.weekday} onChange={(e) => edit({ weekday: Number(e.target.value) })}>
            {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>
        <label className="hq-bud-field"><span>At</span>
          <select value={form.hour} onChange={(e) => edit({ hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}</select></label>
      </div>
      <p className="hq-note">Set these to match when your Claude plan's week resets ({reset.tz.replace(/_/g, " ")} time).</p>
      <fieldset className="hq-bud-shares"><legend>Each app's share of the week</legend>
        {apps.map((a) => {
          const pct = form.shares[a.key] ?? 0;
          return <div key={a.key} className="hq-bud-share">
            <label htmlFor={`bud-share-${a.key}`}>{a.name}</label>
            <input id={`bud-share-${a.key}`} type="range" min={0} max={100} step={1} value={pct}
              aria-valuetext={`${pct} percent`} onChange={(e) => edit({ shares: rebalance(form.shares, a.key, Number(e.target.value)) })} />
            <output htmlFor={`bud-share-${a.key}`}>{pct}%{cents != null ? ` · about ${usd(shareCents(cents, pct) / 100)}` : ""}</output>
          </div>;
        })}
        <p className={cx("hq-bud-total", total !== 100 && "t-bad")} role="status">Shares add up to {total}%.</p>
      </fieldset>
      <div className="hq-bud-actions">
        <button type="submit" className="hq-btn" disabled={busy || cents == null || total !== 100 || !dirty}>{busy ? "Saving…" : "Save budget"}</button>
        {!active && <span className="hq-note">Saving needs Developer Unlock. <button type="button" className="hq-link" onClick={unlockDialogOpen}>Unlock…</button></span>}
        {form.amount !== "" && cents == null && <span className="hq-note t-bad">Enter dollars and cents, for example 250 or 250.50.</span>}
        {note && <span className={cx("hq-note", `t-${note.tone}`)} role="status">{note.text}</span>}
      </div>
    </form>
  </section>;
}

/** Project keys to names, from the live state and the task system. */
function useProjectNames(): Map<string, string> {
  const o = useSelector(app.store, (d) => Object.fromEntries([...(d.state?.projects ?? []).map((p) => [p.key, p.name]),
    ...d.taskProjects.map((p) => [p.key, p.name])]) as Record<string, string>, (a, b) => JSON.stringify(a) === JSON.stringify(b));
  return useMemo(() => new Map(Object.entries(o)), [o]);
}
