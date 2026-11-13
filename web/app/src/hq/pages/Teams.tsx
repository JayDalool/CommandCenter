// Teams (roadmap P3.5): who works on each project, from the sessions herdr reports (hq/data/teams.ts). A lead shows
// only when the project's coordinator is one of those sessions; nothing is invented. Each session opens Classic's
// Agents screen at #/agents/<id>, where Open and Focus are, so this page has no actions of its own.
//
// Two views of the same data: an org chart (the prototype's hierarchy: Jay, then each project's lead, then the
// sessions working on it, then the subagents the lead can call) and the list of team panels. The chart is drawn with
// nested lists and CSS lines, so it reads in order for a screen reader and needs no layout code.
import { useMemo, useState } from "react";
import "./office.css";
import "./teams.css";
import { href } from "../../lib/router";
import { ago, dur } from "../../lib/time";
import { modelOf } from "../../screens/Agents";
import { buildTeams, PRESENCE_LABEL, type Team, type TeamMember } from "../data";
import { useHqData } from "./live";
import { Kpi, Pill, PRESENCE_TONE, cx, plural } from "./ui";
import { Icon } from "../frame/icons";

interface Extra { model: string; last: { at: number; text: string } | null }

function Member({ m, x, lead, now }: { m: TeamMember; x?: Extra; lead?: boolean; now: number }) {
  return <a className={cx("hq-sess", lead && "is-lead")} href={href("agents", m.id)} title={m.cwd || undefined}>
    <span className="hq-sess-top"><b className="hq-ellip">{m.name}</b><Pill tone={PRESENCE_TONE[m.presence]}>{PRESENCE_LABEL[m.presence]}</Pill></span>
    <small className="hq-ellip">{lead ? "Lead · " : ""}{m.agent}{x?.model && x.model !== "—" ? ` · ${x.model}` : ""}{m.ticket ? ` · ${m.ticket}` : ""}</small>
    {m.waitingSince != null ? <small className="t-jay">Waiting for you {dur(now - m.waitingSince)}</small>
      : x?.last && <small className="hq-ellip" title={x.last.text}>{ago(x.last.at, now)} · {x.last.text}</small>}
  </a>;
}

function TeamPanel({ t, extra, now, stale }: { t: Team; extra: Map<string, Extra>; now: number; stale: boolean }) {
  const n = t.members.length + (t.lead ? 1 : 0);
  const defined = t.defined.filter((d, i) => t.defined.findIndex((x) => x.name === d.name && x.model === d.model) === i);
  return <section className="hq-panel hq-team" aria-labelledby={`hq-team-${t.key}`} style={{ ["--pj" as string]: `var(--hq-pj-${t.key}, var(--hq-accent))` }}>
    <header><h3 id={`hq-team-${t.key}`}>{t.name} <small>{plural(n, "session")}{stale ? " last reported" : ""} · {plural(t.openTasks, "open task")}</small></h3>
      <span className="hq-team-links"><a className="hq-link" href={href("tasks", null, { project: t.key })}>Tasks</a>
        <a className="hq-link" href={href("projects", t.key)}>Project</a></span></header>
    <div className="hq-sess-grid">
      {t.lead ? <Member m={t.lead} x={extra.get(t.lead.id)} lead now={now} />
        : <div className="hq-sess is-empty"><b>No lead</b><small>{t.leadWhy}</small></div>}
      {t.members.map((m) => <Member key={m.id} m={m} x={extra.get(m.id)} now={now} />)}
    </div>
    {defined.length > 0 && <p className="hq-note">The lead can also call {defined.map((d, i) => <span key={`${d.name}:${d.model}`}>{i ? ", " : ""}
      <b>{d.name}</b>{d.model ? ` (${d.model})` : ""}</span>)}. They run only when called, so they have no status here.</p>}
  </section>;
}

/** One project's branch of the chart: its header, the lead (or why there is none), the sessions, and who can be called. */
function OrgBranch({ t, extra, now }: { t: Team; extra: Map<string, Extra>; now: number }) {
  const defined = t.defined.filter((d, i) => t.defined.findIndex((x) => x.name === d.name && x.model === d.model) === i);
  return <li className="hq-org-branch" style={{ ["--pj" as string]: `var(--hq-pj-${t.key}, var(--hq-accent))` }}>
    <div className="hq-org-proj">
      <span className="hq-org-proj-t"><i aria-hidden /><b className="hq-ellip">{t.name}</b></span>
      <small>{plural(t.openTasks, "open task")}</small>
      <span className="hq-team-links"><a className="hq-link" href={href("tasks", null, { project: t.key })}>Tasks</a>
        <a className="hq-link" href={href("projects", t.key)}>Project</a></span>
    </div>
    {t.lead ? <Member m={t.lead} x={extra.get(t.lead.id)} lead now={now} />
      : <div className="hq-sess is-empty"><b>No lead</b><small>{t.leadWhy}</small></div>}
    {(t.members.length > 0 || defined.length > 0) && <ul className="hq-org-reports" aria-label={`${t.name}: working with the lead`}>
      {t.members.map((m) => <li key={m.id}><Member m={m} x={extra.get(m.id)} now={now} /></li>)}
      {defined.length > 0 && <li className="hq-org-defined"><details>
        <summary>{plural(defined.length, "subagent")} the lead can call</summary>
        <ul>{defined.map((d) => <li key={`${d.name}:${d.model}`}><b>{d.name}</b>{d.model ? ` · ${d.model}` : ""}</li>)}</ul>
      </details></li>}
    </ul>}
  </li>;
}

