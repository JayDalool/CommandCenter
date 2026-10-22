// OPERATIONS TOPOLOGY — the dedicated full-page graph (reference 00, with 05 and 09).
// Jay → projects → pipeline stages → (tasks) → hosts. Pan, zoom, fit, expand stages, filter, layers,
// Topology | Table | Timeline, and an inspector that can itself be popped out to another monitor.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { HOSTS, PROJECTS, TASKS, agent, healthOf, leadConversation, project, task as taskOf, type ProjectKey } from "../data/seed";
import { projectProfile, useOrg } from "../data/org";
import { startNewProject, Lifecycle } from "./onboarding/NewProject";
import { TARGET_MODES } from "../data/catalog";
import { ALL_LAYERS, ROOT, STAGE_GROUPS, buildGraph, curve, groupOf, ports, type Filters, type GNode, type Layers } from "../data/graph";
import { useViewState } from "../data/live";
import { go } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, AvatarStack, Demo, Panel, Pill, ProjIcon, Spark, StagePill, TaskKey, ViewAll, cx, plural } from "../components/ui";
import { AgentDot, AgentRow, AgentStatus, useAgentView, useOpenAgent } from "../components/agent";
import { Detachable, PopButton } from "../windows/Detachable";
import { SPARK } from "../data/seed";

const V = "page:topology";
/** Who is on each project's team (from the organisation store). Their live status comes from the feed. */
const roster = (key: string) => project(key).team.map((m) => m.id);

export function AlertStrip() {
  const cards = [
    { tone: "bad", icon: "info", t: "3 items need Jay", s: "2 approvals · 1 blocked task", to: () => go("decisions") },
    { tone: "ok", icon: "rocket", t: "1 release ready", s: "SamVision v0.4.2 · waits for a window", to: () => go("engineering") },
    { tone: "warn", icon: "info", t: "1 blocked task", s: "MFE-014 · release window undecided", to: () => go("engineering") },
    { tone: "info", icon: "chart", t: `${PROJECTS.filter((p) => p.health !== "paused" && p.health !== "onboarding").length} active · ${PROJECTS.filter((p) => p.health === "paused").length} paused${PROJECTS.some((p) => p.health === "onboarding") ? ` · ${PROJECTS.filter((p) => p.health === "onboarding").length} onboarding` : ""}`,
      s: PROJECTS.filter((p) => p.health === "paused").map((p) => `${p.name} paused by Jay`).join(" · ") || "Nothing paused", to: () => go("teams") },
  ];
  return <div className="alert-strip">{cards.map((c) => <button key={c.t} type="button" className={`alert-card t-${c.tone}`} onClick={c.to}>
    <span className="ac-ico"><Icon name={c.icon} size={20} /></span><span><b>{c.t}</b><small>{c.s}</small></span><Icon name="chevron" size={16} /></button>)}</div>;
}

