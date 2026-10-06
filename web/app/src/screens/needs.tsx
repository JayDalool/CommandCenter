import { app } from "../store/app";
import { href } from "../lib/router";
import type { JayItem } from "../tickets/model";
import { Project, EmptyState, Ago, Flags } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { openAgent } from "../lib/openAgent";

export function NeedsTable({ items }: { items: JayItem[] }) {
  const cols: Column<JayItem>[] = [
    { id: "v", header: "Do", cell: (j) => <span className={`flag${j.kind === "answer" ? "" : ""}`}
      style={j.kind === "answer" ? { color: "var(--st-blocked)", borderColor: "var(--st-blocked)", background: "transparent" } : undefined}>{j.verb.toUpperCase()}</span> },
    { id: "p", header: "Project", cell: (j) => <Project k={j.project} /> },
    { id: "r", header: "Ref", cell: (j) => j.kind === "ticket" ? <a className="key" href={href("tasks", j.ref)}>{j.ref}</a>
      : <span className="mono">{j.ref}</span> },
    { id: "t", header: "What", className: "is-title", cell: (j) => <span className="row"><span className="t trunc" title={j.text}>{j.text}</span><Flags flags={j.flags} /></span> },
    { id: "s", header: "Waiting", className: "is-num", cell: (j) => <Ago at={j.since} /> },
  ];
  return <div className="tbl-wrap"><DataTable label="Needs Jay" rows={items} columns={cols} rowKey={(j) => j.id}
    onActivate={(_, j) => {
      if (j.kind === "answer" && j.agentId) openAgent(j.agentId);
      else if (j.kind === "ticket" || j.kind === "gate") location.hash = href("tasks", j.ref);
      else if (j.url) window.open(j.url, "_blank", "noopener");
      else if (j.kind === "merge") location.hash = href("development");
      else app.toast(`${j.project}: ${j.text}`);
    }}
    empty={<EmptyState title="Nothing waits on you." hint="blocked agents, merges and flagged tickets land here" />} /></div>;
}
