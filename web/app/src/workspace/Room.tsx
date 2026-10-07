// A ROOM on the Workspace wall (spec §13–§16, docs/design/terminal-reference.png).
//
//   Task Room        bound to one ticket: its Claude task session, Codex, a shell in its worktree, Server
//   Project Console  no ticket: the project coordinator, Codex, a shell in the registered repo, Server
//
// Tools are toggled on and off (1–4 panes, laid out 1 · 2 side by side · 1 over 2 · 2×2) and only
// what is shown is attached. Every pane can pop out to its own window and the whole room can too;
// both attach to the EXACT same ccd session by name (rooms.sessionName), so nothing is started twice.
// A popped pane leaves "+ Add Pane" in its place.
import { useEffect, useRef, useState } from "react";
import { app } from "../store/app";
import { Store, useSelector } from "../lib/store";
import { usePrefs } from "../lib/prefs";
import type { WorkspaceProject } from "../api/types";
import { initials, pjVar, stageOf, STAGE } from "../lib/control";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";
import { TerminalView } from "./Terminal";
import { ClaudeDock } from "./ClaudeDock";
import { StagePill } from "./Dossier";
import { TOOLS, TOOL_LABEL, addPane, dropSlot, layout, popOutPane, popOutRoom, reattachPane, sessionName, toggleTool,
  type Room as RoomT, type Tool } from "./rooms";

// ---------- registered projects (roots, prefixes, coordinators), loaded once ----------
const wsProjects = new Store<{ rows: WorkspaceProject[] | null; err: string | null }>({ rows: null, err: null });
let wsLoading: Promise<void> | null = null;
export function useWsProjects() {
  const v = useSelector(wsProjects, (d) => d);
  useEffect(() => {
    if (v.rows || wsLoading) return;
    wsLoading = app.api.workspaceProjects().then((r) => wsProjects.set({ rows: r.projects, err: null }))
      .catch((e) => { wsProjects.set({ rows: null, err: (e as Error).message }); })
      .finally(() => { wsLoading = null; });
  }, [v.rows]);
  return v;
}
export function resetWsProjects() { wsProjects.set({ rows: null, err: null }); }

function useTheme(): "dark" | "light" {
  const t = usePrefs((p) => p.theme);
  return t === "light" ? "light" : "dark";
}

/** The ticket's task Claude session, live from herdr's agents (named after the key: sv-071). */
function useTaskSession(key: string | null) {
  return useSelector(app.store, (d) => {
    if (!key) return null;
    const names = [key.toLowerCase(), key.toUpperCase()];
    // The same rule as ccd's coordid.task_session: a live Claude named (or labelled) after the key.
    const hits = (d.state?.agents ?? []).filter((a) => (!a.agent || a.agent === "claude") && a.live !== false
      && (names.includes(a.agent_name) || names.includes(a.label)));
    return hits.length === 1 ? { paneId: hits[0].id, status: hits[0].status } : hits.length > 1 ? { paneId: null, status: "multiple" } : null;
  }, (a, b) => JSON.stringify(a) === JSON.stringify(b));
}

/** Claude for a Task Room: attach to the task session, or say plainly that none is running. */
function TaskClaude({ room, proj, active }: { room: RoomT; proj: WorkspaceProject; active: boolean }) {
  const theme = useTheme();
  const dev = useDevActive();
  const s = useTaskSession(room.key);
  const [asked, setAsked] = useState(false);
  if (!s || !s.paneId) {
    const coord = proj.coordinator;
    const ask = async () => {
      if (!dev) { unlockDialogOpen(); return; }
      if (!coord?.id) { app.toast(`${proj.name} has no coordinator running`, "bad"); return; }
      const ok = await app.action(() => app.api.prompt(coord.id!, `Start the Claude task session for ${room.key} (a herdr pane named ` +
        `${room.key!.toLowerCase()}, so Command Center can attach to it) and continue the ticket from its recorded work state ` +
        `(python -m ccd.pipeline_cli work ${room.key}).`), `Asked ${coord.name ?? proj.key} to start ${room.key!.toLowerCase()}`);
      if (ok) setAsked(true);
    };
    return <div className="pane-empty" role="status">
      <span className="ro-tag is-off">{s?.status === "multiple" ? "SEVERAL SESSIONS" : "NO TASK SESSION"}</span>
      <p className="muted">{s?.status === "multiple" ? `More than one Claude is named ${room.key!.toLowerCase()} — close the extra one in herdr.`
        : `No Claude task session for ${room.key} is running (it would be named ${room.key!.toLowerCase()}). Command Center never starts one itself.`}</p>
      {!s && <button type="button" className="btn is-sm" disabled={asked} onClick={() => void ask()}>
        {asked ? "Asked the coordinator" : `Ask ${coord?.name ?? "the coordinator"} to start it`}</button>}
    </div>;
  }
  return <TerminalView key={`claude:${room.key}`} name={`claude:${room.key}`} label={`Claude · ${room.key}`} active={active} theme={theme}
    info={`${room.key!.toLowerCase()} · ${s.status}`}
    closeText={`Close this view of ${room.key}'s Claude? Only the attach client closes — the task session keeps running.`} />;
}

