// A project's cockpit: state, agents, tickets, PRs, activity, worktrees, health, workspace access.
import { useMemo } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import type { ProjectView, Ticket } from "../api/types";
import { CLOSED, jayQueue, sortTickets } from "../tickets/model";
import { DataTable, type Column } from "../components/DataTable";
import { Panel, Project, AgentState, Ci, EmptyState, StateText, PriorityMark, Assignee, Command, Ago, StaleIndicator, DetailRow, Flags } from "../components/ui";
import { ActivityRow, meaningful } from "../components/Feed";
import { NeedsTable } from "./needs";
import { jayAction } from "./PullRequests";
import { workspace } from "../workspace/transport";

export function Projects() {
  const route = useRoute();
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  if (!st) return <EmptyState title="Loading…" />;
  if (route.id) {
    const p = st.projects.find((x) => x.key === route.id);
    if (p) return <Cockpit p={p} />;
    const tp = app.data.taskProjects.find((x) => x.key === route.id);
    if (!tp) return <EmptyState title={`No project ${route.id}`} />;
    return <TicketOnlyProject k={tp.key} name={tp.name} />;
  }
  const cols: Column<ProjectView>[] = [
    { id: "n", header: "Project", cell: (p) => <Project k={p.key} name={p.name} /> },
    { id: "s", header: "State", className: "is-title", cell: (p) => <span className="t text2 trunc">{p.summary}</span> },
    { id: "a", header: "Agents", className: "is-num", cell: (p) => <span className="mono">{p.panes.length}</span> },
    { id: "t", header: "Open tasks", className: "is-num", cell: (p) => <span className="mono">{tickets.filter((t) => t.project === p.key && !CLOSED.has(t.status) && !t.archived).length}</span> },
    { id: "pr", header: "PRs", className: "is-num", cell: (p) => <span className="mono">{p.prs.length}</span> },
    { id: "ci", header: "Main", cell: (p) => <Ci mark={p.main_ci} /> },
    { id: "j", header: "Needs Jay", className: "is-num", cell: (p) => { const n = jayQueue(st).filter((j) => j.project === p.key).length; return <span className={n ? "jay-t mono" : "faint mono"}>{n}</span>; } },
  ];
  return <Panel title="Projects" count={st.projects.length}>
    <div className="tbl-wrap"><DataTable label="Projects" rows={st.projects} columns={cols} rowKey={(p) => p.key} onActivate={(k) => go("projects", k)} /></div>
  </Panel>;
}

