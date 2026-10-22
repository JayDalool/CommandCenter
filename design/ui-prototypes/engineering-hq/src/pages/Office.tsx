// MY OFFICE — calm executive landing page (reference 01, secondary 12).
import { PROJECTS, SPARK, agent, healthOf, project, rosterAgents } from "../data/seed";
import { useOrg } from "../data/org";
import { startNewAgent } from "./onboarding/NewAgent";
import { startNewProject } from "./onboarding/NewProject";
import { AgentMeta, AgentStatus, statusOf, useAgentView, useOpenAgent } from "../components/agent";
import { feed, useViewState, FEED_STALE_MS } from "../data/live";
import { useStore } from "../lib/store";
import { go } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, AvatarStack, Demo, Panel, Pill, ProjIcon, TaskKey, Spark, ViewAll, cx, plural } from "../components/ui";
import { GraphFrame, type FEdge, type FNode } from "../components/GraphFrame";
import { PopButton } from "../windows/Detachable";
import { useNow } from "../lib/time";

const TEAMS = [
  { id: "plan", label: "Planning", icon: "search", n: 2 },
  { id: "build", label: "Build & Test", icon: "code", n: 3 },
  { id: "qa", label: "Review & QA", icon: "mobile", n: 2 },
  { id: "rel", label: "Deploy & Verify", icon: "rocket", n: 1 },
];

function OfficeGraph() {
  const W = 1180, H = 386;
  const ps = PROJECTS.filter((p) => p.key !== "commandcenter");
  const PA = (k: string) => project(k).team.map((m) => m.id);
  const gap = 30, pw = Math.min(236, (W - 60 - (ps.length - 1) * gap) / ps.length), x0 = (W - (ps.length * pw + (ps.length - 1) * gap)) / 2;
  const nodes: FNode[] = [{ id: "jay", x: W / 2 - 110, y: 6, w: 220, h: 98, color: "#4f7bff", className: "k-jay", label: "Jay",
    body: <><span className="av av-jay" style={{ width: 44, height: 44, fontSize: 19 }}>J</span><span className="gn-body"><b>Jay</b><small>Engineering Director</small><span className="pres t-ok"><i /><b>Online</b></span></span></> }];
  const edges: FEdge[] = [];
  ps.forEach((p, i) => {
    const paused = p.health === "paused";
    const h = healthOf(p);
    nodes.push({ id: p.key, x: x0 + i * (pw + gap), y: 136, w: pw, h: 124, color: p.color, className: "k-project", label: p.name, onClick: () => go("teams", p.key),
      body: <><span className="gn-row"><ProjIcon k={p.key} size={40} /><span className="gn-body"><b>{p.name}</b><small>{p.health === "onboarding" ? "Observation only" : `${p.version} · ${p.env}`}</small></span></span>
        <span className="gn-row gn-mid"><span className={`pres t-${h.tone}`}><i /><b>{h.label}</b></span>{!paused && p.health !== "onboarding" && <Spark data={i % 2 ? SPARK.b : SPARK.a} color={p.color} w={80} h={22} />}</span>
        <span className="gn-row gn-foot">{PA(p.key).length ? <AvatarStack ids={PA(p.key).slice(0, 3)} size={22} /> : <Icon name="lock" size={14} />}<span>{PA(p.key).length ? plural(PA(p.key).length, "agent") : "No agents yet"}</span></span></> });
    edges.push({ from: "jay", to: p.key, color: p.color, ao: (i - (ps.length - 1) / 2) * 26, dashed: paused || p.health === "onboarding" });
  });
  const tw = 214, tg = 30, tx0 = (W - (TEAMS.length * tw + (TEAMS.length - 1) * tg)) / 2;
  TEAMS.forEach((t, i) => {
    nodes.push({ id: t.id, x: tx0 + i * (tw + tg), y: 310, w: tw, h: 70, color: "#33405e", className: "k-team", label: t.label, onClick: () => go("topology"),
      body: <span className="gn-row"><span className="gn-ico"><Icon name={t.icon} size={22} /></span><span className="gn-body"><b>{t.label}</b><small>{plural(t.n, "agent")}</small></span></span> });
    edges.push({ from: ps[i].key, to: t.id, color: ps[i].color, bo: -18 });
    if (i < TEAMS.length - 1) edges.push({ from: ps[i + 1].key, to: t.id, color: ps[i + 1].color, ao: -30, bo: 18 });
  });
  return <GraphFrame w={W} h={H} nodes={nodes} edges={edges} className="office-graph" />;
}

