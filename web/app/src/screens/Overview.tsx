// Five questions in five seconds: is the server healthy, what is working, what
// is blocked, what needs Jay, what changed. No KPI-card wall.
import { useMemo } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href, go } from "../lib/router";
import { jayQueue, PIPELINE, STATUS_META, CLOSED } from "../tickets/model";
import { Panel, AgentState, Project, EmptyState, Ago, StatusDot, Flags } from "../components/ui";
import { ActivityRow, meaningful } from "../components/Feed";
import { DataTable, type Column } from "../components/DataTable";
import { NeedsTable } from "./needs";
import { ServerMeters } from "./Server";
import { dur } from "../lib/time";
import type { Agent } from "../api/types";

export function Overview() {
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const activity = useSelector(app.store, (d) => d.activity);
  const queue = useMemo(() => jayQueue(st), [st]);
  if (!st) return <EmptyState title="Loading state from ccd…" />;
  const working = st.agents.filter((a) => a.status === "working");
  const blocked = st.agents.filter((a) => a.status === "blocked");
  const h = st.host;
  const memPct = h.memTotal ? Math.round((100 * (h.memUsed ?? 0)) / h.memTotal) : null;
  const healthBad = !st.sources.herdr.ok || (h.disk ?? 0) >= 85 || (h.swapPct ?? 0) >= 60 || (h.oomKills24h ?? 0) > 0;
  const openTickets = tickets.filter((t) => !t.archived && !CLOSED.has(t.status));
  const last = activity.filter(meaningful)[0];
  const agentCols: Column<Agent>[] = [
    { id: "p", header: "Project", cell: (a) => <Project k={a.project} name={st.projects.find((p) => p.key === a.project)?.name} /> },
    { id: "n", header: "Agent", cell: (a) => <span className="mono">{a.agent_name || a.id}</span> },
    { id: "r", header: "Role", cell: (a) => <span className="text2">{a.role}</span> },
    { id: "s", header: "State", cell: (a) => <AgentState status={a.status} /> },
    { id: "t", header: "For", className: "is-num", cell: (a) => a.blockedForMin != null
      ? <span className="mono-xs jay-t">{dur(a.blockedForMin * 60)}</span> : <span className="faint">—</span> },
  ];
  const active = [...blocked, ...working, ...st.agents.filter((a) => !["blocked", "working"].includes(a.status))];
  return <div className="ov">
    <section className="ov-glance" aria-label="At a glance">
      <a className={`glance${healthBad ? " is-bad" : ""}`} href={href("server")}>
        <span className="glance-q"><StatusDot tone={healthBad ? "failed" : "working"} />Server</span>
        <span className="glance-a">{healthBad ? (!st.sources.herdr.ok ? "herdr down" : "needs a look") : "healthy"}
          <span className="mono-xs muted"> · mem {memPct ?? "—"}% · disk {h.disk ?? "—"}%</span></span></a>
      <a className="glance" href={href("agents")}>
        <span className="glance-q"><StatusDot tone="working" />Working</span>
        <span className="glance-a">{working.length ? working.map((a) => a.agent_name || a.project).join(", ") : "nothing running"}</span></a>
      <a className={`glance${blocked.length ? " is-jay" : ""}`} href={href("agents")}>
        <span className="glance-q"><StatusDot tone="blocked" shape="square" />Blocked</span>
        <span className="glance-a">{blocked.length ? `${blocked.length} waiting for an answer` : "none"}</span></a>
      <a className={`glance${queue.length ? " is-jay" : ""}`} href="#needs">
        <span className="glance-q"><StatusDot tone="jay" />Needs Jay</span>
        <span className="glance-a">{queue.length ? `${queue.length} item${queue.length > 1 ? "s" : ""}` : "nothing"}</span></a>
      <a className="glance" href={href("activity")}>
        <span className="glance-q"><StatusDot tone="review" shape="ring" />Changed</span>
        <span className="glance-a">{last ? last.text : "quiet"}</span></a>
    </section>
    <div className="ov-cols">
      <div className="stack">
        <Panel id="needs" title="Needs Jay" count={queue.length} jay={queue.length > 0}
          meta={queue.length ? "blocked agents first, then merges, then flagged tickets" : undefined}
          tools={<a className="goto" href={href("tasks", null, { view: "jay" })}>Queue →</a>}>
          <NeedsTable items={queue.slice(0, 10)} />
        </Panel>
        <Panel id="agents" title="Active agents" count={st.agents.length}
          meta={`${working.length} working · ${blocked.length} blocked`} tools={<a className="goto" href={href("agents")}>All agents →</a>}>
          <div className="tbl-wrap"><DataTable label="Agents" rows={active.slice(0, 8)} columns={agentCols} rowKey={(a) => a.id}
            rowClass={(a) => (a.status === "blocked" ? "is-attn" : "")} onActivate={(k) => go("agents", k)}
            empty={<EmptyState title="No live agents" hint={st.sources.herdr.ok ? undefined : "herdr is unreachable"} />} /></div>
        </Panel>
        <Panel id="pipeline" title="Task pipeline" count={openTickets.length} tools={<a className="goto" href={href("tasks", null, { view: "board" })}>Board →</a>}>
          <div className="pipe-strip">{PIPELINE.map((s) => {
            const n = tickets.filter((t) => !t.archived && t.status === s).length;
            const m = STATUS_META[s];
            return <a key={s} className={`pipe-cell tone-${m.tone}`} href={href("tasks", null, { view: "list", status: s })}>
              <span className="caps muted trunc">{m.short}</span>
              <span className={`pipe-n${n ? "" : " is-zero"}`}>{n}</span>
              <span className="pipe-bar" style={{ opacity: n ? .85 : .15 }} aria-hidden />
            </a>;
          })}</div>
          {openTickets.some((t) => t.flags.length) && <div className="panel-body is-pad row" style={{ flexWrap: "wrap", borderTop: "1px solid var(--line)" }}>
            <span className="caps muted">flagged</span>
            {openTickets.filter((t) => t.flags.length).slice(0, 6).map((t) => <a key={t.key} href={href("tasks", t.key)} className="row">
              <span className="key">{t.key}</span><Flags flags={t.flags} /></a>)}
          </div>}
        </Panel>
      </div>
      <aside className="stack">
        <Panel id="server" title="Server health" meta={<>jay-server · <Ago at={h.asOf} /></>} tools={<a className="goto" href={href("server")}>Details →</a>}>
          <ServerMeters compact />
        </Panel>
        <Panel id="activity" title="Recent activity" tools={<a className="goto" href={href("activity")}>All →</a>}>
          <ul className="compact" aria-label="Recent activity">{activity.filter(meaningful).slice(0, 12).map((e) => <ActivityRow key={e.seq} e={e} />)}
            {!activity.length && <li><EmptyState title="No events yet" /></li>}</ul>
        </Panel>
      </aside>
    </div>
  </div>;
}
