// TEAMS — one project's team: lead → specialist leads, work queues, conversations, open questions (reference 04).
import { useEffect } from "react";
import { AGENTS, PROJECTS, TASKS, agent, healthOf, leadConversation, leadOf, project, teamConversation } from "../data/seed";
import { projectProfile, useOrg } from "../data/org";
import { TARGET_MODES } from "../data/catalog";
import { startNewAgent } from "./onboarding/NewAgent";
import { Lifecycle, startNewProject } from "./onboarding/NewProject";
import { chat, useViewState } from "../data/live";
import { useStore } from "../lib/store";
import { go, useRoute } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, AvatarStack, Demo, Pill, ViewAll, cx, plural } from "../components/ui";
import { AgentMeta, AgentStatus, useAgentView, useOpenAgent } from "../components/agent";
import { GraphFrame, type FEdge, type FNode } from "../components/GraphFrame";
import { PopButton } from "../windows/Detachable";

const QUEUES = [
  { id: "plan", label: "Planning", icon: "doc", color: "#4f7bff", items: [["Define v0.5 roadmap", "In progress", "info"], ["Research comparable-sales API", "Waiting on research", "idle"], ["Competitive analysis", "Not started", "idle"]], blocked: 1 },
  { id: "impl", label: "Implementation", icon: "star", color: "#a463ff", items: [["SV-025 Comparison layout", "In progress", "info"], ["Optimise pricing calc", "In progress", "info"], ["Add batch processing", "Not started", "idle"]], blocked: 0 },
  { id: "review", label: "Review", icon: "check", color: "#22c98e", items: [["PR-842 Comparison layout", "In review", "violet"], ["PR-839 Import retry", "In review", "violet"], ["PR-838 Test coverage", "Queued", "warn"]], blocked: 0 },
  { id: "test", label: "Testing", icon: "mobile", color: "#ff4fa0", items: [["Cross-device testing", "Queued", "warn"], ["Performance testing", "In progress", "info"], ["Accessibility audit", "Not started", "idle"]], blocked: 0 },
  { id: "deploy", label: "Deployment", icon: "box", color: "#ffb020", items: [["Staging environment (v0.4.2)", "Ready", "ok"], ["Release runbook", "In progress", "info"]], blocked: 0 },
];

/** SamVision keeps the reference's demo queues; every other team shows its own tasks, grouped by stage. */
const STAGE_Q: Record<string, string[]> = { plan: ["Planning"], impl: ["Implementing", "Blocked"], review: ["Reviewing"], test: ["UI Testing"], deploy: ["Verifying", "Ready to Merge", "Deploying", "Needs Jay"] };
function queuesFor(key: string): { id: string; label: string; icon: string; color: string; items: string[][]; blocked: number; who?: string[] }[] {
  if (key === "samvision") return QUEUES;
  return QUEUES.map((q) => { const ts = TASKS.filter((t) => t.project === key && STAGE_Q[q.id].includes(t.stage));
    return { ...q, items: ts.map((t) => [`${t.key} ${t.title}`, t.stage, t.stage === "Blocked" || t.stage === "Needs Jay" ? "bad" : "info"]), blocked: ts.filter((t) => t.stage === "Blocked").length, who: [...new Set(ts.map((t) => t.owner))] }; });
}

function LeadBody({ id, paused, version, name, onboarding }: { id: string; paused: boolean; version: string; name: string; onboarding: boolean }) {
  const a = agent(id);
  const v = useAgentView(id, { pausedProject: paused });
  return <><Avatar id={id} size={58} />
    <span className="gn-body"><span className="gn-row"><b className="lg">{a.name}</b><Pill tone="warn"><Icon name="star" size={12} /> Project Lead</Pill></span>
      <AgentStatus v={v} />
      <AgentMeta v={v} />
      <small>Coordinates the {name} team: turns Jay's requests into scoped tasks, delegates, and keeps Jay informed.</small></span>
    <span className="lead-facts">{onboarding ? <><span><Icon name="eye" size={14} /> Observing only (onboarding)</span><span><Icon name="list" size={14} /> Fingerprint and first audit</span></>
      : <><span><Icon name="branch" size={14} /> 5 active workstreams</span><span><Icon name="help" size={14} /> 2 items waiting on decision</span><span><Icon name="calendar" size={14} /> On track for {version}</span></>}</span></>;
}

