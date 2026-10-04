import { useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
const NO_TYPES: string[] = [];
import { go, useRoute } from "../lib/router";
import { typing } from "../components/Shell";
import type { Ticket, TicketStatus, Priority } from "../api/types";
import { PRIORITIES } from "../api/types";
import { filterTickets, sortTickets, groupByStatus, stepStatus, PIPELINE, OFF, ALL_STATUSES, STATUS_META, PRIORITY_META,
  jayQueue, openCounts, PROJECT_CHIP_ORDER, type TicketFilter } from "../tickets/model";
import { DataTable, type Column } from "../components/DataTable";
import { StateText, PriorityMark, Assignee, Project, Flags, Ago, EmptyState, Seg, Kbd } from "../components/ui";
import { TicketDetailPane } from "./TicketDetail";
import { NeedsTable } from "./needs";

type View = "list" | "board" | "jay" | "inbox";

export function Tasks() {
  const route = useRoute();
  const view = (route.params.get("view") as View) || "list";
  const openKey = route.id;
  const tickets = useSelector(app.store, (d) => d.tickets);
  const loaded = useSelector(app.store, (d) => d.ticketsLoaded);
  const projects = useSelector(app.store, (d) => d.taskProjects);
  const types = useSelector(app.store, (d) => d.meta?.types ?? NO_TYPES);
  const st = useSelector(app.store, (d) => d.state);
  const [f, setF] = useState<TicketFilter>(() => ({
    project: route.params.get("project") ? [route.params.get("project")!] : [],
    status: route.params.get("status") ? [route.params.get("status") as TicketStatus] : [],
  }));
  const archivedTickets = useSelector(app.store, (d) => d.archivedTickets);
  const [history, setHistory] = useState(false);
  const [sel, setSel] = useState<string | null>(openKey);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const focus = () => search.current?.focus();
    window.addEventListener("cc:focus-search", focus);
    return () => window.removeEventListener("cc:focus-search", focus);
  }, []);
  useEffect(() => { if (openKey) setSel(openKey); }, [openKey]);

  const nav = (patch: { view?: View; key?: string | null }) => {
    const p: Record<string, string | undefined> = { view: (patch.view ?? view) === "list" ? undefined : patch.view ?? view };
    go("tasks", patch.key === undefined ? openKey : patch.key, p);
  };

  useEffect(() => { if (history) void app.loadHistory().catch(() => {}); }, [history]);
  // ALL projects by default; History adds archived (and closed) tickets to the same list.
  const pool = useMemo(() => {
    if (!history) return tickets;
    const seen = new Set(tickets.map((t) => t.key));
    return [...tickets, ...archivedTickets.filter((t) => !seen.has(t.key))];
  }, [tickets, archivedTickets, history]);
  const base = useMemo(() => {
    const ff: TicketFilter = { ...f, includeArchived: history };
    if (view === "inbox") ff.status = ["INBOX", "PROPOSED"];
    return filterTickets(pool, ff);
  }, [pool, f, view, history]);
  const open = useMemo(() => openCounts(tickets), [tickets]);
  const chips = useMemo(() => {
    const rank = (p: { key: string }) => { const i = PROJECT_CHIP_ORDER.indexOf(p.key); return i < 0 ? 99 : i; };
    return [...projects].sort((a, b) => rank(a) - rank(b) || a.prefix.localeCompare(b.prefix));
  }, [projects]);
  const rows = useMemo(() => sortTickets(base, "status"), [base]);
  const labels = useMemo(() => [...new Set(tickets.flatMap((t) => t.labels))].sort(), [tickets]);
  const assignees = useMemo(() => [...new Set(tickets.map((t) => t.assignee ?? "none"))].sort(), [tickets]);
  const counts = useMemo(() => ({
    list: filterTickets(tickets, {}).length,
    inbox: tickets.filter((t) => !t.archived && (t.status === "INBOX" || t.status === "PROPOSED")).length,
    jay: jayQueue(st).length,
  }), [tickets, st]);

  // Board/list keyboard: Shift+←/→ moves the selected ticket one pipeline step.
  const move = async (t: Ticket, dir: -1 | 1) => {
    const to = stepStatus(t.status, dir);
    if (to === t.status) return;
    await app.mutate(() => app.api.updateTask(t.key, { status: to }), `${t.key} → ${STATUS_META[to].label}`).catch(() => {});
  };
  const onKeyExtra = (e: React.KeyboardEvent, t: Ticket) => {
    if (e.shiftKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) { e.preventDefault(); void move(t, e.key === "ArrowRight" ? 1 : -1); return true; }
    if (e.key === "Escape" && openKey) { e.preventDefault(); nav({ key: null }); return true; }
    return false;
  };

  const cols: Column<Ticket>[] = [
    { id: "id", header: "ID", cell: (t) => <span className="key">{t.key}</span>, sort: (a, b) => a.project.localeCompare(b.project) || a.number - b.number },
    { id: "title", header: "Title", className: "is-title", cell: (t) => <span className="row"><span className="t trunc" title={t.title}>{t.title}</span>
      {t.labels.slice(0, 2).map((l) => <span key={l} className="label">{l}</span>)}
      {t.subtasks.total > 0 && <span className="mono-xs muted">{t.subtasks.done}/{t.subtasks.total}</span>}</span>, sort: (a, b) => a.title.localeCompare(b.title) },
    { id: "status", header: "Status", cell: (t) => <StateText status={t.status} />, sort: (a, b) => ALL_STATUSES.indexOf(a.status) - ALL_STATUSES.indexOf(b.status) },
    { id: "prio", header: "Pri", cell: (t) => <PriorityMark p={t.priority} />, sort: (a, b) => PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank },
    { id: "project", header: "Project", cell: (t) => <Project k={t.project} />, sort: (a, b) => a.project.localeCompare(b.project) },
    { id: "assignee", header: "Assignee", cell: (t) => <Assignee value={t.assignee} />, sort: (a, b) => (a.assignee ?? "~").localeCompare(b.assignee ?? "~") },
    { id: "updated", header: "Updated", className: "is-num", cell: (t) => <Ago at={t.updatedAt} />, sort: (a, b) => a.updatedAt - b.updatedAt },
    { id: "pr", header: "PR", cell: (t) => t.prNumber ? <span className="mono">#{t.prNumber}</span> : <span className="faint">—</span>,
      sort: (a, b) => (a.prNumber ?? 0) - (b.prNumber ?? 0) },
    { id: "flags", header: "Flags", cell: (t) => <span className="row">{t.blockedBy.length > 0 && <span className="flag" style={{ color: "var(--st-blocked)" }}>blocked</span>}<Flags flags={t.flags} /></span> },
  ];

  const toggle = <K extends keyof TicketFilter>(k: K, v: TicketFilter[K]) => setF((x) => ({ ...x, [k]: x[k] === v ? undefined : v }));
  const pick = (k: "project" | "status" | "priority" | "type" | "assignee" | "label", v: string) =>
    setF((x) => ({ ...x, [k]: v ? [v] : [] }));
  const active = Object.entries(f).filter(([, v]) => (Array.isArray(v) ? v.length : v)).length;

  return <div className="tasks">
    <div className="tasks-bar">
      <Seg<View> label="View" value={view} onChange={(v) => nav({ view: v })} options={[
        { v: "list", label: "Table", n: counts.list }, { v: "board", label: "Pipeline" },
        { v: "jay", label: "Needs Jay", n: counts.jay }, { v: "inbox", label: "Inbox", n: counts.inbox }]} />
      <label className="search"><span className="sr">Search tasks</span>
        <input ref={search} className="input" type="search" placeholder="Search key, title, label, #PR" value={f.q ?? ""}
          onChange={(e) => setF((x) => ({ ...x, q: e.target.value }))}
          onKeyDown={(e) => { if (e.key === "Escape") { (e.target as HTMLInputElement).blur(); } }} /></label>
      <span className="muted mono-xs">{rows.length} shown</span>
      <span style={{ marginLeft: "auto" }} className="row muted mono-xs"><Kbd>/</Kbd> search <Kbd>j</Kbd><Kbd>k</Kbd> move
        <Kbd>Enter</Kbd> open <Kbd>⇧←→</Kbd> status <Kbd>N</Kbd> new</span>
    </div>
    {view !== "jay" && <div className="filters" role="group" aria-label="Filters">
      <span className="row" role="group" aria-label="Project" style={{ gap: 4 }}>
        <button type="button" className="fchip" aria-pressed={!f.project?.length} onClick={() => pick("project", "")}>
          ALL <span className="mono-xs">{[...open.values()].reduce((a, b) => a + b, 0)}</span></button>
        {chips.map((p) => <button key={p.key} type="button" className="fchip" aria-pressed={f.project?.[0] === p.key}
          title={p.name} onClick={() => pick("project", p.key)}>{p.prefix} <span className="mono-xs">{open.get(p.key) ?? 0}</span></button>)}
      </span>
      {view !== "inbox" && <select className={`fsel${f.status?.length ? " is-on" : ""}`} value={f.status?.[0] ?? ""} onChange={(e) => pick("status", e.target.value)} aria-label="Status">
        <option value="">Open statuses</option>{ALL_STATUSES.map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}</select>}
      <select className={`fsel${f.priority?.length ? " is-on" : ""}`} value={f.priority?.[0] ?? ""} onChange={(e) => pick("priority", e.target.value)} aria-label="Priority">
        <option value="">Any priority</option>{PRIORITIES.map((p: Priority) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}</select>
      <select className={`fsel${f.type?.length ? " is-on" : ""}`} value={f.type?.[0] ?? ""} onChange={(e) => pick("type", e.target.value)} aria-label="Type">
        <option value="">Any type</option>{types.map((t) => <option key={t} value={t}>{t.toLowerCase().replace("_", " ")}</option>)}</select>
      <select className={`fsel${f.assignee?.length ? " is-on" : ""}`} value={f.assignee?.[0] ?? ""} onChange={(e) => pick("assignee", e.target.value)} aria-label="Assignee">
        <option value="">Anyone</option>{assignees.map((a) => <option key={a} value={a}>{a === "none" ? "Unassigned" : a}</option>)}</select>
      {labels.length > 0 && <select className={`fsel${f.label?.length ? " is-on" : ""}`} value={f.label?.[0] ?? ""} onChange={(e) => pick("label", e.target.value)} aria-label="Label">
        <option value="">Any label</option>{labels.map((l) => <option key={l} value={l}>{l}</option>)}</select>}
      <button type="button" className="fchip is-jay" aria-pressed={!!f.needsJay} onClick={() => toggle("needsJay", true)}>needs Jay</button>
      <button type="button" className="fchip" aria-pressed={!!f.blocked} onClick={() => toggle("blocked", true)}>blocked</button>
      <button type="button" className="fchip" aria-pressed={!!f.hasPr} onClick={() => setF((x) => ({ ...x, hasPr: !x.hasPr, noPr: false }))}>has PR</button>
      <button type="button" className="fchip" aria-pressed={!!f.noPr} onClick={() => setF((x) => ({ ...x, noPr: !x.noPr, hasPr: false }))}>no PR</button>
      <button type="button" className="fchip" aria-pressed={!!f.includeClosed} onClick={() => toggle("includeClosed", true)}>show closed</button>
      <button type="button" className="fchip" aria-pressed={history} onClick={() => setHistory((h) => !h)}>Include archived/history</button>
      {(active > 0 || history) && <button type="button" className="btn is-quiet is-sm" onClick={() => { setF({}); setHistory(false); }}>Clear</button>}
    </div>}
    <div className={`tasks-body${openKey ? " has-detail" : ""}`}>
      <div className="tasks-list">
        {!loaded ? <EmptyState title="Loading tickets…" />
          : view === "jay" ? <div style={{ padding: 16 }}><NeedsTable items={jayQueue(st)} /></div>
          : view === "board" ? <Board rows={base} selected={sel} onOpen={(k) => nav({ key: k })} onMove={move} />
          : <DataTable label="Tasks" rows={rows} columns={cols} rowKey={(t) => t.key} selected={sel} onSelect={(k) => setSel(k)}
              onActivate={(k) => nav({ key: k })} onKeyExtra={onKeyExtra} initialSort={{ id: "status", dir: 1 }}
              empty={<EmptyState title={tickets.length ? "No ticket matches these filters." : "No tickets yet."}
                hint={tickets.length ? "Clear filters, or press N to capture one." : "Press N to capture the first one."} />} />}
      </div>
      {openKey && <TicketDetailPane ticketKey={openKey} onClose={() => nav({ key: null })} />}
    </div>
  </div>;
}

