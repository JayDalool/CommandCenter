// Company, the operations topology (roadmap P3.1): projects, where their open work sits in the pipeline, and the hosts
// it runs on, from hq/data/topology.ts. Drawn as three columns; each flow is a row, so no line implies a dependency
// that is not there. A host's status comes from its own feed. Worker nodes are read from the same GET /api/workers as
// Settings › Workers. Each project opens Classic's project screen at #/projects/<key>. Nothing here starts, stops,
// enrols or deploys.
import { useEffect, useMemo, useState } from "react";
import "./office.css";
import "./topology.css";
import { app } from "../../store/app";
import { href } from "../../lib/router";
import { ago } from "../../lib/time";
import { isActive } from "../../lib/control";
import type { WorkersState } from "../../api/types";
import { buildDecisions, buildTopology, PRESENCE_LABEL, type Health, type HostStatus, type TopoFilter, type TopoHost,
  type TopoProject, type TopoStage } from "../data";
import { useHqData } from "./live";
import { Pill, plural } from "./ui";

const HEALTH: Record<Health, [string, string]> = { healthy: ["Healthy", "ok"], degraded: ["Degraded", "bad"], unknown: ["Unknown", "idle"] };
const HOST: Record<HostStatus, [string, string]> = { online: ["Online", "ok"], offline: ["Offline", "idle"], pending: ["Pending approval", "warn"],
  revoked: ["Revoked", "bad"], unknown: ["Unknown", "idle"] };
const EDGE: Record<TopoProject["edge"], [string, string]> = { blocked: ["Blocked work", "t-bad"], active: ["Work open", ""], idle: ["No open work", "hq-dim"] };
const STATUS: [NonNullable<TopoFilter["status"]>, string][] = [["all", "All work"], ["attention", "Needs attention"], ["blocked", "Blocked"]];
const TASKS_SHOWN = 5;

