// herdr's real layout, drawn from pane rectangles: a map of the workspace with
// every pane's agent, role, state and cwd. Actions are the safe ones ccd allows
// (focus in herdr, read-only tail) plus the exact command for the interactive
// terminal. Layout changes (split, close, new pane) stay in herdr itself.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { go, useRoute } from "../lib/router";
import type { Workspace, WorkspacePaneCell, WorkspaceTab } from "../api/types";
import { AgentState, Project, EmptyState, Command, Kbd, DetailRow } from "../components/ui";
import { workspace } from "../workspace/transport";
import { modelOf } from "./Agents";
import { openAgent } from "../lib/openAgent";

const HERDR_KEYS: [string, string][] = [["split ↓", "Ctrl+B −"], ["split →", "Ctrl+B v"], ["focus", "Ctrl+B h j k l"],
  ["zoom", "Ctrl+B z"], ["new tab", "Ctrl+B c"], ["workspaces", "Ctrl+B w"], ["detach", "Ctrl+B q"]];

export function Workspaces() {
  const route = useRoute();
  const spaces = useSelector(app.store, (d) => d.state?.workspaces ?? null);
  const herdrOk = useSelector(app.store, (d) => d.state?.sources.herdr.ok ?? false);
  const order = (w: Workspace) => (w.tabs.some((t) => t.panes.some((p) => p.live)) ? 0 : 1);
  const list = spaces ? [...spaces].sort((a, b) => order(a) - order(b) || (a.number ?? 0) - (b.number ?? 0)) : [];
  const current = list.find((w) => w.id === route.id) ?? list.find((w) => w.focused) ?? list[0];
  if (!spaces) return <EmptyState title="Loading…" />;
  if (!list.length) return <EmptyState title="No herdr workspaces in the last snapshot." hint={herdrOk ? undefined : "herdr is unreachable — start it on jay-server"} />;
  return <div className="ws">
    <div className="ws-tabs" role="tablist" aria-label="herdr workspaces">
      {list.map((w) => { const live = w.tabs.flatMap((t) => t.panes).filter((p) => p.live);
        const blocked = live.some((p) => p.status === "blocked");
        return <button key={w.id} type="button" role="tab" className="ws-tab" aria-selected={w.id === current?.id} onClick={() => go("workspaces", w.id)}>
          {w.project && <Project k={w.project} name="" />}<span>{w.label || w.id}</span>
          <span className="mono-xs">{live.length ? `${live.length} agent${live.length > 1 ? "s" : ""}` : ""}{blocked ? " · blocked" : ""}</span>
          {w.focused && <span className="mono-xs" title="focused in herdr">●</span>}</button>; })}
    </div>
    {current && <WorkspaceView w={current} stale={!herdrOk} />}
    <div className="ws-toolbar" aria-label="herdr keys (in an attached herdr session)">
      <span className="ro-tag">IN HERDR</span>
      {HERDR_KEYS.map(([what, keys]) => <span key={what} className="hint">{what} <Kbd>{keys}</Kbd></span>)}
      <span className="hint" style={{ marginLeft: "auto" }}>palette <Kbd>Ctrl+K</Kbd></span>
    </div>
  </div>;
}

function WorkspaceView({ w, stale }: { w: Workspace; stale: boolean }) {
  // Attention first: the tab with a blocked agent, else the tab herdr shows.
  const start = () => w.tabs.find((t) => t.panes.some((p) => p.status === "blocked"))?.id ?? w.activeTabId ?? w.tabs[0]?.id;
  const [tabId, setTabId] = useState(start);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { setTabId(start()); setSel(null); }, [w.id]);
  const tab = w.tabs.find((t) => t.id === tabId) ?? w.tabs[0];
  const pane = tab?.panes.find((p) => p.id === sel) ?? tab?.panes.find((p) => p.live) ?? tab?.panes[0] ?? null;
  return <div className="ws-body">
    <div className="ws-stage">
      <div className="ws-subtabs">
        {w.tabs.map((t) => <button key={t.id} type="button" className="fchip" aria-pressed={t.id === tab?.id} onClick={() => setTabId(t.id)}>
          tab {t.number ?? "?"}{t.label && t.label !== String(t.number) ? ` · ${t.label}` : ""} <span className="mono-xs muted">{t.panes.length}</span></button>)}
        <span style={{ marginLeft: "auto" }} className="row">
          {stale && <span className="stale-tag">herdr down · last known layout</span>}
          <button type="button" className="btn is-sm" onClick={() => workspace.focusWorkspace(w.id)}>Open in herdr</button>
          {tab && <button type="button" className="btn is-sm" onClick={() => workspace.focusTab(tab.id)}>Focus tab</button>}
        </span>
      </div>
      {tab ? <Canvas tab={tab} selected={pane?.id ?? null} onSelect={setSel} /> : <EmptyState title="No tabs." />}
    </div>
    <aside className="ws-side" aria-label="Selected pane">{pane ? <PaneDetail p={pane} w={w} /> : <EmptyState title="Select a pane" />}</aside>
  </div>;
}