/** Compact pipeline: one column per status, rows not cards. */
function Board({ rows, selected, onOpen, onMove }: { rows: Ticket[]; selected: string | null; onOpen: (k: string) => void;
  onMove: (t: Ticket, dir: -1 | 1) => void }) {
  const groups = useMemo(() => groupByStatus(rows), [rows]);
  const cols = [...PIPELINE, ...OFF].filter((s) => (OFF as readonly string[]).includes(s) ? (groups.get(s)?.length ?? 0) > 0 : true);
  const ref = useRef<HTMLDivElement>(null);
  const onKey = (e: React.KeyboardEvent, t: Ticket) => {
    if (typing(e)) return;
    if (e.shiftKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) { e.preventDefault(); onMove(t, e.key === "ArrowRight" ? 1 : -1); return; }
    const all = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>(".trow") ?? []);
    const i = all.findIndex((el) => el.dataset.key === t.key);
    const col = (e.currentTarget as HTMLElement).closest(".col");
    const inCol = Array.from(col?.querySelectorAll<HTMLButtonElement>(".trow") ?? []);
    const ci = inCol.findIndex((el) => el.dataset.key === t.key);
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); inCol[ci + 1]?.focus(); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); inCol[ci - 1]?.focus(); }
    else if (e.key === "ArrowRight" || e.key === "l") { e.preventDefault(); (col?.nextElementSibling?.querySelector(".trow") as HTMLElement | null)?.focus(); }
    else if (e.key === "ArrowLeft" || e.key === "h") { e.preventDefault(); (col?.previousElementSibling?.querySelector(".trow") as HTMLElement | null)?.focus(); }
    void i;
  };
  return <div className="board" ref={ref} role="list" aria-label="Pipeline">
    {cols.map((s) => {
      const list = groups.get(s) ?? [];
      const m = STATUS_META[s];
      return <section key={s} className={`col${(OFF as readonly string[]).includes(s) ? " is-off" : ""}`} role="listitem" aria-label={`${m.label}, ${list.length}`}>
        <header className="col-head"><StateText status={s} /><span className="col-n">{list.length}</span></header>
        <div className="col-list">{list.map((t) => <button key={t.key} type="button" className="trow" data-key={t.key}
          aria-selected={selected === t.key} onClick={() => onOpen(t.key)} onKeyDown={(e) => onKey(e, t)}>
          <span className="trow-top"><PriorityMark p={t.priority} /><span className="key">{t.key}</span>
            <span style={{ marginLeft: "auto" }}><Assignee value={t.assignee} compact /></span></span>
          <span className="trow-title">{t.title}</span>
          {(t.flags.length > 0 || t.prNumber || t.blockedBy.length > 0) && <span className="trow-meta">
            {t.prNumber && <span className="mono-xs">#{t.prNumber}</span>}
            {t.blockedBy.length > 0 && <span className="flag" style={{ color: "var(--st-blocked)" }}>blocked</span>}
            <Flags flags={t.flags} /></span>}
        </button>)}
          {!list.length && <div className="faint mono-xs" style={{ padding: "6px 4px" }}>—</div>}</div>
      </section>;
    })}
  </div>;
}