function OrgChart({ teams, unassigned, extra, now, waiting, stale }: {
  teams: Team[]; unassigned: TeamMember[]; extra: Map<string, Extra>; now: number; waiting: number; stale: boolean;
}) {
  return <section className="hq-panel hq-org-wrap" aria-label="Org chart">
    <div className="hq-org">
      <ul className="hq-org-root">
        <li>
          <a className="hq-org-jay" href={href("needs")}>
            <span className="hq-org-av" aria-hidden>J</span>
            <span><b>Jay</b>{" "}<small>Directs {plural(teams.length, "project")}
              {stale ? "" : waiting ? ` · ${waiting} waiting for you` : " · nothing waiting for you"}</small></span></a>
          {teams.length > 0 && <ul className="hq-org-projects">{teams.map((t) => <OrgBranch key={t.key} t={t} extra={extra} now={now} />)}</ul>}
        </li>
      </ul>
    </div>
    {unassigned.length > 0 && <div className="hq-org-loose"><h4>No project <small>{plural(unassigned.length, "session")}</small></h4>
      <div className="hq-sess-grid">{unassigned.map((m) => <Member key={m.id} m={m} x={extra.get(m.id)} now={now} />)}</div></div>}
  </section>;
}

const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 760px)").matches;

export function Teams() {
  const { src, ev } = useHqData();
  const v = useMemo(() => buildTeams(src, ev), [src, ev]);
  const st = src.state;
  // Classic's Agents columns: the model each session runs and its latest event.
  const extra = useMemo(() => {
    const m = new Map<string, Extra>();
    for (const a of st?.agents ?? []) m.set(a.id, { model: modelOf(a, st!.projectsConfig), last: null });
    for (const e of src.activity) { const x = e.agentId ? m.get(e.agentId) : undefined; if (x && !x.last) x.last = { at: e.at, text: e.text }; }
    return m;
  }, [st, src.activity]);
  const stale = ev.sessions !== "live";
  const s = v.sessions;
  const leads = v.teams.filter((t) => t.lead).length;
  const [mode, setMode] = useState<"chart" | "list">(() => narrow() ? "list" : "chart");

  return <div className="hq-page hq-teams">
    <header className="hq-hero"><div><h2>Teams</h2>
      <p>Who works on each project, from the sessions herdr reports. Open a session for its details, Open and Focus.</p></div>
      <div className="hq-teams-tools">
        {stale && <Pill tone="warn">Feed not live · status unknown</Pill>}
        <div className="hq-seg" role="group" aria-label="View">
          {([["chart", "Org chart", "users"], ["list", "List", "list"]] as const).map(([k, label, icon]) =>
            <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}><Icon name={icon} size={14} />{label}</button>)}
        </div></div></header>

    <section className="hq-kpis" aria-label="Summary">
      <Kpi label="Sessions" value={stale ? "Unknown" : s.total} tone={stale ? "idle" : undefined}
        sub={stale ? `${s.total} last reported by herdr` : `${s.working} working · ${s.offline} offline`} />
      <Kpi label="Waiting for you" value={stale ? "Unknown" : s.waiting} tone={stale ? "idle" : s.waiting ? "jay" : undefined}
        sub={stale ? "Session feed not live" : "Sessions that asked you something"} to={href("needs")} />
      <Kpi label="Leads" value={`${leads} of ${v.teams.length}`} sub="Projects with a coordinator session" />
      <Kpi label="Status unknown" value={s.unknown} tone={s.unknown ? "idle" : undefined} sub={stale ? "The feed is not live" : "No recent report"} />
    </section>

    {!v.teams.length && !v.unassigned.length ? <p className="hq-empty">No projects reported yet.</p>
      : mode === "chart" ? <OrgChart teams={v.teams} unassigned={v.unassigned} extra={extra} now={ev.now} waiting={s.waiting} stale={stale} />
      : v.teams.map((t) => <TeamPanel key={t.key} t={t} extra={extra} now={ev.now} stale={stale} />)}

    {mode === "list" && v.unassigned.length > 0 && <section className="hq-panel" aria-labelledby="hq-team-none">
      <header><h3 id="hq-team-none">No project <small>{plural(v.unassigned.length, "session")}</small></h3></header>
      <div className="hq-sess-grid">{v.unassigned.map((m) => <Member key={m.id} m={m} x={extra.get(m.id)} now={ev.now} />)}</div>
    </section>}
  </div>;
}
