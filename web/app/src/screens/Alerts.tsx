import { app } from "../store/app";
import { useSelector } from "../lib/store";
import type { Alert } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { Panel, EmptyState, Ago, Project } from "../components/ui";

export function Alerts() {
  const alerts = useSelector(app.store, (d) => d.state?.alerts ?? null);
  if (!alerts) return <EmptyState title="Loading…" />;
  const cols: Column<Alert>[] = [
    { id: "s", header: "Severity", cell: (a) => <span className={`caps ${a.severity === "action" ? "jay-t" : a.severity === "warn" ? "warn-t" : "muted"}`}>{a.severity}</span> },
    { id: "src", header: "Source", cell: (a) => <span className="mono-xs text2">{a.source}</span> },
    { id: "p", header: "Project", cell: (a) => <Project k={a.project} /> },
    { id: "m", header: "Message", className: "is-title", cell: (a) => <span className="t">{a.text}</span> },
    { id: "since", header: "Since", className: "is-num", cell: (a) => <Ago at={a.since} />, sort: (a, b) => a.since - b.since },
    { id: "ack", header: "Acknowledged", cell: (a) => a.ack ? <span className="muted mono-xs">yes · <Ago at={a.ackAt} /></span>
      : <button type="button" className="btn is-sm" onClick={(e) => { e.stopPropagation(); void app.action(() => app.api.ack(a.id), "Acknowledged").then(() => app.scheduleState(0)); }}>Acknowledge</button> },
  ];
  const sorted = [...alerts].sort((a, b) => Number(a.ack) - Number(b.ack) || b.since - a.since);
  return <Panel title="Alerts" count={alerts.filter((a) => !a.ack).length} meta="active alerts; an alert that clears and returns starts unacknowledged">
    <div className="tbl-wrap"><DataTable label="Alerts" rows={sorted} columns={cols} rowKey={(a) => a.id} rowClass={(a) => (a.ack ? "" : "is-attn")}
      empty={<EmptyState title="No active alerts." />} /></div>
  </Panel>;
}
