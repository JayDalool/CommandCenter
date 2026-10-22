// Agent identity, shown the same way everywhere.
// A persona (Iris, Nova, …) is a stable role. What it is doing now (status, task, project, model,
// session, last activity) comes from the status feed and can change at any time. Status from the demo
// feed is always marked, and a stale feed turns every status into Unknown with its last-seen time.
import { AGENTS, PRESENCE_LABEL, SESSION_HISTORY, agent, modelLabel, project, task, type AgentState, type Presence } from "../data/seed";
import { FEED_STALE_MS, feed, useViewState } from "../data/live";
import { useStore } from "../lib/store";
import { go } from "../lib/router";
import { useNow } from "../lib/time";
import { Icon } from "./Icon";
import { Avatar, cx } from "./ui";
import { PopButton, useElsewhere } from "../windows/Detachable";
import { Store } from "../lib/store";

/** The agent shown in THIS window's drawer. Local, so a click in one window never opens a drawer in another. */
const drawerAgent = new Store<string | null>(null);

export function ago(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

export interface AgentView {
  id: string; s: AgentState; status: Presence; stale: boolean; sim: boolean; paused: boolean; lastSeen: string;
}

/** The persona's current state as the UI should show it: paused projects and stale feeds win over the feed's claim. */
export function useAgentView(id: string, opts: { pausedProject?: boolean } = {}): AgentView {
  const f = useStore(feed);
  const now = useNow(5000);
  const s = f.agents[id] ?? { status: "unknown" as Presence, detail: "", at: 0 };
  const stale = f.outage || now - f.beat > FEED_STALE_MS;
  const paused = !!opts.pausedProject || (s.project ? project(s.project).health === "paused" : false);
  const status: Presence = paused ? "paused" : stale ? "unknown" : s.status;
  return { id, s, status, stale, sim: f.source === "demo", paused, lastSeen: s.at ? ago(now - s.at) : "never" };
}

const TONE: Record<Presence, string> = { working: "ok", idle: "idle", researching: "info", reviewing: "violet", waiting: "warn",
  blocked: "bad", queued: "warn", paused: "idle", offline: "off", disconnected: "bad", unknown: "idle" };

/** "Working · SV-025", "Waiting for Jay · 1 question", "Unknown · last seen 3m ago". */
export function AgentStatus({ v, task: showTask = true, detail, size, questions = true }: { v: AgentView; task?: boolean; detail?: boolean; size?: "lg"; questions?: boolean }) {
  const extra = v.status === "unknown" && v.stale ? `last seen ${v.lastSeen}`
    : questions && v.status === "waiting" && v.s.questions ? `${v.s.questions} question${v.s.questions === 1 ? "" : "s"}` : null;
  const showKey = showTask && v.s.task && !["paused", "offline", "unknown"].includes(v.status);
  return <span className={cx("pres", `t-${TONE[v.status]}`, v.sim && "is-sim", size === "lg" && "is-lg")}
    title={v.sim ? "Simulated status from the prototype's demo feed. Not a real session." : undefined}>
    <i aria-hidden /><b>{PRESENCE_LABEL[v.status]}</b>
    {showKey && <span className="mono pres-key"> · {v.s.task}</span>}
    {extra && <span> · {extra}</span>}
    {detail && v.s.detail && v.status !== "unknown" && <span> · {v.s.detail}</span>}
    {v.sim && <abbr className="sim" title="Demo status, not a real session">demo</abbr>}
  </span>;
}

/** "Claude Opus 5.5 · SamVision · 2m ago" — the facts that change between sessions. */
export function AgentMeta({ v, project: showProject = true }: { v: AgentView; project?: boolean }) {
  const p = v.s.project ? project(v.s.project) : null;
  return <span className="agent-meta">
    <span className="am-model" title={v.s.model ?? "No active session"}><Icon name="cpu" size={12} /> {modelLabel(v.s.model)}</span>
    {showProject && p && <span className="am-proj"><i style={{ background: p.color }} />{p.name}</span>}
    <span className="am-time" title="Last activity"><Icon name="clock" size={12} /> {v.lastSeen}</span>
  </span>;
}

/** A small status dot on an avatar (hollow when it is demo status). */
export function AgentDot({ id }: { id: string }) {
  const v = useAgentView(id);
  return <i className={cx("av-pres", `t-${TONE[v.status]}`, v.sim && "is-sim")} title={`${PRESENCE_LABEL[v.status]}${v.sim ? " (demo)" : ""}`} aria-hidden />;
}

/** One row: avatar, name, role, status, then model / project / last activity. Click opens the inspector. */
export function AgentRow({ id, size = 34, compact }: { id: string; size?: number; compact?: boolean }) {
  const a = agent(id);
  const v = useAgentView(id);
  const open = useOpenAgent();
  return <button type="button" className={cx("agent-row", compact && "is-compact")} onClick={() => open(id)} aria-label={`${a.name}, ${a.role}. Open details`}>
    <Avatar id={id} size={size} />
    <span className="ar-main">
      <span className="ar-top"><b>{a.name}</b><small className="ar-role">{a.role}</small></span>
      <AgentStatus v={v} />
      {!compact && <AgentMeta v={v} />}
    </span>
  </button>;
}

/** Open a persona's details: in the popped-out Agent Inspector if there is one, else in this window's drawer. */
export function useOpenAgent() {
  const [, setShared] = useViewState<string | null>("panel:agent", "id", null);
  const out = useElsewhere("panel:agent");
  return (id: string) => { setShared(id); if (!out) drawerAgent.set(id); };
}

/** This window's drawer. Hidden while the inspector is popped out to another window. */
export function AgentDrawer() {
  const id = useStore(drawerAgent);
  const out = useElsewhere("panel:agent");
  if (!id || out) return null;
  return <div className="agent-drawer" role="dialog" aria-label="Agent details"
    onKeyDown={(e) => { if (e.key === "Escape") drawerAgent.set(null); }}>
    <AgentInspector id={id} onClose={() => drawerAgent.set(null)} onPick={(x) => drawerAgent.set(x)} />
  </div>;
}

/** Full details for one persona. Mounted once per window; it can also be popped out as panel:agent. */
export function AgentInspector({ id: given, onClose, onPick }: { id?: string; onClose?: () => void; onPick?: (id: string) => void }) {
  const [shared, setShared] = useViewState<string | null>("panel:agent", "id", "claude");
  const standalone = !given;
  const id = given ?? shared ?? "claude";
  const setId = (x: string) => { setShared(x); onPick?.(x); };
  const [hist, setHist] = useViewState("panel:agent", "history", false);
  const v = useAgentView(id);
  const a = agent(id);
  const t = v.s.task ? task(v.s.task) : null;
  const p = v.s.project ? project(v.s.project) : null;
  const conv = a.id === "claude" ? (v.s.project === "commandcenter" ? "cc-lead" : "sv-lead") : a.id;
  const body = <>
    <header className="ai-head"><Avatar id={a.id} size={52} ring /><div><h2>{a.name}</h2><p>{a.role}</p></div><span className="sp" />
      <PopButton id="panel:agent" compact />
      {onClose && <button type="button" className="icon-btn" aria-label="Close agent details" onClick={onClose}><Icon name="x" size={16} /></button>}</header>
    <div className="ai-switch" role="tablist" aria-label="Agents">{AGENTS.map((x) =>
      <button key={x.id} type="button" role="tab" aria-selected={x.id === a.id} onClick={() => setId(x.id)} title={x.name} aria-label={x.name}><Avatar id={x.id} size={24} /></button>)}</div>
    <section className="ai-sec">
      <h3>Now</h3>
      <AgentStatus v={v} size="lg" />
      {v.s.detail && v.status !== "unknown" && <p className="ai-detail">{v.s.detail}</p>}
      <dl className="kv ai-kv">
        <dt>Task</dt><dd>{t ? <button type="button" className="link mono" onClick={() => go("task", t.key)}>{t.key}</button> : "—"}{t && <span className="muted"> · {t.title}</span>}</dd>
        <dt>Project</dt><dd>{p ? <span className="am-proj"><i style={{ background: p.color }} />{p.name}</span> : "—"}</dd>
        <dt>Model</dt><dd>{modelLabel(v.s.model)}{v.s.model && <code className="ai-code">{v.s.model}</code>}</dd>
        <dt>Session</dt><dd>{v.s.session ? <code className="ai-code">{v.s.session}</code> : <span className="muted">No active session</span>}</dd>
        <dt>Last activity</dt><dd>{v.lastSeen}{v.stale && <span className="t-warn"> · feed stale</span>}</dd>
      </dl>
      {v.sim && <p className="ai-note"><Icon name="info" size={14} /> Demo status. In the live build this comes from ccd session events; when they stop, the status shows Unknown, never Working.</p>}
    </section>
    <section className="ai-sec">
      <h3>Role</h3>
      <dl className="kv ai-kv"><dt>Specialisation</dt><dd>{a.spec}</dd><dt>Pipeline stage</dt><dd>{a.stage}</dd></dl>
    </section>
    <section className="ai-sec">
      <button type="button" className="ai-expand" aria-expanded={hist} onClick={() => setHist(!hist)}><Icon name={hist ? "chevdown" : "chevron"} size={14} /> Earlier sessions <small className="muted">the role stays, the model and session change</small></button>
      {hist && <ul className="ai-hist">{(SESSION_HISTORY[a.id] ?? []).map((h) => <li key={h.session}><code>{h.session}</code><span>{modelLabel(h.model)}</span><span className="mono">{h.task}</span><small className="muted">{h.ended}</small></li>)}</ul>}
    </section>
    <footer className="row-gap"><button type="button" className="btn btn-primary" onClick={() => go("messages", conv)}><Icon name="message" size={16} /> Chat with {a.name}</button>
      {t && <button type="button" className="btn" onClick={() => go("task", t.key)}><Icon name="terminal" size={16} /> Task Room</button>}</footer>
  </>;
  return <aside className={cx("agent-insp", standalone && "is-standalone")} aria-label={`${a.name} details`}>{body}</aside>;
}