export function PaneBody({ room, tool, proj, active }: { room: RoomT; tool: Tool; proj: WorkspaceProject; active: boolean }) {
  const theme = useTheme();
  const st = useSelector(app.store, (d) => d.state);
  if (tool === "claude") {
    if (room.kind === "task") return <TaskClaude room={room} proj={proj} active={active} />;
    const coord = st?.coordinators[proj.key] ?? null;
    const agent = coord?.paneId ? st?.agents.find((a) => a.id === coord.paneId) ?? null : null;
    const model = st?.projectsConfig.find((x) => x.key === proj.key)?.model ?? null;
    return <ClaudeDock proj={proj} coord={coord} agent={agent} model={model} active={active} theme={theme} />;
  }
  const name = sessionName(room, tool, proj.prefix);
  const label = `${TOOL_LABEL[tool]} · ${room.kind === "task" ? room.key : proj.name}`;
  const info = tool === "server" ? "jay-server" : tool === "codex" ? `codex · ${room.kind === "task" ? `${room.key} worktree` : proj.root ?? proj.name}`
    : room.kind === "task" ? `${room.key} worktree` : `${proj.root ?? proj.name} · ${proj.branch ?? "—"}`;
  return <TerminalView key={name} name={name} label={label} active={active} theme={theme} info={info} />;
}

function AddPane({ room, slot }: { room: RoomT; slot: number }) {
  const [open, setOpen] = useState(false);
  const free = TOOLS.filter((t) => !room.slots.includes(t));
  return <div className="pane-add">
    {open ? <div className="pane-add-menu" role="menu" aria-label="Add a pane">
      {free.map((t) => <button key={t} type="button" role="menuitem" className="btn is-sm" onClick={() => addPane(room.id, slot, t)}>
        {TOOL_LABEL[t]}{room.out[t] ? " (bring back)" : ""}</button>)}
      <button type="button" className="btn is-quiet is-sm" onClick={() => dropSlot(room.id, slot)}>Remove slot</button>
    </div> : <button type="button" className="pane-add-btn" onClick={() => setOpen(true)}>+ Add Pane</button>}
  </div>;
}

/** Room-internal split ratios (draggable dividers), per room, this window only. */
function useSplit() {
  const [x, setX] = useState(0.5);
  const [y, setY] = useState(0.5);
  return { x, y, setX, setY };
}