function NodeCard({ n, sel, dim, hot, expanded, onSel, onHover, onToggle }: {
  n: GNode; sel: boolean; dim: boolean; hot: boolean; expanded: boolean; onSel: () => void; onHover: (h: boolean) => void; onToggle: () => void }) {
  const style = { left: n.x, top: n.y, width: n.w, height: n.h, ["--c" as string]: n.color };
  const common = { className: cx("gnode", `k-${n.kind}`, sel && "is-sel", dim && "is-dim", hot && "is-hot"), style, onClick: onSel,
    onMouseEnter: () => onHover(true), onMouseLeave: () => onHover(false), onFocus: () => onHover(true), onBlur: () => onHover(false), "data-node": n.id };
  if (n.kind === "root") {
    const p = project(n.ref!);
    return <button type="button" {...common} aria-label="CommandCenter, control plane directed by Jay">
      <span className="gn-row"><ProjIcon k={p.key} size={42} /><span className="gn-body"><b className="lg">{p.name}</b><small>{p.version} · {p.env}</small></span>
        <Spark data={SPARK.a} color={p.color} w={70} h={24} /></span>
      <span className="gn-row gn-mid"><span className="pres t-ok"><i /><b>Healthy</b></span><span className="gn-sep" />
        <span className="root-jay"><span className="av av-jay" style={{ width: 22, height: 22, fontSize: 11 }}>J</span>Directed by <b>Jay</b></span></span>
      <span className="gn-row gn-foot">{roster(p.key).length ? <AvatarStack ids={roster(p.key).slice(0, 3)} size={20} /> : <Icon name="lock" size={14} />}<span>{roster(p.key).length ? plural(roster(p.key).length, "agent") : "No agents"}</span>
        <span className="gn-sep" /><Icon name="rocket" size={14} /><span>shadow autonomy</span></span>
    </button>;
  }
  if (n.kind === "project") {
    const p = project(n.ref!);
    const paused = p.health === "paused";
    const h = healthOf(p);
    const nTasks = TASKS.filter((t) => t.project === p.key && t.stage !== "Closed").length;
    return <button type="button" {...common} aria-label={`${p.name}, ${h.label.toLowerCase()}`}>
      <span className="gn-row"><ProjIcon k={p.key} size={40} /><span className="gn-body"><b>{p.name}</b><small>{p.health === "onboarding" ? "Observation only" : `${p.version} · ${p.env}`}</small></span></span>
      <span className="gn-row gn-mid"><span className={`pres t-${h.tone}`}><i /><b>{h.label}</b></span>
        {!paused && p.health !== "onboarding" && <Spark data={p.key === "mfe" ? SPARK.c : p.key === "gyst" ? SPARK.b : SPARK.a} color={p.color} w={84} h={22} />}</span>
      <span className="gn-row gn-foot">{roster(p.key).length ? <AvatarStack ids={roster(p.key).slice(0, 3)} size={20} /> : <Icon name="lock" size={14} />}<span>{roster(p.key).length ? plural(roster(p.key).length, "agent") : "No agents"}</span>
        <span className="gn-sep" /><Icon name="list" size={14} /><span>{plural(nTasks, "task")}</span></span>
    </button>;
  }
  if (n.kind === "stage") {
    const g = STAGE_GROUPS.find((s) => s.id === n.ref)!;
    const ts = TASKS.filter((t) => groupOf(t) === g.id);
    const blocked = ts.some((t) => t.stage === "Blocked");
    return <div className="gnode-wrap" style={{ position: "absolute", left: n.x, top: n.y }}>
      <button type="button" {...common} style={{ ...style, left: 0, top: 0, position: "relative" }} aria-label={`${g.label}, ${ts.length} tasks`}>
        <span className="gn-row"><span className="gn-ico"><Icon name={g.icon} size={20} /></span><span className="gn-body"><b>{g.label}</b><small>{plural(ts.length, "task")}</small></span></span>
        <span className="gn-row gn-foot"><AvatarStack ids={[...new Set(ts.map((t) => t.owner))].slice(0, 3)} size={20} />
          <Pill tone={blocked ? "bad" : "ok"}>{blocked ? "Blocked" : "Working"}</Pill></span>
      </button>
      <button type="button" className="gn-expand" onClick={onToggle} aria-expanded={expanded} aria-label={`${expanded ? "Collapse" : "Expand"} ${g.label} tasks`}>
        <Icon name={expanded ? "zoomout" : "plus"} size={13} /></button>
    </div>;
  }
  if (n.kind === "task") {
    const t = taskOf(n.ref!)!;
    return <button type="button" {...common} aria-label={`${t.key} ${t.title}`}>
      <i className="tab-dot" style={{ background: n.color }} /><b className="mono">{t.key}</b><span className="ellip">{t.title}</span></button>;
  }
  const h = HOSTS.find((x) => x.id === n.ref)!;
  const on = h.status === "online";
  return <button type="button" {...common} aria-label={`${h.name}, ${on ? "online" : "status unknown"}`}>
    <span className="gn-row"><span className="gn-ico is-lg"><Icon name={h.kind === "server" ? "server" : "laptop"} size={30} /></span>
      <span className="gn-body"><b>{h.name}</b><span className={`pres t-${on ? "ok" : "idle"}`}><i /><b>{on ? "Online" : "Not reporting"}</b></span>
        <small><Icon name="users" size={13} /> {on ? `${h.sessions} agent sessions` : "no placement allowed by policy"}</small></span>
      {on ? <span className="meters">{(["cpu", "mem", "disk"] as const).map((m) => <span key={m} className="meter"><small>{m.toUpperCase()}</small><span><i style={{ width: `${h[m]}%` }} /></span><small>{h[m]}%</small></span>)}</span>
        : <span className="meters muted">Last seen: unknown<br />Shown as unknown, never as online.</span>}</span>
  </button>;
}

