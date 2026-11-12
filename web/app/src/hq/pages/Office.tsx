// My Office (roadmap P3.2): the HQ landing page, on live data from hq/data/office.ts. Read-only: every row links to
// the Classic screen where the work is done. Status only from evidence: a stale feed reads Unknown, never Working.
// Lead updates have no source until Project Lead conversations exist (P5.1), so that panel is not shown.
import { useMemo, useState } from "react";
import "./office.css";
import { href } from "../../lib/router";
import { ago } from "../../lib/time";
import { buildOffice, PRESENCE_LABEL, type DecisionItem, type Health, type OfficeProject, type Presence, type TeamMember } from "../data";
import { useHqData } from "./live";
import { Kpi, Pill, PRESENCE_TONE, cx, plural } from "./ui";
import type { Alert } from "../../api/types";

const HEALTH: Record<Health, { label: string; tone: string }> = {
  healthy: { label: "Healthy", tone: "ok" }, degraded: { label: "Degraded", tone: "bad" }, unknown: { label: "Unknown", tone: "idle" },
};

function greeting(d: Date) { const h = d.getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; }

function ProjectCard({ p, stale }: { p: OfficeProject; stale: boolean }) {
  const h = HEALTH[p.health];
  return <a className="hq-proj" href={href("projects", p.key)} style={{ ["--pj" as string]: `var(--hq-pj-${p.key}, var(--hq-accent))` }}>
    <span className="hq-proj-top"><b>{p.name}</b><Pill tone={h.tone} title={p.healthWhy}>{h.label}</Pill></span>
    <small className="hq-proj-why">{p.healthWhy}</small>
    <span className="hq-proj-counts">
      <span className={cx(p.counts.needs > 0 && "t-jay")}><b>{p.counts.needs}</b>needs you</span>
      <span><b>{p.counts.progress}</b>in progress</span>
      <span><b>{p.counts.review}</b>in review</span>
      <span><b>{p.counts.merge}</b>to merge</span>
    </span>
    <span className="hq-proj-foot">
      {p.blocked > 0 && <span className="t-bad">{p.blocked} blocked</span>}
      <span>{plural(p.sessions, "session")}{stale && " last reported"}</span>
      <span>{p.lead ? `Lead: ${p.lead}` : "No lead session"}</span>
    </span>
  </a>;
}

function AttentionRow({ d, now }: { d: DecisionItem; now: number }) {
  return <li><a href={d.ticket ? href("tasks", d.ticket) : href("needs")}>
    <span className="hq-attn-body"><span className="hq-ellip" title={d.title}>{d.ticket && <code>{d.ticket}</code>} {d.title}</span>
      <small>{d.sub}{d.since ? ` · ${ago(d.since, now)}` : ""}</small></span>
    <Pill tone={d.pill[1]}>{d.pill[0]}</Pill></a></li>;
}

function AlertRow({ a, now }: { a: Alert; now: number }) {
  return <li><a href={href("alerts")}>
    <span className="hq-attn-body"><span className="hq-ellip" title={a.text}>{a.text}</span>
      <small>{a.source}{a.project ? ` · ${a.project}` : ""} · {ago(a.since, now)}</small></span>
    <Pill tone={a.severity === "action" ? "bad" : a.severity === "warn" ? "warn" : "info"}>{a.severity === "action" ? "Action" : a.severity === "warn" ? "Warning" : "Info"}</Pill></a></li>;
}

const FILTERS: (Presence | "all")[] = ["all", "working", "waiting", "idle", "offline", "unknown"];

function SessionCard({ m }: { m: TeamMember }) {
  const body = <>
    <span className="hq-sess-top"><b className="hq-ellip">{m.name}</b><Pill tone={PRESENCE_TONE[m.presence]}>{PRESENCE_LABEL[m.presence]}</Pill></span>
    <small className="hq-ellip">{m.agent}{m.ticket ? ` · ${m.ticket}` : ""}</small></>;
  return m.ticket ? <a className="hq-sess" href={href("tasks", m.ticket)}>{body}</a> : <div className="hq-sess">{body}</div>;
}

