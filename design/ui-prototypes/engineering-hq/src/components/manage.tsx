// Agent lifecycle actions, shown in the Agent Inspector: edit, pause / resume, reassign, change model,
// change machines, review permissions, work history and offboarding. MOCK ONLY: every action changes the
// prototype's organisation store and is written to its audit log with Jay as the actor.
import { useState } from "react";
import { currentProfile, offboard, projectProfile, reassign, setLife, useOrg } from "../data/org";
import { PERMISSIONS, PERM_GROUPS, TASK_MODES, effective, projectRules, worker } from "../data/catalog";
import { SESSION_HISTORY, modelLabel, type Agent } from "../data/seed";
import { useViewState } from "../data/live";
import { notify } from "../windows/manager";
import { Icon } from "./Icon";
import { Field, GrantBadge, Modal } from "./form";
import { Pill, TaskKey, cx, plural } from "./ui";
import { ago } from "./agent";
import { startAgentEdit } from "../pages/onboarding/NewAgent";

export function LifePill({ a }: { a: Agent }) {
  const l = a.life ?? "active";
  return <Pill tone={l === "active" ? "ok" : l === "paused" ? "warn" : "idle"} dot>{l === "active" ? "Active" : l === "paused" ? "Paused by Jay" : "Offboarded"}</Pill>;
}

export function ManageSection({ a }: { a: Agent }) {
  const o = useOrg();
  const [dlg, setDlg] = useState<null | "reassign" | "offboard" | "pause">(null);
  const life = a.life ?? "active";
  const off = life === "offboarded";
  return <section className="ai-sec">
    <h3>Manage <span className="sp" /><LifePill a={a} /></h3>
    {off ? <p className="muted small">{a.name} was offboarded{a.lifeNote ? ` (${a.lifeNote})` : ""}. Its ID <code>{a.id}</code> is retired; its history stays below.</p>
      : <div className="mg-grid">
        <button type="button" className="mg" onClick={() => startAgentEdit(a.id)}><Icon name="edit" size={15} /> Edit</button>
        {life === "paused" ? <button type="button" className="mg" onClick={() => { setLife(a.id, "active"); notify(`${a.name} resumed (mock).`); }}><Icon name="pulse" size={15} /> Resume</button>
          : <button type="button" className="mg" onClick={() => setDlg("pause")}><Icon name="clock" size={15} /> Pause</button>}
        <button type="button" className="mg" onClick={() => setDlg("reassign")}><Icon name="graph" size={15} /> Reassign</button>
        <button type="button" className="mg" onClick={() => startAgentEdit(a.id, "intelligence")}><Icon name="cpu" size={15} /> Change model</button>
        <button type="button" className="mg" onClick={() => startAgentEdit(a.id, "access")}><Icon name="server" size={15} /> Change machines</button>
        <button type="button" className="mg is-bad" onClick={() => setDlg("offboard")} disabled={a.id === "claude" && o.agents.filter((x) => x.life !== "offboarded").length < 2}><Icon name="x" size={15} /> Offboard</button>
      </div>}
    {dlg === "pause" && <PauseDialog a={a} onClose={() => setDlg(null)} />}
    {dlg === "reassign" && <ReassignDialog a={a} onClose={() => setDlg(null)} />}
    {dlg === "offboard" && <OffboardDialog a={a} onClose={() => setDlg(null)} />}
  </section>;
}

function PauseDialog({ a, onClose }: { a: Agent; onClose: () => void }) {
  const [note, setNote] = useState("");
  return <Modal title={`Pause ${a.name}?`} onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button>
    <button type="button" className="btn btn-primary" data-autofocus onClick={() => { setLife(a.id, "paused", note.trim()); notify(`${a.name} paused (mock). It keeps its tasks and history.`); onClose(); }}>Pause {a.name}</button></>}>
    <p>{a.name} stops taking new work and shows as Paused everywhere. Its tasks stay assigned; nothing is deleted. You can resume it at any time.</p>
    <Field label="Reason" optional>{(id) => <input id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Waiting for designs" />}</Field>
  </Modal>;
}