const ATTN = [
  { icon: "doc", tone: "info", k: "SV-025", t: "Rental comparison redesign", s: "Awaiting your decision · 2h ago", pill: ["High", "bad"], to: () => go("decisions") },
  { icon: "lock", tone: "warn", k: "MFE-014", t: "Release window undecided", s: "Blocks mobile settings · 3h ago", pill: ["Blocker", "bad"], to: () => go("task", "MFE-014") },
  { icon: "code", tone: "violet", k: "GYST-019", t: "Personal-data trigger", s: "Memory retention needs Jay · 6h ago", pill: ["Needs input", "warn"], to: () => go("task", "GYST-019") },
  { icon: "shield", tone: "ok", k: "CC-058", t: "Autonomy v3 shadow report", s: "Read-only comparison ready · 1d ago", pill: ["Review", "violet"], to: () => go("task", "CC-058") },
];
const UPDATES = [
  { a: "claude", role: "Project Lead", p: "samvision", t: "SV-025 implementation is in progress. Core comparison works; working on edge cases.", at: "2h ago" },
  { a: "nova", role: "Implementation Agent", p: "gyst", t: "Finished the memory layer refactor. Waiting on your personal-data review.", at: "4h ago" },
  { a: "atlas", role: "Code Review Lead", p: "mfe", t: "Review of MFE-012 approved at head. Ready for UI testing.", at: "6h ago" },
  { a: "pixel", role: "UI Testing Lead", p: "mfe", t: "Cross-device run done: 2 minor UI issues, not blocking.", at: "1d ago" },
];

function AgentCard({ id }: { id: string }) {
  const a = agent(id);
  const v = useAgentView(id);
  const open = useOpenAgent();
  return <button type="button" className="agent-card" onClick={() => open(id)} aria-label={`${a.name}, ${a.role}. Open details`}>
    <Avatar id={id} size={40} />
    <span className="ac-main"><span className="ac-top"><b>{a.name}</b><small className="muted">{a.role}</small></span>
      <AgentStatus v={v} />
      <AgentMeta v={v} /></span>
  </button>;
}

