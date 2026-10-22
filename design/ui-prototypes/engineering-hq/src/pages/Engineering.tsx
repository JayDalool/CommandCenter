// ENGINEERING — dense workbench behind its own tab (references 06 and 10).
import { TASKS, project, agent, task as taskOf, type Task } from "../data/seed";
import { useViewState } from "../data/live";
import { AgentStatus, useAgentView, useOpenAgent } from "../components/agent";
import { go } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Prio, ProjIcon, StagePill, TaskKey, cx } from "../components/ui";
import { Detachable, PopButton } from "../windows/Detachable";

const V = "page:engineering";

function Assignee({ id }: { id: string }) {
  if (id === "jay") return <span className="assignee"><Avatar id="jay" size={26} /><span><b>Jay</b><small className="muted">until a lead is assigned</small></span></span>;
  return <AgentAssignee id={id} />;
}
function AgentAssignee({ id }: { id: string }) {
  const v = useAgentView(id);
  const open = useOpenAgent();
  return <button type="button" className="assignee" onClick={() => open(id)} aria-label={`${agent(id).name} details`}>
    <Avatar id={id} size={26} /><span><b>{agent(id).name}</b><AgentStatus v={v} task={false} /></span></button>;
}

export function TaskDetail({ k }: { k?: string }) {
  const [selV] = useViewState(V, "sel", "CC-061");
  const t = taskOf(k ?? selV) ?? TASKS[0];
  const [tab, setTab] = useViewState("panel:task-detail", "tab", "Details");
  return <aside className="tdetail" aria-label="Task detail">
    <header className="td-crumb"><ProjIcon k={t.project} size={20} /><span>{project(t.project).name}</span><span className="muted">/</span><TaskKey k={t.key} /><span className="sp" /><PopButton id="panel:task-detail" compact /></header>
    <div className="td-title"><h2>{t.title}</h2><StagePill s={t.stage} /></div>
    <div className="seg seg-under" role="tablist">{["Details", "Plan", "Checks", "Activity"].map((x) => <button key={x} role="tab" type="button" aria-selected={tab === x} onClick={() => setTab(x)}>{x}</button>)}</div>
    <div className="td-meta"><div><small>Assignee</small><Assignee id={t.owner} />{t.formerOwners?.length ? <small className="muted">Previously {t.formerOwners.map((x) => agent(x).name).join(", ")}</small> : null}</div><div><small>Reviewers</small><span><Avatar id="atlas" size={24} /><Avatar id="claude" size={24} /></span></div><div><small>Updated</small><span>{t.updated}</span></div></div>
    <div className="td-labels"><small>Labels</small>{t.labels.map((l) => <span key={l} className="label">{l}</span>)}{t.pr && <span className="label is-link"><Icon name="branch" size={13} /> PR {t.pr}</span>}</div>
    <section className="td-sec"><span className="td-ico t-bad"><Icon name="target" size={18} /></span><h3>Why</h3><p>{t.why}</p></section>
    <section className="td-sec"><span className="td-ico t-info"><Icon name="list" size={18} /></span><h3>Plan</h3><ol>{t.plan.map((p) => <li key={p}>{p}</li>)}</ol></section>
    <section className="td-sec"><span className="td-ico t-ok"><Icon name="check" size={18} /></span><h3>Acceptance Criteria</h3><ul className="checks">{t.criteria.map((p) => <li key={p}>{p}</li>)}</ul></section>
    {t.questions.length > 0 && <section className="td-sec"><span className="td-ico t-info"><Icon name="help" size={18} /></span><h3>Questions</h3><ul>{t.questions.map((q) => <li key={q}>{q}</li>)}</ul><button type="button" className="btn btn-sm" onClick={() => go("decisions")}>Answer Questions</button></section>}
    <section className="td-sec"><span className="td-ico t-violet"><Icon name="image" size={18} /></span><h3>Evidence</h3><div className="files">{["playwright-1920.png", "review-notes.md", "spec.md"].map((f) => <span key={f} className="file"><Icon name="doc" size={16} />{f}</span>)}</div></section>
    <footer className="td-actions"><button type="button" className="btn btn-primary"><Icon name="doc" size={15} /> Review Plan</button><button type="button" className="btn" onClick={() => go("decisions")}><Icon name="help" size={15} /> Answer Questions</button>
      <button type="button" className="btn btn-ok" disabled title="Deploys need the existing gates and a release window; never from the prototype"><Icon name="lock" size={15} /> Approve Deploy (gated)</button>
      <button type="button" className="btn" onClick={() => go("task", t.key)}><Icon name="terminal" size={15} /> Open Room</button></footer>
  </aside>;
}

