// WORKSPACE — the live control wall (spec §5, §12, §17; docs/design/workspace-reference.webp).
//
//   ┌ PROJECTS ─────────┬ TASK DETAIL ─────────────┬ WALL (this window: up to 4 rooms) ─────┐
//   │ ▼ SamVision (4)   │ SV-071  Valuation layout │ ┌ SV-071 · SamVision ┐┌ GZ-029 ─────────┐ │
//   │     Project Cons. │ Overview Plan Questions… │ │ Claude ✓ Project   ││ Claude ✓        │ │
//   │     SV-071 ■ Jay  │ Why · Status · Plan ·    │ └────────────────────┘└─────────────────┘ │
//   │ ▶ GauzeMate (3)   │ Acceptance · Questions   │ ┌ MFE-018 ───────────┐┌ + Open Task or  ┐ │
//   └───────────────────┴──────────────────────────┴─└────────────────────┘└── Project Console┘─┘
//
// Single click a task: its detail. Double click (or Open Room): its live Task Room. A fifth room
// offers to pop one out or open a new Workspace window. Nothing scrolls the page: the wall fits the
// viewport and each terminal scrolls inside xterm only.
import { useEffect, useMemo, useState } from "react";
import { app } from "../store/app";
import { shallowEqual, useSelector } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import { prefs, usePrefs } from "../lib/prefs";
import type { Ticket } from "../api/types";
import { byProjectOrder, initials, isActive, pjVar, stageOf, STAGE, type Focus } from "../lib/control";
import { Dialog } from "../components/Dialog";
import { EmptyState } from "../components/ui";
import { Dossier } from "../workspace/Dossier";
import { Divider, RoomView } from "../workspace/Room";
import { MAX_ROOMS, closeRoom, layout, newWall, openRoom, openWorkspaceWindow, popOutRoom, returnRoom, setSplit,
  wallShape, type Room } from "../workspace/rooms";

type Spec = { kind: Room["kind"]; project: string; key: string | null };

function TaskRow({ t, selected, onPick, onOpen }: { t: Ticket; selected: boolean; onPick: () => void; onOpen: () => void }) {
  const stage = stageOf(t);
  return <div role="treeitem" aria-selected={selected} tabIndex={0} className={`tr-task${selected ? " is-sel" : ""}`}
    onClick={onPick} onDoubleClick={onOpen} title={`${t.key} — ${t.title}\nDouble-click to open its Task Room`}
    onKeyDown={(e) => { if (e.key === "Enter") { if (e.shiftKey) onOpen(); else onPick(); } }}>
    <i className={`sq vs-${STAGE[stage].tone}`} aria-hidden />
    <span className="tr-key">{t.key}</span>
    <span className="tr-title trunc">{t.title}</span>
    <span className={`tr-stage vs-t-${STAGE[stage].tone}`}>{STAGE[stage].short}</span>
  </div>;
}