function Canvas({ tab, selected, onSelect }: { tab: WorkspaceTab; selected: string | null; onSelect: (id: string) => void }) {
  const W = Math.max(1, tab.area.w), H = Math.max(1, tab.area.h);
  const panes = tab.zoomed && tab.focusedPaneId ? tab.panes.filter((p) => p.id === tab.focusedPaneId) : tab.panes;
  return <div className="ws-canvas" role="group" aria-label={`Layout of tab ${tab.number ?? ""}${tab.zoomed ? " (zoomed in herdr)" : ""}`}
    style={{ aspectRatio: `${W * 0.62} / ${H}` }}>
    {panes.map((p) => {
      const r = tab.zoomed ? { x: 0, y: 0, w: W, h: H } : p.rect;
      return <button key={p.id} type="button" className={`wpane${p.focused ? " is-focused" : ""}${p.live ? "" : " is-shell"}${p.status === "blocked" ? " is-blocked" : ""}`}
        aria-pressed={selected === p.id} onClick={() => onSelect(p.id)}
        style={{ left: `${(100 * r.x) / W}%`, top: `${(100 * r.y) / H}%`, width: `calc(${(100 * r.w) / W}% - 6px)`, height: `calc(${(100 * r.h) / H}% - 6px)` }}
        aria-label={`${p.agentName ?? p.label ?? p.id}${p.live ? `, ${p.status}` : ", shell"}`}>
        <span className="wpane-head">{p.project && <Project k={p.project} name="" />}
          <span className="name">{p.agentName ?? p.label ?? (p.live ? p.agent : "shell")}</span>
          <span style={{ marginLeft: "auto" }}>{p.live ? <AgentState status={p.status ?? "unknown"} /> : <span className="mono-xs faint">SHELL</span>}</span></span>
        <span className="wpane-body">{p.live && <span className="mono-xs text2">{p.role ?? "agent"} · {p.agent}</span>}
          <span className="mono-xs muted trunc">{p.cwd ?? ""}</span></span>
        <span className="wpane-foot"><span>{p.id}</span>{p.focused && <span>· focused</span>}</span>
      </button>;
    })}
  </div>;
}

function PaneDetail({ p, w }: { p: WorkspacePaneCell; w: Workspace }) {
  const st = app.data.state;
  const agent = st?.agents.find((a) => a.id === p.id);
  const q = st?.blocked.find((b) => b.pane_id === p.id);
  return <>
    <div className="row"><span className="mono" style={{ fontWeight: 600 }}>{p.agentName ?? p.label ?? p.id}</span>
      {p.live ? <AgentState status={p.status ?? "unknown"} /> : <span className="ro-tag">SHELL</span>}</div>
    <dl>
      <DetailRow label="project"><Project k={p.project} /></DetailRow>
      {agent && <DetailRow label="role · model"><span className="mono-xs">{agent.role} · {st ? modelOf(agent, st.projectsConfig) : "—"}</span></DetailRow>}
      <DetailRow label="cwd"><span className="mono-xs">{p.cwd ?? "—"}</span></DetailRow>
      <DetailRow label="pane"><span className="mono-xs">{p.id} · {w.label || w.id}</span></DetailRow>
      {q && <DetailRow label="asks"><span className="jay-t">{q.question}</span></DetailRow>}
    </dl>
    <div style={{ display: "grid", gap: 6 }}>
      <div className="caps muted">Safe actions</div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {p.live && <button type="button" className="btn is-sm" onClick={() => workspace.focusAgent(p.id)}>Focus agent</button>}
        {p.live && <button type="button" className="btn is-sm" onClick={() => openAgent(p.id)}>
          {q ? "Answer…" : "Read-only tail"}</button>}
        <button type="button" className="btn is-sm" onClick={() => workspace.focusWorkspace(w.id)}>Open workspace</button>
      </div>
    </div>
    <div style={{ display: "grid", gap: 6 }}>
      <div className="caps muted">Interactive — Windows Terminal</div>
      {p.agentName && <Command cmd={workspace.attachCommand(p.agentName)} />}
      <Command cmd={workspace.attachCommand(null)} />
      <span className="muted mono-xs">Browser mode never types into a pane except a blocked agent's one-line answer. A full terminal comes with the desktop app.</span>
    </div>
  </>;
}