function ReassignDialog({ a, onClose }: { a: Agent; onClose: () => void }) {
  const o = useOrg();
  const homes = o.projects.filter((p) => p.team.some((m) => m.id === a.id));
  const [from, setFrom] = useState(homes[0]?.key ?? "");
  const [to, setTo] = useState(homes[0]?.key ?? o.projects[0].key);
  const target = o.projects.find((p) => p.key === to)!;
  const lead = target.team.find((m) => m.reportsTo === "jay" && m.id !== a.id)?.id;
  const [boss, setBoss] = useState(lead ?? "jay");
  const leadsFrom = homes.find((p) => p.key === from)?.team.find((m) => m.id === a.id)?.reportsTo === "jay";
  const options = target.team.filter((m) => m.id !== a.id).map((m) => m.id);
  const err = boss === "jay" && lead ? `${o.agents.find((x) => x.id === lead)?.name} already leads ${target.name}.` : leadsFrom && from !== to ? `${a.name} leads ${homes.find((p) => p.key === from)?.name}. Choose a new lead there first (Edit that agent), or offboard with a handover.` : "";
  return <Modal title={`Reassign ${a.name}`} onClose={onClose} footer={<><button type="button" className="btn" onClick={onClose}>Cancel</button>
    <button type="button" className="btn btn-primary" disabled={!!err} onClick={() => { reassign(a.id, from, to, boss); notify(`${a.name} reassigned (mock).`); onClose(); }}>Reassign</button></>}>
    <div className="fld-grid">
      <Field label="From project">{(id) => <select id={id} value={from} onChange={(e) => setFrom(e.target.value)}>{homes.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}</select>}</Field>
      <Field label="To project">{(id) => <select id={id} value={to} onChange={(e) => { setTo(e.target.value); const p = o.projects.find((x) => x.key === e.target.value)!; setBoss(p.team.find((m) => m.reportsTo === "jay" && m.id !== a.id)?.id ?? "jay"); }}>
        {o.projects.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}</select>}</Field>
      <Field label="Reports to" error={err || undefined}>{(id) => <select id={id} value={boss} onChange={(e) => setBoss(e.target.value)}>
        <option value="jay">Jay (as project lead)</option>{options.map((m) => <option key={m} value={m}>{o.agents.find((x) => x.id === m)?.name}</option>)}</select>}</Field>
    </div>
    <p className="muted small">Its permissions in {target.name} are limited by {target.name}'s rules. Its open tasks stay with it.</p>
  </Modal>;
}