function Tree({ selected, onPick, onOpen, onConsole }: {
  selected: string | null; onPick: (t: Ticket) => void; onOpen: (t: Ticket) => void; onConsole: (project: string) => void;
}) {
  const tickets = useSelector(app.store, (d) => d.tickets);
  const taskProjects = useSelector(app.store, (d) => d.taskProjects);
  const st = useSelector(app.store, (d) => d.state);
  const collapsed = usePrefs((p) => p.wsCollapsed);
  const route = useRoute();
  const [q, setQ] = useState("");
  const focusProject = route.params.get("project");
  const projects = useMemo(() => {
    const live = new Set((st?.projects ?? []).map((p) => p.key));
    return byProjectOrder(taskProjects.filter((p) => !live.size || live.has(p.key) || tickets.some((t) => t.project === p.key && isActive(t))));
  }, [taskProjects, st, tickets]);
  useEffect(() => {   // ?project= (a dashboard panel) opens that project's folder
    if (focusProject && collapsed.includes(focusProject)) prefs.patch({ wsCollapsed: collapsed.filter((k) => k !== focusProject) });
  }, [focusProject]);  // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (k: string) => prefs.patch({ wsCollapsed: collapsed.includes(k) ? collapsed.filter((x) => x !== k) : [...collapsed, k] });
  const needle = q.trim().toLowerCase();
  return <nav className="tree" aria-label="Projects and tasks">
    <div className="tree-head"><b>Projects</b><span className="sl-fill" />
      <button type="button" className="btn is-quiet is-xs" aria-label="New task" title="New task (N)"
        onClick={() => window.dispatchEvent(new Event("cc:new-task"))}>+</button></div>
    <input className="input is-sm tree-find" placeholder="Filter tasks…" aria-label="Filter tasks" value={q} onChange={(e) => setQ(e.target.value)} />
    <div role="tree" className="tree-body">
      {projects.map((p) => {
        const name = st?.projects.find((x) => x.key === p.key)?.name ?? p.name;
        const rows = tickets.filter((t) => t.project === p.key && isActive(t)
          && (!needle || `${t.key} ${t.title}`.toLowerCase().includes(needle)))
          .sort((a, b) => a.number - b.number);
        const open = !collapsed.includes(p.key) || !!needle;
        return <div key={p.key} role="group" style={pjVar(p.key)}>
          <div role="treeitem" aria-expanded={open} tabIndex={0} className="tr-proj" onClick={() => toggle(p.key)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(p.key); } }}>
            <span className="tr-caret" aria-hidden>{open ? "▾" : "▸"}</span>
            <span className="pj-badge is-sm" aria-hidden>{initials(p.prefix, name)}</span>
            <span className="trunc">{name}</span><span className="muted">({rows.length})</span>
          </div>
          {open && <div className="tr-kids">
            <div role="treeitem" tabIndex={0} className="tr-console" onDoubleClick={() => onConsole(p.key)}
              onClick={() => onConsole(p.key)} onKeyDown={(e) => { if (e.key === "Enter") onConsole(p.key); }}
              title="Open the Project Console (no ticket needed)">
              <span className="tr-ico" aria-hidden>›_</span><span>Project Console</span></div>
            {rows.map((t) => <TaskRow key={t.key} t={t} selected={selected === t.key} onPick={() => onPick(t)} onOpen={() => onOpen(t)} />)}
            <button type="button" className="tr-new" onClick={() => window.dispatchEvent(new CustomEvent("cc:new-task", { detail: { project: p.key } }))}>+ New Task</button>
          </div>}
        </div>;
      })}
    </div>
    <a className="tr-history" href={href("tasks", null, { history: "1" })}>Task History →</a>
  </nav>;
}

/** The "Open Room" picker: any active task or a project console. */
function Picker({ onPick, onClose }: { onPick: (s: Spec) => void; onClose: () => void }) {
  const tickets = useSelector(app.store, (d) => d.tickets);
  const taskProjects = useSelector(app.store, (d) => d.taskProjects);
  const [q, setQ] = useState("");
  const n = q.trim().toLowerCase();
  const rows = tickets.filter(isActive).filter((t) => !n || `${t.key} ${t.title} ${t.project}`.toLowerCase().includes(n)).slice(0, 40);
  return <Dialog title="Open a room" onClose={onClose}>
    <input className="input" data-autofocus placeholder="Task key, title or project…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a task" />
    <div className="picker">
      <div className="caps muted">Project consoles</div>
      {byProjectOrder(taskProjects).filter((p) => !n || p.name.toLowerCase().includes(n) || p.key.includes(n)).map((p) =>
        <button key={p.key} type="button" className="picker-row" style={pjVar(p.key)} onClick={() => onPick({ kind: "project", project: p.key, key: null })}>
          <span className="pj-badge is-sm">{initials(p.prefix, p.name)}</span>{p.name} · Project Console</button>)}
      <div className="caps muted">Tasks</div>
      {rows.map((t) => <button key={t.key} type="button" className="picker-row" style={pjVar(t.project)} onClick={() => onPick({ kind: "task", project: t.project, key: t.key })}>
        <i className={`sq vs-${STAGE[stageOf(t)].tone}`} /><span className="key">{t.key}</span><span className="trunc">{t.title}</span></button>)}
    </div>
  </Dialog>;
}