function SpecBody({ id, paused }: { id: string; paused: boolean }) {
  const a = agent(id);
  const v = useAgentView(id, { pausedProject: paused });
  const line = v.status === "unknown" ? "No recent status" : v.status === "notstarted" ? "New · waiting for its first task" : v.status === "paused" && a.life === "paused" ? `Paused by Jay${a.lifeNote ? ` · ${a.lifeNote}` : ""}`
    : `${v.status === "waiting" && v.s.questions ? `${plural(v.s.questions, "question")} for Jay · ` : ""}${v.s.detail}`;
  return <><span className="gn-row"><Avatar id={id} size={40} /><span className="gn-body"><b>{a.name}</b><Pill tone="idle">{a.role}</Pill></span></span>
    <AgentStatus v={v} questions={false} />
    <small className="ellip">{line}</small>
    <AgentMeta v={v} />
    <span className="gn-row gn-foot"><Icon name="list" size={14} /><span>{plural(TASKS.filter((t) => t.owner === id).length, "task")}</span><span className="sp" /><span className="muted">{a.stage}</span></span></>;
}

/** The team as an org chart: the lead on top, then each level of reports. Built from the project's team record. */
function teamGraph(p: ReturnType<typeof project>, paused: boolean, open: (id: string) => void) {
  const lead = leadOf(p);
  const levels: string[][] = [];
  const placed = new Set<string>(lead ? [lead] : []);
  let cur = lead ? [lead] : [];
  while (cur.length) {
    const next = p.team.filter((m) => cur.includes(m.reportsTo) && !placed.has(m.id)).map((m) => m.id);
    next.forEach((x) => placed.add(x));
    if (next.length) levels.push(next);
    cur = next;
  }
  const orphans = p.team.filter((m) => !placed.has(m.id)).map((m) => m.id);
  if (orphans.length) { if (levels[0]) levels[0].push(...orphans); else levels.push(orphans); }
  const sw = 248, sg = 22, sh = 194, widest = Math.max(1, ...levels.map((l) => l.length));
  const W = Math.max(1330, widest * (sw + sg) + 40);
  const nodes: FNode[] = [lead
    ? { id: lead, x: W / 2 - 310, y: 4, w: 620, h: 150, color: "#ff8a3d", className: "k-lead", label: `${agent(lead).name}, Project Lead. Open details`, onClick: () => open(lead),
      body: <LeadBody id={lead} paused={paused} version={p.version} name={p.name} onboarding={p.health === "onboarding"} /> }
    : { id: "nolead", x: W / 2 - 310, y: 4, w: 620, h: 150, color: "#5d6a85", className: "k-lead is-empty", label: "No project lead. Plan one", onClick: () => startNewAgent(p.key, "lead"),
      body: <><span className="gn-ico is-lg"><Icon name="plus" size={28} /></span><span className="gn-body"><b className="lg">No project lead yet</b><small>Nobody coordinates {p.name} or brings you its decisions. Click to onboard a Project Lead.</small></span></> }];
  const edges: FEdge[] = [];
  levels.forEach((row, li) => {
    const y = 214 + li * (sh + 64);
    const x0 = (W - (row.length * sw + (row.length - 1) * sg)) / 2;
    row.forEach((id, i) => {
      const a = agent(id);
      nodes.push({ id, x: x0 + i * (sw + sg), y, w: sw, h: sh, color: a.color, className: "k-spec", label: `${a.name}, ${a.role}. Open details`, onClick: () => open(id), body: <SpecBody id={id} paused={paused} /> });
      const parent = p.team.find((m) => m.id === id)?.reportsTo;
      const from = parent && nodes.some((n) => n.id === parent) ? parent : nodes[0].id;
      const siblings = row.filter((x) => (p.team.find((m) => m.id === x)?.reportsTo ?? "") === parent);
      const si = siblings.indexOf(id);
      edges.push({ from, to: id, color: a.color, ao: (si - (siblings.length - 1) / 2) * 26, bus: y - 30, dashed: paused || a.life === "paused" });
    });
  });
  const H = levels.length ? 214 + (levels.length - 1) * (sh + 64) + sh + 4 : 160;
  return { nodes, edges, W, H };
}

