// DASHBOARD — the manager's morning / night view (spec §4, docs/design/dashboard-reference.webp).
//
// One equal panel per registered project, in its colour. Each answers, and only answers:
//   Latest update   what the agents did last (night / morning shift)
//   Needs Jay       only the decisions and actions that wait on him
//   Active work     counts by stage, and what is ready to merge
//   Went live       meaningful deployments, when there were any
//   Blockers        meaningful blockers, when there are any
// No repository statistics, KPIs, charts, commit or file counts, no diagnostics.
import { useMemo } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href } from "../lib/router";
import { jayQueue, type JayItem } from "../tickets/model";
import { byProjectOrder, greeting, initials, isActive, jayHref, jayWords, pjVar, stageOf, taskHref } from "../lib/control";
import type { CcdEvent, Ticket } from "../api/types";
import { ago, nowS } from "../lib/time";
import { useTick } from "../components/Shell";
import { NotificationBell } from "../components/Notifications";
import { DevDot } from "../components/DevMode";
import { EmptyState } from "../components/ui";
import { NightShiftButton, TaskCheckButton } from "../components/TaskCheck";
import { NightLine, useNightShift } from "../components/NightShift";
import type { NightShiftState } from "../api/types";

/** Events worth a manager's eye: work moving, PRs, CI, deployments, questions. Not agent chatter. */
export function newsworthy(e: CcdEvent): boolean {
  if (e.kind === "task.pipeline") return !["pipeline.role", "pipeline.handoff", "pipeline.writer", "pipeline.finding"]
    .includes(String(e.data?.kind ?? ""));
  if (e.kind === "task.updated") return (e.data as { kind?: string })?.kind === "status";
  return ["task.created", "pr.opened", "pr.closed", "pr.ci_changed", "ci.main_changed", "agent.blocked",
    "jay.action_required"].includes(e.kind);
}

const PHRASE: Record<string, string> = { READY_TO_MERGE: "ready to merge", IN_REVIEW: "in review", VERIFYING: "merged — verifying",
  DONE: "completed", IN_PROGRESS: "implementation started", BLOCKED: "blocked", RESEARCHING: "planning",
  READY_TO_IMPLEMENT: "plan accepted", CANCELLED: "cancelled", DENIED: "denied" };

/** An event in a manager's words: "SV-042 ready to merge", not "status IN_REVIEW → READY_TO_MERGE". */
export function newsText(e: CcdEvent): string {
  const d = e.data as { kind?: string; to?: string };
  if (e.kind === "task.updated" && d?.kind === "status" && d.to) return `${e.ref ?? ""} ${PHRASE[d.to] ?? d.to.toLowerCase().replace(/_/g, " ")}`.trim();
  return e.text;
}

const night = (at: number) => { const h = new Date(at * 1000).getHours(); return h >= 22 || h < 7; };
const shiftOf = (at: number) => (night(at) ? "night shift" : new Date(at * 1000).getHours() < 12 ? "morning shift" : "day shift");

function Mark({ e }: { e: CcdEvent }) {
  const k = String(e.data?.kind ?? e.kind);
  const glyph = /deployed|merged|done|verified|ready_to_merge/.test(k) ? "✓" : /blocked|failed|ci/.test(k) ? "!"
    : /questions|gate/.test(k) ? "?" : "•";
  return <span className={`dash-mark${glyph === "!" ? " is-bad" : glyph === "✓" ? " is-ok" : glyph === "?" ? " is-jay" : ""}`} aria-hidden>{glyph}</span>;
}

interface PanelData {
  key: string; name: string; prefix: string; active: Ticket[]; news: CcdEvent[]; needs: JayItem[];
  counts: { needs: number; progress: number; review: number; merge: number };
  live: CcdEvent[]; blocked: Ticket[];
}

export function projectPanels(projects: { key: string; name: string; prefix: string }[], tickets: Ticket[],
                              activity: CcdEvent[], queue: JayItem[], now = nowS()): PanelData[] {
  return byProjectOrder(projects).map((p) => {
    const active = tickets.filter((t) => t.project === p.key && isActive(t));
    const stages = active.map(stageOf);
    const n = (...s: string[]) => stages.filter((x) => s.includes(x)).length;
    const mine = activity.filter((e) => e.project === p.key);
    return {
      key: p.key, name: p.name, prefix: p.prefix, active,
      news: mine.filter(newsworthy).slice(0, 2),
      needs: queue.filter((j) => j.project === p.key),
      counts: { needs: queue.filter((j) => j.project === p.key).length,
        progress: n("Planning", "Implementing", "UI Testing", "Verifying", "Deploying"), review: n("Reviewing"),
        merge: n("Ready to Merge") },
      live: mine.filter((e) => e.kind === "task.pipeline" && e.data?.kind === "pipeline.deployed" && now - e.at < 7 * 86400).slice(0, 2),
      blocked: active.filter((t) => stageOf(t) === "Blocked"),
    };
  });
}