/** Workspace is full (4/4): pop one out, or a new Workspace window (spec §17). */
function FullDialog({ wall, spec, onClose }: { wall: string; spec: Spec; onClose: () => void }) {
  const ids = useSelector(layout, (l) => l.walls[wall] ?? [], shallowEqual);
  const rooms = useSelector(layout, (l) => l.rooms);
  const label = (id: string) => (rooms[id]?.kind === "task" ? rooms[id].key : `${rooms[id]?.project} console`);
  return <Dialog title={`Workspace is full (${MAX_ROOMS}/${MAX_ROOMS})`} onClose={onClose}>
    <p className="text2">Opening {spec.key ?? `${spec.project} console`} needs a free slot. Its room and every other one keep their sessions.</p>
    <div className="caps muted" style={{ marginTop: 10 }}>Pop out an existing room</div>
    <div className="row" style={{ flexWrap: "wrap", marginTop: 6 }}>
      {ids.map((id) => <button key={id} type="button" className="btn" onClick={() => { popOutRoom(id); openRoom(wall, spec); onClose(); }}>
        Pop Out {label(id)} ↗</button>)}
    </div>
    <div className="row" style={{ marginTop: 14 }}>
      <button type="button" className="btn is-primary" data-autofocus onClick={() => {
        const w = newWall(); openRoom(w, spec); openWorkspaceWindow(w); onClose();
      }}>Open New Workspace Window</button>
      <button type="button" className="btn is-quiet" onClick={onClose}>Cancel</button>
    </div>
  </Dialog>;
}

function Wall({ wall, onPicker }: { wall: string; onPicker: () => void }) {
  const ids = useSelector(layout, (l) => l.walls[wall] ?? [], shallowEqual);
  const rooms = useSelector(layout, (l) => l.rooms);
  const split = useSelector(layout, (l) => l.split[wall] ?? { x: 0.5, y: 0.5 }, shallowEqual);
  const detached = Object.values(rooms).filter((r) => r.where === "detached");
  const popped = Object.values(rooms).filter((r) => r.where === "popped");
  const walls = useSelector(layout, (l) => Object.keys(l.walls), shallowEqual);
  const shape = wallShape(ids.length);
  const cols = shape.cols === 2 ? `${split.x}fr 6px ${1 - split.x}fr` : "1fr";
  const rows = shape.rows === 2 ? `${split.y}fr 6px ${1 - split.y}fr` : "1fr";
  const cell = (i: number): React.CSSProperties => ({ gridColumn: shape.cols === 1 ? "1" : i % 2 === 0 ? "1" : "3",
    gridRow: shape.rows === 1 ? "1" : i < 2 ? "1" : "3" });
  return <section className="wall" aria-label={`Workspace ${wall}`}>
    <div className="wall-bar">
      {walls.map((w) => <a key={w} className={`wall-tab${w === wall ? " is-on" : ""}`} href={href("workspace", null, { w })}
        aria-current={w === wall ? "page" : undefined}>Workspace {w}</a>)}
      <button type="button" className="btn is-quiet is-xs" title="New Workspace window (another monitor)" aria-label="New Workspace window"
        onClick={() => { const w = newWall(); openWorkspaceWindow(w); }}>+</button>
      {popped.length > 0 && <span className="mono-xs muted" title="Rooms in their own windows">↗ {popped.map((r) => r.key ?? r.project).join(", ")}</span>}
      {detached.map((r) => <button key={r.id} type="button" className="chip-btn" title="Its window was closed; sessions kept running. Bring it back."
        onClick={() => { if (!returnRoom(r.id, wall)) app.toast("This Workspace is full — pop a room out first", "bad"); }}>↺ {r.key ?? `${r.project} console`}</button>)}
      <span className="sl-fill" />
      <span className="mono-xs muted">Active Rooms: {ids.length}/{MAX_ROOMS}</span>
      <button type="button" className="btn is-sm is-outline" onClick={onPicker}>Open Room</button>
    </div>
    {ids.length === 0 ? <div className="wall-empty">
      <button type="button" className="slot-empty" onClick={onPicker}><span className="slot-plus">+</span>Open Task or Project Console</button>
      <p className="muted mono-xs">Double-click a task in the tree, or pick one here. Up to {MAX_ROOMS} rooms per window.</p>
    </div>
      : <div className="wall-grid" style={{ gridTemplateColumns: cols, gridTemplateRows: rows }}>
        {ids.map((id, i) => rooms[id] && <div key={id} className="wall-cell" style={cell(i)}>
          <RoomView room={rooms[id]} onClose={() => closeRoom(id)} /></div>)}
        {shape.cells > ids.length && Array.from({ length: shape.cells - ids.length }, (_, j) => <div key={`e${j}`} className="wall-cell" style={cell(ids.length + j)}>
          <button type="button" className="slot-empty" onClick={onPicker}><span className="slot-plus">+</span>Open Task or Project Console</button></div>)}
        {shape.cols === 2 && <div className="wsplit-track" style={{ gridColumn: "2", gridRow: "1 / -1" }} data-r={split.x}>
          <Divider axis="x" onRatio={(x) => setSplit(wall, { ...split, x })} /></div>}
        {shape.rows === 2 && <div className="wsplit-track" style={{ gridColumn: "1 / -1", gridRow: "2" }} data-r={split.y}>
          <Divider axis="y" onRatio={(y) => setSplit(wall, { ...split, y })} /></div>}
      </div>}
  </section>;
}

