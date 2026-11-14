// Company, the operations topology (roadmap P3.1): projects, where their open work sits in the pipeline, and the hosts
// it runs on, from hq/data/topology.ts. Graph view follows the prototype's Topology page: Jay → projects → stages →
// (an expanded stage's tasks) → hosts, laid out by topo-graph.ts, with pan, zoom, fit and an inspector for the selected
// node. List view is the same data as three columns, for narrow screens and screen readers. A host's status comes from
// its own feed; worker nodes are read from the same GET /api/workers as Settings › Workers. Every action is a link to
// the Classic screen where the work is done: nothing here starts, stops, enrols or deploys.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import "./office.css";
import "./topology.css";
import { LiveTag, ReleaseNote, useRelease } from "../release";
import { app } from "../../store/app";
import { href } from "../../lib/router";
import { ago } from "../../lib/time";
import { isActive, stageOf } from "../../lib/control";
import type { Ticket, WorkersState } from "../../api/types";
import { Icon } from "../frame/icons";
import { buildDecisions, buildTopology, PRESENCE_LABEL, type DecisionItem, type Evidence, type Health, type HostStatus,
  type TopoFilter, type TopoHost, type TopoProject, type TopoStage, type TopologyView } from "../data";
import type { AppData } from "../../store/app";
import { useHqData } from "./live";
import { ALL_LAYERS, TASK_NODES, curve, hostId, layoutTopology, neighbours, ports, type GNode, type Layers } from "./topo-graph";
import { AttentionRow, Pill, PRESENCE_TONE, cx, plural } from "./ui";

const HEALTH: Record<Health, [string, string]> = { healthy: ["Healthy", "ok"], degraded: ["Degraded", "bad"], unknown: ["Unknown", "idle"] };
const HOST: Record<HostStatus, [string, string]> = { online: ["Online", "ok"], offline: ["Offline", "idle"], pending: ["Pending approval", "warn"],
  revoked: ["Revoked", "bad"], unknown: ["Unknown", "idle"] };
const EDGE: Record<TopoProject["edge"], [string, string]> = { blocked: ["Blocked work", "t-bad"], active: ["Work open", ""], idle: ["No open work", "hq-dim"] };
const STATUS: [NonNullable<TopoFilter["status"]>, string][] = [["all", "All work"], ["attention", "Needs attention"], ["blocked", "Blocked"]];
const LAYERS: [keyof Layers, string][] = [["manage", "Directs"], ["flow", "Task flow"], ["host", "Runs on"]];
const STAGE_ICON: Record<string, string> = { plan: "search", build: "code", review: "check", qa: "mobile", release: "rocket" };
const TASKS_SHOWN = 5;
const pjColor = (key: string) => `var(--hq-pj-${key}, var(--hq-accent))`;

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

const pct = (n: number | null) => n == null ? "—" : `${Math.round(n)}%`;

/** What the page knows about each project beyond buildTopology: the Classic project row and Jay's queue. */
/** `live`: ccd's live switch per project; empty on a ccd without the release store. */
interface Ctx { src: AppData; ev: Evidence; all: TopologyView; needs: DecisionItem[]; names: Map<string, string>; stale: boolean;
  live: Record<string, { live: boolean }> }
const openTasks = (c: Ctx, key: string) => c.src.tickets.filter((t) => t.project === key && isActive(t)).length;
const needsOf = (c: Ctx, key: string) => c.needs.filter((d) => d.project === key).length;

// ---------- graph ----------

/** Fit the graph to its box on first paint, on a resize, and when `key` changes (what is drawn, not how far a stage
 *  is expanded: showing a stage's tasks keeps the pan and zoom you had; 0 or the Fit button refits). */
function useFit(box: React.RefObject<HTMLDivElement | null>, bounds: { w: number; h: number }, key: string) {
  const [t, setT] = useState({ x: 0, y: 0, k: 0.8 });
  const fit = useCallback(() => {
    const el = box.current; if (!el) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const legend = 48;   // keep the legend and zoom tools clear of the graph
    const k = Math.min(r.width / (bounds.w + 60), (r.height - legend) / (bounds.h + 30), 1.25);
    setT({ k, x: (r.width - bounds.w * k) / 2, y: Math.max(12, (r.height - legend - bounds.h * k) / 2) });
  }, [box, bounds.w, bounds.h]);
  const latest = useRef(fit);
  latest.current = fit;
  useLayoutEffect(() => { latest.current(); }, [key]);
  useEffect(() => {
    const el = box.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => latest.current()); ro.observe(el);
    return () => ro.disconnect();
  }, [box]);
  return { t, setT, fit };
}

