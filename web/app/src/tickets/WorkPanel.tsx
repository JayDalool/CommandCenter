// WORK — the ticket's pipeline at a glance: PLAN · BUILD · REVIEW · MERGE · VERIFY, the one
// owner action when a gate is open, and the durable state a new coordinator resumes from.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { href } from "../lib/router";
import type { TicketDetail, TicketWork } from "../api/types";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";
import { DetailRow } from "../components/ui";
import { useSelector } from "../lib/store";
import { openAgent } from "../lib/openAgent";

const MARK = { done: "✓", active: "●", blocked: "■", todo: "—" } as const;
const GATE_TEXT: Record<string, string> = { plan: "Plan needs your approval", merge: "Ready to merge",
  ui: "UI review needed", deploy: "Deploy needs your approval", failure: "Blocked" };

export function WorkPanel({ t }: { t: TicketDetail }) {
  const [w, setW] = useState<TicketWork | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const dev = useDevActive();
  const agents = useSelector(app.store, (d) => d.state?.agents);
  // Re-read whenever the ticket changes (every pipeline step touches updatedAt).
  useEffect(() => {
    let live = true;
    app.api.taskWork(t.key).then((x) => { if (live) { setW(x); setErr(null); } }, (e) => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [t.key, t.updatedAt]);
  if (err) return <section aria-label="Work"><div className="td-sec-title">Work</div><div className="muted mono-xs">{err}</div></section>;
  if (!w) return null;
  // A ticket work session (implementer/reviewer named after the ticket), never the project coordinator.
  const sessions = Object.values(w.roles).map((r) => r.session).filter(Boolean);
  const worker = agents?.find((a) => a.role !== "coordinator" && a.agent_name && sessions.includes(a.agent_name)) ?? null;

  const confirm = async (gate: string) => {
    if (!dev) { unlockDialogOpen(); return; }
    const r = await app.action(() => app.api.confirmGate(t.key, gate), `${t.key}: ${gate} confirmed`);
    if (r) setW(r as TicketWork);
  };
  const prUrl = t.prUrl ?? null;
  const action = (() => {
    switch (w.gate) {
      case "plan": return <button type="button" className="btn is-jay is-sm" onClick={() => void confirm("plan")}>Approve plan</button>;
      case "merge": return prUrl ? <a className="btn is-jay is-sm" href={prUrl} target="_blank" rel="noopener noreferrer">Open PR ↗</a> : null;
      case "ui": return <>
        <a className="btn is-jay is-sm" href={href("workspace", null, { project: t.project, ticket: t.key })}>Open Workspace</a>
        <button type="button" className="btn is-sm" onClick={() => void confirm("ui")}>UI is right</button></>;
      case "deploy": return <button type="button" className="btn is-jay is-sm" onClick={() => void confirm("deploy")}>Approve deploy</button>;
      case "failure": return <button type="button" className="btn is-jay is-sm" onClick={() => void confirm("failure")}>Resume</button>;
      default: return null;
    }
  })();

  return <section aria-label="Work">
    <div className="td-sec-title">Work</div>
    {worker && <div className="row" style={{ marginBottom: 6 }}>
      <button type="button" className="btn is-sm" onClick={() => openAgent(worker.id)}>Open work session</button>
      <span className="mono-xs muted">{worker.agent_name} · {worker.status}</span></div>}
    <ol className="pipe" aria-label="Pipeline">
      {w.stages.map((s) => <li key={s.stage} className={`pipe-step is-${s.state}`} aria-current={s.state === "active" ? "step" : undefined}>
        <span className="pipe-mark" aria-hidden>{MARK[s.state]}</span><span className="caps">{s.stage}</span>
        <span className="sr">{s.state}</span></li>)}
    </ol>
    {w.gate && <div className="pipe-gate" role="status">
      <b className="jay-t">{GATE_TEXT[w.gate]}</b>{w.gateReason && <span className="muted trunc"> · {w.gateReason}</span>}
      <span className="sl-fill" />{action}
    </div>}
    <dl>
      {w.plan.summary && <DetailRow label="Plan"><span className="trunc" title={w.plan.approach || w.plan.summary}>{w.plan.summary}
        {w.planState === "proposed" && <span className="label">proposed</span>}</span></DetailRow>}
      {(w.branch || w.worktree) && <DetailRow label="Branch"><span className="mono-xs trunc" title={w.worktree ?? ""}>{w.branch ?? "—"}</span></DetailRow>}
      {w.review.verdict && <DetailRow label="Review"><span className="mono-xs">{w.review.verdict === "APPROVE" ? "approved" : "changes requested"}
        {w.review.head ? ` at ${w.review.head.slice(0, 7)}` : ""}{w.review.cycles ? ` · cycle ${w.review.cycles}` : ""}</span></DetailRow>}
      {w.merge && <DetailRow label="Merged"><span className="mono-xs">{w.merge.pr}{w.merge.sha ? ` · ${w.merge.sha.slice(0, 7)}` : ""}</span></DetailRow>}
      {w.verification && <DetailRow label="Verified"><span className={`mono-xs ${w.verification.result === "pass" ? "ok-t" : "bad-t"}`}>
        {w.verification.result} · {w.verification.evidence}</span></DetailRow>}
      {w.blocked && <DetailRow label="Blocked"><span className="bad-t">{w.blocked.stage}: {w.blocked.reason}</span></DetailRow>}
      {w.handoff?.next && <DetailRow label="Next"><span className="trunc" title={w.handoff.done}>{w.handoff.next}</span></DetailRow>}
      {Object.keys(w.roles).length > 0 && <DetailRow label="Roles"><span className="mono-xs muted">
        {Object.entries(w.roles).map(([r, v]) => `${r}${v.model ? ` (${v.model})` : ""}`).join(" · ")}</span></DetailRow>}
      {w.findings.length > 0 && <DetailRow label="Findings"><span className="mono-xs muted">
        {w.findings.filter((f) => f.scope === "in").length} in scope · {w.findings.filter((f) => f.scope === "out").length} out of scope</span></DetailRow>}
    </dl>
  </section>;
}
