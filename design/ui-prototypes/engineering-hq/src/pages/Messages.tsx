// MESSAGES — a full communication workspace (references 02 and 13): conversations, the project-lead
import { openMenu, type MenuItem } from "../components/overlay";
import { popOut } from "../windows/manager";
// DM thread, and a collapsible / resizable task-context inspector. Every conversation can be popped
// out on its own (dm:<id>), and so can the inspector (panel:task-context).
import { useEffect, useRef, useState } from "react";
import { CONVERSATIONS, PROJECTS, agent, conversation, project, task, type ChatMessage } from "../data/seed";
import { useOrg } from "../data/org";
import { startNewProject } from "./onboarding/NewProject";
import { chat, sendDemo, useViewState } from "../data/live";
import { AgentDot, AgentMeta, AgentRow, AgentStatus, useAgentView, useOpenAgent } from "../components/agent";
import { useStore } from "../lib/store";
import { go, useRoute } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Pill, ProdBanner, ProjIcon, cx } from "../components/ui";
import { Detachable, PopButton, useElsewhere } from "../windows/Detachable";

function Bubble({ m }: { m: ChatMessage }) {
  const jay = m.from === "jay";
  const name = jay ? "Jay" : agent(m.from).name;
  const t = m.card ? task(m.card) : null;
  return <div className={cx("msg", jay && "is-jay")}>
    <Avatar id={m.from} size={38} />
    <div className="msg-body">
      <p className="msg-meta"><b>{name}</b><time>{m.at}</time></p>
      <div className="msg-text">{m.text.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
        {m.list && <ol className="steps">{m.list.map((l, i) => <li key={i}><span>{i + 1}</span>{l}</li>)}</ol>}
        {m.list && <p>I'll share the current status below.</p>}
        {t && <div className="task-card">
          <div className="tc-head"><span className="tc-ico"><Icon name="doc" size={20} /></span><div><b>{t.key} · {t.title}</b><small>Task status and workflow overview</small></div><Pill tone="violet">In implementation</Pill></div>
          <div className="tc-grid"><dl><dt>Project</dt><dd><ProjIcon k={t.project} size={18} /> {project(t.project).name}</dd><dt>Priority</dt><dd className="t-bad">↑ {t.priority}</dd><dt>Created</dt><dd>2 days ago</dd><dt>Last updated</dt><dd>{t.updated}</dd></dl>
            <div className="tc-progress"><small>Overall status</small><span className="dots">{[1, 1, 1, 2, 0, 0, 0].map((s, i) => <i key={i} className={s === 2 ? "is-now" : s ? "is-done" : ""} />)}</span><span className="tc-foot"><small>3 of 6 complete</small><button type="button" className="link" onClick={() => go("task", t.key)}>View task <Icon name="arrowr" size={13} /></button></span></div></div>
          <p className="tc-note"><Icon name="shield" size={17} /> All work is proceeding as planned. Production remains untouched and no live changes have been made.</p>
        </div>}
        {m.ask && <div className="ask-card">
          <span className="ask-ico"><Icon name="help" size={18} /></span>
          <div><b>Decision needed · {m.ask}</b><small>Replying here is not a decision. Choose in the Decision Room; this conversation keeps its place.</small></div>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => go("decisions")}><Icon name="shield" size={15} /> Open Decision Room</button>
        </div>}
      </div>
    </div>
  </div>;
}

function SlackPanel() {
  return <div className="slack-panel">
    <span className="slack-ico"><Icon name="slack" size={30} /></span>
    <h3>Slack is not connected</h3>
    <p>Slack is planned as a mobile bridge for notifications, questions and approvals. It stays off until its scopes, storage and security model are reviewed and you authorise it.</p>
    <ul className="checks"><li>Outbound notifications only to start; replies must be signed and verified</li><li>A Slack reply is never an authorisation by itself — decisions still go through the Decision Room and existing gates</li>
      <li>CommandCenter stays the single source of truth; Slack messages are marked as Slack</li><li>No change to the loopback / SSH-only API exposure</li></ul>
    <div className="row-gap"><button type="button" className="btn" disabled>Connect Slack (needs your approval)</button><Demo label="Integration proposal" /></div>
  </div>;
}

export function Thread({ conv, standalone }: { conv: string; standalone?: boolean }) {
  const c = conversation(conv);
  const msgs = useStore(chat)[conv] ?? [];
  const v = useAgentView(c?.agent ?? "claude");
  const openAgent = useOpenAgent();
  const [draft, setDraft] = useViewState(`dm:${conv}`, "draft", "");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length, conv]);
  if (!c) return <div className="empty">Choose a conversation.</div>;
  const a = c.agent ? agent(c.agent) : null;
  const send = () => { const t = draft.trim(); if (!t) return; setDraft(""); sendDemo(conv, t, c.agent); };
  return <section className={cx("thread", standalone && "is-standalone")} aria-label={`Conversation with ${c.title}`}>
    <header className="thread-head">
      {standalone && <button type="button" className="icon-btn" aria-label="Back to Messages" onClick={() => go("messages", conv)}><Icon name="arrowl" size={18} /></button>}
      {a ? <button type="button" className="av-btn" onClick={() => openAgent(a.id)} aria-label={`${a.name} details`}><Avatar id={a.id} size={44} /></button>
        : c.kind === "slack" ? <span className="slack-ico is-sm"><Icon name="slack" size={22} /></span> : <ProjIcon k={c.project ?? "samvision"} size={40} icon="users" />}
      <div className="thread-title"><h2>{c.title}{a && <span className="muted"> · {a.role}</span>}{c.kind === "dm" && <span className="private-chip" title="Only you and this agent's sessions see this conversation"><Icon name="lock" size={12} /> Private</span>}</h2>
        <p>{c.project && <span className="am-proj"><i style={{ background: project(c.project).color }} />{project(c.project).name} {c.kind === "team" ? "team channel" : "team"}</span>}{!c.project && c.sub}</p>
        {a && <p className="thread-agent"><AgentStatus v={v} detail /><AgentMeta v={v} project={false} /></p>}</div>
      <span className="sp" />
      {c.kind !== "slack" && <><button type="button" className="btn btn-outline" onClick={() => go("teams", c.project)}><Icon name="users" size={16} /><span className="btn-text">Open Team Space</span></button>
        <button type="button" className="btn btn-outline" onClick={() => go("decisions")} title="Formal decisions are recorded in the Decision Room, not by chat"><Icon name="shield" size={16} /><span className="btn-text">Decision Room</span></button></>}
      <PopButton id={`dm:${conv}`} />
    </header>
    <div className="thread-scroll" data-testid="thread-scroll">
      {c.kind === "slack" ? <SlackPanel /> : <>
        <p className="thread-note"><Demo label="Demo conversation" /> Mock messages for the prototype. Chatting here never grants authorisation; decisions are recorded in the Decision Room.</p>
        {c.archived && <p className="callout t-idle"><Icon name="lock" size={15} /> Archived. {a?.name} was offboarded; this conversation is kept for the record and can't receive new messages.</p>}
        {!msgs.length && !c.archived && <div className="thread-empty"><Icon name="message" size={26} /><b>No messages yet</b><p>{a ? `${a.name} hasn't started a session. Messages you send are queued for its first session (demo).` : "Start the conversation."}</p></div>}
        {msgs.map((m) => <Bubble key={m.cid} m={m} />)}
      </>}
      <div ref={end} />
    </div>
    {c.kind !== "slack" && !c.archived && <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
      <button type="button" className="icon-btn is-box" aria-label="Attach (demo)"><Icon name="plus" size={18} /></button>
      <div className="composer-in"><input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`Message ${c.title}…`} aria-label={`Message ${c.title}`} />
        <Icon name="smile" size={19} /><Icon name="clip" size={19} /></div>
      <button type="submit" className="send" aria-label="Send" disabled={!draft.trim()}><Icon name="send" size={20} /></button>
    </form>}
  </section>;
}