/** GET /api/workers every 30 s, as Settings › Workers does. Null until the first answer. */
function useWorkers() {
  const [w, setW] = useState<WorkersState | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () => app.api.workers().then((d) => { if (live) { setW(d); setFailed(false); } }, () => { if (live) setFailed(true); });
    void load();
    const t = setInterval(load, 30_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  return { workers: w, failed };
}

function ProjectNode({ p, summary, prs, open, needs, stale }: { p: TopoProject; summary: string; prs: number | null; open: number; needs: number; stale: boolean }) {
  const [label, tone] = HEALTH[p.health];
  const [edge, edgeCls] = EDGE[p.edge];
  return <a className="hq-proj hq-topo-node" href={href("projects", p.key)} style={{ ["--pj" as string]: `var(--hq-pj-${p.key}, var(--hq-accent))` }}>
    <span className="hq-proj-top"><b>{p.name}</b><Pill tone={tone} title={p.healthWhy}>{label}</Pill></span>
    <small className="hq-proj-why">{p.healthWhy}</small>
    {summary && <small className="hq-ellip" title={summary}>{summary}</small>}
    <span className="hq-proj-foot">
      <span className={edgeCls}>{edge}</span>
      <span>{plural(open, "open task")}</span>
      {needs > 0 && <span className="t-jay">{needs} need you</span>}
      {prs != null && <span>{plural(prs, "PR")}</span>}
      <span>{plural(p.sessions, "session")}{stale ? " last reported" : ""}</span>
      <span>{p.coordinator ? `Lead: ${PRESENCE_LABEL[p.coordinator.presence]}` : "No lead session"}</span>
    </span>
  </a>;
}

function StageNode({ s, names, project }: { s: TopoStage; names: Map<string, string>; project: string | null }) {
  const more = s.tasks.length - TASKS_SHOWN;
  return <section className="hq-topo-stage" aria-label={s.label}>
    <h4>{s.label} <small>{plural(s.tasks.length, "task")}</small></h4>
    <ul className="hq-topo-flows">{s.flows.map((f) => <li key={f.project} style={{ ["--pj" as string]: `var(--hq-pj-${f.project}, var(--hq-accent))` }}>
      <i aria-hidden /><span className="hq-ellip">{names.get(f.project) ?? f.project}</span>
      <span className="hq-topo-flags">{f.blocked && <Pill tone="bad">Blocked</Pill>}{f.needsJay && <Pill tone="jay">Needs you</Pill>}</span>
      <b>{f.count}</b></li>)}</ul>
    <ul className="hq-topo-tasks">{s.tasks.slice(0, TASKS_SHOWN).map((t) => <li key={t.key}><a href={href("tasks", t.key)}>
      <code>{t.key}</code><span className="hq-ellip" title={t.title}>{t.title}</span>
      {t.blocked ? <Pill tone="bad">Blocked</Pill> : t.needsJay ? <Pill tone="jay">Needs you</Pill> : null}</a></li>)}</ul>
    {more > 0 && <a className="hq-link" href={href("tasks", null, project ? { project } : {})}>{more} more in Engineering</a>}
  </section>;
}

function pct(n: number | null) { return n == null ? "—" : `${Math.round(n)}%`; }

function HostNode({ h, now }: { h: TopoHost; now: number }) {
  const [label, tone] = HOST[h.status];
  return <div className="hq-sess hq-topo-host">
    <span className="hq-sess-top"><b className="hq-ellip">{h.name}</b><Pill tone={tone} title={h.why}>{label}</Pill></span>
    <small>{h.kind === "ccd" ? "ccd host" : `${h.kind} worker`} · {h.why}</small>
    {h.kind === "ccd" && <small>CPU {pct(h.cpuPct)} · Memory {pct(h.memPct)} · Disk {pct(h.diskPct)}
      {h.sessions != null ? ` · ${plural(h.sessions, "live session")}` : ""}</small>}
    {h.asOf != null && <small>{h.kind === "ccd" ? "Vitals" : "Heartbeat"} {ago(h.asOf, now)}</small>}
  </div>;
}

export function Topology() {
  const { src, ev } = useHqData();
  const { workers, failed } = useWorkers();
  const [status, setStatus] = useState<NonNullable<TopoFilter["status"]>>("all");
  const [only, setOnly] = useState<string[]>([]);
  const all = useMemo(() => buildTopology(src, ev, {}, workers), [src, ev, workers]);
  const v = useMemo(() => buildTopology(src, ev, { projects: only, status }, workers), [src, ev, only, status, workers]);
  const needs = useMemo(() => buildDecisions(src).items, [src]);
  const names = new Map(all.projects.map((p) => [p.key, p.name]));
  const st = src.state;
  const stale = ev.sessions !== "live";
  const toggle = (k: string) => setOnly(only.includes(k) ? only.filter((x) => x !== k) : [...only, k]);
  const filtered = only.length > 0 || status !== "all";

  return <div className="hq-page hq-topology">
    <header className="hq-hero"><div><h2>Company</h2>
      <p>Your projects, where their open work sits in the pipeline, and the machines it runs on. Open a project for its tasks, pull requests and branches.</p></div></header>

    <div className="hq-topo-filters">
      <div className="hq-seg" role="group" aria-label="Filter work">
        {STATUS.map(([k, label]) => <button key={k} type="button" aria-pressed={status === k} onClick={() => setStatus(k)}>{label}</button>)}
      </div>
      <div className="hq-seg" role="group" aria-label="Filter by project">
        {all.projects.map((p) => <button key={p.key} type="button" aria-pressed={only.includes(p.key)} onClick={() => toggle(p.key)}>{p.name}</button>)}
      </div>
      {filtered && <button type="button" className="hq-btn" onClick={() => { setOnly([]); setStatus("all"); }}>Clear</button>}
    </div>

    <div className="hq-topo">
      <section className="hq-panel" aria-labelledby="hq-topo-projects">
        <header><h3 id="hq-topo-projects">Projects <small>{v.projects.length}</small></h3></header>
        {v.projects.length ? <div className="hq-topo-col">{v.projects.map((p) => {
          const pv = st?.projects.find((x) => x.key === p.key);
          return <ProjectNode key={p.key} p={p} summary={pv?.summary ?? ""} prs={pv ? pv.prs.length : null} stale={stale}
            open={src.tickets.filter((t) => t.project === p.key && isActive(t)).length} needs={needs.filter((d) => d.project === p.key).length} />;
        })}</div> : <p className="hq-empty">No projects reported yet.</p>}
      </section>

      <section className="hq-panel" aria-labelledby="hq-topo-stages">
        <header><h3 id="hq-topo-stages">Pipeline <small>{plural(v.stages.reduce((n, s) => n + s.tasks.length, 0), "open task")}</small></h3>
          <a className="hq-link" href={href("tasks")}>Engineering</a></header>
        {v.stages.length ? <div className="hq-topo-col">{v.stages.map((s) => <StageNode key={s.id} s={s} names={names} project={only.length === 1 ? only[0] : null} />)}</div>
          : <p className="hq-empty">{filtered ? "No open work matches this filter." : "No open work."}</p>}
      </section>

      <section className="hq-panel" aria-labelledby="hq-topo-hosts">
        <header><h3 id="hq-topo-hosts">Hosts <small>{v.hosts.length}</small></h3>
          <a className="hq-link" href={href("settings", null, { tab: "workers" })}>Workers</a></header>
        <div className="hq-topo-col">{v.hosts.map((h) => <HostNode key={`${h.kind}:${h.id}`} h={h} now={ev.now} />)}</div>
        {failed ? <p className="hq-note">Could not read the worker nodes; only the ccd host is shown.</p>
          : workers && !workers.available ? <p className="hq-note">Worker nodes are not enabled on this server.</p>
          : workers && !workers.nodes.length ? <p className="hq-note">No worker node is enrolled.</p> : null}
        {!v.hosts.length && <p className="hq-empty">No host reported yet.</p>}
      </section>
    </div>
    {stale && <p className="hq-note">The session feed is not live, so lead status and session counts are the last ones reported.</p>}
  </div>;
}