function OffboardDialog({ a, onClose }: { a: Agent; onClose: () => void }) {
  const o = useOrg();
  const open = o.tasks.filter((t) => t.owner === a.id && t.stage !== "Closed");
  const leads = o.projects.filter((p) => p.team.some((m) => m.id === a.id && m.reportsTo === "jay"));
  const candidates = o.agents.filter((x) => x.id !== a.id && x.life !== "offboarded");
  const [to, setTo] = useState(candidates[0]?.id ?? "");
  const [reason, setReason] = useState("");
  const [ok, setOk] = useState(false);
  const need = (open.length > 0 || leads.length > 0);
  return <Modal title={`Offboard ${a.name}?`} tone="bad" onClose={onClose} footer={<><button type="button" className="btn" data-autofocus onClick={onClose}>Keep {a.name}</button>
    <button type="button" className="btn btn-danger" disabled={!ok || (need && !to)} onClick={() => { offboard(a.id, need ? to : "", reason.trim()); notify(`${a.name} offboarded (mock). History kept under ID ${a.id}.`, "warn"); onClose(); }}>Offboard {a.name}</button></>}>
    <ul className="checks">
      <li>{a.name} can't be assigned new work. The ID <code>{a.id}</code> is retired and never reused.</li>
      <li>Everything it did stays attributed to it: tasks, decisions, reviews, messages, usage and the audit log.</li>
      <li>Its conversations are archived, not deleted.</li>
      {open.length > 0 && <li>{plural(open.length, "open task")} ({open.map((t) => t.key).join(", ")}) move to the agent you choose, with {a.name} kept as former owner.</li>}
      {leads.length > 0 && <li>It leads {leads.map((p) => p.name).join(", ")}. The handover agent becomes the lead there.</li>}
    </ul>
    <div className="fld-grid">
      {need && <Field label="Hand open work to">{(id) => <select id={id} value={to} onChange={(e) => setTo(e.target.value)}>{candidates.map((x) => <option key={x.id} value={x.id}>{x.name} · {x.role}</option>)}</select>}</Field>}
      <Field label="Reason" optional>{(id) => <input id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
    </div>
    <label className="toggle-row"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /><span>I understand {a.name} will stop working, and that this is recorded in the audit log.</span></label>
  </Modal>;
}

/** Effective permissions in each of its projects (agent ∩ project ∩ worker ∩ task mode). */
export function PermissionsReview({ a }: { a: Agent }) {
  const o = useOrg();
  const prof = currentProfile(a.id, o);
  const homes = o.projects.filter((p) => p.team.some((m) => m.id === a.id));
  const [pk, setPk] = useViewState("panel:agent", "permProject", homes[0]?.key ?? "");
  const p = homes.find((x) => x.key === pk) ?? homes[0];
  if (!p) return <p className="muted small">Not on any project team.</p>;
  const pp = projectProfile(p.key, o);
  const workers = prof.machines.filter((m) => p.machines.includes(m));
  const onboarding = pp.phase === "onboarding";
  return <div className="ai-perm">
    {homes.length > 1 && <div className="seg is-sm" role="tablist">{homes.map((h) => <button key={h.key} type="button" role="tab" aria-selected={h.key === p.key} onClick={() => setPk(h.key)}>{h.name}</button>)}</div>}
    <p className="muted small">In {p.name}: its permissions ∩ {p.name}'s rules ∩ {workers.map((w) => worker(w)?.label).join(", ") || "no eligible machine"} ∩ {TASK_MODES.find((m) => m.id === pp.taskMode)?.label} task mode{onboarding ? ". The project is in onboarding, so agents only observe." : "."}</p>
    {PERM_GROUPS.map((g) => <div key={g} className="ai-pg"><b>{g}</b><span>{PERMISSIONS.filter((x) => x.group === g).map((x) => {
      const r = onboarding && x.acts ? "deny" : effective(x.id, prof.grants, projectRules(pp.deploy), workers, pp.taskMode).result;
      return <span key={x.id} title={x.label}><GrantBadge g={r}>{x.label}</GrantBadge></span>; })}</span></div>)}
  </div>;
}

export function WorkHistory({ a }: { a: Agent }) {
  const o = useOrg();
  const tasks = o.tasks.filter((t) => t.owner === a.id || t.formerOwners?.includes(a.id));
  const events = o.audit.filter((e) => e.subject === a.id).slice().reverse();
  const versions = (o.profiles[a.id] ?? []).slice().reverse();
  return <div className="ai-hist2">
    <h4>Tasks</h4>
    {tasks.length ? <ul>{tasks.map((t) => <li key={t.key}><TaskKey k={t.key} /> <span className="ellip">{t.title}</span>{t.owner !== a.id && <small className="muted"> · handed to {o.agents.find((x) => x.id === t.owner)?.name}</small>}</li>)}</ul> : <p className="muted small">No tasks yet.</p>}
    <h4>Earlier sessions</h4>
    {(SESSION_HISTORY[a.id] ?? []).length ? <ul className="ai-hist">{SESSION_HISTORY[a.id].map((h) => <li key={h.session}><code>{h.session}</code><span>{modelLabel(h.model)}</span><span className="mono">{h.task}</span><small className="muted">{h.ended}</small></li>)}</ul>
      : <p className="muted small">No sessions yet.</p>}
    <h4>Config versions</h4>
    <ul>{versions.map((v) => <li key={v.version}><b>v{v.version}</b> <span>{modelLabel(v.model)}</span> <small className="muted">· {v.note} · {ago(Date.now() - v.at)}</small></li>)}</ul>
    <h4>Audit (prototype)</h4>
    {events.length ? <ul>{events.map((e) => <li key={e.id} className={cx("aud")}><small className="muted">{ago(Date.now() - e.at)} · Jay</small> {e.text}</li>)}</ul> : <p className="muted small">No changes recorded in this prototype yet.</p>}
  </div>;
}
