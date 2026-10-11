// DEVELOPMENT — one row per ticket that has work: branch, commits, PR, CI,
// review, merge, verify, deploy. The PR table lives here too, because a pull
// request is development, not its own section of the product.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href, go, useRoute } from "../lib/router";
import type { DevRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { EmptyState, Panel, Project, Seg, StateText, StaleIndicator } from "../components/ui";
import { DevTrail, Dash, ciStage, mergeStage, reviewCell } from "../components/DevTrail";
import { PullRequests } from "./PullRequests";

type View = "tickets" | "prs";

export function Development() {
  const route = useRoute();
  const dev = useSelector(app.store, (d) => d.development);
  const projects = useSelector(app.store, (d) => d.state?.projectsConfig ?? null);
  const seq = useSelector(app.store, (d) => d.state?.seq ?? 0);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>(route.params.get("project") || "all");
  const view = (route.params.get("view") as View) || "tickets";

  // Loaded on demand and refreshed whenever ccd's state moves, so a merged PR
  // or a new commit count appears without a reload.
  useEffect(() => { void app.refreshDevelopment(); }, []);
  useEffect(() => { if (seq) app.scheduleDevelopment(); }, [seq]);

  const setView = (v: View) => go("development", null, v === "tickets" ? undefined : { view: v });
  const head = <Seg<View> label="Development view" value={view} onChange={setView}
    options={[{ v: "tickets", label: "Tickets" }, { v: "prs", label: "Pull requests" }]} />;

  if (view === "prs") {
    return <div className="stack">
      <div className="row">{head}</div>
      <PullRequests />
    </div>;
  }

  const rows = (dev?.rows ?? []).filter((r) => filter === "all" || r.project === filter);
  const repoOf = (k: string) => projects?.find((p) => p.key === k)?.repo ?? null;
  const cols: Column<DevRow>[] = [
    { id: "k", header: "Ticket", cell: (r) => <a className="key" href={href("tasks", r.key)}
      onClick={(e) => e.stopPropagation()}>{r.key}</a>, sort: (a, b) => a.key.localeCompare(b.key) },
    { id: "t", header: "Title", className: "is-title", cell: (r) => <span className="t trunc">{r.title}</span> },
    { id: "p", header: "Project", cell: (r) => <Project k={r.project} />, sort: (a, b) => a.project.localeCompare(b.project) },
    { id: "s", header: "Status", cell: (r) => <StateText status={r.status} code /> },
    { id: "b", header: "Branch", cell: (r) => r.branch
      ? <span className="mono-xs trunc" title={`${r.branch.name} · ${r.branch.evidence}`}>{r.branch.name}</span>
      : <Dash why="no branch names this ticket" /> },
    { id: "c", header: "Commits", className: "is-num", cell: (r) => r.branch?.countOk && r.commits != null
      ? <span className="mono">{r.commits}</span> : <Dash why="not counted" />,
      sort: (a, b) => (a.commits ?? -1) - (b.commits ?? -1) },
    { id: "pr", header: "PR", cell: (r) => r.pr?.number != null
      ? <span className="row" style={{ gap: 6 }}>
        {r.pr.url ? <a className="mono link" href={r.pr.url} target="_blank" rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}>#{r.pr.number}</a> : <span className="mono">#{r.pr.number}</span>}
        <span className="mono-xs faint">{r.pr.state}</span></span>
      : <Dash why="no PR linked" /> },
    { id: "ci", header: "CI", cell: (r) => ciStage(r.ci) },
    { id: "rv", header: "Review", cell: (r) => reviewCell(r) },
    { id: "mg", header: "Merge", cell: (r) => mergeStage(r), sort: (a, b) =>
      Number(b.merge === "WAITING FOR JAY") - Number(a.merge === "WAITING FOR JAY") },
    { id: "vf", header: "Verify", cell: (r) => r.verify ? <span className="text2">{r.verify}</span> : <Dash /> },
    { id: "dp", header: "Deploy", cell: () => <Dash why="ccd observes no deployments" /> },
  ];
  const waiting = rows.filter((r) => r.merge === "WAITING FOR JAY").length;
  return <div className="stack">
    <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
      {head}
      <Seg label="Project" value={filter} onChange={setFilter}
        options={[{ v: "all", label: "All" }, ...(filter !== "all" && !projects?.some((p) => p.key === filter) ? [{ v: filter, label: filter }] : []), ...(projects ?? []).map((p) => ({ v: p.key, label: p.name }))]} />
    </div>
    <Panel title="Ticket development" count={rows.length}
      meta={<>{waiting ? <b className="jay-t">{waiting} waiting for Jay to merge</b> : "git as of "}
        {!waiting && <StaleIndicator at={dev?.gitAsOf} limitS={600} />}
        {" · "}strong evidence only: the ticket's branch, a branch whose leading segment is the key, or a linked PR</>}
      tools={<button type="button" className="btn is-quiet is-sm" onClick={() => void app.refreshDevelopment()}>Refresh</button>}>
      <div className="tbl-wrap"><DataTable label="Ticket development" rows={rows} columns={cols}
        rowKey={(r) => r.key} selected={open} expanded={open} initialSort={{ id: "mg", dir: 1 }}
        onSelect={(k) => setOpen(k === open ? null : k)}
        rowClass={(r) => (r.merge === "WAITING FOR JAY" ? "is-attn" : "")}
        renderExpansion={(r) => <div className="dev-expand">
          <DevTrail row={r} repo={repoOf(r.project)} />
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <a className="btn is-sm" href={href("tasks", r.key)}>Open {r.key}</a>
            <a className="btn is-sm" href={href("workspace", null, { project: r.project, ticket: r.key })}>Workspace</a>
          </div>
        </div>}
        empty={<EmptyState title={dev ? "No ticket has development work yet." : "Loading development…"}
          hint={dev ? "A branch or a linked PR puts a ticket here." : undefined} />} /></div>
    </Panel>
  </div>;
}