const SHORT: Record<string, string> = { claude: "Project Lead", iris: "Research", nova: "Implement", atlas: "Review", pixel: "UI Test", orion: "Deploy" };

export function TaskContext({ conv }: { conv: string }) {
  const c = conversation(conv);
  const t = task(c?.project === "commandcenter" ? "CC-061" : "SV-025")!;
  const [tab, setTab] = useViewState("panel:task-context", "tab", "Requirements");
  const stale = useAgentView("claude").stale;
  const flow = ["claude", "iris", "nova", "atlas", "pixel", "orion"];
  return <aside className="ctx" aria-label="Current task context">
    <header className="ctx-head"><Icon name="gear" size={20} /><h2>Current Task Context</h2><span className="sp" /><PopButton id="panel:task-context" compact />
      <button type="button" className="link" onClick={() => go("task", t.key)}>View in Project <Icon name="arrowr" size={13} /></button></header>
    <div className="ctx-task">
      <div className="ctx-row"><span className="tc-ico"><Icon name="doc" size={22} /></span><b className="ctx-key">{t.key}</b><span>{t.title}</span><span className="sp" /><Pill tone="bad">{t.priority}</Pill></div>
      <dl className="ctx-kv"><dt>Project</dt><dd><ProjIcon k={t.project} size={18} /> {project(t.project).name}</dd><dt>Stage</dt><dd><Pill tone="violet">In implementation</Pill></dd>
        <dt>Created</dt><dd>2 days ago</dd><dt>Updated</dt><dd>{t.updated}</dd></dl>
      <ProdBanner compact />
    </div>
    <div className="seg seg-wide" role="tablist">{["Requirements", "Acceptance Criteria"].map((x) => <button key={x} role="tab" type="button" aria-selected={tab === x} onClick={() => setTab(x)}>{x}</button>)}</div>
    <div className="ctx-box"><h3><Icon name="doc" size={17} /> {tab}</h3>
      <ol className="numlist">{(tab === "Requirements" ? t.plan : t.criteria).map((r, i) => <li key={r}><span>{i + 1}</span>{r}</li>)}</ol></div>
    <div className="ctx-box"><h3><Icon name="graph" size={17} /> Delegation Workflow <span className="sp" /><button type="button" className="link" onClick={() => go("teams", t.project)}>View Details <Icon name="arrowr" size={13} /></button></h3>
      <div className="flow">{flow.map((id, i) => { const a = agent(id); return <div key={id} className="flow-step">{i > 0 && <Icon name="arrowr" size={14} className="flow-arrow" />}
        <Avatar id={id} size={36} /><b>{a.name}</b><small>{SHORT[id]}</small><small className="muted">{a.stage}</small></div>; })}</div></div>
    <div className="ctx-box"><h3><Icon name="users" size={17} /> Agent Status {stale && <Pill tone="warn" dot>Stale</Pill>}<span className="sp" /><button type="button" className="link" onClick={() => go("teams", t.project)}>View All Agents <Icon name="arrowr" size={13} /></button></h3>
      <div className="status-rows">{project(t.project).team.map((m) => <AgentRow key={m.id} id={m.id} size={30} />)}</div></div>
  </aside>;
}