export function Workspace() {
  const route = useRoute();
  const tickets = useSelector(app.store, (d) => d.tickets);
  const loaded = useSelector(app.store, (d) => d.ticketsLoaded);
  const detailOpen = usePrefs((p) => p.wsDetailOpen);
  const wall = route.params.get("w") || "1";
  const taskParam = route.params.get("task") || route.params.get("ticket");
  const focus = (route.params.get("focus") as Focus) || null;
  const [picker, setPicker] = useState(false);
  const [full, setFull] = useState<Spec | null>(null);
  const selected = taskParam && tickets.some((t) => t.key === taskParam) ? taskParam : null;

  const request = (spec: Spec) => {
    const r = openRoom(wall, spec);
    if (!r.ok) { setFull(spec); return; }
    if (r.existed && r.wall && r.wall !== wall) app.toast(`${spec.key ?? spec.project} is open in Workspace ${r.wall}`);
    else if (r.existed && r.room.where === "popped") app.toast(`${spec.key ?? spec.project} is in its own window`);
  };
  const select = (key: string, f: Focus = null) => go("workspace", null, { w: wall !== "1" ? wall : undefined, task: key, focus: f ?? undefined });
  const openTask = (t: Ticket) => { select(t.key); request({ kind: "task", project: t.project, key: t.key }); };

  // ?open=1 (a notification, a Needs Jay item, a dashboard link): open the room once, then drop the flag.
  const wantOpen = route.params.get("open") === "1";
  const consoleParam = route.params.get("console");
  useEffect(() => {
    if (!wantOpen || !loaded) return;
    if (consoleParam) request({ kind: "project", project: consoleParam, key: null });
    else if (selected) { const t = tickets.find((x) => x.key === selected)!; request({ kind: "task", project: t.project, key: t.key }); }
    else return;
    go("workspace", null, { w: wall !== "1" ? wall : undefined, task: selected ?? undefined, focus: focus ?? undefined });
    if (!prefs.get().wsDetailOpen && focus) prefs.patch({ wsDetailOpen: true });
  }, [wantOpen, loaded, selected, consoleParam]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!loaded) return <EmptyState title="Loading tasks…" />;
  const showDetail = detailOpen && !!selected;
  return <div className={`ws3${showDetail ? " has-detail" : ""}`}>
    <Tree selected={selected} onPick={(t) => { select(t.key); if (!prefs.get().wsDetailOpen) prefs.patch({ wsDetailOpen: true }); }}
      onOpen={openTask} onConsole={(p) => request({ kind: "project", project: p, key: null })} />
    {showDetail && <Dossier ticketKey={selected!} focus={focus}
      onOpenRoom={() => { const t = tickets.find((x) => x.key === selected); if (t) request({ kind: "task", project: t.project, key: t.key }); }}
      onCollapse={() => prefs.patch({ wsDetailOpen: false })} />}
    {!showDetail && selected && <button type="button" className="detail-rail" onClick={() => prefs.patch({ wsDetailOpen: true })}
      aria-label="Show task details" title="Show task details">▸ {selected}</button>}
    <Wall wall={wall} onPicker={() => setPicker(true)} />
    {picker && <Picker onClose={() => setPicker(false)} onPick={(s) => { setPicker(false); if (s.key) select(s.key); request(s); }} />}
    {full && <FullDialog wall={wall} spec={full} onClose={() => setFull(null)} />}
  </div>;
}
