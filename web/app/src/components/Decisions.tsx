// SETTINGS → DECISIONS — the Decision and Approval records, read-only (v2 Phase 1). Decisions are Jay's policy
// decisions and his answers to Claude's questions; append-only, a change supersedes. Approvals mirror today's gates:
// each is bound to what it approves (the reviewed head, the plan's hash, the deploy request). The gates still decide.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import type { ApprovalState, LedgerState } from "../api/types";
import { Panel, DetailRow, EmptyState } from "./ui";

const STATE: Record<ApprovalState, string> = { pending: "waiting for you", approved: "approved, not used yet",
  consumed: "approved and used", void: "void", rejected: "rejected" };

function day(at: number | null): string {   // a policy decision has a date, not a time: show it in UTC
  return at ? new Date(at * 1000).toLocaleDateString(undefined, { timeZone: "UTC", year: "numeric", month: "short", day: "numeric" }) : "—";
}

function when(at: number | null): string {
  return at ? new Date(at * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

export function Decisions() {
  const [data, setData] = useState<LedgerState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { app.api.decisions().then(setData).catch((e) => setErr((e as Error).message)); }, []);
  if (err) return <EmptyState title="Decisions unavailable">{err}</EmptyState>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.available) return <EmptyState title="No records">The task system is off.</EmptyState>;
  const total = Object.values(data.counts).reduce((a, n) => a + (n ?? 0), 0);
  const counts = Object.entries(data.counts).map(([s, n]) => `${n} ${STATE[s as ApprovalState] ?? s}`).join(" · ");
  return <div className="stack">
    <Panel title="Approvals" count={total} meta={<span className="mono-xs muted">{counts || "none yet"}</span>}>
      <p className="text2 led-note">One per gate, bound to exactly what it approves: a new PR head or a changed plan makes it void.
        Today's gates still decide; this is their record.</p>
      {data.approvals.length === 0 ? <p className="muted led-note">No approvals recorded yet.</p>
        : <div className="tbl-wrap"><table className="tbl"><thead><tr><th>ticket</th><th>gate</th><th>state</th><th>bound to</th>
          <th>asked</th><th>decided</th><th>note</th></tr></thead><tbody>
          {data.approvals.map((a) => <tr key={a.id}>
            <td className="key">{a.key ?? a.project}</td><td>{a.subject}</td>
            <td className={a.state === "pending" ? "warn-t" : a.state === "void" || a.state === "rejected" ? "muted" : ""}>
              {STATE[a.state]}{a.overdue ? " · overdue" : ""}</td>
            <td className="mono-xs" title={a.subjectHash}>{a.subjectHash.slice(0, 10)}</td>
            <td className="mono-xs">{when(a.requestedAt)}</td>
            <td className="mono-xs">{a.decidedBy ? `${a.decidedBy} via ${a.via ?? "?"} · ${when(a.decidedAt)}` : "—"}</td>
            <td className="muted">{a.voidReason ?? a.reason ?? ""}</td>
          </tr>)}</tbody></table></div>}
    </Panel>
    <Panel title="Decisions" count={data.decisions.length}>
      <dl className="pol-dl">
        {data.decisions.length === 0 && <DetailRow label="—">No decisions recorded yet.</DetailRow>}
        {data.decisions.map((d) => <DetailRow key={d.id} label={`${d.ref ?? d.key ?? d.project} · ${d.source === "policy" ? day(d.decidedAt) : when(d.decidedAt)}`}>
          <b>{d.question}</b>{!d.current && <span className="muted"> · superseded</span>}<br />{d.decision}
          <br /><span className="muted mono-xs">{d.decidedBy}{d.via ? ` via ${d.via}` : ""} · {d.source}</span>
        </DetailRow>)}
      </dl>
    </Panel>
  </div>;
}