function Meter({ label, value }: { label: string; value: number | null }) {
  return <span className="hq-gmeter"><small>{label}</small><span><i style={{ width: `${Math.min(100, Math.max(0, value ?? 0))}%` }} /></span><small>{pct(value)}</small></span>;
}

function NodeBody({ n, c, v, expanded }: { n: GNode; c: Ctx; v: TopologyView; expanded: boolean }): ReactNode {
  if (n.kind === "root") {
    const k = c.needs.length;
    return <>
      <span className="hq-gn-row"><span className="hq-gn-av" aria-hidden>J</span>
        <span className="hq-gn-body"><b className="is-lg">Jay</b><small>Directs every project</small></span></span>
      <span className="hq-gn-row hq-gn-foot"><span className={k ? "t-jay" : undefined}>{k ? `${k} need you` : "Nothing needs you"}</span>
        <i className="hq-gn-sep" /><span>{plural(c.all.projects.length, "project")}</span></span>
    </>;
  }
  if (n.kind === "project") {
    const p = v.projects.find((x) => x.key === n.ref)!;
    const [label, tone] = HEALTH[p.health];
    const need = needsOf(c, p.key);
    const foot = [plural(openTasks(c, p.key), "task"), `${plural(p.sessions, "session")}${c.stale ? " (last)" : ""}`,
      p.coordinator ? `Lead ${PRESENCE_LABEL[p.coordinator.presence].toLowerCase()}` : "No lead"].join(" · ");
    return <>
      <span className="hq-gn-row"><i className="hq-gn-dot" aria-hidden /><span className="hq-gn-body"><b>{p.name}</b>
        <small className="hq-ellip" title={p.healthWhy}>{p.healthWhy}</small></span></span>
      <span className="hq-gn-row"><Pill tone={tone}>{label}</Pill>{need > 0 && <Pill tone="jay">{need} need you</Pill>}<LiveTag project={p.key} /></span>
      <span className="hq-gn-row hq-gn-foot"><span className="hq-ellip">{foot}</span></span>
    </>;
  }
  if (n.kind === "stage") {
    const s = v.stages.find((x) => x.id === n.ref)!;
    return <>
      <span className="hq-gn-row"><span className="hq-gn-ico"><Icon name={STAGE_ICON[s.id] ?? "pulse"} size={19} /></span>
        <span className="hq-gn-body"><b>{s.label}</b><small>{plural(s.tasks.length, "task")}{expanded ? "" : ` · ${plural(s.flows.length, "project")}`}</small></span></span>
      <span className="hq-gn-row hq-gn-foot">{s.flows.some((f) => f.blocked) && <Pill tone="bad">Blocked</Pill>}
        {s.flows.some((f) => f.needsJay) && <Pill tone="jay">Needs you</Pill>}
        {!s.flows.some((f) => f.blocked || f.needsJay) && <span>Nothing waiting on you</span>}</span>
    </>;
  }
  if (n.kind === "task") {
    const t = v.stages.flatMap((s) => s.tasks).find((x) => x.key === n.ref)!;
    return <><i className="hq-gn-dot" aria-hidden /><code>{t.key}</code><span className="hq-ellip">{t.title}</span>
      {t.blocked ? <Pill tone="bad">Blocked</Pill> : t.needsJay ? <Pill tone="jay">You</Pill> : null}</>;
  }
  if (n.kind === "more") {
    const s = v.stages.find((x) => x.id === n.ref)!;
    return <span>{s.tasks.length - TASK_NODES} more · listed in the inspector</span>;
  }
  const h = v.hosts.find((x) => hostId(x) === n.ref)!;
  const [label, tone] = HOST[h.status];
  return <span className="hq-gn-row is-top"><span className="hq-gn-ico is-lg"><Icon name={h.kind === "ccd" ? "server" : "laptop"} size={28} /></span>
    <span className="hq-gn-body"><b className="hq-ellip">{h.name}</b>
      <span className="hq-gn-row"><Pill tone={tone}>{label}</Pill><small className="hq-ellip">{h.kind === "ccd" ? "ccd host" : `${h.kind} worker`}</small></span>
      {h.kind === "ccd" && h.status === "online" ? <span className="hq-gmeters"><Meter label="CPU" value={h.cpuPct} /><Meter label="MEM" value={h.memPct} />
        <Meter label="DISK" value={h.diskPct} /></span>
        : <small className="hq-ellip">{h.why}{h.asOf != null ? ` · ${h.kind === "ccd" ? "vitals" : "heartbeat"} ${ago(h.asOf, c.ev.now)} ago` : ""}</small>}
      {h.sessions != null && <small>{plural(h.sessions, "live session")}</small>}</span></span>;
}

