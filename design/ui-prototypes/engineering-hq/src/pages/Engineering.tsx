// ENGINEERING — dense workbench behind its own tab (references 06 and 10).
import { TASKS, project, agent, task as taskOf, type Task } from "../data/seed";
import { useViewState } from "../data/live";
import { AgentStatus, useAgentView, useOpenAgent } from "../components/agent";
import { go } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Prio, ProjIcon, StagePill, TaskKey, cx } from "../components/ui";
import { Detachable, PopButton } from "../windows/Detachable";
import { notify } from "../windows/manager";

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

/** Mock progress through a task's plan, from its stage. */
function planDone(t: Task): number {
  const order: Record<string, number> = { Planning: 0, Implementing: 1, Reviewing: 2, "UI Testing": 2, Verifying: 3, "Ready to Merge": 4, Deploying: 4, Closed: 9 };
  return Math.min(t.plan.length, order[t.stage] ?? 0);
}
type Check = [string, "pass" | "fail" | "run" | "wait", string];
function CHECKS(t: Task): Check[] {
  const later = ["Planning", "Implementing"].includes(t.stage);
  return [
    ["Build", later && t.stage === "Planning" ? "wait" : "pass", "web + server · 2m 41s"],
    ["Unit tests", later ? (t.stage === "Planning" ? "wait" : "run") : "pass", t.stage === "Planning" ? "Starts after the first commit" : "312 tests"],
    ["Security scan", t.stage === "Blocked" ? "fail" : later ? "wait" : "pass", t.stage === "Blocked" ? "1 finding to triage" : "No new findings"],
    ["Independent review", ["Reviewing", "Planning", "Implementing"].includes(t.stage) ? (t.stage === "Reviewing" ? "run" : "wait") : "pass", "Reviewer is never the implementer"],
    ["UI tests", t.stage === "UI Testing" ? "run" : ["Verifying", "Ready to Merge", "Deploying", "Closed"].includes(t.stage) ? "pass" : "wait", "1366 and 1920, light and dark"],
  ];
}
function ACTIVITY(t: Task): [string, string, string][] {
  const lead = t.owner === "claude" ? "claude" : t.project === "samvision" || t.project === "commandcenter" ? "claude" : "claude";
  return [
    [t.owner, `moved it to ${t.stage}`, t.updated],
    ["atlas", "left two review notes on the plan", "3h ago"],
    [lead, `assigned it to ${t.owner === "jay" ? "Jay" : agent(t.owner).name}`, "1d ago"],
    ["jay", "created the task", "2d ago"],
  ];
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
    {tab === "Details" && <>
      <section className="td-sec"><span className="td-ico t-bad"><Icon name="target" size={18} /></span><h3>Why</h3><p>{t.why}</p></section>
      <section className="td-sec"><span className="td-ico t-info"><Icon name="list" size={18} /></span><h3>Plan</h3><ol>{t.plan.map((p) => <li key={p}>{p}</li>)}</ol></section>
      <section className="td-sec"><span className="td-ico t-ok"><Icon name="check" size={18} /></span><h3>Acceptance Criteria</h3><ul className="checks">{t.criteria.map((p) => <li key={p}>{p}</li>)}</ul></section>
    {t.questions.length > 0 && <section className="td-sec"><span className="td-ico t-info"><Icon name="help" size={18} /></span><h3>Questions</h3><ul>{t.questions.map((q) => <li key={q}>{q}</li>)}</ul><button type="button" className="btn btn-sm" onClick={() => go("decisions")}>Answer Questions</button></section>}
      <section className="td-sec"><span className="td-ico t-violet"><Icon name="image" size={18} /></span><h3>Evidence</h3><div className="files">{["playwright-1920.png", "review-notes.md", "spec.md"].map((f) => <span key={f} className="file"><Icon name="doc" size={16} />{f}</span>)}</div></section>
    </>}
    {tab === "Plan" && <section className="td-sec is-wide"><span className="td-ico t-info"><Icon name="list" size={18} /></span><h3>Plan <Demo label="Demo" /></h3>
      {t.plan.length ? <ol className="td-steps">{t.plan.map((p, i) => <li key={p} className={i < planDone(t) ? "is-done" : i === planDone(t) ? "is-now" : ""}><i>{i < planDone(t) ? <Icon name="tick" size={11} stroke={3} /> : i + 1}</i><span>{p}</span><small className="muted">{i < planDone(t) ? "Done" : i === planDone(t) ? "In progress" : "Next"}</small></li>)}</ol>
        : <p className="muted">No plan yet. Paused tasks keep their history.</p>}
      <p className="muted small">Written by {agent(t.owner === "jay" ? "claude" : t.owner).name}. Plans the profile marks (production, data, security) go to Jay.</p></section>}
    {tab === "Checks" && <section className="td-sec is-wide"><span className="td-ico t-ok"><Icon name="check" size={18} /></span><h3>Checks <Demo label="Demo" /></h3>
      <ul className="td-checks">{CHECKS(t).map(([n, st, d]) => <li key={n}><span className={`pill no-dot t-${st === "pass" ? "ok" : st === "fail" ? "bad" : st === "run" ? "info" : "idle"}`}>{st === "pass" ? "Passed" : st === "fail" ? "Failed" : st === "run" ? "Running" : "Waiting"}</span><b>{n}</b><small className="muted">{d}</small></li>)}</ul>
      <h3 className="td-sub">Acceptance criteria</h3><ul className="checks">{t.criteria.map((p) => <li key={p}>{p}</li>)}</ul></section>}
    {tab === "Activity" && <section className="td-sec is-wide"><span className="td-ico t-violet"><Icon name="clock" size={18} /></span><h3>Activity <Demo label="Demo" /></h3>
      <ol className="td-activity">{ACTIVITY(t).map(([who, what, at], i) => <li key={i}><Avatar id={who} size={24} /><span><b>{who === "jay" ? "Jay" : agent(who).name}</b> {what}</span><small className="muted">{at}</small></li>)}</ol></section>}
    <footer className="td-actions"><button type="button" className="btn btn-primary" onClick={() => setTab("Plan")} aria-pressed={tab === "Plan"}><Icon name="doc" size={15} /> Review Plan</button><button type="button" className="btn" onClick={() => go("decisions")}><Icon name="help" size={15} /> Answer Questions</button>
      <button type="button" className="btn btn-ok" disabled title="Deploys need the existing gates and a release window; never from the prototype"><Icon name="lock" size={15} /> Approve Deploy (gated)</button>
      <button type="button" className="btn" onClick={() => go("task", t.key)}><Icon name="terminal" size={15} /> Open Room</button></footer>
  </aside>;
}