export function Office() {
  const { src, ev } = useHqData();
  const v = useMemo(() => buildOffice(src, ev), [src, ev]);
  const [filter, setFilter] = useState<Presence | "all">("all");
  const now = new Date(ev.now * 1000);
  const s = v.kpis.sessions;
  const stale = ev.sessions !== "live";
  const shown = v.agents.filter((a) => filter === "all" || a.presence === filter);
  const count = (f: Presence | "all") => (f === "all" ? v.agents.length : v.agents.filter((a) => a.presence === f).length);
  const health = HEALTH[v.kpis.health.state];
  return <div className="hq-page hq-office">
    <header className="hq-hero">
      <div><h2>{greeting(now)}, <em>Jay</em></h2><p>What is happening across your projects, from live data.</p></div>
      <time dateTime={now.toISOString()}>{now.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" })}</time>
    </header>

    <section className="hq-kpis" aria-label="Summary">
      <Kpi label="Projects" value={v.kpis.projects} to={href("projects")}
        sub={`${v.projects.filter((p) => p.health === "healthy").length} healthy · ${v.projects.filter((p) => p.health === "degraded").length} degraded`} />
      <Kpi label="Sessions" value={stale ? "Unknown" : s.total} tone={stale ? "idle" : undefined} to={href("agents")}
        sub={stale ? "Session feed not live" : `${s.working} working · ${s.waiting} waiting for you`} />
      <Kpi label="Needs you" value={v.kpis.needsYou.total} tone={v.kpis.needsYou.total ? "jay" : undefined} to={href("needs")}
        sub={`${v.kpis.needsYou.urgent} urgent`} />
      {/* Degraded: the failing projects. Unknown: the Server screen, which shows which feed is not reporting. */}
      <Kpi label="Health" value={health.label} tone={health.tone} sub={v.kpis.health.why}
        to={v.kpis.health.state === "degraded" ? href("projects") : href("server")} />
    </section>

    <div className="hq-office-grid">
      <section className="hq-panel hq-office-projects" aria-labelledby="hq-office-projects">
        <header><h3 id="hq-office-projects">Projects</h3><a className="hq-link" href={href("projects")}>All projects</a></header>
        {v.projects.length ? <div className="hq-proj-grid">{v.projects.map((p) => <ProjectCard key={p.key} p={p} stale={stale} />)}</div>
          : <p className="hq-empty">No projects reported yet.</p>}
      </section>
      <div className="hq-office-side">
        <section className="hq-panel" aria-labelledby="hq-office-attn">
          <header><h3 id="hq-office-attn">Needs your attention</h3><a className="hq-link" href={href("needs")}>View all {v.kpis.needsYou.total}</a></header>
          {v.attention.length ? <ul className="hq-attn">{v.attention.map((d) => <AttentionRow key={d.id} d={d} now={ev.now} />)}</ul>
            : <p className="hq-empty">Nothing is waiting for you.</p>}
        </section>
        {v.alerts.length > 0 && <section className="hq-panel" aria-labelledby="hq-office-alerts">
          <header><h3 id="hq-office-alerts">Alerts</h3><a className="hq-link" href={href("alerts")}>View all {v.alerts.length}</a></header>
          <ul className="hq-attn">{v.alerts.slice(0, 4).map((a) => <AlertRow key={a.id} a={a} now={ev.now} />)}</ul>
        </section>}
      </div>
    </div>

    <section className="hq-panel" aria-labelledby="hq-office-sessions">
      <header><h3 id="hq-office-sessions">Sessions <small>{plural(v.agents.length, "session")} {stale ? "last reported" : "reported"} by herdr</small></h3>
        {stale && <Pill tone="warn">Feed not live · status unknown</Pill>}
        <div className="hq-seg" role="group" aria-label="Filter sessions">
          {FILTERS.map((f) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {f === "all" ? "All" : PRESENCE_LABEL[f]} ({count(f)})</button>)}
        </div></header>
      {shown.length ? <div className="hq-sess-grid">{shown.map((m) => <SessionCard key={m.id} m={m} />)}</div>
        : <p className="hq-empty">{v.agents.length ? "No session matches this filter." : "herdr reports no sessions."}</p>}
    </section>
  </div>;
}