function Cockpit({ p }: { p: ProjectView }) {
  const st = useSelector(app.store, (d) => d.state)!;
  const tickets = useSelector(app.store, (d) => d.tickets);
  const activity = useSelector(app.store, (d) => d.activity);
  const mine = useMemo(() => sortTickets(tickets.filter((t) => t.project === p.key && !t.archived && !CLOSED.has(t.status)), "status"), [tickets, p.key]);
  const queue = jayQueue(st).filter((j) => j.project === p.key);
  const wts = (st.worktrees?.[p.key] ?? []).slice(1);
  const stale = st.stale.filter((s) => s.project === p.key);
  const spaces = (st.workspaces ?? []).filter((w) => w.project === p.key);
  const coord = st.coordinators[p.key];
  const cfg = st.projectsConfig.find((c) => c.key === p.key);
  const tcols: Column<Ticket>[] = [
    { id: "k", header: "ID", cell: (t) => <span className="key">{t.key}</span> },
    { id: "t", header: "Title", className: "is-title", cell: (t) => <span className="row"><span className="t trunc">{t.title}</span><Flags flags={t.flags} /></span> },
    { id: "s", header: "Status", cell: (t) => <StateText status={t.status} /> },
    { id: "p", header: "Pri", cell: (t) => <PriorityMark p={t.priority} /> },
    { id: "a", header: "Assignee", cell: (t) => <Assignee value={t.assignee} /> },
    { id: "pr", header: "PR", cell: (t) => t.prNumber ? <span className="mono">#{t.prNumber}</span> : <span className="faint">—</span> },
  ];
  return <div className="stack">
    <section className="panel" aria-label="Project state"><div className="kv" style={{ gridTemplateColumns: "repeat(6, minmax(0,1fr))" }}>
      <div><span className="caps muted">State</span><span className="trunc">{p.summary}</span></div>
      <div><span className="caps muted">Coordinator</span><span className="row"><span className="mono">{coord?.name ?? "—"}</span><AgentState status={coord?.status ?? "offline"} /></span></div>
      <div><span className="caps muted">Main checks</span><span className="row"><Ci mark={p.main_ci} /><span className="mono-xs muted">{cfg?.branch}</span></span></div>
      <div><span className="caps muted">GitHub</span><span className="row">{p.github.error ? <span className="bad-t trunc" title={p.github.error}>failing</span> : <span className="ok-t">ok</span>}
        <Ago at={p.github.asOf} /><StaleIndicator at={p.github.asOf} limitS={300} /></span></div>
      <div><span className="caps muted">Jay checks</span><span className="mono">{p.tests.ui.open} UI · {p.tests.actions.open} actions</span></div>
      <div><span className="caps muted">Repo</span><span className="mono-xs trunc" title={p.path}>{p.repo}</span></div>
    </div></section>
    {queue.length > 0 && <Panel title="Needs Jay" count={queue.length} jay><NeedsTable items={queue} /></Panel>}
    <div className="grid-2">
      <div className="stack">
        <Panel title="Tickets" count={mine.length} tools={<><button type="button" className="btn is-sm" onClick={() => window.dispatchEvent(new Event("cc:new-task"))}>New</button>
          <a className="goto" href={href("tasks", null, { project: p.key })}>All →</a></>}>
          <div className="tbl-wrap"><DataTable label={`${p.name} tickets`} rows={mine.slice(0, 15)} columns={tcols} rowKey={(t) => t.key}
            onActivate={(k) => go("tasks", k)} empty={<EmptyState title="No open tickets." hint="N captures one" />} /></div>
        </Panel>
        <Panel title="Pull requests" count={p.prs.length}>
          {p.prs.length ? <table className="tbl"><tbody>{p.prs.map((pr) => { const j = jayAction(pr); return <tr key={pr.number}>
            <td><a className="mono link" href={pr.url ?? "#"} target="_blank" rel="noopener noreferrer">#{pr.number}</a></td>
            <td className="is-title"><span className="t trunc">{pr.title}</span></td><td><Ci mark={pr.ci} /></td>
            <td><span className={j.cls}>{j.text}</span></td></tr>; })}</tbody></table> : <EmptyState title="No open PRs." />}
        </Panel>
        <Panel title="Activity" tools={<a className="goto" href={href("activity", null, { project: p.key })}>All →</a>}>
          <ul>{activity.filter((e) => e.project === p.key && meaningful(e)).slice(0, 12).map((e) => <ActivityRow key={e.seq} e={e} />)}</ul>
        </Panel>
      </div>
      <div className="stack">
        <Panel title="Agents" count={p.panes.length}>
          {p.panes.length ? <table className="tbl"><tbody>{p.panes.map((a) => <tr key={a.id} className="is-click" onClick={() => go("agents", a.id)}>
            <td className="mono">{a.agent_name || a.id}</td><td className="text2">{a.role}</td><td><AgentState status={a.status} /></td>
            <td className="mono-xs faint trunc" style={{ maxWidth: 200 }}>{a.cwd}</td></tr>)}</tbody></table> : <EmptyState title="No live agents." />}
          {p.team.filter((m) => !m.pane_id).length > 0 && <div className="panel-body is-pad mono-xs muted" style={{ borderTop: "1px solid var(--line)" }}>
            team via coordinator: {p.team.filter((m) => !m.pane_id).map((m) => `${m.name} (${m.model})`).join(" · ")}</div>}
        </Panel>
        <Panel title="Workspace access">
          <div className="panel-body is-pad" style={{ display: "grid", gap: 8 }}>
            <div className="row" style={{ flexWrap: "wrap" }}>
              {spaces.map((w) => <button key={w.id} type="button" className="btn is-sm" onClick={() => go("workspaces", w.id)}>Open {w.label || w.id}</button>)}
              {coord?.paneId && <button type="button" className="btn is-sm" onClick={() => workspace.focusAgent(coord.paneId!)}>Focus coordinator</button>}
              {!spaces.length && !coord?.paneId && <span className="muted">No herdr workspace for this project right now.</span>}
            </div>
            {coord?.paneId && <Command cmd={workspace.attachCommand(coord.name)} />}
          </div>
        </Panel>
        <Panel title="Branches & worktrees" count={wts.length}>
          <div className="panel-body is-pad" style={{ display: "grid", gap: 4 }}>
            <dl><DetailRow label="checkout"><span className="mono-xs">{p.path}</span></DetailRow></dl>
            {wts.map((w) => <div key={w} className="mono-xs text2 trunc" title={w}>{w}</div>)}
            {wts.length > 6 && <div className="warn-t">{wts.length} worktrees — over the limit. Cleanup is Jay's call; nothing is deleted automatically.</div>}
            {stale.map((s) => <div key={s.text} className="warn-t mono-xs">{s.text}</div>)}
            {!wts.length && !stale.length && <span className="muted">No lane worktrees.</span>}
          </div>
        </Panel>
        {p.handoff.length > 0 && <Panel title="Handoff"><div className="panel-body is-pad text2">{p.handoff.map((l, i) => <div key={i}>{l}</div>)}</div></Panel>}
      </div>
    </div>
  </div>;
}

function TicketOnlyProject({ k, name }: { k: string; name: string }) {
  const all = useSelector(app.store, (d) => d.tickets);
  const tickets = all.filter((t) => t.project === k && !t.archived);
  return <Panel title={name} count={tickets.length} meta="tickets only — no repository is polled for this project">
    <div className="panel-body is-pad"><a className="goto" href={href("tasks", null, { project: k })}>Open its tickets →</a></div>
  </Panel>;
}
