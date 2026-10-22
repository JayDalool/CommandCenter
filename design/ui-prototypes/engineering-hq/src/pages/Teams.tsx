// TEAMS — one project's team: lead → specialist leads, work queues, conversations, open questions (reference 04).
import { useEffect } from "react";
import { AGENTS, PROJECTS, TASKS, agent, project } from "../data/seed";
import { feed, useViewState, FEED_STALE_MS } from "../data/live";
import { useStore } from "../lib/store";
import { go, useRoute } from "../lib/router";
import { useNow } from "../lib/time";
import { Icon } from "../components/Icon";
import { Avatar, AvatarStack, Demo, Pill, PresenceDot, StagePill, ViewAll, cx, plural } from "../components/ui";
import { GraphFrame, type FEdge, type FNode } from "../components/GraphFrame";
import { PopButton } from "../windows/Detachable";

const QUEUES = [
  { id: "plan", label: "Planning", icon: "doc", color: "#4f7bff", items: [["Define v0.5 roadmap", "In progress", "info"], ["Research comparable-sales API", "Waiting on research", "idle"], ["Competitive analysis", "Not started", "idle"]], blocked: 1 },
  { id: "impl", label: "Implementation", icon: "star", color: "#a463ff", items: [["SV-025 Comparison layout", "In progress", "info"], ["Optimise pricing calc", "In progress", "info"], ["Add batch processing", "Not started", "idle"]], blocked: 0 },
  { id: "review", label: "Review", icon: "check", color: "#22c98e", items: [["PR-842 Comparison layout", "In review", "violet"], ["PR-839 Import retry", "In review", "violet"], ["PR-838 Test coverage", "Queued", "warn"]], blocked: 0 },
  { id: "test", label: "Testing", icon: "mobile", color: "#ff4fa0", items: [["Cross-device testing", "Queued", "warn"], ["Performance testing", "In progress", "info"], ["Accessibility audit", "Not started", "idle"]], blocked: 0 },
  { id: "deploy", label: "Deployment", icon: "box", color: "#ffb020", items: [["Staging environment (v0.4.2)", "Ready", "ok"], ["Release runbook", "In progress", "info"]], blocked: 0 },
];

