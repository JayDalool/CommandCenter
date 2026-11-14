// My Office (roadmap P3.2): the HQ landing page, on live data from hq/data/office.ts. Top to bottom: the figures,
// the Briefing (what happened while Jay was away) and Where we are (each project's milestones) beside what needs him,
// then the projects and the sessions, on the office floor (Floor.tsx) or as a list. Everything but the milestones is
// read-only: a row links to the Classic screen where the work is done. Status only from evidence: a stale feed reads
// Unknown, never Working.
import { useMemo, useState } from "react";
import "./office.css";
import { href } from "../../lib/router";
import { ago } from "../../lib/time";
import { buildOffice, PRESENCE_LABEL, type Health, type OfficeProject, type Presence, type TeamMember } from "../data";
import { useHqData } from "./live";
import { AttentionRow, Kpi, Pill, PRESENCE_TONE, cx, plural } from "./ui";
import type { Alert } from "../../api/types";
import { Fun, Persona, PRESENCE_EMOJI, useFun } from "../persona/mode";
import { ProjectLogo } from "../logos";
import { LiveTag } from "../release";
import { Briefing } from "./Briefing";
import { Milestones } from "./Milestones";
import { Floor } from "./Floor";
import { prefs, usePrefs } from "../../lib/prefs";

const HEALTH: Record<Health, { label: string; tone: string }> = {
  healthy: { label: "Healthy", tone: "ok" }, degraded: { label: "Degraded", tone: "bad" }, unknown: { label: "Unknown", tone: "idle" },
};

function greeting(d: Date) { const h = d.getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; }

function ProjectCard({ p, stale }: { p: OfficeProject; stale: boolean }) {
  const h = HEALTH[p.health];
  return <a className="hq-proj" href={href("projects", p.key)} style={{ ["--pj" as string]: `var(--hq-pj-${p.key}, var(--hq-accent))` }}>
    <span className="hq-proj-top"><span className="hq-live-with"><b className="hq-with-logo"><ProjectLogo project={p.key} size={22} />{p.name}</b>
      <LiveTag project={p.key} /></span><Pill tone={h.tone} title={p.healthWhy}>{h.label}</Pill></span>
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
      <span className="hq-proj-lead">{p.lead && <Persona lead={p.key} size={20} />}{p.lead ? `Lead: ${p.lead}` : "No lead session"}</span>
    </span>
  </a>;
}

function AlertRow({ a, now }: { a: Alert; now: number }) {
  return <li><a href={href("alerts")}>
    <span className="hq-attn-body"><span className="hq-ellip" title={a.text}>{a.text}</span>
      <small>{a.source}{a.project ? ` · ${a.project}` : ""} · {ago(a.since, now)}</small></span>
    <Pill tone={a.severity === "action" ? "bad" : a.severity === "warn" ? "warn" : "info"}>{a.severity === "action" ? "Action" : a.severity === "warn" ? "Warning" : "Info"}</Pill></a></li>;
}

const FILTERS: (Presence | "all")[] = ["all", "working", "waiting", "idle", "offline", "unknown"];

function SessionCard({ m }: { m: TeamMember }) {
  const fun = useFun();
  const text = <>
    <span className="hq-sess-top"><b className="hq-ellip">{m.name}</b>
      <Pill tone={PRESENCE_TONE[m.presence]}>{PRESENCE_LABEL[m.presence]}<Fun e={PRESENCE_EMOJI[m.presence]} /></Pill></span>
    <small className="hq-ellip">{m.agent}{m.ticket ? ` · ${m.ticket}` : ""}</small></>;
  const body = fun ? <><Persona lead={m.leadOf} name={m.name} size={36} /><span className="hq-sess-body">{text}</span></> : text;
  const cls = cx("hq-sess", fun && "has-face");
  return m.ticket ? <a className={cls} href={href("tasks", m.ticket)}>{body}</a> : <div className={cls}>{body}</div>;
}

export function Office() {
  const { src, ev } = useHqData();
  const v = useMemo(() => buildOffice(src, ev), [src, ev]);
  const [filter, setFilter] = useState<Presence | "all">("all");
  const view = usePrefs((p) => p.sessions);
  const now = new Date(ev.now * 1000);
  const s = v.kpis.sessions;
  const stale = ev.sessions !== "live";
  const shown = v.agents.filter((a) => filter === "all" || a.presence === filter);
  const count = (f: Presence | "all") => (f === "all" ? v.agents.length : v.agents.filter((a) => a.presence === f).length);
  const health = HEALTH[v.kpis.health.state];
  return <div className="hq-page hq-office">
    <header className="hq-hero">
      <div><h2>{greeting(now)}, <em>Jay</em><Fun e={now.getHours() < 12 ? "☀️" : now.getHours() < 18 ? "🌤️" : "🌙"} /></h2><p>What is happening across your projects, from live data.</p></div>
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
      <div className="hq-office-main">
        <Briefing now={now} />
        <Milestones projects={v.projects} now={now} />
      </div>
      <div className="hq-office-side">
        <section className="hq-panel" aria-labelledby="hq-office-attn">
          <header><h3 id="hq-office-attn">Needs your attention</h3><a className="hq-link" href={href("needs")}>View all {v.kpis.needsYou.total}</a></header>
          {v.attention.length ? <ul className="hq-attn">{v.attention.map((d) => <AttentionRow key={d.id} d={d} now={ev.now} />)}</ul>
            : <p className="hq-empty">Nothing is waiting for you.<Fun e="🎉" /></p>}
        </section>
        {v.alerts.length > 0 && <section className="hq-panel" aria-labelledby="hq-office-alerts">
          <header><h3 id="hq-office-alerts">Alerts</h3><a className="hq-link" href={href("alerts")}>View all {v.alerts.length}</a></header>
          <ul className="hq-attn">{v.alerts.slice(0, 4).map((a) => <AlertRow key={a.id} a={a} now={ev.now} />)}</ul>
        </section>}
      </div>
    </div>

    <section className="hq-panel hq-office-projects" aria-labelledby="hq-office-projects">
      <header><h3 id="hq-office-projects">Projects</h3><a className="hq-link" href={href("projects")}>All projects</a></header>
      {v.projects.length ? <div className="hq-proj-grid">{v.projects.map((p) => <ProjectCard key={p.key} p={p} stale={stale} />)}</div>
        : <p className="hq-empty">No projects reported yet.</p>}
    </section>

    <section className="hq-panel" aria-labelledby="hq-office-sessions">
      <header><h3 id="hq-office-sessions">Sessions <small>{plural(v.agents.length, "session")} {stale ? "last reported" : "reported"} by herdr</small></h3>
        {stale && <Pill tone="warn">Feed not live · status unknown</Pill>}
        {view === "list" && <div className="hq-seg" role="group" aria-label="Filter sessions">
          {FILTERS.map((f) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {f === "all" ? "All" : PRESENCE_LABEL[f]} ({count(f)})</button>)}
        </div>}
        <div className="hq-seg" role="group" aria-label="Show sessions as">
          {(["floor", "list"] as const).map((x) => <button key={x} type="button" aria-pressed={view === x}
            onClick={() => prefs.patch({ sessions: x })}>{x === "floor" ? "Floor" : "List"}</button>)}
        </div></header>
      {view === "floor" ? <Floor src={src} ev={ev} />
        : shown.length ? <div className="hq-sess-grid">{shown.map((m) => <SessionCard key={m.id} m={m} />)}</div>
        : <p className="hq-empty">{v.agents.length ? "No session matches this filter." : "herdr reports no sessions."}</p>}
    </section>
  </div>;
}