const convMenu = (id: string, title: string): MenuItem[] => [
  { label: `Open ${title}`, icon: "message", run: () => go("messages", id) },
  { label: "Open in new window", icon: "popout", hint: "⌥⇧O", run: () => popOut(`dm:${id}`) },
];

export function Messages() {
  const route = useRoute();
  useOrg();
  const [showArch, setShowArch] = useViewState("page:messages", "archived", false);
  const [sel, setSel] = useViewState("page:messages", "conv", "sv-lead");
  const conv = route.screen === "messages" && route.id && conversation(route.id) ? route.id : sel;
  useEffect(() => { if (conv !== sel) setSel(conv); }, [conv, sel, setSel]);
  const [q, setQ] = useViewState("page:messages", "q", "");
  const [ctxOpen, setCtxOpen] = useViewState("page:messages", "ctxOpen", true);
  const [ctxW, setCtxW] = useViewState("page:messages", "ctxW", 470);
  const msgs = useStore(chat);
  const elsewhereCtx = useElsewhere("panel:task-context");
  const list = CONVERSATIONS.filter((c) => (showArch || !c.archived) && (!q || `${c.title} ${c.sub}`.toLowerCase().includes(q.toLowerCase())));
  const nArch = CONVERSATIONS.filter((c) => c.archived).length;
  const drag = useRef<{ x: number; w: number } | null>(null);
  const [, force] = useState(0);
  return <div className="page page-messages">
    <div className="page-head"><div><h1>Messages</h1><p>Direct and group conversations across your projects, agents and teams.</p></div>
      <button type="button" className="btn btn-primary" onClick={() => go("messages", "sv-lead")}><Icon name="edit" size={16} /> New Message</button></div>
    <div className="msg-grid" style={{ gridTemplateColumns: `clamp(240px, 19vw, 310px) minmax(0,1fr) ${ctxOpen ? `min(${ctxW}px, 31vw)` : "44px"}` }}>
      <div className="conv-col">
        <div className="conv-search"><Icon name="search" size={17} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search messages…" aria-label="Search messages" /><Icon name="edit" size={17} /></div>
        <ul className="conv-list" aria-label="Conversations">{list.map((c) => { const last = (msgs[c.id] ?? []).at(-1); const out = false;
          return <li key={c.id}><a href={`#/messages/${c.id}`} onContextMenu={(e) => { e.preventDefault(); openMenu({ x: e.clientX, y: e.clientY }, convMenu(c.id, c.title), c.title); }}
            onKeyDown={(e) => { if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); openMenu(e.currentTarget, convMenu(c.id, c.title), c.title); } }} className={cx("conv", conv === c.id && "is-sel", out && "is-out", c.archived && "is-archived")} aria-current={conv === c.id ? "true" : undefined}>
            {c.agent ? <span className="av-wrap"><Avatar id={c.agent} size={42} /><AgentDot id={c.agent} /></span> : c.kind === "slack" ? <span className="slack-ico is-sm"><Icon name="slack" size={20} /></span> : <ProjIcon k={c.project ?? "samvision"} size={40} icon="users" />}
            <span className="conv-body"><span className="conv-top"><b>{c.title}</b><time>{last?.at ?? ""}</time></span><small>{c.sub}</small>
              <span className="ellip muted">{c.kind === "slack" ? "Not connected · see proposal" : last ? last.text.split("\n")[0] : ""}</span></span>
            <ConvOut id={c.id} /></a></li>; })}</ul>
        {nArch > 0 && <button type="button" className="link conv-arch" onClick={() => setShowArch(!showArch)}><Icon name="lock" size={12} /> {showArch ? "Hide" : "Show"} archived ({nArch})</button>}
        <div className="conv-projects"><h3>Projects <button type="button" className="icon-btn" aria-label="New Project" onClick={() => startNewProject()}><Icon name="plus" size={16} /></button></h3>
          {PROJECTS.map((p) => <a key={p.key} href={`#/teams/${p.key}`} className="conv-proj"><i style={{ background: p.color }} />{p.name}{p.health === "paused" && <small className="muted"> · paused</small>}</a>)}</div>
      </div>
      <Detachable id={`dm:${conv}`} className="thread"><Thread conv={conv} /></Detachable>
      {ctxOpen ? <div className="ctx-wrap">
        <div className="ctx-resize" role="separator" aria-orientation="vertical" aria-label="Resize task context" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "ArrowLeft") setCtxW(Math.min(640, ctxW + 20)); if (e.key === "ArrowRight") setCtxW(Math.max(340, ctxW - 20)); }}
          onPointerDown={(e) => { drag.current = { x: e.clientX, w: ctxW }; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); }}
          onPointerMove={(e) => { if (drag.current) { setCtxW(Math.max(340, Math.min(640, drag.current.w + drag.current.x - e.clientX))); force((n) => n + 1); } }}
          onPointerUp={() => { drag.current = null; }} />
        <button type="button" className="ctx-collapse" onClick={() => setCtxOpen(false)} aria-label="Collapse task context"><Icon name="chevron" size={14} /></button>
        {elsewhereCtx ? <Detachable id="panel:task-context" className="ctx"><span /></Detachable> : <TaskContext conv={conv} />}
      </div> : <button type="button" className="ctx-rail" onClick={() => setCtxOpen(true)} aria-label="Show task context"><Icon name="doc" size={18} /><span>Task context</span></button>}
    </div>
  </div>;
}

function ConvOut({ id }: { id: string }) {
  const out = useElsewhere(`dm:${id}`);
  return out ? <span className="conv-out" title="Open in another window"><Icon name="popout" size={14} /></span> : null;
}
