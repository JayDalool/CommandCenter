import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href, useRoute } from "../lib/router";
import type { PrRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { Project, Ci, EmptyState, Panel, StaleIndicator } from "../components/ui";

interface Row extends PrRow { project: string; repo: string; ticket: string | null }

export function jayAction(pr: PrRow): { text: string; cls: string } {
  if (pr.draft) return { text: "—", cls: "faint" };
  if (pr.ready) return { text: "JAY MUST MERGE", cls: "flag" };
  if (pr.ci === "✗") return { text: "checks failing", cls: "bad-t" };
  if (pr.review === "CHANGES_REQUESTED") return { text: "changes requested", cls: "warn-t" };
  if (pr.mergeable === "CONFLICTING") return { text: "conflicts", cls: "bad-t" };
  return { text: "agents reviewing", cls: "muted" };
}

export function PullRequests() {
  const route = useRoute();
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  if (!st) return <EmptyState title="Loading…" />;
  const rows: Row[] = st.projects.flatMap((p) => p.prs.map((pr) => ({ ...pr, project: p.key, repo: p.repo,
    ticket: tickets.find((t) => t.project === p.key && t.prNumber === pr.number)?.key ?? (pr.ref?.match(/^[A-Z]+-\d+$/) ? pr.ref : null) })));
  const cols: Column<Row>[] = [
    { id: "n", header: "PR", cell: (r) => r.url ? <a className="mono link" href={r.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>#{r.number}</a> : <span className="mono">#{r.number}</span>, sort: (a, b) => a.number - b.number },
    { id: "p", header: "Project", cell: (r) => <Project k={r.project} />, sort: (a, b) => a.project.localeCompare(b.project) },
    { id: "t", header: "Title", className: "is-title", cell: (r) => <span className="row"><span className="t trunc">{r.title}</span>{r.draft && <span className="label">draft</span>}</span> },
    { id: "k", header: "Task", cell: (r) => r.ticket ? <a className="key" href={href("tasks", r.ticket)} onClick={(e) => e.stopPropagation()}>{r.ticket}</a> : <span className="faint">—</span> },
    { id: "h", header: "Head", cell: (r) => <span className="mono-xs text2">{r.branch ?? "—"} <span className="faint">{r.sha}</span></span> },
    { id: "c", header: "CI", cell: (r) => <Ci mark={r.ci} /> },
    { id: "r", header: "Review", cell: (r) => <span className={r.review === "APPROVED" ? "ok-t" : r.review === "CHANGES_REQUESTED" ? "warn-t" : "muted"}>
      {r.review ? r.review.toLowerCase().replace("_", " ") : "none"}</span> },
    { id: "m", header: "Mergeability", cell: (r) => <span className={r.mergeable === "CONFLICTING" ? "bad-t" : r.mergeable === "MERGEABLE" ? "text2" : "faint"}>{r.mergeable?.toLowerCase() ?? "unknown"}</span> },
    { id: "j", header: "Jay action", cell: (r) => { const j = jayAction(r); return <span className={j.cls}>{j.text}</span>; },
      sort: (a, b) => Number(b.ready) - Number(a.ready) },
    { id: "a", header: "Idle", className: "is-num", cell: (r) => <span className="mono-xs muted">{r.age_h < 1 ? "<1h" : `${Math.round(r.age_h)}h`}</span>, sort: (a, b) => a.age_h - b.age_h },
  ];
  const ghAsOf = Math.min(...Object.values(st.sources.github).map((g) => g.asOf ?? 0));
  return <Panel title="Pull requests" count={rows.length} meta={<>GitHub as of <StaleIndicator at={ghAsOf} limitS={300} /> · merging happens in GitHub or the coordinator's pane, not here</>}>
    <div className="tbl-wrap"><DataTable label="Pull requests" rows={rows} columns={cols} rowKey={(r) => `${r.project}#${r.number}`}
      selected={route.id} initialSort={{ id: "j", dir: 1 }} onActivate={(_, r) => r.url && window.open(r.url, "_blank", "noopener")}
      rowClass={(r) => (r.ready ? "is-attn" : "")} empty={<EmptyState title="No open pull requests." />} /></div>
  </Panel>;
}
