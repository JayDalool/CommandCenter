// DECISIONS — Sentry-style investigation + formal decision desk (references 03 and 08).
// Discussing is not deciding: an answer is recorded once, with actor, task, policy and evidence, and
// in the real app would go to the EXISTING task session through the existing gates. Nothing here merges or deploys.
import { useState } from "react";
import { DECISION, task } from "../data/seed";
import { useViewState } from "../data/live";
import { go } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Pill, ProdBanner, cx } from "../components/ui";
import { Detachable, PopButton } from "../windows/Detachable";

const V = "page:decisions";
const LOGS = [
  ["2026-10-21 14:32:11", "INFO", "compare_request listings=4 filters=2"],
  ["2026-10-21 14:32:12", "INFO", "results_returned count=24 latency=412ms"],
  ["2026-10-21 14:33:01", "INFO", "comparison_view experiment=single_page"],
  ["2026-10-21 14:33:02", "INFO", "engagement option=A dwell=42s"],
  ["2026-10-21 14:40:18", "WARN", "drop_off step=details rate=0.27 (current flow)"],
  ["2026-10-21 14:40:19", "INFO", "comparison_view experiment=split_flow"],
];

function MockShot({ variant }: { variant: "a" | "b" }) {
  return <div className={`mockshot v-${variant}`} aria-hidden>
    <div className="ms-bar" />{variant === "a" ? <div className="ms-grid">{[0, 1, 2, 3].map((i) => <div key={i} className="ms-row"><i /><span /><span /><b /></div>)}</div>
      : <div className="ms-split"><div className="ms-photo" /><div className="ms-lines"><span /><span /><span /><b /></div></div>}
  </div>;
}

export function Evidence() {
  const [tab, setTab] = useViewState("panel:evidence", "tab", "Logs");
  const [shot, setShot] = useViewState("panel:evidence", "shot", 0);
  return <aside className="evidence" aria-label="Evidence and context">
    <header className="ev-head"><Icon name="db" size={22} /><h2>Evidence &amp; Context</h2><span className="sp" /><PopButton id="panel:evidence" compact /></header>
    <div className="seg seg-boxed" role="tablist">{["Logs", "Screenshots", "UI Findings", "Files"].map((x) => <button key={x} type="button" role="tab" aria-selected={tab === x} onClick={() => setTab(x)}>{x}</button>)}</div>
    {(tab === "Logs" || tab === "Files") && <section className="ev-sec"><h3><Icon name="doc" size={16} /> Relevant Logs <Demo label="Demo" /></h3>
      <pre className="code">{LOGS.map(([t, l, m], i) => <span key={i} className={l === "WARN" ? "is-warn" : ""}><i>{i + 1}</i>[{t}] {l} {m}{"\n"}</span>)}</pre></section>}
    <section className="ev-sec"><h3><Icon name="image" size={16} /> UI Screenshots <span className="sp" /><small className="muted">staging · mock</small></h3>
      <div className="carousel"><button type="button" className="icon-btn" aria-label="Previous screenshot" onClick={() => setShot((shot + 5) % 6)}><Icon name="arrowl" size={16} /></button>
        <MockShot variant={shot % 2 ? "b" : "a"} /><button type="button" className="icon-btn" aria-label="Next screenshot" onClick={() => setShot((shot + 1) % 6)}><Icon name="arrowr" size={16} /></button></div>
      <p className="muted small">Option {shot % 2 ? "B" : "A"} – comparison (staging) · {shot + 1} of 6. No property records in screenshots (SamVision policy).</p></section>
    <section className="ev-sec"><h3><Icon name="users" size={16} /> Precedents &amp; Policy</h3>
      <ul className="prec"><li><span className="prec-ico t-violet"><Icon name="doc" size={16} /></span><div><b>D-004 · SamVision release windows</b><small>Thu / Sat 01:00 America/Winnipeg; otherwise prepare and hold for Jay.</small></div></li>
        <li><span className="prec-ico t-info"><Icon name="shield" size={16} /></span><div><b>Plan approval required</b><small>ui_change_client_visible → full plan package, Claude + Codex review.</small></div></li></ul></section>
    <section className="ev-sec"><h3><Icon name="list" size={16} /> Related Tasks</h3>
      <ul className="prec"><li><span className="prec-ico t-ok"><Icon name="code" size={16} /></span><div><b>SV-029 · Listing import retry</b><small>Reviewing · independent of this decision</small></div></li></ul></section>
  </aside>;
}

