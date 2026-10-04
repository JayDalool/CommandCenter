import { useMemo, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import type { Agent } from "../api/types";
import { ticketForAgent } from "../tickets/model";
import { DataTable, type Column } from "../components/DataTable";
import { AgentState, Project, EmptyState, Panel, Command, StateText, DetailRow } from "../components/ui";
import { usePrefs } from "../lib/prefs";
import { workspace } from "../workspace/transport";
import { dur, nowS } from "../lib/time";

export function modelOf(a: Agent, cfg: { key: string; model?: string; effort?: string }[]): string {
  if (a.role !== "coordinator") return "—";  // herdr does not report a lane's model
  const p = cfg.find((c) => c.key === a.project);
  return p?.model ? `${p.model}${p.effort ? "/" + p.effort : ""}` : "—";
}

export function Agents() {
  const route = useRoute();
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const activity = useSelector(app.store, (d) => d.activity);
  const host = usePrefs((p) => p.sshHost);
  const [expanded, setExpanded] = useState<string | null>(route.id);
  const lastEvent = useMemo(() => {
    const m = new Map<string, { at: number; text: string }>();
    for (const e of activity) if (e.agentId && !m.has(e.agentId)) m.set(e.agentId, { at: e.at, text: e.text });
    return m;
  }, [activity]);
  if (!st) return <EmptyState title="Loading…" />;
  const order = { blocked: 0, working: 1, unknown: 2, idle: 3, done: 4 } as Record<string, number>;
  const rows = [...st.agents].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || (a.project ?? "").localeCompare(b.project ?? ""));
  const cols: Column<Agent>[] = [
    { id: "p", header: "Project", cell: (a) => <Project k={a.project} name={st.projects.find((p) => p.key === a.project)?.name} />,
      sort: (a, b) => (a.project ?? "").localeCompare(b.project ?? "") },
    { id: "n", header: "Agent", cell: (a) => <span className="mono">{a.agent_name || "—"}</span> },
    { id: "r", header: "Role", cell: (a) => <span className="text2">{a.role}</span> },
    { id: "m", header: "Model", cell: (a) => <span className="mono-xs text2">{modelOf(a, st.projectsConfig)}</span> },
    { id: "s", header: "State", cell: (a) => <AgentState status={a.status} />, sort: (a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) },
    { id: "t", header: "Task", cell: (a) => { const t = ticketForAgent(tickets, a); return t ? <a className="key" href={href("tasks", t.key)} onClick={(e) => e.stopPropagation()}>{t.key}</a> : <span className="faint">—</span>; } },
    { id: "b", header: "Branch", cell: (a) => { const t = ticketForAgent(tickets, a); return <span className="mono-xs text2">{t?.branch ?? "—"}</span>; } },
    { id: "pr", header: "PR", cell: (a) => { const t = ticketForAgent(tickets, a); return t?.prNumber ? <span className="mono">#{t.prNumber}</span> : <span className="faint">—</span>; } },
    { id: "e", header: "Elapsed", className: "is-num", cell: (a) => a.blockedForMin != null ? <span className="mono-xs jay-t">{dur(a.blockedForMin * 60)}</span>
      : <span className="mono-xs muted">{lastEvent.get(a.id) ? dur(nowS() - lastEvent.get(a.id)!.at) : "—"}</span> },
    { id: "l", header: "Last event", className: "is-title", cell: (a) => <span className="t muted trunc">{lastEvent.get(a.id)?.text ?? "—"}</span> },
    { id: "pane", header: "Pane", cell: (a) => <span className="mono-xs faint">{a.id}</span> },
  ];
  return <div className="stack">
    {st.herdr_error && <div className="banner is-offline" role="status"><span className="caps">herdr</span>{st.herdr_error} — agents below are the last known set; their state is unknown.</div>}
    <Panel title="Agents" count={rows.length} meta={`${rows.filter((a) => a.status === "working").length} working · ${rows.filter((a) => a.status === "blocked").length} blocked`}>
      <div className="tbl-wrap"><DataTable label="Agents" rows={rows} columns={cols} rowKey={(a) => a.id} selected={expanded}
        expanded={expanded} onSelect={(k) => setExpanded(k)} onActivate={(k) => { setExpanded(expanded === k ? null : k); go("agents", expanded === k ? null : k); }}
        rowClass={(a) => (a.status === "blocked" ? "is-attn" : "")}
        renderExpansion={(a) => <AgentExpansion a={a} host={host} />}
        empty={<EmptyState title="No live agents" hint={st.sources.herdr.ok ? "herdr reports no agent panes" : "herdr unreachable"} />} /></div>
    </Panel>
  </div>;
}

function AgentExpansion({ a, host }: { a: Agent; host: string }) {
  const st = app.data.state!;
  const q = st.blocked.find((b) => b.pane_id === a.id);
  const t = ticketForAgent(app.data.tickets, a);
  const ws = st.workspaces?.find((w) => w.id === a.workspace_id);
  return <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, padding: "10px 14px" }}>
    <dl>
      <DetailRow label="cwd"><span className="mono-xs">{a.cwd || "—"}</span></DetailRow>
      <DetailRow label="workspace"><span className="mono-xs">{a.workspace || "—"} · {a.workspace_id} / {a.tab_id}</span></DetailRow>
      <DetailRow label="session"><span className="mono-xs faint">{a.session_id || "—"}</span></DetailRow>
      {t && <DetailRow label="ticket"><span className="row"><a className="key" href={href("tasks", t.key)}>{t.key}</a><StateText status={t.status} /><span className="trunc">{t.title}</span></span></DetailRow>}
      {q && <DetailRow label="question"><span className="jay-t">{q.question}</span></DetailRow>}
    </dl>
    <div style={{ display: "grid", gap: 8, alignContent: "start" }}>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button type="button" className="btn is-sm" onClick={() => workspace.focusAgent(a.id)}>Focus in herdr</button>
        <button type="button" className="btn is-sm" onClick={() => window.dispatchEvent(new CustomEvent("cc:console", { detail: a.id }))}>Read tail</button>
        {q && <button type="button" className="btn is-jay is-sm" onClick={() => window.dispatchEvent(new CustomEvent("cc:console", { detail: a.id }))}>Answer…</button>}
        {ws && <button type="button" className="btn is-sm" onClick={() => go("workspaces", ws.id)}>Open workspace</button>}
      </div>
      {a.agent_name && <Command cmd={workspace.attachCommand(a.agent_name)} />}
      <span className="muted mono-xs">Interactive: run in Windows Terminal ({host}). This page only reads.</span>
    </div>
  </div>;
}