function nodeLabel(n: GNode, v: TopologyView, c: Ctx): string {
  switch (n.kind) {
    case "root": return `Jay, ${c.needs.length} need you`;
    case "project": {
      const p = v.projects.find((x) => x.key === n.ref)!;
      const live = c.live[p.key];
      return `${p.name}, ${HEALTH[p.health][0].toLowerCase()}${live ? (live.live ? ", live" : ", not live") : ""}`;
    }
    case "stage": { const s = v.stages.find((x) => x.id === n.ref)!; return `${s.label}, ${plural(s.tasks.length, "task")}`; }
    case "task": { const t = v.stages.flatMap((s) => s.tasks).find((x) => x.key === n.ref)!; return `${t.key} ${t.title}`; }
    case "more": return `More ${v.stages.find((x) => x.id === n.ref)!.label} tasks`;
    default: { const h = v.hosts.find((x) => hostId(x) === n.ref)!; return `${h.name}, ${HOST[h.status][0].toLowerCase()}`; }
  }
}

function Canvas({ v, c, sel, setSel, layers, expanded, setExpanded }: { v: TopologyView; c: Ctx; sel: string; setSel: (s: string) => void;
  layers: Layers; expanded: string[]; setExpanded: (e: string[]) => void }) {
  const g = useMemo(() => layoutTopology(v, expanded, layers), [v, expanded, layers]);
  const off = useMemo(() => ports(g.nodes, g.edges), [g]);
  const byId = useMemo(() => new Map(g.nodes.map((n) => [n.id, n])), [g]);
  const box = useRef<HTMLDivElement>(null);
  const fitKey = [v.projects.map((p) => p.key), v.stages.map((s) => s.id), v.hosts.map(hostId)].join("|");
  const { t, setT, fit } = useFit(box, g.bounds, fitKey);
  const [hover, setHover] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const linked = useMemo(() => hover ? neighbours(hover, g.edges) : null, [hover, g.edges]);
  const zoom = useCallback((f: number, cx?: number, cy?: number) => setT((p) => {
    const r = box.current?.getBoundingClientRect();
    const px = cx ?? (r ? r.width / 2 : 0), py = cy ?? (r ? r.height / 2 : 0);
    const k = Math.max(0.3, Math.min(2.4, p.k * f));
    return { k, x: px - ((px - p.x) * k) / p.k, y: py - ((py - p.y) * k) / p.k };
  }), [setT]);
  // Ctrl + scroll (and a trackpad pinch, which arrives as one) zooms; a plain scroll still scrolls the page.
  useEffect(() => {
    const el = box.current; if (!el) return;
    const w = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", w, { passive: false });
    return () => el.removeEventListener("wheel", w);
  }, [zoom]);
  const onKey = (e: KeyboardEvent) => {
    if ((e.target as HTMLElement).tagName === "BUTTON" && !["+", "-", "=", "0"].includes(e.key)) return;
    const step = 60;
    if (e.key === "+" || e.key === "=") zoom(1.15); else if (e.key === "-") zoom(1 / 1.15); else if (e.key === "0") fit();
    else if (e.key === "ArrowLeft") setT((p) => ({ ...p, x: p.x + step })); else if (e.key === "ArrowRight") setT((p) => ({ ...p, x: p.x - step }));
    else if (e.key === "ArrowUp") setT((p) => ({ ...p, y: p.y + step })); else if (e.key === "ArrowDown") setT((p) => ({ ...p, y: p.y - step }));
    else return;
    e.preventDefault();
  };
  const toggle = (id: string) => setExpanded(expanded.includes(id) ? expanded.filter((x) => x !== id) : [...expanded, id]);

  return <div className="hq-canvas" ref={box} tabIndex={0} onKeyDown={onKey} data-testid="topology-canvas"
    aria-label="Company graph. Arrow keys move it, plus and minus zoom, 0 fits. Ctrl and scroll also zooms."
    onPointerDown={(e) => { if ((e.target as HTMLElement).closest("button")) return; drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y };
      e.currentTarget.setPointerCapture?.(e.pointerId); }}
    onPointerMove={(e) => { const d = drag.current; if (d) setT((p) => ({ ...p, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y })); }}
    onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
    <div className="hq-world" style={{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.k})`, width: g.bounds.w, height: g.bounds.h }}>
      <svg className="hq-edges" width={g.bounds.w} height={g.bounds.h} aria-hidden>
        {g.edges.map((e) => {
          const a = byId.get(e.from), b = byId.get(e.to); if (!a || !b) return null;
          const o = off.get(e.id) ?? { a: 0, b: 0 };
          const d = curve(a, b, o.a, o.b);
          const dim = linked && !(linked.has(e.from) && linked.has(e.to));
          return <g key={e.id} className={cx("hq-edge", `ek-${e.kind}`, dim && "is-dim", e.blocked && "is-blocked", e.idle && "is-idle")}
            style={{ ["--c" as string]: e.pj ? pjColor(e.pj) : undefined }} data-edge={e.id}>
            <path d={d} className="hq-edge-line" />
            <circle cx={a.x + a.w / 2 + o.a} cy={a.y + a.h} r="2.6" /><circle cx={b.x + b.w / 2 + o.b} cy={b.y} r="2.6" />
          </g>;
        })}
      </svg>
      {g.nodes.map((n) => {
        const isOpen = n.kind === "stage" && expanded.includes(n.ref);
        const node = <button key={n.id} type="button" data-node={n.id} aria-label={nodeLabel(n, v, c)} aria-pressed={sel === n.id}
          className={cx("hq-gnode", `k-${n.kind}`, sel === n.id && "is-sel", linked && !linked.has(n.id) && "is-dim", hover === n.id && "is-hot")}
          style={{ left: n.x, top: n.y, width: n.w, height: n.h, ["--c" as string]: n.pj ? pjColor(n.pj) : undefined }}
          onClick={() => setSel(n.kind === "more" ? `s:${n.ref}` : n.id)}
          onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}>
          <NodeBody n={n} c={c} v={v} expanded={isOpen} /></button>;
        if (n.kind !== "stage") return node;
        const s = v.stages.find((x) => x.id === n.ref)!;
        return [node, <button key={`x:${n.id}`} type="button" className="hq-gn-expand" style={{ left: n.x + n.w - 11, top: n.y + n.h / 2 - 11 }}
          aria-expanded={isOpen} aria-label={`${isOpen ? "Hide" : "Show"} ${s.label} tasks`} onClick={() => toggle(n.ref)}>
          <Icon name={isOpen ? "zoomout" : "plus"} size={13} /></button>];
      })}
    </div>
    <div className="hq-canvas-tools" role="toolbar" aria-label="Zoom">
      <button type="button" onClick={() => zoom(1.15)} aria-label="Zoom in"><Icon name="zoomin" size={17} /></button>
      <button type="button" onClick={() => zoom(1 / 1.15)} aria-label="Zoom out"><Icon name="zoomout" size={17} /></button>
      <button type="button" onClick={fit} aria-label="Fit to screen"><Icon name="fit" size={17} /></button>
      <span className="hq-zoom-pct">{Math.round(t.k * 100)}%</span>
    </div>
    <div className="hq-legend" aria-label="Legend">
      <span><i className="lg-manage" />Directs</span><span><i className="lg-flow" />Task flow</span><span><i className="lg-host" />Runs on</span>
      <span><i className="lg-blocked" />Blocked</span><span><i className="lg-idle" />No open work</span>
    </div>
  </div>;
}

// ---------- inspector ----------

function TaskList({ tasks, stage }: { tasks: { key: string; title: string; blocked: boolean; needsJay: boolean }[]; stage?: Map<string, string> }) {
  return <ul className="hq-topo-tasks">{tasks.map((t) => <li key={t.key}><a href={href("tasks", t.key)}>
    <code>{t.key}</code><span className="hq-ellip" title={t.title}>{t.title}</span>
    {t.blocked ? <Pill tone="bad">Blocked</Pill> : t.needsJay ? <Pill tone="jay">Needs you</Pill>
      : stage?.get(t.key) ? <small className="hq-dim">{stage.get(t.key)}</small> : null}</a></li>)}</ul>;
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return <div><b className={tone ? `t-${tone}` : undefined}>{value}</b><small>{label}</small></div>;
}

function Inspector({ sel, c, onBack }: { sel: string; c: Ctx; onBack: () => void }) {
  const { all, src, ev } = c;
  const kind = sel.slice(0, sel.indexOf(":"));
  const ref = sel.slice(sel.indexOf(":") + 1);
  const stageOfTask = new Map(all.stages.flatMap((s) => s.tasks.map((t) => [t.key, s.label] as const)));
  let body: ReactNode = null;

  if (kind === "p") {
    const p = all.projects.find((x) => x.key === ref);
    if (p) {
      const pv = src.state?.projects.find((x) => x.key === p.key);
      const [label, tone] = HEALTH[p.health];
      const tasks = all.stages.flatMap((s) => s.tasks).filter((t) => t.project === p.key);
      const need = needsOf(c, p.key);
      body = <>
        <div className="hq-insp-head" style={{ ["--pj" as string]: pjColor(p.key) }}><i className="hq-gn-dot" aria-hidden />
          <div><h3>{p.name}</h3><p>{pv?.summary || "Project"}</p></div></div>
        <div className="hq-insp-status"><Pill tone={tone}>{label}</Pill><span className="hq-dim">{p.healthWhy}</span></div>
        <ReleaseNote project={p.key} />
        <div className="hq-insp-stats"><Stat label="Open tasks" value={openTasks(c, p.key)} /><Stat label="Need you" value={need} tone={need ? "jay" : undefined} />
          <Stat label="PRs" value={pv ? pv.prs.length : "—"} /><Stat label={c.stale ? "Sessions (last)" : "Sessions"} value={p.sessions} /></div>
        <p className="hq-note">{p.coordinator ? <>Lead session: <Pill tone={PRESENCE_TONE[p.coordinator.presence]}>{PRESENCE_LABEL[p.coordinator.presence]}</Pill></>
          : "No lead session is running for this project."}</p>
        <h4 className="hq-insp-h">Open work <a className="hq-link" href={href("tasks", null, { project: p.key })}>All in Engineering</a></h4>
        {tasks.length ? <TaskList tasks={tasks.slice(0, 8)} stage={stageOfTask} /> : <p className="hq-empty">No open tasks.</p>}
        <div className="hq-insp-actions"><a className="hq-btn is-primary" href={href("projects", p.key)}>Open project</a>
          <a className="hq-btn" href={href("agents")}>Teams</a></div>
      </>;
    }
  } else if (kind === "s") {
    const s = all.stages.find((x) => x.id === ref);
    if (s) body = <>
      <div className="hq-insp-head"><span className="hq-gn-ico is-lg"><Icon name={STAGE_ICON[s.id] ?? "pulse"} size={24} /></span>
        <div><h3>{s.label}</h3><p>Pipeline stage · {plural(s.tasks.length, "task")} across {plural(s.flows.length, "project")}</p></div></div>
      <ul className="hq-topo-flows">{s.flows.map((f) => <li key={f.project} style={{ ["--pj" as string]: pjColor(f.project) }}>
        <i aria-hidden /><span className="hq-ellip">{c.names.get(f.project) ?? f.project}</span>
        <span className="hq-topo-flags">{f.blocked && <Pill tone="bad">Blocked</Pill>}{f.needsJay && <Pill tone="jay">Needs you</Pill>}</span>
        <b>{f.count}</b></li>)}</ul>
      <h4 className="hq-insp-h">Tasks <a className="hq-link" href={href("tasks")}>Engineering</a></h4>
      <TaskList tasks={s.tasks} />
    </>;
  } else if (kind === "t") {
    const t: Ticket | undefined = src.tickets.find((x) => x.key === ref && isActive(x));
    if (t) {
      const tt = all.stages.flatMap((s) => s.tasks).find((x) => x.key === t.key);
      body = <>
        <div className="hq-insp-head" style={{ ["--pj" as string]: pjColor(t.project) }}><i className="hq-gn-dot" aria-hidden />
          <div><h3><code>{t.key}</code> {t.title}</h3><p>{c.names.get(t.project) ?? t.project}{stageOfTask.get(t.key) ? ` · ${stageOfTask.get(t.key)}` : ""}</p></div></div>
        <div className="hq-insp-status">{tt?.blocked && <Pill tone="bad">Blocked</Pill>}{tt?.needsJay && <Pill tone="jay">Needs you</Pill>}
          <Pill tone="info">{stageOf(t)}</Pill></div>
        <dl className="hq-kv">
          <dt>Owner</dt><dd>{t.assignee ?? t.agentRole ?? "Nobody yet"}</dd>
          <dt>Priority</dt><dd>{t.priority}</dd>
          {t.branch && <><dt>Branch</dt><dd><code>{t.branch}</code></dd></>}
          {t.prNumber != null && <><dt>Pull request</dt><dd>#{t.prNumber}</dd></>}
          {t.blockedBy.length > 0 && <><dt>Blocked by</dt><dd>{t.blockedBy.join(", ")}</dd></>}
          <dt>Updated</dt><dd>{ago(t.updatedAt, ev.now)} ago</dd>
        </dl>
        <div className="hq-insp-actions"><a className="hq-btn is-primary" href={href("tasks", t.key)}>Open task</a></div>
      </>;
    }
  } else if (kind === "h") {
    const h: TopoHost | undefined = all.hosts.find((x) => hostId(x) === sel);
    if (h) {
      const [label, tone] = HOST[h.status];
      body = <>
        <div className="hq-insp-head"><span className="hq-gn-ico is-lg"><Icon name={h.kind === "ccd" ? "server" : "laptop"} size={24} /></span>
          <div><h3>{h.name}</h3><p>{h.kind === "ccd" ? "ccd host · runs every agent session" : `${h.kind} worker node`}</p></div></div>
        <div className="hq-insp-status"><Pill tone={tone}>{label}</Pill><span className="hq-dim">{h.why}</span></div>
        <dl className="hq-kv">
          {h.kind === "ccd" && <><dt>CPU</dt><dd>{pct(h.cpuPct)}</dd><dt>Memory</dt><dd>{pct(h.memPct)}</dd><dt>Disk</dt><dd>{pct(h.diskPct)}</dd></>}
          <dt>Live sessions</dt><dd>{h.sessions ?? (h.kind === "ccd" ? "Unknown" : "None: workers run no sessions yet")}</dd>
          <dt>{h.kind === "ccd" ? "Vitals" : "Heartbeat"}</dt><dd>{h.asOf != null ? `${ago(h.asOf, ev.now)} ago` : "Never reported"}</dd>
        </dl>
        <div className="hq-insp-actions"><a className="hq-btn" href={href("settings", null, { tab: "workers" })}>Settings › Workers</a></div>
      </>;
    }
  }
  if (!body) {
    const top = c.needs.slice(0, 6);
    const count = (hh: Health) => all.projects.filter((p) => p.health === hh).length;
    body = <>
      <div className="hq-insp-head"><span className="hq-gn-av is-lg" aria-hidden>J</span><div><h3>Jay</h3><p>Directs every project from CommandCenter.</p></div></div>
      <div className="hq-insp-stats"><Stat label="Need you" value={c.needs.length} tone={c.needs.length ? "jay" : undefined} />
        <Stat label="Healthy" value={count("healthy")} tone={count("healthy") ? "ok" : undefined} />
        <Stat label="Degraded" value={count("degraded")} tone={count("degraded") ? "bad" : undefined} />
        <Stat label="Unknown" value={count("unknown")} /></div>
      <h4 className="hq-insp-h">Needs you <a className="hq-link" href={href("needs")}>Decisions</a></h4>
      {top.length ? <ul className="hq-attn">{top.map((d) => <AttentionRow key={d.id} d={d} now={ev.now} />)}</ul>
        : <p className="hq-empty">Nothing is waiting on you.</p>}
      <p className="hq-note">Select something in the graph.</p>
    </>;
  }
  return <aside className="hq-panel hq-topo-insp" aria-label="Inspector">
    {sel !== "root" && body && <button type="button" className="hq-insp-back" onClick={onBack} aria-label="Back to Jay"><Icon name="x" size={15} /></button>}
    {body}
  </aside>;
}

// ---------- list ----------

function ProjectNode({ p, c }: { p: TopoProject; c: Ctx }) {
  const [label, tone] = HEALTH[p.health];
  const [edge, edgeCls] = EDGE[p.edge];
  const pv = c.src.state?.projects.find((x) => x.key === p.key);
  const need = needsOf(c, p.key);
  return <a className="hq-proj hq-topo-node" href={href("projects", p.key)} style={{ ["--pj" as string]: pjColor(p.key) }}>
    <span className="hq-proj-top"><span className="hq-live-with"><b>{p.name}</b><LiveTag project={p.key} /></span><Pill tone={tone} title={p.healthWhy}>{label}</Pill></span>
    <small className="hq-proj-why">{p.healthWhy}</small>
    {pv?.summary && <small className="hq-ellip" title={pv.summary}>{pv.summary}</small>}
    <span className="hq-proj-foot">
      <span className={edgeCls}>{edge}</span>
      <span>{plural(openTasks(c, p.key), "open task")}</span>
      {need > 0 && <span className="t-jay">{need} need you</span>}
      {pv && <span>{plural(pv.prs.length, "PR")}</span>}
      <span>{plural(p.sessions, "session")}{c.stale ? " last reported" : ""}</span>
      <span>{p.coordinator ? `Lead: ${PRESENCE_LABEL[p.coordinator.presence]}` : "No lead session"}</span>
    </span>
  </a>;
}

function StageNode({ s, names, project }: { s: TopoStage; names: Map<string, string>; project: string | null }) {
  const more = s.tasks.length - TASKS_SHOWN;
  return <section className="hq-topo-stage" aria-label={s.label}>
    <h4>{s.label} <small>{plural(s.tasks.length, "task")}</small></h4>
    <ul className="hq-topo-flows">{s.flows.map((f) => <li key={f.project} style={{ ["--pj" as string]: pjColor(f.project) }}>
      <i aria-hidden /><span className="hq-ellip">{names.get(f.project) ?? f.project}</span>
      <span className="hq-topo-flags">{f.blocked && <Pill tone="bad">Blocked</Pill>}{f.needsJay && <Pill tone="jay">Needs you</Pill>}</span>
      <b>{f.count}</b></li>)}</ul>
    <TaskList tasks={s.tasks.slice(0, TASKS_SHOWN)} />
    {more > 0 && <a className="hq-link" href={href("tasks", null, project ? { project } : {})}>{more} more in Engineering</a>}
  </section>;
}

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

function Columns({ v, c, filtered, only }: { v: TopologyView; c: Ctx; filtered: boolean; only: string[] }) {
  return <div className="hq-topo">
    <section className="hq-panel" aria-labelledby="hq-topo-projects">
      <header><h3 id="hq-topo-projects">Projects <small>{v.projects.length}</small></h3></header>
      {v.projects.length ? <div className="hq-topo-col">{v.projects.map((p) => <ProjectNode key={p.key} p={p} c={c} />)}</div>
        : <p className="hq-empty">No projects reported yet.</p>}
    </section>
    <section className="hq-panel" aria-labelledby="hq-topo-stages">
      <header><h3 id="hq-topo-stages">Pipeline <small>{plural(v.stages.reduce((n, s) => n + s.tasks.length, 0), "open task")}</small></h3>
        <a className="hq-link" href={href("tasks")}>Engineering</a></header>
      {v.stages.length ? <div className="hq-topo-col">{v.stages.map((s) => <StageNode key={s.id} s={s} names={c.names} project={only.length === 1 ? only[0] : null} />)}</div>
        : <p className="hq-empty">{filtered ? "No open work matches this filter." : "No open work."}</p>}
    </section>
    <section className="hq-panel" aria-labelledby="hq-topo-hosts">
      <header><h3 id="hq-topo-hosts">Hosts <small>{v.hosts.length}</small></h3>
        <a className="hq-link" href={href("settings", null, { tab: "workers" })}>Workers</a></header>
      <div className="hq-topo-col">{v.hosts.map((h) => <HostNode key={hostId(h)} h={h} now={c.ev.now} />)}</div>
      {!v.hosts.length && <p className="hq-empty">No host reported yet.</p>}
    </section>
  </div>;
}

// ---------- page ----------

const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 760px)").matches;

export function Topology() {
  const { src, ev } = useHqData();
  const { workers, failed } = useWorkers();
  const rel = useRelease();
  const [mode, setMode] = useState<"graph" | "list">(() => narrow() ? "list" : "graph");
  const [status, setStatus] = useState<NonNullable<TopoFilter["status"]>>("all");
  const [only, setOnly] = useState<string[]>([]);
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [sel, setSel] = useState("root");
  const all = useMemo(() => buildTopology(src, ev, {}, workers), [src, ev, workers]);
  const v = useMemo(() => buildTopology(src, ev, { projects: only, status }, workers), [src, ev, only, status, workers]);
  const needs = useMemo(() => buildDecisions(src).items, [src]);
  const c: Ctx = { src, ev, all, needs, names: new Map(all.projects.map((p) => [p.key, p.name])), stale: ev.sessions !== "live",
    live: rel.data?.projects ?? {} };
  const toggle = (k: string) => setOnly(only.includes(k) ? only.filter((x) => x !== k) : [...only, k]);
  const filtered = only.length > 0 || status !== "all";
  const graph = mode === "graph";

  return <div className="hq-page hq-topology">
    <header className="hq-hero"><div><h2>Company</h2>
      <p>Projects, their open work and the machines it runs on.</p></div>
      <div className="hq-seg" role="group" aria-label="View">
        {([["graph", "Graph", "graph"], ["list", "List", "list"]] as const).map(([k, label, icon]) =>
          <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}><Icon name={icon} size={14} />{label}</button>)}
      </div></header>

    <div className="hq-topo-filters">
      <div className="hq-seg" role="group" aria-label="Filter work">
        {STATUS.map(([k, label]) => <button key={k} type="button" aria-pressed={status === k} onClick={() => setStatus(k)}>{label}</button>)}
      </div>
      <div className="hq-seg" role="group" aria-label="Filter by project">
        {all.projects.map((p) => <button key={p.key} type="button" aria-pressed={only.includes(p.key)} onClick={() => toggle(p.key)}>{p.name}</button>)}
      </div>
      {graph && <div className="hq-seg" role="group" aria-label="Show lines">
        {LAYERS.map(([k, label]) => <button key={k} type="button" aria-pressed={layers[k]} onClick={() => setLayers({ ...layers, [k]: !layers[k] })}>{label}</button>)}
        <button type="button" aria-pressed={expanded.length > 0} onClick={() => setExpanded(expanded.length ? [] : v.stages.map((s) => s.id))}>
          {expanded.length ? "Hide all tasks" : "Show all tasks"}</button>
      </div>}
      {filtered && <button type="button" className="hq-btn" onClick={() => { setOnly([]); setStatus("all"); }}>Clear</button>}
    </div>

    {graph ? <div className="hq-topo-main">
      <section className="hq-panel hq-topo-graph" aria-label="Graph">
        {v.projects.length || v.hosts.length ? <Canvas v={v} c={c} sel={sel} setSel={setSel} layers={layers} expanded={expanded} setExpanded={setExpanded} />
          : <p className="hq-empty">No projects reported yet.</p>}
        {filtered && !v.stages.length && <p className="hq-note">No open work matches this filter.</p>}
      </section>
      <Inspector sel={sel} c={c} onBack={() => setSel("root")} />
    </div> : <Columns v={v} c={c} filtered={filtered} only={only} />}

    {failed ? <p className="hq-note">Could not read the worker nodes; only the ccd host is shown.</p>
      : workers && !workers.available ? <p className="hq-note">Worker nodes are not enabled on this server.</p>
      : workers && !workers.nodes.length ? <p className="hq-note">No worker node is enrolled.</p> : null}
    {c.stale && <p className="hq-note">Session feed not live: lead status and session counts are the last reported.</p>}
  </div>;
}