function ProjectPanel({ d, night, onNight }: { d: PanelData; night: NightShiftState | null; onNight: () => void }) {
  const top = d.news[0];
  return <section className="dash-card" style={pjVar(d.key)} aria-label={d.name}>
    <a className="dash-head" href={href("workspace", null, { project: d.key })} title={`Open ${d.name} in the Workspace`}>
      <span className="pj-badge is-lg" aria-hidden>{initials(d.prefix, d.name)}</span>
      <span className="dash-title"><b>{d.name}</b><span className="muted">{d.active.length} active task{d.active.length === 1 ? "" : "s"}</span></span>
    </a>

    <div className="dash-box">
      <div className="dash-label">Latest update{top ? <span className="faint"> · {shiftOf(top.at)}</span> : null}</div>
      {top ? <>
        <div className="dash-news"><Mark e={top} /><a className="trunc2" href={top.ref ? taskHref(top.ref, null, false) : href("activity")}
          title={top.text}>{newsText(top)}</a></div>
        <div className="dash-sub muted">{d.news[1] ? <span className="trunc" title={d.news[1].text}>{newsText(d.news[1])}</span> : null}
          <span className="mono-xs faint">{ago(top.at, nowS())}</span></div>
      </> : <div className="muted dash-sub">No updates yet.</div>}
    </div>
    <NightLine project={d.key} name={d.name} n={night?.projects[d.key]} onChanged={onNight} />

    <div className="dash-needs">
      <div className={`dash-label is-jay${d.needs.length ? "" : " is-clear"}`}>Needs Jay:</div>
      {d.needs.length ? <ul>{d.needs.slice(0, 3).map((j) => <li key={j.id}><a href={jayHref(j)} title={j.text}>{jayWords(j)}</a></li>)}
        {d.needs.length > 3 && <li className="muted"><a href={href("workspace", null, { project: d.key })}>+{d.needs.length - 3} more</a></li>}</ul>
        : <div className="muted dash-sub">Nothing — all clear.</div>}
    </div>

    {(d.live.length > 0 || d.blocked.length > 0) && <div className="dash-extra">
      {d.live.map((e) => <div key={e.seq} className="dash-line is-live"><span aria-hidden>▲</span><span className="trunc">Went live: {e.ref ?? e.text}</span>
        <span className="mono-xs faint">{ago(e.at, nowS())}</span></div>)}
      {d.blocked.slice(0, 2).map((t) => <a key={t.key} className="dash-line is-blocked" href={taskHref(t.key, "blocker")}>
        <span aria-hidden>■</span><span className="trunc">Blocked: {t.key} — {t.gateReason ?? t.title}</span></a>)}
    </div>}

    <div className="dash-counts">
      <span className="dash-count is-jay"><b>{d.counts.needs}</b>Needs Jay</span>
      <span className="dash-count is-impl"><b>{d.counts.progress}</b>In Progress</span>
      <span className="dash-count is-review"><b>{d.counts.review}</b>Reviewing</span>
    </div>
    <div className={`dash-merge${d.counts.merge ? " is-on" : ""}`}><i aria-hidden />{d.counts.merge} Ready to Merge</div>
  </section>;
}

export function Dashboard() {
  useTick(30_000);
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const activity = useSelector(app.store, (d) => d.activity);
  const taskProjects = useSelector(app.store, (d) => d.taskProjects);
  const queue = useMemo(() => jayQueue(st, undefined, tickets), [st, tickets]);
  const projects = useMemo(() => {
    const reg = taskProjects.length ? taskProjects : (st?.projectsConfig ?? []).map((p) => ({ key: p.key, name: p.name, prefix: p.prefix ?? "" }));
    // Only projects the server actually tracks (a registered repository), never a name with nothing behind it.
    const live = new Set((st?.projects ?? []).map((p) => p.key));
    return reg.filter((p) => !live.size || live.has(p.key) || tickets.some((t) => t.project === p.key && isActive(t)))
      .map((p) => ({ key: p.key, name: st?.projects.find((x) => x.key === p.key)?.name ?? p.name, prefix: p.prefix }));
  }, [taskProjects, st, tickets]);
  const panels = useMemo(() => projectPanels(projects, tickets, activity, queue), [projects, tickets, activity, queue]);
  const [night, reloadNight] = useNightShift();
  if (!st) return <EmptyState title="Loading state from ccd…" />;
  const now = new Date();
  return <div className="dash">
    <header className="dash-top">
      <span className="dash-sun" aria-hidden>{now.getHours() >= 7 && now.getHours() < 19 ? "☀" : "☾"}</span>
      <div className="dash-hello"><h2>{greeting(now)}, J</h2>
        <span className="muted">{now.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric", year: "numeric" })}
          {" · "}{now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span></div>
      <span className="sl-fill" />
      <DevDot />
      <NotificationBell />
      <TaskCheckButton className="btn is-outline" />
      <NightShiftButton className="btn is-outline" />
      <a className="btn is-outline" href={href("workspace")}>Open Workspace →</a>
    </header>
    <div className="dash-grid" style={{ ["--n" as string]: String(Math.max(1, panels.length)) }}>
      {panels.map((d) => <ProjectPanel key={d.key} d={d} night={night} onNight={reloadNight} />)}
    </div>
  </div>;
}
