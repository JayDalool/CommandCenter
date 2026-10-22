// AGENTS — the directory of every agent (active, paused, offboarded), saved drafts and the prototype's
// audit log. The canonical list comes from the organisation store; no page keeps its own copy.
import { deleteDraft, saveDraft, useOrg, type AgentDraft, type ProjectDraft } from "../data/org";
import { useViewState } from "../data/live";
import { currentProfile } from "../data/org";
import { modelLabel, projectsOf, type Agent } from "../data/seed";
import { templateOf } from "../data/catalog";
import { Icon } from "../components/Icon";
import { Demo, Panel, Pill, cx, plural } from "../components/ui";
import { AgentStatus, ago, useAgentView, useOpenAgent } from "../components/agent";
import { Avatar } from "../components/ui";
import { LifePill, agentMenu } from "../components/manage";
import { useContextMenu } from "../components/overlay";
import { PopButton } from "../windows/Detachable";
import { notify } from "../windows/manager";
import { peekView, putView, showPage } from "./onboarding/Wizard";
import { AGENT_VIEW, startNewAgent } from "./onboarding/NewAgent";
import { PROJECT_VIEW, startNewProject } from "./onboarding/NewProject";

function Row({ a }: { a: Agent }) {
  const v = useAgentView(a.id);
  const open = useOpenAgent();
  const prof = currentProfile(a.id);
  const menu = useContextMenu(() => agentMenu(a, open), a.name);
  return <tr className={cx(a.life === "offboarded" && "is-off")} onClick={() => open(a.id)} onContextMenu={menu.onContextMenu}>
    <td><button type="button" className="dir-name" onClick={(e) => { e.stopPropagation(); open(a.id); }} onKeyDown={menu.onKeyDown} aria-label={`${a.name}, ${a.role}. Open details`}>
      <Avatar id={a.id} size={34} /><span><b>{a.name}</b><small>{a.role}</small></span></button></td>
    <td><AgentStatus v={v} /></td>
    <td>{projectsOf(a.id).map((p) => <span key={p.key} className="am-proj dir-proj"><i style={{ background: p.color }} />{p.name}</span>)}{!projectsOf(a.id).length && <span className="muted">—</span>}</td>
    <td>{modelLabel(prof.model)}</td>
    <td><span className="muted">{templateOf(prof.template).title}</span> <small className="muted">v{prof.version}</small></td>
    <td><LifePill a={a} /></td>
    <td className="muted">{v.evidence}</td>
  </tr>;
}

export function Agents() {
  const o = useOrg();
  const [filter, setFilter] = useViewState("page:agents", "filter", "active");
  const list = o.agents.filter((a) => filter === "all" || (a.life ?? "active") === filter);
  const count = (l: string) => o.agents.filter((a) => (a.life ?? "active") === l).length;
  const resume = (id: string) => {
    const dr = o.drafts.find((x) => x.id === id); if (!dr) return;
    const view = dr.kind === "agent" ? AGENT_VIEW : PROJECT_VIEW;
    const cur = peekView<AgentDraft | ProjectDraft>(view, "draft");
    if (cur && cur.touched) { saveDraft(cur); notify("Your unfinished draft was saved to Drafts first.", "warn"); }
    putView(view, "draft", { ...dr.data, touched: false });
    showPage(dr.kind === "agent" ? "onboard" : "newproject");
  };
  return <div className="page page-agents">
    <div className="page-head"><div><h1>Agents</h1><p>Every AI team member, what it's doing, and its lifecycle. Approvals here change only this prototype.</p></div>
      <div className="row-gap"><button type="button" className="btn btn-outline" onClick={() => startNewProject()}><Icon name="layers" size={16} /> New Project</button>
        <button type="button" className="btn btn-primary" onClick={() => startNewAgent()}><Icon name="plus" size={16} /> New Agent</button><PopButton id="page:agents" /></div></div>
    {o.drafts.length > 0 && <Panel icon="doc" iconTone="violet" title={<>Drafts <small className="muted">{plural(o.drafts.length, "saved draft")}. Not part of the organisation until approved.</small></>}>
      <ul className="drafts">{o.drafts.map((dr) => <li key={dr.id}><Icon name={dr.kind === "agent" ? "users" : "layers"} size={16} /><b>{dr.label}</b><Pill tone="idle">{dr.kind === "agent" ? "Agent" : "Project"}</Pill>
        <small className="muted">saved {ago(Date.now() - dr.at)}</small><span className="sp" />
        <button type="button" className="btn btn-sm" onClick={() => resume(dr.id)}>Resume</button>
        <button type="button" className="btn btn-sm" onClick={() => deleteDraft(dr.id)} aria-label={`Delete draft ${dr.label}`}>Delete</button></li>)}</ul>
    </Panel>}
    <Panel icon="users" iconTone="info" title={<>Directory <Demo label="Demo status" /></>}
      action={<div className="seg seg-pills" role="tablist" aria-label="Lifecycle">{[["active", `Active (${count("active")})`], ["paused", `Paused (${count("paused")})`], ["offboarded", `Offboarded (${count("offboarded")})`], ["all", `All (${o.agents.length})`]].map(([k, l]) =>
        <button key={k} type="button" role="tab" aria-selected={filter === k} onClick={() => setFilter(k)}>{l}</button>)}</div>}>
      <div className="dir-wrap"><table className="dir"><thead><tr><th>Agent</th><th>Status</th><th>Projects</th><th>Model</th><th>Template</th><th>Lifecycle</th><th>Evidence</th></tr></thead>
        <tbody>{list.map((a) => <Row key={a.id} a={a} />)}</tbody></table>
        {!list.length && <p className="empty">No agents here.</p>}</div>
    </Panel>
    <Panel icon="shield" iconTone="violet" title={<>Audit log <small className="muted">prototype only · every approval and lifecycle change</small></>}>
      {o.audit.length ? <ul className="audit">{o.audit.slice().reverse().slice(0, 30).map((e) => <li key={e.id}><small className="muted">{ago(Date.now() - e.at)}</small><code>{e.kind}</code><span>{e.text}</span><small className="muted">by Jay</small></li>)}</ul>
        : <p className="empty">Nothing recorded yet. Approvals and lifecycle changes appear here.</p>}
    </Panel>
    <AgentsFoot />
  </div>;
}
function AgentsFoot() { return <p className="muted small">Status marked <abbr className="sim-inline">demo</abbr> is simulated. A new agent shows <b>Not started</b> until ccd reports a real session; it is never shown as Working without evidence.</p>; }
