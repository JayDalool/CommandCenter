// TASK DETAIL — the ticket as a strong Jira issue a manager can read (spec §6): why, current status,
// the plan, acceptance criteria, Jay's questions, the workflow history with evidence, and its files.
// Technical details (SHAs, worktree, record path) stay behind an expansion.
import { useEffect, useMemo, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href } from "../lib/router";
import type { TaskRecord, TicketDetail } from "../api/types";
import { initials, pjVar, stageOf, STAGE, type Focus } from "../lib/control";
import { dossier, walk, STATUS_WORD } from "../tickets/dossier";
import { useWork } from "../tickets/useWork";
import { QuestionsForm, AnsweredList } from "../tickets/Questions";
import { GateCard } from "../tickets/GateCard";
import { AttachmentsPanel } from "../components/Attachments";
import { Ago, EmptyState } from "../components/ui";

type Tab = "overview" | "plan" | "questions" | "history" | "files";

export function StagePill({ stage }: { stage: keyof typeof STAGE }) {
  return <span className={`stage-pill vs-${STAGE[stage].tone}`}>{STAGE[stage].short}</span>;
}

/** One sentence for "Current status". */
function statusLine(stage: string, t: TicketDetail, open: number): string {
  if (stage === "Needs Jay") return open ? `Waiting for your answer${open > 1 ? "s" : ""} (${open}).` : "Waiting for your decision.";
  if (stage === "Blocked") return "work has stopped; what happened and the recommended action are above.";
  if (stage === "Planning") return "Planning — Opus is investigating and writing the plan.";
  if (stage === "Implementing") return "Implementing the accepted plan.";
  if (stage === "Reviewing") return "A fresh reviewer is checking the change.";
  if (stage === "UI Testing") return "Merged; the UI is being tested.";
  if (stage === "Verifying") return "Merged; being verified.";
  if (stage === "Ready to Merge") return "Reviewed and green; ready to merge.";
  if (stage === "Deploying") return "Approved for live; deploying and verifying.";
  return `${STATUS_WORD[t.status] ?? t.status}.`;
}