export function Engineering() {
  const [sel, setSel] = useViewState(V, "sel", "CC-061");
  const [proj, setProj] = useViewState(V, "proj", "all");
  const [stage, setStage] = useViewState(V, "stage", "active");
  const [sort, setSort] = useViewState(V, "sort", "key");
  const rows = TASKS.filter((t) => (proj === "all" || t.project === proj) && (stage === "all" || (stage === "active" ? !["Closed", "Paused"].includes(t.stage) : t.stage === stage)))
    .sort((a, b) => (sort === "priority" ? ["High", "Medium", "Low"].indexOf(a.priority) - ["High", "Medium", "Low"].indexOf(b.priority) : a.key.localeCompare(b.key)));
  return <div className="page page-eng">
    <div className="eng-top">
      <div className="eng-hero"><h1><Icon name="wrench" size={40} /> Engineering</h1><p>Build, ship and operate with clarity. Turn plans into production.</p>
        <div className="filters">
          <label><small>Project</small><select value={proj} onChange={(e) => setProj(e.target.value)}><option value="all">All projects</option>{["samvision", "gyst", "mfe", "gauzemate", "commandcenter"].map((k) => <option key={k} value={k}>{project(k).name}</option>)}</select></label>
          <label><small>Environment</small><select defaultValue="all"><option value="all">All environments</option><option>Staging</option><option>Production</option></select></label>
          <label><small>Status</small><select value={stage} onChange={(e) => setStage(e.target.value)}><option value="active">Active</option><option value="all">All</option><option>Blocked</option><option>Reviewing</option><option>Implementing</option></select></label>
          <label><small>Assignee</small><select defaultValue="all"><option value="all">All assignees</option></select></label>
          <label><small>Date range</small><span className="fake-select"><Icon name="calendar" size={15} /> Last 30 days</span></label>
        </div></div>
      <section className="panel eng-gate"><h3><Icon name="rocket" size={24} /> Release Gate <span className="sp" /><a className="link" href="#/topology">View All <Icon name="arrowr" size={13} /></a></h3>
        <p>v0.4.2 · SamVision <span className="pill t-ok no-dot">Ready</span></p>
        <ol className="stepper">{["Build", "Tests", "Security", "Review", "Deploy"].map((s, i) => <li key={s} className={i < 3 ? "is-done" : ""}><i>{i < 3 && <Icon name="tick" size={12} stroke={3} />}</i><span>{s}</span></li>)}</ol></section>
      <section className="panel eng-usage"><h3><Icon name="db" size={24} /> Model Usage / Cost <Demo label="Demo" /></h3>
        <p className="big">$— <small className="muted">Live figures come from ccd's usage meter (AI spend, not revenue)</small></p>
        <div className="bars">{[5, 7, 4, 8, 6, 9, 7, 5, 8, 10, 6, 9, 7, 8, 6, 9, 5, 7].map((h, i) => <i key={i} style={{ height: h * 4, background: i % 4 === 0 ? "#4e5a78" : i % 3 === 0 ? "#6d5cff" : "#8fa2ff" }} />)}</div>
        <p className="legend-row"><span><i style={{ background: "#8fa2ff" }} />Claude</span><span><i style={{ background: "#6d5cff" }} />Codex</span><span><i style={{ background: "#4e5a78" }} />Other</span></p></section>
    </div>
    <div className="eng-grid">
      <section className="panel workbench">
        <header className="panel-h"><span className="panel-ico t-info"><Icon name="list" size={22} /></span><div className="panel-t"><h2>Engineering Workbench</h2><p>Active tasks across all teams and services. Select a task to view details. <Demo /></p></div>
          <div className="panel-a"><label className="inline"><small>Sort</small><select value={sort} onChange={(e) => setSort(e.target.value)}><option value="key">Key</option><option value="priority">Priority</option></select></label>
            <button type="button" className="btn btn-primary" disabled title="Creating tasks needs the approved API (proposal in the plan)"><Icon name="plus" size={15} /> New Task</button><PopButton id={V} /></div></header>
        <table className="grid wb"><thead><tr><th><input type="checkbox" aria-label="Select all" /></th><th>Key</th><th>Title</th><th>Service</th><th>Status</th><th>Priority</th><th>Assignee</th><th>Updated</th></tr></thead>
          <tbody>{rows.map((t: Task) => <tr key={t.key} className={cx(sel === t.key && "is-sel")} onClick={() => setSel(t.key)} aria-selected={sel === t.key}>
            <td><input type="checkbox" checked={sel === t.key} readOnly aria-label={`Select ${t.key}`} /></td><td><TaskKey k={t.key} /></td><td className="wb-title">{t.title}</td>
            <td><span className="cell-pj"><ProjIcon k={t.project} size={22} />{project(t.project).name}</span></td><td><StagePill s={t.stage} /></td><td><Prio p={t.priority} /></td>
            <td><span className="cell-pj"><Avatar id={t.owner} size={24} />{agent(t.owner).name}</span></td><td className="muted">{t.updated}</td></tr>)}</tbody></table>
      </section>
      <Detachable id="panel:task-detail" className="tdetail"><TaskDetail /></Detachable>
    </div>
  </div>;
}