/** Mock environment, from the stage: where the task's latest build runs. */
function envOf(t: Task): string {
  return ["Verifying", "Ready to Merge", "UI Testing"].includes(t.stage) ? "Staging" : ["Deploying", "Closed"].includes(t.stage) ? "Production" : "Development";
}

export function Engineering() {
  const [sel, setSel] = useViewState(V, "sel", "CC-061");
  const [proj, setProj] = useViewState(V, "proj", "all");
  const [stage, setStage] = useViewState(V, "stage", "active");
  const [sort, setSort] = useViewState(V, "sort", "key");
  const [env, setEnv] = useViewState(V, "env", "all");
  const [who, setWho] = useViewState(V, "who", "all");
  const [picked, setPicked] = useViewState<string[]>(V, "picked", []);
  const owners = [...new Set(TASKS.map((t) => t.owner))];
  const rows = TASKS.filter((t) => (proj === "all" || t.project === proj) && (stage === "all" || (stage === "active" ? !["Closed", "Paused"].includes(t.stage) : t.stage === stage))
      && (env === "all" || envOf(t) === env) && (who === "all" || t.owner === who))
    .sort((a, b) => (sort === "priority" ? ["High", "Medium", "Low"].indexOf(a.priority) - ["High", "Medium", "Low"].indexOf(b.priority) : a.key.localeCompare(b.key)));
  return <div className="page page-eng">
    <div className="eng-top">
      <div className="eng-hero"><h1><Icon name="wrench" size={40} /> Engineering</h1><p>Build, ship and operate with clarity. Turn plans into production.</p>
        <div className="filters">
          <label><small>Project</small><select value={proj} onChange={(e) => setProj(e.target.value)}><option value="all">All projects</option>{["samvision", "gyst", "mfe", "gauzemate", "commandcenter"].map((k) => <option key={k} value={k}>{project(k).name}</option>)}</select></label>
          <label><small>Environment</small><select value={env} onChange={(e) => setEnv(e.target.value)}><option value="all">All environments</option><option>Development</option><option>Staging</option><option>Production</option></select></label>
          <label><small>Status</small><select value={stage} onChange={(e) => setStage(e.target.value)}><option value="active">Active</option><option value="all">All</option><option>Blocked</option><option>Reviewing</option><option>Implementing</option></select></label>
          <label><small>Assignee</small><select value={who} onChange={(e) => setWho(e.target.value)}><option value="all">All assignees</option>{owners.map((o) => <option key={o} value={o}>{o === "jay" ? "Jay" : agent(o).name}</option>)}</select></label>
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
        {picked.length > 0 && <div className="wb-bulk" role="status"><b>{picked.length} selected</b><span className="muted">{picked.join(", ")}</span><span className="sp" />
          <button type="button" className="btn btn-sm" onClick={() => { navigator.clipboard?.writeText(picked.join(" ")).then(() => notify("Task keys copied."), () => notify("Copy is blocked here. Select the keys instead.", "warn")); }}><Icon name="doc" size={14} /> Copy keys</button>
          <button type="button" className="btn btn-sm" disabled title="Bulk changes need the approved task API (proposal in the plan)">Change status</button>
          <button type="button" className="btn btn-sm" onClick={() => setPicked([])}>Clear</button></div>}
        {!rows.length && <p className="empty">No tasks match these filters. <button type="button" className="link" onClick={() => { setProj("all"); setStage("active"); setEnv("all"); setWho("all"); }}>Reset filters</button></p>}
        <table className="grid wb"><thead><tr><th><input type="checkbox" aria-label="Select all" checked={rows.length > 0 && rows.every((t) => picked.includes(t.key))}
          ref={(el) => { if (el) el.indeterminate = picked.length > 0 && !rows.every((t) => picked.includes(t.key)); }}
          onChange={(e) => setPicked(e.target.checked ? rows.map((t) => t.key) : [])} /></th><th>Key</th><th>Title</th><th>Service</th><th>Status</th><th>Priority</th><th>Assignee</th><th>Updated</th></tr></thead>
          <tbody>{rows.map((t: Task) => <tr key={t.key} className={cx(sel === t.key && "is-sel")} onClick={() => setSel(t.key)} aria-selected={sel === t.key}>
            <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={picked.includes(t.key)} aria-label={`Select ${t.key}`}
              onChange={(e) => setPicked(e.target.checked ? [...picked, t.key] : picked.filter((x) => x !== t.key))} /></td><td><TaskKey k={t.key} /></td><td className="wb-title">{t.title}</td>
            <td><span className="cell-pj"><ProjIcon k={t.project} size={22} />{project(t.project).name}</span></td><td><StagePill s={t.stage} /></td><td><Prio p={t.priority} /></td>
            <td><span className="cell-pj"><Avatar id={t.owner} size={24} />{agent(t.owner).name}</span></td><td className="muted">{t.updated}</td></tr>)}</tbody></table>
      </section>
      <Detachable id="panel:task-detail" className="tdetail"><TaskDetail /></Detachable>
    </div>
  </div>;
}