export function Teams() {
  const route = useRoute();
  const [pk, setPk] = useViewState("page:teams", "project", "samvision");
  const key = route.screen === "teams" && route.id && PROJECTS.some((p) => p.key === route.id) ? route.id : pk;
  useEffect(() => { if (key !== pk) setPk(key); }, [key, pk, setPk]);
  const p = project(key);
  const [focus, setFocus] = useViewState<string | null>("page:teams", "focus", null);
  const f = useStore(feed);
  const now = useNow(5000);
  const stale = f.outage || now - f.beat > FEED_STALE_MS;
  const paused = p.health === "paused";
  const specs = AGENTS.slice(1);
  const W = 1330, H = 384;
  const sw = 246, sg = 21, sx0 = (W - (specs.length * sw + (specs.length - 1) * sg)) / 2;
  const lead = f.agents.claude;
  const nodes: FNode[] = [{ id: "lead", x: W / 2 - 290, y: 4, w: 580, h: 132, color: "#ff8a3d", className: "k-lead", label: "Claude, Project Lead", onClick: () => setFocus("claude"),
    body: <><Avatar id="claude" size={58} /><span className="gn-body"><span className="gn-row"><b className="lg">Claude</b><Pill tone="warn"><Icon name="star" size={12} /> Project Lead</Pill></span>
      <PresenceDot s={paused ? "paused" : stale ? "unknown" : lead.status} detail={paused ? "project paused" : lead.detail} />
      <small>Coordinates the {p.name} team: turns Jay's requests into scoped tasks, delegates, and keeps Jay informed.</small></span>
      <span className="lead-facts"><span><Icon name="branch" size={14} /> 5 active workstreams</span><span><Icon name="help" size={14} /> 2 items waiting on decision</span><span><Icon name="calendar" size={14} /> On track for {p.version}</span></span></> }];
  const edges: FEdge[] = [];
  specs.forEach((a, i) => {
    const s = f.agents[a.id];
    nodes.push({ id: a.id, x: sx0 + i * (sw + sg), y: 214, w: sw, h: 164, color: a.color, className: cx("k-spec", focus === a.id && "is-sel"), label: `${a.name}, ${a.role}`, onClick: () => setFocus(a.id),
      body: <><span className="gn-row"><Avatar id={a.id} size={40} /><span className="gn-body"><b>{a.name}</b><Pill tone="idle">{a.role}</Pill></span></span>
        <PresenceDot s={paused ? "paused" : stale ? "unknown" : s.status} /><small className="ellip2">{s.detail}</small>
        <span className="gn-row gn-foot"><Icon name="list" size={14} /><span>{plural(TASKS.filter((t) => t.owner === a.id).length, "task")}</span></span></> });
    edges.push({ from: "lead", to: a.id, color: a.color, ao: (i - 2) * 40, dashed: paused });
  });
  const fa = focus ? agent(focus) : null;
  return <div className="page page-teams">
    <a className="back" href="#/teams"><Icon name="arrowl" size={15} /> Teams</a>
    <header className="team-head">
      <h1>{p.name} <em style={{ color: "#a98bff" }}>Team</em></h1>
      <span className={cx("pill-lg", paused ? "t-idle" : "t-ok")}><Icon name="pulse" size={17} /> {paused ? "Paused" : "Healthy"}</span>
      <span className="pill-lg t-idle"><Icon name="branch" size={17} /> {p.env}</span>
      <span className="sp" />
      <button type="button" className="btn btn-outline" onClick={() => go("messages", p.key === "commandcenter" ? "cc-lead" : "sv-lead")}><Icon name="message" size={16} /> Message Lead</button>
      <button type="button" className="btn btn-outline" onClick={() => go("messages", "team-samvision")}><Icon name="users" size={16} /> Open Team Space</button>
      <button type="button" className="btn btn-outline" onClick={() => go("engineering")}><Icon name="list" size={16} /> View Active Tasks</button>
      <PopButton id="page:teams" />
    </header>
    <p className="team-blurb">{p.blurb}</p>
    <div className="team-switch" role="tablist" aria-label="Project teams">{PROJECTS.map((x) => <a key={x.key} role="tab" aria-selected={x.key === key} href={`#/teams/${x.key}`} style={{ ["--c" as string]: x.color }}><i />{x.name}</a>)}</div>
    {paused && <p className="callout t-idle"><Icon name="lock" size={16} /> {p.pausedReason}. Agents are shown as Paused, not working.</p>}
    <section className="panel team-lead">
      <header className="panel-h"><span className="panel-ico t-info"><Icon name="users" size={20} /></span><div className="panel-t"><h2>Team Leadership</h2><p>Project lead and specialist leads for {p.name} <Demo label="Demo roster" /></p></div></header>
      <div className="team-lead-grid">
        <GraphFrame w={W} h={H} nodes={nodes} edges={edges} className="team-graph" />
        <aside className="glance"><h3>{p.name} at a Glance <span className="sp" /><ViewAll label="View Project" onClick={() => go("topology")} /></h3>
          <dl><dt>Status</dt><dd className={paused ? "" : "t-ok"}><Icon name="heart" size={15} /> {paused ? "Paused" : "Healthy"}</dd><dt>Environment</dt><dd><Icon name="branch" size={15} /> {p.env} ({p.version})</dd>
            <dt>Active agents</dt><dd><Icon name="users" size={15} /> {paused ? "0 / 6" : "5 / 6"}</dd><dt>Open tasks</dt><dd className="t-bad"><Icon name="list" size={15} /> {TASKS.filter((t) => t.project === p.key).length} ({TASKS.filter((t) => t.project === p.key && t.stage === "Blocked").length} blocked)</dd>
            <dt>Merge rule</dt><dd>{p.merge}</dd><dt>Project repo</dt><dd className="link">JayDalool/{p.key === "samvision" ? "SamVisionAI" : p.key === "gyst" ? "gyst-lifeops" : p.key === "mfe" ? "MyFamilyExpenses" : p.key === "gauzemate" ? "GauzeMate" : "CommandCenter"}</dd></dl></aside>
      </div>
    </section>
    {fa && <div className="drawer" role="dialog" aria-label={`${fa.name} details`}>
      <header><Avatar id={fa.id} size={44} /><div><h2>{fa.name}</h2><p>{fa.role} · {fa.model}</p></div><span className="sp" /><button type="button" className="icon-btn" aria-label="Close" onClick={() => setFocus(null)}><Icon name="x" size={16} /></button></header>
      <dl className="kv"><dt>Status</dt><dd><PresenceDot s={paused ? "paused" : stale ? "unknown" : f.agents[fa.id].status} detail={f.agents[fa.id].detail} /></dd>
        <dt>Active ticket</dt><dd className="mono">{f.agents[fa.id].task ?? "—"}</dd><dt>Last update</dt><dd>{stale ? `${Math.round((now - f.beat) / 1000)}s ago (stale)` : "just now"}</dd>
        <dt>Session</dt><dd>Same session identity everywhere; opening chat never starts a duplicate.</dd></dl>
      <div className="row-gap"><button type="button" className="btn btn-primary" onClick={() => go("messages", fa.id === "claude" ? "sv-lead" : fa.id)}><Icon name="message" size={16} /> Chat</button>
        {f.agents[fa.id].task && <button type="button" className="btn" onClick={() => go("task", f.agents[fa.id].task!)}>Open Task Room</button>}</div>
    </div>}
    <section className="panel">
      <header className="panel-h"><span className="panel-ico t-info"><Icon name="list" size={20} /></span><div className="panel-t"><h2>Team Work Queues <small className="muted">Current work across the {p.name} team</small></h2></div><div className="panel-a"><ViewAll label="View All Tasks" onClick={() => go("engineering")} /></div></header>
      <div className="queues">{QUEUES.map((q) => <div key={q.id} className="queue" style={{ ["--c" as string]: q.color }}>
        <h3><span className="q-ico"><Icon name={q.icon} size={16} /></span>{q.label}<span className="sp" /><small>{q.items.length} tasks</small></h3>
        <ul>{q.items.map(([t, s, tone]) => <li key={t}><i /><span className="ellip">{t}</span><Pill tone={tone} dot>{s}</Pill></li>)}</ul>
        <footer><AvatarStack ids={AGENTS.slice(0, 2 + (q.id.length % 3)).map((a) => a.id)} size={22} /><span className="sp" />{q.blocked ? <span className="t-bad"><Icon name="info" size={14} /> {q.blocked} blocked</span> : <span className="muted"><Icon name="clock" size={14} /> 0 blocked</span>}</footer>
      </div>)}</div>
    </section>
    <div className="team-bottom">
      <section className="panel"><header className="panel-h"><span className="panel-ico t-violet"><Icon name="message" size={20} /></span><div className="panel-t"><h2>Team Conversations <small className="muted">Recent messages from the {p.name} team</small></h2></div><div className="panel-a"><ViewAll onClick={() => go("messages", "team-samvision")} /></div></header>
        <ul className="convo-rows">{[["claude", "2h ago", "SV-025 is making good progress. Nova is about 70% complete; Atlas reviews next."], ["nova", "4h ago", "Pushed a new commit for the comparison layout. Ready for review → PR #842"], ["atlas", "6h ago", "Left comments on PR #839. Main issue is error handling."]].map(([a, at, t]) =>
          <li key={at}><Avatar id={a} size={26} /><b>{agent(a).name}</b><small>{at}</small><span className="ellip">{t}</span></li>)}</ul></section>
      <section className="panel"><header className="panel-h"><span className="panel-ico t-info"><Icon name="help" size={20} /></span><div className="panel-t"><h2>Open Questions from Team <small className="muted">Items waiting on Jay</small></h2></div><div className="panel-a"><ViewAll onClick={() => go("decisions")} /></div></header>
        <ul className="convo-rows">{[["claude", "2h ago", "Prioritise comparable-sales research for v0.5, or ship v0.4.2 first?", "High", "bad"], ["iris", "4h ago", "Preferred provider for additional listing data?", "Medium", "warn"], ["orion", "6h ago", "OK to add a staging load test (~$200/month)?", "Medium", "warn"]].map(([a, at, t, pr, tone]) =>
          <li key={at}><Avatar id={a} size={26} /><b>{agent(a).name}</b><small>{at}</small><span className="ellip">{t}</span><Pill tone={tone}>{pr}</Pill></li>)}</ul></section>
    </div>
    <p className="muted small"><StagePill s="Implementing" /> Statuses come from the demo feed. Real presence must say Disconnected / Unknown when a stream is stale, never "Working".</p>
  </div>;
}
