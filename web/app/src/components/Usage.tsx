// SETTINGS → USAGE (v2 Phase 1, PR 7): tokens the agents used, read from their own session logs on this machine, and
// an estimated cost at list prices. Not a bill: subscription plans are not charged per token. Budgets from project
// profiles are shown against this month; nothing is stopped when one is passed.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import type { UsageRow, UsageState } from "../api/types";
import { EmptyState, Panel } from "./ui";

export function tokens(n: number): string {
  return n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
}
export function usd(n: number): string {
  return n >= 100 ? `$${Math.round(n)}` : `$${n.toFixed(2)}`;
}

function Table({ rows, label }: { rows: UsageRow[]; label: string }) {
  if (!rows.length) return <p className="muted led-note">Nothing yet.</p>;
  return <div className="tbl-wrap"><table className="tbl"><thead><tr><th>{label}</th><th>replies</th><th>input</th><th>output</th>
    <th>cache read</th><th>cache write</th><th>est. cost</th></tr></thead><tbody>
    {rows.map((r) => <tr key={r.key}>
      <td className="mono">{r.key}</td><td>{r.replies}</td><td>{tokens(r.input)}</td><td>{tokens(r.output)}</td>
      <td>{tokens(r.cacheRead)}</td><td>{tokens(r.cacheWrite)}</td>
      <td title={r.unpriced ? `${r.unpriced} repl${r.unpriced === 1 ? "y" : "ies"} with no list price (counted in tokens only)` : undefined}>
        {usd(r.costUsd)}{r.unpriced ? "*" : ""}</td>
    </tr>)}</tbody></table></div>;
}

export function Usage() {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<UsageState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => app.api.usage(days).then((d) => { if (live) { setData(d); setErr(null); } })
      .catch((e) => { if (live) setErr((e as Error).message); });
    void load();
    const t = setInterval(() => void load(), 60_000);
    return () => { live = false; clearInterval(t); };
  }, [days]);
  if (err && !data) return <EmptyState title="Usage unavailable">{err}</EmptyState>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.available) return <EmptyState title="No usage metering">The task system is off, or metering is turned off in config.</EmptyState>;
  const t = data.total!;
  return <div className="stack">
    <Panel title={`Last ${data.days} days`}>
      <p className="text2 led-note">{data.note} Prices as of {data.pricesAsOf}.</p>
      <div className="au-pad"><div className="seg" role="group" aria-label="Window">
        {[1, 7, 14, 30].map((d) => <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)}>{d === 1 ? "Today" : `${d} days`}</button>)}
      </div></div>
      <p className="us-total"><b>{usd(t.costUsd)}</b> estimated · {tokens(t.input + t.output + t.cacheRead + t.cacheWrite)} tokens · {t.replies} model replies
        {t.unpriced ? <span className="muted"> · {t.unpriced} without a list price</span> : null}</p>
    </Panel>
    {!!data.budgets?.length && <Panel title="Budgets this month" count={data.budgets.length}>
      <ul className="mono-xs au-sum">{data.budgets.map((b) => <li key={b.project}>{b.project}: {usd(b.spentUsd)}{b.monthlyUsd != null ? ` of ${usd(b.monthlyUsd)}` : ""}
        {b.monthlyTokens != null ? ` · ${tokens(b.spentTokens)} of ${tokens(b.monthlyTokens)} tokens` : ""}
        {(b.monthlyUsd != null && b.spentUsd > b.monthlyUsd) || (b.monthlyTokens != null && b.spentTokens > b.monthlyTokens) ? <b className="ny-overdue"> · over (shown only)</b> : null}</li>)}</ul>
    </Panel>}
    <Panel title="By project"><Table rows={data.byProject ?? []} label="project" /></Panel>
    <Panel title="By model"><Table rows={data.byModel ?? []} label="model" /></Panel>
    <Panel title="Top tasks"><Table rows={data.byTicket ?? []} label="task" /></Panel>
    <Panel title="By day"><Table rows={data.byDay ?? []} label="day" /></Panel>
    <Panel title="By source"><p className="text2 led-note">"reported" is what agents said they used in their work steps.
      It is usually the same replies the logs already count, so it is shown here and not added to the totals.</p>
      <Table rows={data.bySource ?? []} label="source" /></Panel>
  </div>;
}