export function Divider({ axis, onRatio }: { axis: "x" | "y"; onRatio: (r: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  return <div ref={ref} role="separator" aria-orientation={axis === "x" ? "vertical" : "horizontal"} tabIndex={0}
    className={`wsplit is-${axis}`} aria-label={axis === "x" ? "Resize columns" : "Resize rows"}
    onPointerDown={(e) => {
      e.preventDefault();
      const box = ref.current?.parentElement?.getBoundingClientRect();
      if (!box) return;
      const el = e.currentTarget; el.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent) => {
        const r = axis === "x" ? (ev.clientX - box.left) / box.width : (ev.clientY - box.top) / box.height;
        onRatio(Math.max(0.15, Math.min(0.85, r)));
      };
      const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
      el.addEventListener("pointermove", move); el.addEventListener("pointerup", up);
    }}
    onKeyDown={(e) => {
      const d = e.key === (axis === "x" ? "ArrowLeft" : "ArrowUp") ? -0.05 : e.key === (axis === "x" ? "ArrowRight" : "ArrowDown") ? 0.05 : 0;
      if (d) { e.preventDefault(); const cur = Number(ref.current?.parentElement?.dataset.r ?? 0.5); onRatio(Math.max(0.15, Math.min(0.85, cur + d))); }
    }} />;
}

export function RoomView({ room, popped = false, onClose, extra }: {
  room: RoomT; popped?: boolean; onClose?: () => void; extra?: React.ReactNode;
}) {
  const { rows } = useWsProjects();
  const ticket = useSelector(app.store, (d) => (room.key ? d.tickets.find((t) => t.key === room.key) ?? null : null));
  const pname = useSelector(app.store, (d) => d.state?.projects.find((p) => p.key === room.project)?.name ?? room.project);
  const split = useSplit();
  const proj = rows?.find((p) => p.key === room.project) ?? null;
  const n = room.slots.length;
  const stage = ticket ? stageOf(ticket) : null;
  const title = room.kind === "task" ? `${room.key} · ${pname}` : `${pname} · Project Console`;
  const cols = n >= 2 ? `${split.x}fr 4px ${1 - split.x}fr` : "1fr";
  const rowsT = n >= 3 ? `${split.y}fr 4px ${1 - split.y}fr` : "1fr";
  // Cells in grid coordinates (col, row) around the divider tracks; 3 panes: one full-width on top.
  const place = (i: number): React.CSSProperties => {
    if (n === 1) return { gridColumn: "1", gridRow: "1" };
    if (n === 2) return { gridColumn: i === 0 ? "1" : "3", gridRow: "1" };
    if (n === 3) return i === 0 ? { gridColumn: "1 / 4", gridRow: "1" } : { gridColumn: i === 1 ? "1" : "3", gridRow: "3" };
    return { gridColumn: i % 2 === 0 ? "1" : "3", gridRow: i < 2 ? "1" : "3" };
  };
  const outs = (Object.entries(room.out) as [Tool, "popped" | "detached"][]);
  return <section className={`room${popped ? " is-popped" : ""}`} style={pjVar(room.project)} aria-label={title}>
    <header className="room-head">
      <span className={`sq ${stage ? `vs-${STAGE[stage].tone}` : "is-pj"}`} aria-hidden />
      {room.kind === "project" && <span className="pj-badge is-sm" aria-hidden>{initials(proj?.prefix, pname)}</span>}
      <b className="room-title trunc" title={ticket ? `${title} — ${ticket.title}` : title}>{title}</b>
      {stage && <StagePill stage={stage} />}
      <span className="sl-fill" />
      {extra}
      {!popped && <button type="button" className="btn is-quiet is-xs" onClick={() => popOutRoom(room.id)} aria-label={`Pop out ${title}`}
        title="Pop out this room to its own window (same sessions)">↗</button>}
      {onClose && <button type="button" className="btn is-quiet is-xs" onClick={onClose} aria-label={`Close ${title}`}
        title="Close this room (its sessions keep running)">×</button>}
    </header>
    <div className="room-tools" role="group" aria-label={`${title} tools`}>
      {TOOLS.map((t) => {
        const on = room.slots.includes(t), out = room.out[t];
        return <button key={t} type="button" className={`tool${on ? " is-on" : ""}${out ? ` is-${out}` : ""}`} aria-pressed={on}
          title={out === "popped" ? `${TOOL_LABEL[t]} is in its own window — click to bring it back` : out === "detached"
            ? `${TOOL_LABEL[t]}'s window was closed; its session keeps running — click to reattach` : on ? `Hide ${TOOL_LABEL[t]}` : `Show ${TOOL_LABEL[t]}`}
          disabled={!on && !out && n >= 4 && !room.slots.includes(null)}
          onClick={() => (out ? reattachPane(room.id, t) : toggleTool(room.id, t))}>
          {TOOL_LABEL[t]}{on ? " ✓" : out === "popped" ? " ↗" : out === "detached" ? " ↺" : ""}</button>;
      })}
    </div>
    {!proj ? <div className="pane-empty muted">Loading project…</div>
      : n === 0 ? <div className="pane-empty">
        <p className="muted">No terminals shown{outs.length ? ` — ${outs.map(([t, w]) => `${TOOL_LABEL[t]} ${w === "popped" ? "is popped out" : "was detached"}`).join(", ")}` : ""}.</p>
        <div className="row">{TOOLS.map((t) => <button key={t} type="button" className="btn is-sm" onClick={() => (room.out[t] ? reattachPane(room.id, t) : toggleTool(room.id, t))}>{TOOL_LABEL[t]}</button>)}</div>
      </div>
      : <div className="room-panes" style={{ gridTemplateColumns: cols, gridTemplateRows: rowsT }}>
        {room.slots.map((tool, i) => <div key={tool ?? `free-${i}`} className="pane" style={place(i)}>
          {tool ? <>
            <div className="pane-head">
              <span className="pane-name">{TOOL_LABEL[tool].toUpperCase()}</span>
              <span className="sl-fill" />
              <button type="button" className="btn is-quiet is-xs" onClick={() => popOutPane(room.id, tool)}
                aria-label={`Pop out ${TOOL_LABEL[tool]}`} title="Pop out to its own window (same session); this slot becomes free">↗</button>
              <button type="button" className="btn is-quiet is-xs" onClick={() => toggleTool(room.id, tool)}
                aria-label={`Hide ${TOOL_LABEL[tool]}`} title="Hide this pane (the session keeps running)">×</button>
            </div>
            <div className="pane-body"><PaneBody room={room} tool={tool} proj={proj} active /></div>
          </> : <AddPane room={room} slot={i} />}
        </div>)}
        {n >= 2 && <div className="wsplit-track" style={{ gridColumn: "2", gridRow: n === 3 ? "3" : n >= 3 ? "1 / 4" : "1" }} data-r={split.x}>
          <Divider axis="x" onRatio={split.setX} /></div>}
        {n >= 3 && <div className="wsplit-track" style={{ gridColumn: "1 / 4", gridRow: "2" }} data-r={split.y}>
          <Divider axis="y" onRatio={split.setY} /></div>}
      </div>}
  </section>;
}

/** A room by id, from the layout every window shares. */
export function useRoom(id: string): RoomT | null {
  return useSelector(layout, (l) => l.rooms[id] ?? null);
}