export function Decisions() {
  const t = task("SV-025")!;
  const [tab, setTab] = useViewState(V, "tab", "Overview");
  const [pick, setPick] = useViewState(V, "pick", "A");
  const [recorded, setRecorded] = useViewState<null | { option: string; at: string }>(V, "recorded", null);
  const [confirm, setConfirm] = useState(false);
  const opt = DECISION.options.find((o) => o.id === pick)!;
  return <div className="page page-decisions">
    <div className="dec-main">
      <a className="back" href="#/decisions"><Icon name="arrowl" size={15} /> Back to Decisions</a>
      <header className="dec-head">
        <span className="dec-ico"><Icon name="edit" size={30} /></span>
        <div className="dec-title"><h1><span className="mono">{t.key}</span> {t.title}</h1>
          <p>SamVision · Improve the rental comparison experience with clearer pricing, filters and a faster flow.</p>
          <div className="row-gap"><Pill tone="bad">High</Pill><Pill tone="idle"><Icon name="image" size={13} /> SamVision</Pill><Pill tone="idle"><Icon name="calendar" size={13} /> Opened 2 days ago</Pill><Pill tone="violet" dot>Reviewing</Pill><Demo /></div></div>
        <div className="dec-actions"><button type="button" className="btn btn-outline" onClick={() => go("messages", "sv-lead")}><Icon name="message" size={16} /> Open Team Chat</button>
          <button type="button" className="btn btn-primary" onClick={() => go("task", t.key)}>View Task <Icon name="arrowr" size={15} /></button><PopButton id={V} /></div>
      </header>
      <div className="tabs-under" role="tablist">{[["Overview", "target"], ["Plan", "edit"], ["Questions", "help"], ["Evidence", "doc"], ["Technical", "code"]].map(([x, ic]) =>
        <button key={x} type="button" role="tab" aria-selected={tab === x} onClick={() => setTab(x)}><Icon name={ic} size={17} />{x}{x === "Questions" && <span className="count">1</span>}</button>)}</div>
      <ProdBanner />
      {tab === "Overview" && <>
        <div className="dec-cards">
          <div className="dcard"><h3><span className="dc-ico t-violet"><Icon name="target" size={18} /></span>Why this matters</h3><p>{t.why}</p></div>
          <div className="dcard"><h3><span className="dc-ico t-info"><Icon name="pulse" size={18} /></span>Current stage <span className="sp" /><Pill tone="violet" dot>Reviewing</Pill></h3>
            <ol className="stepper">{["Define", "Build", "Reviewing", "Approve", "Implement"].map((s, i) => <li key={s} className={i < 2 ? "is-done" : i === 2 ? "is-now" : ""}><i>{i < 2 && <Icon name="tick" size={12} stroke={3} />}</i><span>{s}</span></li>)}</ol>
            <p className="muted">Team is reviewing options and evidence. Your decision moves it to approval.</p></div>
          <div className="dcard"><h3><span className="dc-ico t-violet"><Icon name="spark" size={18} /></span>Recommended action</h3>
            <p>Choose Option A (single-page flow): fewer steps for realtors, lower engineering risk, and it matched user testing.</p>
            {recorded ? <p className="callout t-ok"><Icon name="check" size={16} /> Decided: Option {recorded.option} · by Jay · {recorded.at} (demo record)</p>
              : <button type="button" className="btn btn-primary btn-block" onClick={() => { setPick("A"); setConfirm(true); }}>Approve Option A <Icon name="arrowr" size={15} /></button>}
            <button type="button" className="btn btn-block" onClick={() => go("messages", "sv-lead")}><Icon name="message" size={15} /> Request Changes</button></div>
        </div>
        <section className="panel dec-request">
          <header className="panel-h"><span className="panel-ico"><Icon name="graph" size={20} /></span><div className="panel-t"><h2>Decision Request</h2><p>{DECISION.title}.</p></div>
            <div className="panel-a"><Pill tone="warn" dot>Requires decision</Pill><span className="muted small"><Icon name="calendar" size={13} /> Due {DECISION.due}</span></div></header>
          <div className="options" role="radiogroup" aria-label="Options">{DECISION.options.map((o) => <button key={o.id} type="button" role="radio" aria-checked={pick === o.id}
            className={cx("option", pick === o.id && "is-picked")} onClick={() => !recorded && setPick(o.id)} disabled={!!recorded && recorded.option !== o.id}>
            <span className="opt-head"><i className="radio" /><b>Option {o.id}</b><span>{o.title}</span><span className="sp" /><Pill tone={o.id === "A" ? "ok" : "info"}>{o.tag}</Pill></span>
            <small>{o.sub}</small>
            <span className="opt-body"><MockShot variant={o.id === "A" ? "a" : "b"} /><ul>{o.pros.map((p) => <li key={p}><Icon name="check" size={15} /> {p}</li>)}{o.cons.map((p) => <li key={p} className="t-warn"><Icon name="info" size={15} /> {p}</li>)}</ul></span>
          </button>)}</div>
          <div className="accept"><h3><Icon name="check" size={18} /> Acceptance Criteria</h3><ul>{t.criteria.map((c) => <li key={c}><Icon name="check" size={15} /> {c}</li>)}</ul></div>
          <footer className="dec-foot"><span className="muted small"><Icon name="lock" size={14} /> Authority: Jay (owner). Recording this answers SV-025's question in its existing session. It does not merge, release or deploy — those keep their own gates.</span>
            {recorded ? <button type="button" className="btn" onClick={() => setRecorded(null)}>Reopen (demo)</button>
              : <button type="button" className="btn btn-primary" onClick={() => setConfirm(true)}>Record decision: Option {pick}</button>}</footer>
        </section>
        <div className="dec-bottom">
          <section className="panel"><header className="panel-h"><span className="panel-ico t-bad"><Icon name="info" size={20} /></span><div className="panel-t"><h2>Needs Your Decision <span className="count t-bad">1</span></h2></div></header>
            <div className="need-row"><span className="dc-ico t-bad"><Icon name="target" size={18} /></span><div><b>Select rental comparison workflow (Option A or B)</b><small>Proposed by Claude · 2 days ago</small></div><Pill tone="bad">High</Pill><button type="button" className="btn btn-primary btn-sm" onClick={() => setConfirm(true)}>Make Decision <Icon name="arrowr" size={13} /></button></div></section>
          <section className="panel"><header className="panel-h"><span className="panel-ico t-info"><Icon name="users" size={20} /></span><div className="panel-t"><h2>Key People</h2></div></header>
            <div className="people">{[["jay", "Jay", "Engineering Director", "Decision owner", "info"], ["claude", "Claude", "Project Lead", "Recommends A", "ok"], ["iris", "Iris", "Research Lead", "Prepared options", "violet"]].map(([id, n, r, p, tone]) =>
              <div key={id}><Avatar id={id} size={32} /><span><b>{n}</b><small>{r}</small><Pill tone={tone}>{p}</Pill></span></div>)}</div></section>
        </div>
      </>}
      {tab === "Plan" && <section className="panel pad"><h2>Plan</h2><ol className="numlist">{t.plan.map((p, i) => <li key={p}><span>{i + 1}</span>{p}</li>)}</ol></section>}
      {tab === "Questions" && <section className="panel pad"><h2>Questions</h2>{t.questions.map((q) => <div key={q} className="need-row"><Icon name="help" size={18} /><div><b>{q}</b><small>Asked by Claude · answer once here; the answer goes to the existing SV-025 session.</small></div><button type="button" className="btn btn-sm" onClick={() => setTab("Overview")}>Answer</button></div>)}</section>}
      {tab === "Evidence" && <section className="panel pad"><h2>Evidence</h2><p className="muted">12 items: 5 logs, 4 screenshots, 2 traces, 1 file. The evidence panel on the right stays in sync and can be popped out.</p></section>}
      {tab === "Technical" && <section className="panel pad"><h2>Technical</h2><dl className="kv"><dt>Branch</dt><dd className="mono">sv-025-comparison (isolated worktree)</dd><dt>PR</dt><dd className="mono">#842 · head 7f3a9c1</dd><dt>Review</dt><dd>Claude always; Codex on plan package</dd><dt>Merge</dt><dd>Owner (Jay)</dd><dt>Deploy</dt><dd>Release window only</dd></dl></section>}
    </div>
    <Detachable id="panel:evidence" className="evidence"><Evidence /></Detachable>
    {confirm && <div className="veil" role="dialog" aria-modal="true" aria-label="Confirm decision">
      <div className="dialog"><h2>Record this decision?</h2>
        <dl className="kv"><dt>Decision</dt><dd>Option {opt.id} · {opt.title}</dd><dt>Task</dt><dd className="mono">SV-025</dd><dt>Actor</dt><dd>Jay (owner)</dd>
          <dt>Policy</dt><dd>Plan approval · ui_change_client_visible (policy/projects/samvision.toml)</dd><dt>Effect</dt><dd>Answers the open question in SV-025's existing session. No merge, no deploy.</dd></dl>
        <p className="callout t-warn"><Icon name="info" size={16} /> Prototype: this records a demo entry in your browser only. Nothing is sent to ccd.</p>
        <div className="row-gap end"><button type="button" className="btn" onClick={() => setConfirm(false)}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={() => { setRecorded({ option: pick, at: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) }); setConfirm(false); }}>Record decision</button></div></div>
    </div>}
  </div>;
}