export function Teams() {
  const route = useRoute();
  useOrg();
  const [pk, setPk] = useViewState("page:teams", "project", "samvision");
  const key = route.screen === "teams" && route.id && PROJECTS.some((p) => p.key === route.id) ? route.id : PROJECTS.some((p) => p.key === pk) ? pk : "samvision";
  useEffect(() => { if (key !== pk) setPk(key); }, [key, pk, setPk]);
  const p = project(key);
  const open = useOpenAgent();
  const paused = p.health === "paused";
  const h = healthOf(p);
  const pp = projectProfile(p.key);
  const { nodes, edges, W, H } = teamGraph(p, paused, open);
  const lc = leadConversation(p.key);
  const chatAll = useStore(chat);
  const tc = teamConversation(p.key);
  const working = p.team.filter((m) => agent(m.id).life !== "paused").length;
  return <div className="page page-teams">
    <a className="back" href="#/teams"><Icon name="arrowl" size={15} /> Teams</a>
    <header className="team-head">
      <h1>{p.name} <em style={{ color: "#a98bff" }}>Team</em></h1>
      <span className={cx("pill-lg", `t-${h.tone}`)}><Icon name={p.health === "onboarding" ? "eye" : "pulse"} size={17} /> {h.label}</span>
      <span className="pill-lg t-idle"><Icon name="branch" size={17} /> {p.env}</span>
      <span className="sp" />
      {lc && <button type="button" className="btn btn-outline" onClick={() => go("messages", lc.id)}><Icon name="message" size={16} /> Message Lead</button>}
      {tc && <button type="button" className="btn btn-outline" onClick={() => go("messages", tc.id)}><Icon name="users" size={16} /> Open Team Space</button>}
      <button type="button" className="btn btn-outline" onClick={() => startNewAgent(p.key)}><Icon name="plus" size={16} /> New Agent</button>
      <PopButton id="page:teams" />
    </header>
    <p className="team-blurb">{p.blurb}</p>
    <div className="team-switch" role="tablist" aria-label="Project teams">{PROJECTS.map((x) => <a key={x.key} role="tab" aria-selected={x.key === key} href={`#/teams/${x.key}`} style={{ ["--c" as string]: x.color }}><i />{x.name}</a>)}
      <button type="button" className="team-new" onClick={() => startNewProject()}><Icon name="plus" size={14} /> New Project</button></div>
    {paused && <p className="callout t-idle"><Icon name="lock" size={16} /> {p.pausedReason}. Agents are shown as Paused, not working.</p>}
    {pp.phase === "onboarding" && <section className="panel pad onb-panel"><div className="onb-banner"><Icon name="eye" size={22} /><div><b>Onboarding / Observation</b>
      <p>Agents only observe {p.name}. Target {TARGET_MODES.find((m) => m.id === pp.target)?.label} applies after the admission review and your approval.{p.repoState === "proposed" && ` The repository ${p.repo} is proposed, not created.`}</p></div></div>
      <Lifecycle at={pp.stage} /></section>}
    <section className="panel team-lead">
      <header className="panel-h"><span className="panel-ico t-info"><Icon name="users" size={20} /></span><div className="panel-t"><h2>Team Leadership</h2><p>Project lead and team for {p.name} <Demo label="Demo status" /></p></div></header>
      <div className="team-lead-grid">
        <GraphFrame w={W} h={H} nodes={nodes} edges={edges} className="team-graph" />
        <aside className="glance"><h3>{p.name} at a Glance <span className="sp" /><ViewAll label="View Project" onClick={() => go("topology")} /></h3>
          <dl><dt>Status</dt><dd className={`t-${h.tone}`}><Icon name="heart" size={15} /> {h.label}</dd><dt>Environment</dt><dd><Icon name="branch" size={15} /> {p.env} ({p.version})</dd>
            <dt>Team</dt><dd><Icon name="users" size={15} /> {paused ? `0 / ${p.team.length} working` : `${working} / ${p.team.length} active`}</dd><dt>Open tasks</dt><dd className="t-bad"><Icon name="list" size={15} /> {TASKS.filter((t) => t.project === p.key).length} ({TASKS.filter((t) => t.project === p.key && t.stage === "Blocked").length} blocked)</dd>
            <dt>Merge rule</dt><dd>{p.merge}</dd><dt>Project repo</dt><dd className="link">{p.repo}{p.repoState === "proposed" && <small className="t-warn"> · proposed</small>}</dd></dl></aside>
      </div>
    </section>
    <section className="panel">
      <header className="panel-h"><span className="panel-ico t-info"><Icon name="list" size={20} /></span><div className="panel-t"><h2>Team Work Queues <small className="muted">Current work across the {p.name} team</small></h2></div><div className="panel-a"><ViewAll label="View All Tasks" onClick={() => go("engineering")} /></div></header>
      <div className="queues">{queuesFor(p.key).map((q) => <div key={q.id} className="queue" style={{ ["--c" as string]: q.color }}>
        <h3><span className="q-ico"><Icon name={q.icon} size={16} /></span>{q.label}<span className="sp" /><small>{q.items.length} tasks</small></h3>
        <ul>{q.items.map(([t, s, tone]) => <li key={t}><i /><span className="ellip">{t}</span><Pill tone={tone} dot>{s}</Pill></li>)}
          {!q.items.length && <li className="muted"><span className="ellip">Nothing here yet</span></li>}</ul>
        <footer><AvatarStack ids={q.who ?? AGENTS.slice(0, 2 + (q.id.length % 3)).map((a) => a.id)} size={22} /><span className="sp" />{q.blocked ? <span className="t-bad"><Icon name="info" size={14} /> {q.blocked} blocked</span> : <span className="muted"><Icon name="clock" size={14} /> 0 blocked</span>}</footer>
      </div>)}</div>
    </section>
    <div className="team-bottom">
      <section className="panel"><header className="panel-h"><span className="panel-ico t-violet"><Icon name="message" size={20} /></span><div className="panel-t"><h2>Team Conversations <small className="muted">Recent messages from the {p.name} team</small></h2></div><div className="panel-a"><ViewAll onClick={() => go("messages", tc?.id ?? "team-samvision")} /></div></header>
        <ul className="convo-rows">{(p.key === "samvision" ? [["claude", "2h ago", "SV-025 is making good progress. Nova is about 70% complete; Atlas reviews next."], ["nova", "4h ago", "Pushed a new commit for the comparison layout. Ready for review → PR #842"], ["atlas", "6h ago", "Left comments on PR #839. Main issue is error handling."]]
          : (tc ? (chatAll[tc.id] ?? []) : []).slice(-3).reverse().map((m) => [m.from, m.at, m.text])).map(([a, at, t]) =>
          <li key={at + t}><Avatar id={a} size={26} /><b>{agent(a).name}</b><small>{at}</small><span className="ellip">{t}</span></li>)}
          {p.key !== "samvision" && !(tc && chatAll[tc.id]?.length) && <li className="muted">No team messages yet.</li>}</ul></section>
      <section className="panel"><header className="panel-h"><span className="panel-ico t-info"><Icon name="help" size={20} /></span><div className="panel-t"><h2>Open Questions from Team <small className="muted">Items waiting on Jay</small></h2></div><div className="panel-a"><ViewAll onClick={() => go("decisions")} /></div></header>
        <ul className="convo-rows">{(p.key === "samvision" ? [["claude", "2h ago", "Prioritise comparable-sales research for v0.5, or ship v0.4.2 first?", "High", "bad"], ["iris", "4h ago", "Preferred provider for additional listing data?", "Medium", "warn"], ["orion", "6h ago", "OK to add a staging load test (~$200/month)?", "Medium", "warn"]]
          : TASKS.filter((t) => t.project === p.key).flatMap((t) => t.questions.map((q) => [t.owner, t.updated, `${t.key}: ${q}`, t.priority, t.priority === "High" ? "bad" : "warn"]))).map(([a, at, t, pr, tone]) =>
          <li key={at + t}><Avatar id={a} size={26} /><b>{agent(a).name}</b><small>{at}</small><span className="ellip">{t}</span><Pill tone={tone}>{pr}</Pill></li>)}
          {p.key !== "samvision" && !TASKS.some((t) => t.project === p.key && t.questions.length) && <li className="muted">No open questions.</li>}</ul></section>
    </div>
    <p className="muted small">Agent statuses marked <abbr className="sim-inline">demo</abbr> come from the prototype's demo feed. Real presence comes from ccd session events and shows Unknown when they stop, never Working.</p>
  </div>;
}
