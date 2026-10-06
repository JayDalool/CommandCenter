// OVERVIEW answers four questions and stops:
//
//   NEEDS JAY        what is waiting for him
//   ACTIVE WORK      what is being worked on right now
//   SYSTEM STATUS    is anything broken
//   RECENT ACTIVITY  what changed
//
// Everything else belongs to a section that owns it. No KPI wall, no widget
// Jay has to decode, nothing repeated from another page.
import { useMemo } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href } from "../lib/router";
import { jayQueue } from "../tickets/model";
import { Panel, AgentState, Project, EmptyState, StateText, StatusDot } from "../components/ui";
import { ActivityRow, meaningful } from "../components/Feed";
import { NeedsTable } from "./needs";
import { dur } from "../lib/time";

/** One line per thing that is wrong, in words. Empty means healthy. */
export function systemProblems(st: NonNullable<ReturnType<typeof app.store.get>["state"]>) {
  const h = st.host;
  const out: { id: string; text: string; where: string }[] = [];
  if (!st.sources.herdr.ok) out.push({ id: "herdr", text: "herdr is unreachable — agent state is unknown", where: "server" });
  Object.entries(st.sources.github ?? {}).forEach(([k, g]) => {
    if (g.error) out.push({ id: `gh:${k}`, text: `GitHub data for ${k} is stale`, where: "server" });
  });
  if ((h.disk ?? 0) >= 85) out.push({ id: "disk", text: `disk is ${h.disk}% full`, where: "server" });
  if ((h.swapPct ?? 0) >= 60) out.push({ id: "swap", text: `swap is ${Math.round(h.swapPct ?? 0)}% used`, where: "server" });
  if ((h.oomKills24h ?? 0) > 0) out.push({ id: "oom", text: `${h.oomKills24h} OOM kills in 24h`, where: "server" });
  (st.host.down ?? []).slice(0, 3).forEach((n) => out.push({ id: `c:${n}`, text: `container ${n} is not running`, where: "server" }));
  st.alerts.filter((a) => !a.ack).slice(0, 4).forEach((a) => out.push({ id: a.id, text: a.text, where: "alerts" }));
  return out;
}

export function Overview() {
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const activity = useSelector(app.store, (d) => d.activity);
  const queue = useMemo(() => jayQueue(st), [st]);
  if (!st) return <EmptyState title="Loading state from ccd…" />;

  const problems = systemProblems(st);
  const working = st.agents.filter((a) => a.status === "working");
  const blocked = st.agents.filter((a) => a.status === "blocked");
  // "Active work" is work, not agents: a ticket someone is on, or an agent that
  // is running without one.
  const live = [...blocked, ...working];
  const rows = live.map((a) => ({
    agent: a,
    ticket: tickets.find((t) => t.agentPaneId === a.id)
      ?? tickets.find((t) => t.project === a.project && t.status === "IN_PROGRESS" && t.assignee === `agent:${a.agent_name}`)
      ?? null,
  }));
  const open = tickets.filter((t) => !t.archived && ["IN_PROGRESS", "IN_REVIEW", "READY_TO_MERGE", "VERIFYING"].includes(t.status));
  const unattended = open.filter((t) => !rows.some((r) => r.ticket?.key === t.key));

  return <div className="ov2">
    <Panel id="needs" title="Needs Jay" count={queue.length} jay={queue.length > 0}
      meta={queue.length ? "blocked agents, then merges, then flagged tickets" : undefined}
      tools={<a className="goto" href={href("tasks", null, { view: "jay" })}>Full queue →</a>}>
      {queue.length ? <NeedsTable items={queue.slice(0, 8)} />
        : <div className="ov-clear"><StatusDot tone="done" /> Nothing is waiting for you.</div>}
    </Panel>

    <Panel id="active" title="Active work" count={rows.length + unattended.length}
      meta={`${working.length} working · ${blocked.length} blocked`}
      tools={<a className="goto" href={href("development")}>Development →</a>}>
      {rows.length ? <ul className="ov-work">
        {rows.map(({ agent, ticket }) => <li key={agent.id} className={agent.status === "blocked" ? "is-attn" : ""}>
          <AgentState status={agent.status} />
          <Project k={agent.project} name={st.projects.find((p) => p.key === agent.project)?.name} />
          {ticket ? <a className="key" href={href("tasks", ticket.key)}>{ticket.key}</a> : <span className="faint">no ticket</span>}
          <span className="trunc t">{ticket?.title ?? agent.agent_name ?? agent.id}</span>
          <span className="mono-xs muted">{agent.role}</span>
          {agent.blockedForMin != null && <span className="mono-xs jay-t">{dur(agent.blockedForMin * 60)}</span>}
          <a className="goto" href={href("workspace", null, { project: agent.project ?? undefined,
            ticket: ticket?.key, tab: agent.role === "coordinator" ? "claude" : undefined })}>Open →</a>
        </li>)}
      </ul> : null}
      {/* Tickets in flight with nobody on them: one line, not nine rows that
          repeat what Development already shows in full. */}
      {unattended.length > 0 && <div className="ov-more">
        <StateText status={unattended[0].status} code />
        <span className="trunc">{unattended.length} open ticket{unattended.length > 1 ? "s" : ""} with no agent on
          {" "}{unattended.length > 1 ? "them" : "it"}: {unattended.slice(0, 4).map((t) => t.key).join(", ")}
          {unattended.length > 4 ? "…" : ""}</span>
        <a className="goto" style={{ marginLeft: "auto" }} href={href("development")}>Development →</a>
      </div>}
      {!rows.length && !unattended.length
        ? <div className="ov-clear"><StatusDot tone="idle" shape="ring" /> Nothing is running.</div> : null}
    </Panel>

    <Panel id="status" title="System status" count={problems.length || undefined}
      meta={problems.length ? undefined : "herdr, GitHub, git and the host all answering"}
      tools={<a className="goto" href={href("server")}>Server →</a>}>
      {problems.length ? <ul className="ov-problems">{problems.map((p) => <li key={p.id}>
        <StatusDot tone="failed" shape="square" />
        <span className="trunc">{p.text}</span>
        <a className="goto" href={href(p.where)}>Look →</a></li>)}</ul>
        : <div className="ov-clear"><StatusDot tone="working" /> Everything is answering.</div>}
    </Panel>

    <Panel id="activity" title="Recent activity" tools={<a className="goto" href={href("activity")}>All →</a>}>
      <ul className="compact" aria-label="Recent activity">
        {activity.filter(meaningful).slice(0, 10).map((e) => <ActivityRow key={e.seq} e={e} />)}
        {!activity.length && <li><EmptyState title="No events yet" /></li>}
      </ul>
    </Panel>
  </div>;
}