export function Office() {
  useOrg();
  const AGENTS = rosterAgents();
  const f = useStore(feed);
  const now = useNow(5000);
  const stale = f.outage || now - f.beat > FEED_STALE_MS;
  const [filter, setFilter] = useViewState("page:office", "agentFilter", "all");
  const agents = AGENTS.filter((a) => filter === "all" || statusOf(a.id, f, now) === filter);
  const counts = (s: string) => AGENTS.filter((a) => statusOf(a.id, f, now) === s).length;
  const hour = new Date().getHours();
  return <div className="page page-office">
    <div className="office-hero">
      <div><h1>Good {hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening"}, <em>Jay</em></h1><p>Here's what's happening across your engineering company.</p></div>
      <div className="office-date"><span>{new Date().toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" })}</span><q>Build with clarity. Ship with confidence.</q></div>
    </div>
    <div className="office-grid">
      <div className="office-left">
        <div className="kpis">
          <button type="button" className="kpi" onClick={() => go("topology")}><span className="kpi-ico t-info"><Icon name="layers" size={24} /></span><span><small>Projects</small><b>{PROJECTS.length}</b><em className="t-ok">↑ {PROJECTS.filter((p) => p.health === "healthy").length} active</em></span><Spark data={SPARK.a} color="#4f7bff" w={72} h={30} /></button>
          <button type="button" className="kpi" onClick={() => go("teams")}><span className="kpi-ico t-violet"><Icon name="users" size={24} /></span><span><small>Active Agents</small><b>{AGENTS.length}</b><em className="t-ok">↑ {counts("working")} working</em></span><Spark data={SPARK.b} color="#a77bff" w={72} h={30} /></button>
          <button type="button" className="kpi" onClick={() => go("decisions")}><span className="kpi-ico t-bad"><Icon name="doc" size={24} /></span><span><small>Decisions</small><b>2</b><em className="t-bad">↑ 1 high priority</em></span><Spark data={SPARK.d} color="#ff4f6d" w={72} h={30} /></button>
          <div className="kpi"><span className="kpi-ico t-ok"><Icon name="pulse" size={24} /></span><span><small>Company Health</small><b className="t-ok">Healthy</b><em>{stale ? <span className="t-warn">Feed stale — showing last known</span> : "All monitored systems OK"}</em></span></div>
        </div>
        <Panel className="office-topo" icon="graph" title="Company Topology" sub="Projects, agents and teams across your organisation"
          action={<><button type="button" className="btn btn-sm" onClick={() => startNewProject()}><Icon name="plus" size={14} /> New Project</button><button type="button" className="btn btn-outline" onClick={() => go("topology")}>View Full Topology <Icon name="arrowr" size={15} /></button><PopButton id="page:topology" /></>}>
          <OfficeGraph />
        </Panel>
      </div>
      <div className="office-right">
        <Panel icon="info" iconTone="bad" title="Needs Your Attention" action={<ViewAll onClick={() => go("decisions")} />}>
          <ul className="attn">{ATTN.map((a) => <li key={a.k}><button type="button" onClick={a.to}><span className={`attn-ico t-${a.tone}`}><Icon name={a.icon} size={18} /></span>
            <span className="attn-body"><span className="ellip"><TaskKey k={a.k} /> {a.t}</span><small>{a.s}</small></span><Pill tone={a.pill[1]}>{a.pill[0]}</Pill><Icon name="chevron" size={16} /></button></li>)}</ul>
        </Panel>
        <Panel icon="message" iconTone="violet" title="Recent Updates from Leads" action={<ViewAll onClick={() => go("messages")} />}>
          <ul className="updates">{UPDATES.map((u) => <li key={u.a + u.at}><Avatar id={u.a} size={40} /><div><p><b>{agent(u.a).name}</b><small>{u.role} · <span style={{ color: project(u.p).color }}>{project(u.p).name}</span></small><time>{u.at}</time></p><span>{u.t}</span></div></li>)}</ul>
        </Panel>
      </div>
    </div>
    <Panel className="agents-strip" icon="users" iconTone="info" title={<>Active Agents <small className="muted">{AGENTS.length} agents across {PROJECTS.filter((p) => p.team.length && p.health !== "paused").length} projects</small> {stale && <Pill tone="warn" dot>Stale · status may be out of date</Pill>} <Demo label="Demo status" /></>}
      action={<div className="seg seg-pills" role="tablist">{[["all", `All (${AGENTS.length})`], ["working", `Working (${counts("working")})`], ["reviewing", `Reviewing (${counts("reviewing")})`], ["waiting", `Waiting for Jay (${counts("waiting")})`], ["blocked", `Blocked (${counts("blocked")})`], ["idle", `Idle (${counts("idle")})`]].map(([k, l]) =>
        <button key={k} type="button" role="tab" aria-selected={filter === k} className={cx(`t-${k}`)} onClick={() => setFilter(k)}>{l}</button>)}
        <button type="button" className="btn btn-sm btn-outline" onClick={() => startNewAgent()}><Icon name="plus" size={14} /> New Agent</button></div>}>
      <div className="agent-cards">{agents.map((a) => <AgentCard key={a.id} id={a.id} />)}</div>
    </Panel>
  </div>;
}