export function Dossier({ ticketKey, focus, onOpenRoom, onCollapse }: {
  ticketKey: string; focus?: Focus; onOpenRoom: () => void; onCollapse?: () => void;
}) {
  const detail = useSelector(app.store, (d) => d.details[ticketKey] ?? null);
  const row = useSelector(app.store, (d) => d.tickets.find((t) => t.key === ticketKey) ?? null);
  const st = useSelector(app.store, (d) => d.state);
  const [work, setWork] = useWork(ticketKey);
  const [tab, setTab] = useState<Tab>(focus === "questions" ? "questions" : focus === "history" ? "history" : "overview");
  const [record, setRecord] = useState<TaskRecord | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setErr(null); setRecord(null); app.loadTicket(ticketKey).catch((e) => setErr((e as Error).message)); }, [ticketKey]);
  useEffect(() => { if (focus === "questions") setTab("questions"); else if (focus === "history") setTab("history"); else if (focus) setTab("overview"); }, [focus, ticketKey]);
  useEffect(() => {
    if (focus && focus !== "questions" && focus !== "history") document.getElementById("gate")?.scrollIntoView({ block: "nearest" });
  }, [focus, work]);
  const d = useMemo(() => (detail ? dossier(detail, work) : null), [detail, work]);

  if (err && !detail) return <EmptyState title={`${ticketKey} could not be loaded`} hint={err} />;
  if (!detail || !row) return <EmptyState title={`Loading ${ticketKey}…`} />;
  const stage = work?.visibleStage ?? stageOf(row);
  const open = work?.openQuestions ?? row.openQuestions ?? 0;
  const project = st?.projects.find((p) => p.key === detail.project);
  const prefix = st?.projectsConfig.find((p) => p.key === detail.project)?.prefix ?? detail.key.split("-")[0];
  const steps = walk(detail.timeline);
  const questions = work?.questions ?? [];

  return <section className="dossier" aria-label={`${ticketKey} details`} style={pjVar(detail.project)}>
    <header className="dossier-head">
      <span className="pj-badge" aria-hidden>{initials(prefix, project?.name ?? detail.project)}</span>
      <span className="key dossier-key">{detail.key}</span>
      <h2 className="dossier-title" title={detail.title}>{detail.title}</h2>
      <StagePill stage={stage} />
      <button type="button" className="btn is-sm is-outline" onClick={onOpenRoom} title="Open the live Task Room (or double-click the task)">Open Room</button>
      {onCollapse && <button type="button" className="btn is-quiet is-sm" onClick={onCollapse} aria-label="Hide task details" title="Hide task details">◂</button>}
    </header>
    <nav className="dossier-tabs" role="tablist" aria-label={`${ticketKey} sections`}>
      {(["overview", "plan", "questions", "history", "files"] as Tab[]).map((x) => <button key={x} type="button" role="tab"
        aria-selected={tab === x} className="dtab" onClick={() => setTab(x)}>
        {x === "questions" ? <>Questions {open > 0 && <span className="dtab-n">{open}</span>}</> : x[0].toUpperCase() + x.slice(1)}</button>)}
    </nav>
    <div className="dossier-body">
      {work && <GateCard ticketKey={ticketKey} work={work} onDone={setWork} />}

      {tab === "overview" && d && <div className={`dossier-cols${open ? " has-q" : ""}`}>
        <div className="dossier-main">
          <h4>Why we're doing this</h4>
          <p className="dossier-p">{d.why || <span className="faint">Not written down yet.</span>}</p>
          {d.problem && <><h4>Problem</h4><p className="dossier-p">{d.problem}</p></>}
          {d.cause && <><h4>Cause</h4><p className="dossier-p">{d.cause}</p></>}
          <h4>Current status</h4>
          <p className="dossier-p row"><i className={`sq vs-${STAGE[stage].tone}`} aria-hidden />{stage} — {statusLine(stage, detail, open)}</p>
          <h4>{d.planBy && /opus/i.test(d.planBy) ? "Opus Plan (Summary)" : "Plan (Summary)"}</h4>
          {d.plan.length ? <ol className="dossier-ol">{d.plan.map((s, i) => <li key={i}>{s}</li>)}</ol>
            : <p className="dossier-p faint">{work?.plan?.summary || "No plan recorded yet."}</p>}
          <h4>Acceptance Criteria</h4>
          {d.acceptance.length ? <ul className="dossier-checks">{d.acceptance.map((c, i) => <li key={i}>
            <input type="checkbox" readOnly checked={detail.status === "DONE"} aria-label={c} tabIndex={-1} /><span>{c}</span></li>)}</ul>
            : <p className="dossier-p faint">No acceptance criteria recorded.</p>}
        </div>
        {open > 0 && work && <aside className="dossier-side" aria-label="Your questions">
          <h4>Your questions ({open})</h4>
          <QuestionsForm key={ticketKey} ticketKey={ticketKey} work={work} onDone={setWork} compact />
        </aside>}
      </div>}

      {tab === "plan" && <div className="dossier-main">
        {!work?.plan?.summary ? <p className="faint">No plan recorded yet.</p> : <>
          <h4>Summary <span className="muted mono-xs">({work.planState})</span></h4><p className="dossier-p">{work.plan.summary}</p>
          {work.plan.requirements?.length ? <><h4>Requirements</h4><ul className="dossier-ul">{work.plan.requirements.map((r, i) => <li key={i}>{r}</li>)}</ul></> : null}
          {work.plan.approach && <><h4>Approach</h4><p className="dossier-p pre">{work.plan.approach}</p></>}
          {work.plan.affected?.length ? <><h4>Affected</h4><p className="dossier-p mono-xs">{work.plan.affected.join(" · ")}</p></> : null}
          {work.plan.risk && <><h4>Risk</h4><p className="dossier-p">{work.plan.risk}</p></>}
          {work.plan.tests?.length ? <><h4>Tests</h4><ul className="dossier-ul">{work.plan.tests.map((r, i) => <li key={i}>{r}</li>)}</ul></> : null}
        </>}
        <h4>Who works on it</h4>
        <ul className="dossier-roles">
          {(["planner", "implementer", "reviewer", "verifier"] as const).map((r) => <li key={r}><span className="muted">{r}</span>
            <span className="mono-xs">{work?.roles?.[r] ? [work.roles[r].model, work.roles[r].session].filter(Boolean).join(" · ") || "recorded" : "—"}</span></li>)}
          <li><span className="muted">writer</span><span className="mono-xs">{work?.writer ?? "—"}</span></li>
        </ul>
        {work?.checkpoint && <><h4>Checkpoint ({work.checkpoint.frm ?? "—"} → {work.checkpoint.to})</h4>
          <dl className="gate-dl mono-xs"><dt>reason</dt><dd>{work.checkpoint.reason || "—"}</dd><dt>commit</dt><dd>{work.checkpoint.commit || "—"}</dd>
            <dt>changed</dt><dd>{work.checkpoint.changed.join(", ") || "—"}</dd><dt>tests</dt><dd>{work.checkpoint.tests || "—"}</dd>
            <dt>remaining</dt><dd>{work.checkpoint.remaining || "—"}</dd></dl></>}
      </div>}

      {tab === "questions" && <div className="dossier-main">
        {work ? <QuestionsForm key={ticketKey} ticketKey={ticketKey} work={work} onDone={setWork} /> : <p className="faint">Loading…</p>}
        <AnsweredList questions={questions} />
      </div>}

      {tab === "history" && <div className="dossier-main">
        <h4>Workflow</h4>
        {steps.length ? <ol className="wf">{steps.map((s, i) => <li key={i} className={s.back ? "is-back" : ""}>
          <span className="wf-to">{s.back ? "↩ " : ""}{STATUS_WORD[s.to] ?? s.to}</span>
          <span className="muted trunc">{s.why || (s.actor === "jay" ? "by Jay" : s.actor)}</span><Ago at={s.at} /></li>)}</ol>
          : <p className="faint">No stage changes yet.</p>}
        {(work?.findings ?? []).length > 0 && <><h4>Review findings</h4><ul className="dossier-ul">
          {work!.findings.map((f, i) => <li key={i}><span className="mono-xs muted">{f.source} · {f.scope} scope · {f.category}</span> {f.summary}</li>)}</ul></>}
        {work?.verification && <><h4>Verification</h4><p className="dossier-p">{work.verification.result.toUpperCase()} — {work.verification.evidence}</p></>}
        {work?.merge && <><h4>Merge</h4><p className="dossier-p mono-xs">{work.merge.pr} · {work.merge.sha?.slice(0, 12) ?? "—"} · <Ago at={work.merge.at} /></p></>}
        {work?.deploy && <><h4>Deployment</h4><p className="dossier-p">{work.deploy.env} · {work.deploy.result ? work.deploy.result.toUpperCase() : work.deploy.approvedAt ? "approved" : "waiting for you"}
          {work.deploy.evidence ? ` — ${work.deploy.evidence}` : ""}</p></>}
        <h4>Evidence</h4>
        {(work?.evidence ?? []).length ? <ul className="dossier-ul">{work!.evidence!.map((e) => <li key={e.id}>
          <span className="mono-xs muted">{e.stage ?? "—"} · {e.kind}</span> {/^https?:\/\//.test(e.ref) ? <a className="link" href={e.ref} target="_blank" rel="noopener noreferrer">{e.ref}</a> : e.ref}
          {e.note ? <span className="muted"> — {e.note}</span> : null}</li>)}</ul> : <p className="faint">No evidence recorded yet.</p>}
        <details className="dossier-tech"><summary>Technical details</summary>
          <dl className="gate-dl mono-xs">
            <dt>status</dt><dd>{detail.status}</dd><dt>branch</dt><dd>{detail.branch ?? "—"}</dd>
            <dt>worktree</dt><dd>{work?.worktree ?? "—"}</dd><dt>PRs</dt><dd>{work?.prs?.join(", ") || "—"}</dd>
            <dt>reviewed head</dt><dd>{work?.review?.head ?? "—"} {work?.review?.verdict ? `(${work.review.verdict})` : ""}</dd>
            <dt>task session</dt><dd>{work?.session ? `${work.session.state}${work.session.paneId ? ` · ${work.session.paneId}` : ""}` : "—"}</dd>
          </dl>
          <button type="button" className="btn is-sm" onClick={() => app.api.record(ticketKey).then(setRecord).catch((e) => app.toast((e as Error).message, "bad"))}>
            Show workflow.md</button>
          {record && <><div className="mono-xs muted">{record.dir ?? "rendered (records are written on the server)"}</div><pre className="dossier-md">{record.workflowMd}</pre></>}
        </details>
        <a className="goto" href={href("tasks", ticketKey)}>Open in Task Manager →</a>
      </div>}

      {tab === "files" && <div className="dossier-main">
        <AttachmentsPanel owner="ticket" ownerKey={ticketKey} />
        <p className="mono-xs muted">Project files: <a className="link" href={href("files", null, { project: detail.project })}>Files →</a></p>
      </div>}
    </div>
  </section>;
}