function useFit(box: React.RefObject<HTMLDivElement | null>, bounds: { w: number; h: number }) {
  const [t, setT] = useState({ x: 0, y: 0, k: 0.8 });
  const fit = useCallback(() => {
    const el = box.current; if (!el) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const legend = 48;   // keep the bottom legend and zoom tools clear of the graph
    const k = Math.min(r.width / (bounds.w + 60), (r.height - legend) / (bounds.h + 30), 1.25);
    setT({ k, x: (r.width - bounds.w * k) / 2, y: Math.max(12, (r.height - legend - bounds.h * k) / 2) });
  }, [box, bounds.w, bounds.h]);
  useLayoutEffect(() => { fit(); }, [fit]);
  useEffect(() => {
    const el = box.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => fit()); ro.observe(el);
    return () => ro.disconnect();
  }, [box, fit]);
  return { t, setT, fit };
}

function Canvas({ sel, setSel, filters, layers, expanded, setExpanded }: {
  sel: string; setSel: (s: string) => void; filters: Filters; layers: Layers; expanded: string[]; setExpanded: (e: string[]) => void }) {
  const { v } = useOrg();
  const g = useMemo(() => buildGraph(filters, expanded, layers), [filters, expanded, layers, v]);   // eslint-disable-line react-hooks/exhaustive-deps
  const off = useMemo(() => ports(g.nodes, g.edges), [g]);
  const byId = useMemo(() => new Map(g.nodes.map((n) => [n.id, n])), [g]);
  const box = useRef<HTMLDivElement>(null);
  const { t, setT, fit } = useFit(box, g.bounds);
  const [hover, setHover] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const focus = hover ?? null;
  const linked = useMemo(() => {
    if (!focus) return null;
    const s = new Set([focus]);
    g.edges.forEach((e) => { if (e.from === focus) s.add(e.to); if (e.to === focus) s.add(e.from); });
    return s;
  }, [focus, g.edges]);
  const zoom = (f: number, cx?: number, cy?: number) => setT((p) => {
    const r = box.current?.getBoundingClientRect();
    const px = cx ?? (r ? r.width / 2 : 0), py = cy ?? (r ? r.height / 2 : 0);
    const k = Math.max(0.3, Math.min(2.4, p.k * f));
    return { k, x: px - ((px - p.x) * k) / p.k, y: py - ((py - p.y) * k) / p.k };
  });
  useEffect(() => {
    const el = box.current; if (!el) return;
    const w = (e: WheelEvent) => { e.preventDefault(); const r = el.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top); };
    el.addEventListener("wheel", w, { passive: false });
    return () => el.removeEventListener("wheel", w);
  });
  const onKey = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).tagName === "BUTTON" && !["+", "-", "=", "0"].includes(e.key)) return;
    const step = 60;
    if (e.key === "+" || e.key === "=") zoom(1.15); else if (e.key === "-") zoom(1 / 1.15); else if (e.key === "0") fit();
    else if (e.key === "ArrowLeft") setT((p) => ({ ...p, x: p.x + step })); else if (e.key === "ArrowRight") setT((p) => ({ ...p, x: p.x - step }));
    else if (e.key === "ArrowUp") setT((p) => ({ ...p, y: p.y + step })); else if (e.key === "ArrowDown") setT((p) => ({ ...p, y: p.y - step }));
    else return;
    e.preventDefault();
  };
  return <div className="canvas" ref={box} tabIndex={0} onKeyDown={onKey} aria-label="Operations topology. Arrow keys pan, plus and minus zoom, 0 fits."
    onPointerDown={(e) => { if ((e.target as HTMLElement).closest("button")) return; drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y }; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); }}
    onPointerMove={(e) => { const d = drag.current; if (d) setT((p) => ({ ...p, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y })); }}
    onPointerUp={() => { drag.current = null; }} data-testid="topology-canvas">
    <div className="world" style={{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.k})`, width: g.bounds.w, height: g.bounds.h }}>
      <svg className="edges" width={g.bounds.w} height={g.bounds.h} aria-hidden>
        <defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3.5" /></filter></defs>
        {g.edges.map((e) => {
          const a = byId.get(e.from), b = byId.get(e.to); if (!a || !b) return null;
          const o = off.get(e.id) ?? { a: 0, b: 0 };
          const d = curve(a, b, o.a, o.b);
          const dim = linked && !(linked.has(e.from) && linked.has(e.to));
          const col = e.blocked ? "#ff4f6d" : e.paused ? "#6b7690" : e.color;
          return <g key={e.id} className={cx("edge", `ek-${e.kind}`, dim && "is-dim", e.blocked && "is-blocked", e.paused && "is-paused")} data-edge={e.id}>
            {e.kind !== "host" && !e.paused && <path d={d} stroke={col} className="edge-glow" filter="url(#glow)" />}
            <path d={d} stroke={col} className="edge-line" />
            <circle cx={a.x + a.w / 2 + o.a} cy={a.y + a.h} r="3.4" fill={col} /><circle cx={b.x + b.w / 2 + o.b} cy={b.y} r="3.4" fill={col} />
          </g>;
        })}
      </svg>
      {g.edges.filter((e) => e.tag).map((e) => {
        const b = byId.get(e.to)!; const o = off.get(e.id) ?? { a: 0, b: 0 };
        return <span key={`tag${e.id}`} className={cx("edge-tag", e.blocked && "t-bad", e.paused && "t-idle")}
          style={{ left: b.x + b.w / 2 + o.b, top: b.y - 26, ["--c" as string]: e.color }}>{e.tag}</span>;
      })}
      {g.nodes.map((n) => <NodeCard key={n.id} n={n} sel={sel === n.id} dim={!!linked && !linked.has(n.id)} hot={hover === n.id}
        expanded={expanded.includes(n.ref ?? "")} onSel={() => setSel(n.id)} onHover={(h) => setHover(h ? n.id : null)}
        onToggle={() => setExpanded(expanded.includes(n.ref!) ? expanded.filter((x) => x !== n.ref) : [...expanded, n.ref!])} />)}
    </div>
    <div className="canvas-tools" role="toolbar" aria-label="Zoom">
      <button type="button" onClick={() => zoom(1.15)} aria-label="Zoom in"><Icon name="zoomin" size={17} /></button>
      <button type="button" onClick={() => zoom(1 / 1.15)} aria-label="Zoom out"><Icon name="zoomout" size={17} /></button>
      <button type="button" onClick={fit} aria-label="Fit to screen"><Icon name="fit" size={17} /></button>
      <span className="zoom-pct">{Math.round(t.k * 100)}%</span>
    </div>
    <div className="legend" aria-label="Legend">
      <span><i className="lg-manage" />Directs</span><span><i className="lg-flow" />Task flow</span><span><i className="lg-host" />Runs on</span>
      <span><i className="lg-blocked" />Blocked</span><span><i className="lg-paused" />Paused</span>
    </div>
  </div>;
}

function TableMode({ setSel }: { setSel: (s: string) => void }) {
  return <div className="topo-table"><table className="grid">
    <thead><tr><th>Node</th><th>Type</th><th>Status</th><th>Open tasks</th><th>Connected to</th></tr></thead>
    <tbody>
      {PROJECTS.map((p) => <tr key={p.key} onClick={() => setSel(`p:${p.key}`)}><td><span className="cell-pj"><ProjIcon k={p.key} size={24} />{p.name}</span></td><td>Project</td>
        <td><Pill tone={healthOf(p).tone} dot>{healthOf(p).label}</Pill></td>
        <td>{TASKS.filter((t) => t.project === p.key).length}</td><td>Jay (directs) · {STAGE_GROUPS.filter((g) => TASKS.some((t) => t.project === p.key && groupOf(t) === g.id)).map((g) => g.label).join(", ") || "—"}</td></tr>)}
      {STAGE_GROUPS.map((g) => <tr key={g.id} onClick={() => setSel(`s:${g.id}`)}><td>{g.label}</td><td>Pipeline stage</td><td>—</td>
        <td>{TASKS.filter((t) => groupOf(t) === g.id).length}</td><td>jay-server (runs on)</td></tr>)}
      {HOSTS.map((h) => <tr key={h.id} onClick={() => setSel(`h:${h.id}`)}><td>{h.name}</td><td>WorkerNode · {h.kind}</td>
        <td><Pill tone={h.status === "online" ? "ok" : "idle"} dot>{h.status === "online" ? "Online" : "Unknown"}</Pill></td><td>—</td><td>{h.sessions} sessions</td></tr>)}
    </tbody></table></div>;
}

function TimelineMode() {
  const days = ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"];
  return <div className="timeline">
    <div className="tl-head"><span />{days.map((d) => <span key={d}>{d}</span>)}</div>
    {PROJECTS.map((p, pi) => <div key={p.key} className="tl-row"><span className="cell-pj"><ProjIcon k={p.key} size={24} />{p.name}</span>
      <div className="tl-lane">{TASKS.filter((t) => t.project === p.key).map((t, i) => {
        const start = (pi + i * 2) % 5, len = 1 + ((i + pi) % 3);
        return <span key={t.key} className={cx("tl-bar", t.stage === "Blocked" && "is-blocked", t.stage === "Paused" && "is-paused")}
          style={{ left: `${(start / 7) * 100}%`, width: `${(len / 7) * 100}%`, top: 6 + i * 26, ["--c" as string]: p.color }} title={`${t.key} · ${t.stage}`}>
          <b className="mono">{t.key}</b> {t.stage}</span>;
      })}</div></div>)}
    <p className="muted small"><Demo /> Bars show when each task moved through stages in the last 7 days. The live version reads the task ledger.</p>
  </div>;
}

function TeamDot({ id }: { id: string }) {
  const open = useOpenAgent();
  const v = useAgentView(id);
  const a = agent(id);
  return <button type="button" className="team-dot" onClick={() => open(id)} title={`${a.name} · ${a.role}`} aria-label={`${a.name} details`}>
    <span className="av-wrap"><Avatar id={id} size={30} /><AgentDot id={id} /></span><small>{a.name}</small>
    <AgentStatus v={v} task={false} /></button>;
}

export function TopologyInspector() {
  const [sel, setSel] = useViewState(V, "sel", "p:samvision");
  const [tab, setTab] = useViewState(V, "itab", "Overview");
  const kind = sel === "root" || sel === "jay" ? "p" : sel.split(":")[0];
  const ref = sel === "root" || sel === "jay" ? ROOT : sel.slice(sel.indexOf(":") + 1);
  let body: React.ReactNode;
  if (kind === "p") {
    const p = project(ref);
    const ts = TASKS.filter((t) => t.project === p.key);
    const paused = p.health === "paused";
    const h = healthOf(p);
    const pp = projectProfile(p.key);
    const lc = leadConversation(p.key);
    body = <>
      <div className="insp-head"><ProjIcon k={p.key} size={46} /><div><h2>{p.name}</h2><p>{p.blurb}</p></div></div>
      <div className="seg seg-under" role="tablist">{["Overview", "Team", "Tasks", "Releases", "Policy"].map((x) => <button key={x} role="tab" type="button" aria-selected={tab === x} onClick={() => setTab(x)}>{x}</button>)}</div>
      {tab === "Overview" && <>
        {p.key === ROOT && <div className="insp-jay"><span className="av av-jay" style={{ width: 30, height: 30, fontSize: 14 }}>J</span><span><b>Jay</b> · Engineering Director<small>Directs every project from here. Merges, deploys and personal-data changes need Jay.</small></span></div>}
        <div className="insp-status"><span className={`pres is-lg t-${h.tone}`}><i /><b>{h.label}</b></span><Pill tone="info">{p.env}</Pill><span className="sp" /><b>{p.version}</b></div>
        {paused && <p className="callout t-idle">{p.pausedReason}. No agent works on it.</p>}
        {pp.phase === "onboarding" && <><p className="callout"><Icon name="eye" size={15} /> Onboarding / Observation: agents only observe. Target {TARGET_MODES.find((m) => m.id === pp.target)?.label} applies after admission review and Jay's approval.</p><Lifecycle at={pp.stage} compact /></>}
        <div className="insp-stats"><div><b>{ts.filter((t) => t.stage !== "Paused").length}</b><small>Active tasks</small></div><div><b>{roster(p.key).length}</b><small>Team members</small></div><div><b>{p.key === "samvision" ? 1 : 0}</b><small>Release ready</small></div></div>
        <h3 className="insp-h">Team now <button type="button" className="link" onClick={() => setTab("Team")}>Details <Icon name="arrowr" size={13} /></button></h3>
        {roster(p.key).length ? <div className="insp-team">{roster(p.key).map((id) => <TeamDot key={id} id={id} />)}</div> : <p className="muted small">No agents on this team yet.</p>}
        <h3 className="insp-h">Live health <Demo label="Demo" /></h3>
        <div className="insp-health">{[["CPU", "28%", SPARK.a], ["Memory", "52%", SPARK.b], ["Task success", "98%", SPARK.c]].map(([l, v, d]) => <div key={l as string}><small>{l as string}</small><b>{v as string}</b><Spark data={d as number[]} color="#5b7cff" w={96} h={28} /></div>)}</div>
        <h3 className="insp-h">Active tasks <ViewAll onClick={() => go("engineering")} /></h3>
        <ul className="mini-list">{ts.slice(0, 4).map((t) => <li key={t.key}><button type="button" onClick={() => go("task", t.key)}><TaskKey k={t.key} /><span className="ellip">{t.title}</span><StagePill s={t.stage} /></button></li>)}</ul>
        {p.releaseWindows && <><h3 className="insp-h">Releases</h3>
          <div className="release-row"><div><b>v0.4.2</b> <Pill tone="ok">Release ready</Pill><small>Staging · waits for a release window ({p.releaseWindows.join(", ")} America/Winnipeg)</small></div>
            <button type="button" className="btn btn-sm" disabled title="Releases go through the existing gates, never from this prototype">Gated</button></div></>}
        <div className="insp-actions"><button type="button" className="btn btn-primary" onClick={() => go("teams", p.key)}><Icon name="users" size={16} /> Open team</button>
          {lc && <button type="button" className="btn" onClick={() => go("messages", lc.id)}><Icon name="message" size={16} /> Message lead</button>}</div>
      </>}
      {tab === "Team" && (roster(p.key).length ? <div className="status-rows">{roster(p.key).map((id) => <AgentRow key={id} id={id} size={30} />)}</div>
        : <p className="muted">No agents on {p.name}'s team yet.</p>)}
      {tab === "Tasks" && <ul className="mini-list">{ts.map((t) => <li key={t.key}><button type="button" onClick={() => go("task", t.key)}><TaskKey k={t.key} /><span className="ellip">{t.title}</span><StagePill s={t.stage} /></button></li>)}</ul>}
      {tab === "Releases" && <p className="muted">{p.releaseWindows ? `Release windows: ${p.releaseWindows.join(", ")} America/Winnipeg. Unattended release needs health checks and auto-rollback, which are not enabled yet; otherwise prepared and held for Jay.` : "No release windows decided yet."}</p>}
      {tab === "Policy" && <dl className="kv"><dt>Mode</dt><dd>{p.modeLabel}</dd><dt>Merge</dt><dd>{p.merge}</dd><dt>Source</dt><dd className="mono">policy/projects/{p.key}.toml</dd><dt>Autonomy</dt><dd>Evaluated in shadow mode only. Nothing executes from it.</dd></dl>}
    </>;
  } else if (kind === "s") {
    const g = STAGE_GROUPS.find((s) => s.id === ref)!;
    const ts = TASKS.filter((t) => groupOf(t) === ref);
    body = <><div className="insp-head"><span className="gn-ico is-lg"><Icon name={g.icon} size={26} /></span><div><h2>{g.label}</h2><p>Pipeline stage · {ts.length} tasks across {new Set(ts.map((t) => t.project)).size} projects</p></div></div>
      <ul className="mini-list">{ts.map((t) => <li key={t.key}><button type="button" onClick={() => go("task", t.key)}><TaskKey k={t.key} /><span className="ellip">{t.title}</span><StagePill s={t.stage} /></button></li>)}</ul>
      <h3 className="insp-h">Agents on this stage</h3>
      <div className="status-rows">{[...new Set(ts.map((t) => t.owner))].map((id) => <AgentRow key={id} id={id} size={30} />)}</div></>;
  } else if (kind === "h") {
    const h = HOSTS.find((x) => x.id === ref)!;
    body = <><div className="insp-head"><span className="gn-ico is-lg"><Icon name={h.kind === "server" ? "server" : "laptop"} size={26} /></span><div><h2>{h.name}</h2><p>WorkerNode · {h.kind}</p></div></div>
      <dl className="kv"><dt>Status</dt><dd>{h.status === "online" ? "Online (demo)" : "Unknown — not reporting"}</dd><dt>Sessions</dt><dd>{h.sessions}</dd>
        <dt>Policy</dt><dd>Agent execution is allowed on the server only (allowed_nodes = server).</dd><dt>Windows</dt><dd>Closing any CommandCenter window never stops a session on this host.</dd></dl></>;
  } else if (kind === "t") {
    const t = taskOf(ref)!;
    body = <><div className="insp-head"><ProjIcon k={t.project} size={40} /><div><h2>{t.key} · {t.title}</h2><p>{project(t.project).name}</p></div></div>
      <div className="insp-status"><StagePill s={t.stage} /><span className="sp" /></div><p>{t.why}</p>
      <h3 className="insp-h">Owner</h3><AgentRow id={t.owner} size={30} />
      <div className="insp-actions"><button type="button" className="btn btn-primary" onClick={() => go("task", t.key)}>Open Task Room</button></div></>;
  } else {
    body = <><div className="insp-head"><span className="av av-jay" style={{ width: 46, height: 46, fontSize: 20 }}>J</span><div><h2>Jay</h2><p>Engineering Director · Senior Technical Lead</p></div></div>
      <h3 className="insp-h">Needs you</h3>
      <ul className="mini-list"><li><button type="button" onClick={() => go("decisions")}><b className="mono">SV-025</b><span className="ellip">Choose comparison workflow</span><Pill tone="bad">Decide</Pill></button></li>
        <li><button type="button" onClick={() => go("task", "MFE-014")}><b className="mono">MFE-014</b><span className="ellip">Pick a release window</span><Pill tone="warn">Blocked</Pill></button></li></ul></>;
  }
  return <aside className="inspector" aria-label="Inspector">
    <div className="insp-tools"><Demo /><span className="sp" /><PopButton id="panel:topology-inspector" compact />
      <button type="button" className="icon-btn" aria-label="Back to SamVision" onClick={() => setSel("p:samvision")}><Icon name="x" size={16} /></button></div>
    {body}
  </aside>;
}

export function Topology() {
  const [mode, setMode] = useViewState(V, "mode", "Topology");
  const [sel, setSel] = useViewState(V, "sel", "p:samvision");
  const [projects, setProjects] = useViewState<ProjectKey[]>(V, "projects", []);
  const [status, setStatus] = useViewState<Filters["status"]>(V, "status", "all");
  const [layers, setLayers] = useViewState<Layers>(V, "layers", ALL_LAYERS);
  const [expanded, setExpanded] = useViewState<string[]>(V, "expanded", []);
  const [immersive, setImmersive] = useState(false);
  const [showFilters, setShowFilters] = useViewState(V, "showFilters", false);
  const active = projects.length + (status !== "all" ? 1 : 0) + Object.values(layers).filter((x) => !x).length;
  const filters = useMemo(() => ({ projects, status }), [projects, status]);
  useEffect(() => { document.body.classList.toggle("is-immersive", immersive); return () => document.body.classList.remove("is-immersive"); }, [immersive]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") setImmersive(false); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, []);
  return <div className={cx("page page-topology", immersive && "is-immersive")}>
    {!immersive && <AlertStrip />}
    <div className="topo-main">
      <section className="panel topo-panel">
        <header className="topo-head">
          <div><h1>Operations Topology</h1><p>Jay, projects, pipeline stages, agents and hosts in one view. <Demo /></p></div>
          <div className="seg" role="tablist" aria-label="View">{["Topology", "Table", "Timeline"].map((m) => <button key={m} role="tab" type="button" aria-selected={mode === m} onClick={() => setMode(m)}>
            <Icon name={m === "Topology" ? "graph" : m === "Table" ? "table" : "timeline"} size={15} />{m}</button>)}</div>
          <button type="button" className={cx("btn btn-sm", showFilters && "btn-outline")} aria-expanded={showFilters} onClick={() => setShowFilters(!showFilters)}>
            <Icon name="filter" size={14} /> Filters{active > 0 && <span className="count">{active}</span>}</button>
          <button type="button" className="btn btn-sm" onClick={() => startNewProject()}><Icon name="plus" size={14} /> New Project</button>
          <PopButton id={V} compact />
          <button type="button" className="icon-btn is-box" onClick={() => setImmersive(!immersive)} aria-pressed={immersive} title={immersive ? "Exit full screen (Esc)" : "Full screen"} aria-label="Full screen graph"><Icon name="fit" size={18} /></button>
        </header>
        {showFilters && <div className="topo-filters">
          <span className="tf-label"><Icon name="filter" size={14} /> Projects</span>
          {PROJECTS.map((p) => { const on = projects.includes(p.key); return <button key={p.key} type="button" className={cx("chip", on && "is-on")} aria-pressed={on} style={{ ["--c" as string]: p.color }}
            onClick={() => setProjects(on ? projects.filter((x) => x !== p.key) : [...projects, p.key])}><i />{p.name}</button>; })}
          <span className="tf-label">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as Filters["status"])} aria-label="Status filter">
            <option value="all">All work</option><option value="attention">Needs attention</option><option value="blocked">Blocked / paused</option></select>
          <span className="tf-label">Layers</span>
          {(Object.keys(ALL_LAYERS) as (keyof Layers)[]).map((l) => <label key={l} className="chk"><input type="checkbox" checked={layers[l]} onChange={() => setLayers({ ...layers, [l]: !layers[l] })} />
            {l === "manage" ? "Directs" : l === "flow" ? "Task flow" : l === "host" ? "Hosts" : "Blocked"}</label>)}
          <button type="button" className="chip" onClick={() => setExpanded(expanded.length ? [] : STAGE_GROUPS.map((g) => g.id))}>{expanded.length ? "Collapse all" : "Expand all stages"}</button>
        </div>}
        {mode === "Topology" && <Canvas sel={sel} setSel={setSel} filters={filters} layers={layers} expanded={expanded} setExpanded={setExpanded} />}
        {mode === "Table" && <TableMode setSel={setSel} />}
        {mode === "Timeline" && <TimelineMode />}
      </section>
      <Detachable id="panel:topology-inspector" className="inspector"><TopologyInspector /></Detachable>
    </div>
    {!immersive && <div className="topo-bottom">
      <Panel title={<>Needs You <span className="count t-bad">3</span></>} action={<ViewAll onClick={() => go("decisions")} />}>
        <ul className="need-list">{[["SV-025", "Choose the comparison workflow (Option A / B)", "22m"], ["MFE-014", "Pick a release window for MyFamilyExpenses", "47m"], ["GYST-019", "Personal-data trigger: memory retention", "2h"]].map(([k, t, a]) =>
          <li key={k}><i /><TaskKey k={k} /><span className="ellip">{t}</span><small>{a}</small></li>)}</ul></Panel>
      <Panel title={<>Release Gates <span className="count t-bad">1</span></>} action={<ViewAll onClick={() => go("engineering")} />}>
        <ul className="gate-list">{[["samvision", "SamVision v0.4.2", "Ready · waits for window", "ok", "12/12"], ["commandcenter", "CommandCenter v1.2.0", "In progress", "info", "8/12"],
          ["gyst", "GYST v0.3.1", "Owner merge", "info", "6/10"], ["mfe", "MyFamilyExpenses v0.2.0", "Blocked (no window)", "bad", "3/10"]].map(([k, n, s, tone, c]) =>
          <li key={n}><ProjIcon k={k} size={20} /><span className="ellip">{n}</span><Pill tone={tone}>{s}</Pill><small className="mono">{c}</small></li>)}</ul></Panel>
      <Panel title={<>Worker Nodes <span className="pres t-ok"><i /><b>1 online</b></span></>} action={<ViewAll onClick={() => go("more")} />}>
        <ul className="gate-list">{HOSTS.map((h) => <li key={h.id}><Icon name={h.kind === "server" ? "server" : "laptop"} size={18} /><span>{h.name}</span>
          <Pill tone={h.status === "online" ? "ok" : "idle"} dot>{h.status === "online" ? "Online" : "Unknown"}</Pill><small>{h.sessions} sessions</small><small className="mono">{h.status === "online" ? `${h.cpu}% CPU` : "—"}</small></li>)}</ul></Panel>
    </div>}
  </div>;
}
