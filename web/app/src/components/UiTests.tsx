// UI TESTS — on request only. Per project: start a run (the coordinator tests the UI merged since its last run
// with Playwright, keeps the tests, reports findings — skills/ui-test/SKILL.md), see the latest report, and decide
// each finding: Fix it (a ui-finding task enters the pipeline) or Skip. While the fix mode is "ask" (the first
// weeks), nothing is fixed without Jay's Fix it.
import { useCallback, useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { byProjectOrder, initials, pjVar, taskHref } from "../lib/control";
import type { UiRun, UiTestsState } from "../api/types";
import { Dialog } from "./Dialog";
import { devOr, useDevActive } from "./DevMode";

const when = (run: string) => { const [y, m, d, hm] = run.split("-"); return `${y}-${m}-${d} ${hm.slice(0, 2)}:${hm.slice(2)}`; };
const counts = (r: UiRun) => {
  const s = r.summary, open = r.findings.filter((f) => !f.decision);
  return `${s.features ?? "?"} features · ${s.passed ?? 0} passed · ${s.failed ?? 0} failed · ${r.findings.length} finding${r.findings.length === 1 ? "" : "s"}`
    + (open.length ? ` (${open.length} to decide)` : "");
};

export function UiTestsButton({ className = "btn" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className={className} onClick={() => setOpen(true)}
      title="Test the UI each project merged since its last run, on request">UI tests</button>
    {open && <UiTestsDialog onClose={() => setOpen(false)} />}
  </>;
}

export function UiTestsDialog({ onClose }: { onClose: () => void }) {
  const dev = useDevActive();
  const taskProjects = useSelector(app.store, (d) => d.taskProjects);
  const [st, setSt] = useState<UiTestsState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sent, setSent] = useState<Record<string, string>>({});
  const [report, setReport] = useState<string | null>(null);
  const load = useCallback(() => { app.api.uiTests().then(setSt).catch((e) => app.toast((e as Error).message, "bad")); }, []);
  useEffect(load, [load]);
  const rows = byProjectOrder(taskProjects).filter((p) => st?.projects[p.key]);

  const start = async (k: string) => {
    if (!devOr(() => void start(k))) return;
    setBusy(k);
    try { const r = await app.api.uiTest(k); setSent((m) => ({ ...m, [k]: `${r.coordinator} is testing` })); }
    catch (e) { setSent((m) => ({ ...m, [k]: (e as Error).message })); }
    finally { setBusy(null); }
  };

  if (report) {
    const name = taskProjects.find((p) => p.key === report)?.name ?? report;
    return <UiReport project={report} name={name} run={st!.projects[report].latest!} onBack={() => { setReport(null); load(); }}
      onClose={onClose} onChanged={load} />;
  }
  return <Dialog title="UI tests" onClose={onClose}>
    <p className="text2">On request only. Each project's Claude tests the UI it merged since its last run with Playwright, keeps the
      tests in the repo, and reports what it finds. <b>You decide every finding</b>: Fix it puts a task in the pipeline, Skip records it.
      Nothing is deployed.</p>
    <div className="tc-list">
      {rows.map((p) => {
        const d = st!.projects[p.key];
        return <div key={p.key} className="tc-row" style={pjVar(p.key)}>
          <span className="pj-badge is-sm" aria-hidden>{initials(p.prefix, p.name)}</span>
          <span className="tc-name"><b>{p.name}</b>
            <span className="mono-xs muted">{d.paused ? `Paused — ${d.paused}` : sent[p.key]
              ?? (d.latest ? `Last run ${when(d.latest.run)}${d.latest.status === "working" ? " · still running" : ""} · ${counts(d.latest)}` : "No run yet")}</span></span>
          <span className="row" style={{ gap: 4 }}>
            {d.latest && <button type="button" className="btn is-sm is-quiet" onClick={() => setReport(p.key)}>Report</button>}
            <button type="button" className="btn is-sm" disabled={busy !== null || !!d.paused} onClick={() => void start(p.key)}>
              {busy === p.key ? "Sending…" : "Run UI tests"}</button>
          </span>
        </div>;
      })}
    </div>
    <div className="row" style={{ marginTop: 14 }}>
      <button type="button" className="btn is-quiet" onClick={onClose}>Close</button>
      {!dev && <span className="mono-xs muted">Running and deciding need Developer Mode.</span>}
    </div>
  </Dialog>;
}

function UiReport({ project, name, run, onBack, onClose, onChanged }: {
  project: string; name: string; run: UiRun; onBack: () => void; onClose: () => void; onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [findings, setFindings] = useState(run.findings);
  const decide = async (id: string, decision: "fix" | "skip") => {
    if (!devOr(() => void decide(id, decision))) return;
    setBusy(id);
    try {
      const r = await app.api.uiDecide(project, run.run, id, decision);
      setFindings((fs) => fs.map((f) => (f.id === id ? { ...f, decision: { decision, ticket: r.ticket, at: Date.now() / 1000 } } : f)));
      app.toast(decision === "fix" ? `${r.ticket} created — it goes through the pipeline` : `${id} skipped`);
      onChanged();
    } catch (e) { app.toast((e as Error).message, "bad"); }
    finally { setBusy(null); }
  };
  return <Dialog title={`${name} · UI tests ${when(run.run)}`} onClose={onClose}>
    <p className="mono-xs muted">{run.status === "working" ? "Still running · " : ""}{counts({ ...run, findings })}</p>
    {findings.length ? <ol className="ui-findings" aria-label="Findings">
      {findings.map((f) => <li key={f.id} className={`ui-f is-${f.severity}`}>
        <div className="row"><span className={`ui-sev is-${f.severity}`}>{f.severity}</span><b className="trunc">{f.title}</b>
          <span className="mono-xs muted">{f.id}{f.feature ? ` · ${f.feature}` : ""}</span></div>
        {f.steps.length > 0 && <ol className="ui-steps">{f.steps.map((x, i) => <li key={i}>{x}</li>)}</ol>}
        {(f.expected || f.actual) && <div className="mono-xs"><span className="muted">Expected:</span> {f.expected || "—"} · <span className="muted">Actual:</span> {f.actual || "—"}</div>}
        {f.evidence && <div className="mono-xs muted">{f.evidence}</div>}
        <div className="row" style={{ marginTop: 4 }}>
          {f.decision ? <span className="mono-xs">{f.decision.decision === "fix"
            ? <>Fixing → {f.decision.ticket ? <a className="key" href={taskHref(f.decision.ticket, null, false)}>{f.decision.ticket}</a> : "task"}</>
            : "Skipped"}</span>
            : <>
              <button type="button" className="btn is-primary is-sm" disabled={busy !== null} onClick={() => void decide(f.id, "fix")}>Fix it</button>
              <button type="button" className="btn is-sm" disabled={busy !== null} onClick={() => void decide(f.id, "skip")}>Skip</button>
            </>}
        </div>
      </li>)}
    </ol> : <p className="muted">No findings.</p>}
    <details className="ui-report"><summary className="mono-xs">Full report</summary><pre className="night-report">{run.report || "(no report.md yet)"}</pre></details>
    <div className="row" style={{ marginTop: 12 }}>
      <button type="button" className="btn" onClick={onBack}>← All projects</button>
      <button type="button" className="btn is-quiet" onClick={onClose}>Close</button>
    </div>
  </Dialog>;
}
