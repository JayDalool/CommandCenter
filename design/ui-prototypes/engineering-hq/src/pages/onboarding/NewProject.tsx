// NEW PROJECT — one shared flow, opened from Office, Teams, Topology and the project switcher.
// Every project starts in ONBOARDING / OBSERVATION. Its target operating mode applies only after the
// admission review and Jay's approval. MOCK ONLY: no repository is created, nothing is provisioned.
import { useState } from "react";
import { useViewState } from "../../data/live";
import { blankProjectDraft, createProject, keyFromName, missingFacts, prefixFromName, saveDraft, useOrg, type AgentDraft, type Org, type ProjectDraft } from "../../data/org";
import {
  AGENT_TEMPLATES, DEPLOY_PRESETS, ENVIRONMENTS, ENV_FACTS, ENV_FACT_LABEL, GRANT_LABEL, KNOWN_REPOS, MODEL_PRICE, ONBOARDING_STAGES, PROJECT_COLORS, PROJECT_ICONS,
  PROJECT_TYPES, PROVIDERS, TARGET_MODES, TASK_MODES, WORKERS, WORKER_CAP_LABEL, type DeployRules, type Grant,
} from "../../data/catalog";
import { MAX_TASK_MODE, scrubSecrets, validateAgent, validateProject, type Issue } from "../../data/validate";
import { modelLabel, type IconName } from "../../data/seed";
import { Icon } from "../../components/Icon";
import { Chips, Field, GrantBadge, GrantPick, Modal, Money, Seg } from "../../components/form";
import { Avatar, Pill, cx, plural } from "../../components/ui";
import { notify } from "../../windows/manager";
import { go } from "../../lib/router";
import { IssueList, Wizard, leavePopout, peekView, putView, showPage, type StepDef } from "./Wizard";
import { DraftAvatar, startPlannedAgent } from "./NewAgent";

export const PROJECT_VIEW = "page:newproject";
export const PSTEPS: StepDef[] = [
  { id: "identity", label: "Identity", icon: "layers", hint: "Name, key, ticket prefix, look and ownership." },
  { id: "repository", label: "Repository", icon: "branch", hint: "Connect an existing repository, or propose a new one for Jay to authorise." },
  { id: "environments", label: "Environments", icon: "cube", hint: "What exists today. Unknown facts can be discovered during onboarding." },
  { id: "workers", label: "Workers", icon: "server", hint: "Machines eligible to run this project's work." },
  { id: "team", label: "Team", icon: "users", hint: "A lead, existing agents, and new agents to plan." },
  { id: "profile", label: "Operating profile", icon: "shield", hint: "The target mode, and how tasks run by default." },
  { id: "budget", label: "Budgets", icon: "receipt", hint: "Cost warnings for the project. Warnings only." },
  { id: "deploy", label: "Deployment rules", icon: "rocket", hint: "Who may merge, deploy and touch production." },
  { id: "review", label: "Review", icon: "check", hint: "Check everything. Approving adds a mock project in Onboarding." },
];

export function startNewProject() {
  const cur = peekView<ProjectDraft>(PROJECT_VIEW, "draft");
  if (!cur || !cur.touched) putView(PROJECT_VIEW, "draft", blankProjectDraft());
  showPage("newproject");
}

/** The lifecycle every new project goes through. `at` is the current stage index. */
export function Lifecycle({ at = 1, compact }: { at?: number; compact?: boolean }) {
  return <ol className={cx("life", compact && "is-compact")} aria-label="Project lifecycle">{ONBOARDING_STAGES.map((s, i) =>
    <li key={s} className={cx(i < at && "is-done", i === at && "is-now")}><span>{i < at ? <Icon name="tick" size={11} stroke={2.6} /> : i + 1}</span><b>{s}</b></li>)}</ol>;
}

export function NewProject() {
  const o = useOrg();
  const [stored, setStored] = useViewState<ProjectDraft | null>(PROJECT_VIEW, "draft", null);
  const [approving, setApproving] = useState(false);
  const d = stored ?? blankProjectDraft();
  const set = (p: Partial<ProjectDraft>) => { const { value, hit } = scrubSecrets({ ...d, ...p, touched: true }); if (hit) notify("That looked like a token or password, so it was removed. Never paste secrets here.", "bad"); setStored(value); };
  const setStep = (i: number) => setStored({ ...d, step: Math.max(0, Math.min(PSTEPS.length - 1, i)) });
  const agentCheck = (a: AgentDraft) => validateAgent(a, o, { key: d.key, name: d.name, repo: d.repo, workers: d.workers, type: d.type, deploy: d.deploy, taskMode: d.taskMode,
    members: [d.lead, ...d.members].filter(Boolean), planned: d.planned.filter((x) => x.id !== a.id) });
  const result = validateProject(d, o, agentCheck);
  const goTo = (id: string) => setStep(PSTEPS.findIndex((s) => s.id === id));
  const applyFix = (i: Issue) => { if (i.fix) setStored({ ...i.fix.apply(d), touched: true }); };
  const approve = () => {
    if (validateProject(d, o, agentCheck).errors.length) return;
    createProject(d);
    notify(`${d.name} created in Onboarding / Observation (mock). No repository, infrastructure or credentials were created.`);
    setApproving(false); setStored(null);
    const plan = peekView<AgentDraft>("page:onboard", "draft"); if (plan?.mode === "plan") putView("page:onboard", "draft", null);
    go("teams", d.key); leavePopout(PROJECT_VIEW);
  };
  return <Wizard viewId={PROJECT_VIEW} title={<>New <em>Project</em></>} sub="Every project starts in Onboarding / Observation. Its operating mode applies only after an admission review and your approval."
    steps={PSTEPS} step={d.step} setStep={setStep} result={result} dirty={d.touched}
    onSave={() => { const id = saveDraft(d); setStored({ ...d, savedId: id, touched: false }); notify("Draft saved. Resume it any time from Agents → Drafts."); }}
    onCancelConfirmed={() => { setStored(null); const plan = peekView<AgentDraft>("page:onboard", "draft"); if (plan?.mode === "plan") putView("page:onboard", "draft", null); go("teams"); leavePopout(PROJECT_VIEW); }}
    approve={{ label: "Approve Mock Project", run: () => setApproving(true) }}
    preview={<ProjectPreview d={d} o={o} />}>
    {d.step === 0 && <IdentityStep d={d} set={set} o={o} />}
    {d.step === 1 && <RepoStep d={d} set={set} o={o} />}
    {d.step === 2 && <EnvStep d={d} set={set} />}
    {d.step === 3 && <WorkerStep d={d} set={set} />}
    {d.step === 4 && <TeamStep d={d} set={set} o={o} agentCheck={agentCheck} />}
    {d.step === 5 && <ProfileStep d={d} set={set} />}
    {d.step === 6 && <BudgetStep d={d} set={set} />}
    {d.step === 7 && <DeployStep d={d} set={set} />}
    {d.step === 8 && <ReviewStep d={d} o={o} errors={result.errors} warnings={result.warnings} goTo={goTo} applyFix={applyFix} />}
    {approving && <Modal title={`Approve ${d.name} as a mock project?`} onClose={() => setApproving(false)}
      footer={<><button type="button" className="btn" onClick={() => setApproving(false)}>Not yet</button>
        <button type="button" className="btn btn-primary" onClick={approve}><Icon name="shield" size={15} /> Approve Mock Project</button></>}>
      <ul className="checks">
        <li>Adds {d.name} ({d.prefix}) to this prototype in <b>Onboarding / Observation</b>. Agents may only observe until you approve its operating profile.</li>
        <li>{d.repoMode === "existing" ? `Records ${d.repo} as its repository. Nothing on GitHub changes.` : `Records ${d.repo} as a proposed repository. It is not created; a “Needs Jay” task asks for that separately.`}</li>
        {d.planned.length > 0 && <li>Adds {plural(d.planned.length, "planned agent")} ({d.planned.map((a) => a.name).join(", ")}), each Not started.</li>}
        <li>No infrastructure, credentials, policies or ccd records are created.</li>
      </ul>
    </Modal>}
  </Wizard>;
}

function ProjectPreview({ d, o }: { d: ProjectDraft; o: Org }) {
  const lead = o.agents.find((a) => a.id === d.lead) ?? d.planned.find((a) => a.id === d.lead);
  const team = [...new Set([d.lead, ...d.members, ...d.planned.map((a) => a.id)].filter(Boolean))];
  return <div className="pv-card">
    <small className="pv-k">Project charter</small>
    <div className="pv-id"><span className="pj-ico" style={{ width: 54, height: 54, ["--c" as string]: d.color }}><Icon name={d.icon} size={30} stroke={2} /></span>
      <div><b>{d.name || "Unnamed project"}</b><span>{PROJECT_TYPES.find((t) => t.id === d.type)?.label}</span><code>{d.key || "key"} · {d.prefix || "PFX"}-001</code></div></div>
    <dl className="pv-kv">
      <dt>Repository</dt><dd className="mono">{d.repo || "—"}{d.repoMode === "proposed" && <Pill tone="warn">Proposed</Pill>}</dd>
      <dt>Lead</dt><dd>{lead ? lead.name : <span className="t-warn">None yet</span>}</dd>
      <dt>Team</dt><dd>{plural(team.length, "agent")}{d.planned.length > 0 && ` (${d.planned.length} planned)`}</dd>
      <dt>Starts in</dt><dd><Pill tone="info" dot>Onboarding · observe only</Pill></dd>
      <dt>Target mode</dt><dd>{TARGET_MODES.find((m) => m.id === d.target)?.label} <small className="muted">after approval</small></dd>
      <dt>Task mode</dt><dd>{TASK_MODES.find((m) => m.id === d.taskMode)?.label}</dd>
    </dl>
    <Lifecycle at={1} compact />
  </div>;
}

// ---------------------------------------------------------------- steps
function errOf(d: ProjectDraft, o: Org, step: string, field: string) { return validateProject(d, o).errors.find((e) => e.step === step && e.field === field)?.msg; }

function IdentityStep({ d, set, o }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void; o: Org }) {
  const used = new Set(o.projects.map((p) => p.color.toLowerCase()));
  return <div className="fld-grid">
    <Field label="Project name" error={errOf(d, o, "identity", "name")}>{(id) => <input id={id} value={d.name} maxLength={40} placeholder="e.g. Listing Scraper" autoComplete="off"
      onChange={(e) => set({ name: e.target.value, key: d.keyTouched ? d.key : keyFromName(e.target.value), prefix: d.prefixTouched ? d.prefix : prefixFromName(e.target.value) })} />}</Field>
    <Field label="Ownership" hint={PROJECT_TYPES.find((t) => t.id === d.type)?.hint}>{(id) => <select id={id} value={d.type} onChange={(e) => {
      const type = e.target.value as ProjectDraft["type"]; set({ type, workers: type === "employer" ? d.workers.filter((w) => w !== "server") : d.workers, visibility: type === "personal" || type === "infra" ? d.visibility : "private",
        target: type === "employer" && !["restricted", "controlled_production", "paused"].includes(d.target) ? "restricted" : d.target }); }}>
      {PROJECT_TYPES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</select>}</Field>
    <Field label="Key" error={errOf(d, o, "identity", "key")} hint="Permanent. Used in links and records.">{(id) => <input id={id} className="mono" value={d.key} maxLength={24} onChange={(e) => set({ key: e.target.value.toLowerCase().trim(), keyTouched: true })} />}</Field>
    <Field label="Ticket prefix" error={errOf(d, o, "identity", "prefix")} hint={d.prefix ? `Tasks will look like ${d.prefix}-001.` : undefined}>{(id) => <input id={id} className="mono" value={d.prefix} maxLength={5} onChange={(e) => set({ prefix: e.target.value.toUpperCase().trim(), prefixTouched: true })} />}</Field>
    <Field label="Description" wide optional>{(id) => <textarea id={id} rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} />}</Field>
    <Field label="Icon">{() => <div className="glyphs" role="radiogroup" aria-label="Icon">{PROJECT_ICONS.map((g) => <button key={g} type="button" role="radio" aria-checked={d.icon === g} aria-label={g} onClick={() => set({ icon: g as IconName })}><Icon name={g} size={18} stroke={2} /></button>)}</div>}</Field>
    <Field label="Colour" hint="Used for this project on every page. Colours already taken are hidden.">{() => <div className="swatches" role="radiogroup" aria-label="Colour">{PROJECT_COLORS.filter((c) => !used.has(c)).map((c) =>
      <button key={c} type="button" role="radio" aria-checked={d.color === c} aria-label={`Colour ${c}`} style={{ background: c }} onClick={() => set({ color: c })} />)}</div>}</Field>
  </div>;
}

function RepoStep({ d, set, o }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void; o: Org }) {
  const bound = new Set(o.projects.map((p) => p.repo.toLowerCase()));
  return <>
    <Seg label="Repository source" value={d.repoMode} onChange={(v) => set({ repoMode: v, repo: v === "proposed" && !d.repo ? `JayDalool/${d.key || "new-project"}` : d.repo })}
      options={[{ id: "existing", label: <><Icon name="plug" size={14} /> Connect an existing repository</> }, { id: "proposed", label: <><Icon name="plus" size={14} /> Propose a new repository</> }]} />
    {d.repoMode === "proposed" && <p className="callout t-warn"><Icon name="lock" size={15} /> <span><b>Requires Jay's authorisation.</b> CommandCenter never creates repositories from this wizard. Approving the project adds a “Needs Jay” task to create it.</span></p>}
    <div className="fld-grid">
      <Field label="Provider">{() => <Seg label="Provider" value="github" options={[{ id: "github", label: "GitHub" }]} onChange={() => {}} />}</Field>
      <Field label={d.repoMode === "existing" ? "Repository (owner/name)" : "Proposed name (owner/name)"} error={errOf(d, o, "repository", "repo")}>{(id) => <>
        <input id={id} className="mono" list={d.repoMode === "existing" ? "known-repos" : undefined} value={d.repo} placeholder="JayDalool/project" autoComplete="off" onChange={(e) => set({ repo: e.target.value })} />
        <datalist id="known-repos">{KNOWN_REPOS.filter((r) => !bound.has(r.toLowerCase())).map((r) => <option key={r} value={r} />)}</datalist></>}</Field>
      <Field label="Default branch" error={errOf(d, o, "repository", "branch")}>{(id) => <input id={id} className="mono" value={d.branch} onChange={(e) => set({ branch: e.target.value })} />}</Field>
      <Field label="Visibility" error={errOf(d, o, "repository", "visibility")}>{() => <Seg label="Visibility" value={d.visibility} onChange={(v) => set({ visibility: v })}
        options={[{ id: "private", label: <><Icon name="lock" size={13} /> Private</> }, { id: "public", label: "Public", disabled: d.type === "client" || d.type === "employer" }]} />}</Field>
      <Field label="Local clone location" optional error={errOf(d, o, "repository", "clone")} hint="On the worker. Recorded only; nothing is cloned.">{(id) => <input id={id} className="mono" value={d.clone} onChange={(e) => set({ clone: e.target.value })} />}</Field>
    </div>
    {d.repoMode === "existing" && <p className="muted small">Suggestions are repositories the GitHub app can already see and that no project uses. Connecting records the binding only.</p>}
  </>;
}

function EnvStep({ d, set }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void }) {
  const [open, setOpen] = useViewState<string[]>(PROJECT_VIEW, "envOpen", []);
  const r = validateProject(d, useOrg());
  return <>
    <label className="toggle-row"><input type="checkbox" checked={d.discover} onChange={(e) => set({ discover: e.target.checked })} />
      <span><b>Let CommandCenter discover the rest during onboarding</b><small className="muted">Proposed in D-024: the fingerprint and first audit fill in hosting, domains and health checks, read-only. You confirm them in the admission review.</small></span></label>
    <div className="env-list">{ENVIRONMENTS.map((e) => { const c = d.envs[e]; const isOpen = open.includes(e); const err = r.errors.find((x) => x.step === "environments" && x.field === e)?.msg;
      return <section key={e} className={cx("env", c.on && "is-on", err && "has-err")}>
        <header><label><input type="checkbox" checked={c.on} onChange={(ev) => set({ envs: { ...d.envs, [e]: { ...c, on: ev.target.checked } } })} /><b>{e}</b></label>
          {e === "Production" && c.on && <Pill tone="warn"><Icon name="shield" size={12} /> Protected</Pill>}<span className="sp" />
          {c.on && <button type="button" className="link" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? open.filter((x) => x !== e) : [...open, e])}>{isOpen ? "Hide details" : "Add details"} <Icon name={isOpen ? "chevdown" : "chevron"} size={12} /></button>}</header>
        {err && <p className="fld-err"><Icon name="info" size={13} /> {err}</p>}
        {c.on && isOpen && <div className="fld-grid">{ENV_FACTS.map((f) => <Field key={f} label={ENV_FACT_LABEL[f]} optional>{(id) =>
          <input id={id} value={c[f]} placeholder={d.discover ? "Discover during onboarding" : ""} onChange={(ev) => set({ envs: { ...d.envs, [e]: { ...c, [f]: ev.target.value } } })} />}</Field>)}</div>}
      </section>; })}</div>
  </>;
}

function WorkerStep({ d, set }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void }) {
  return <>
    <div className="worker-grid">{WORKERS.map((w) => { const on = d.workers.includes(w.id); const blocked = d.type === "employer" && w.id === "server";
      return <button key={w.id} type="button" className={cx("worker", on && "is-on", blocked && "is-off")} aria-pressed={on} disabled={blocked && !on}
        onClick={() => set({ workers: on ? d.workers.filter((x) => x !== w.id) : [...d.workers, w.id] })}>
        <span className="worker-h"><Icon name={w.id === "server" ? "server" : "laptop"} size={18} /><b>{w.label}</b><Pill tone={w.status === "online" ? "ok" : "idle"} dot>{w.status === "online" ? "Online" : "Unknown"}</Pill></span>
        <span className="worker-caps">{w.caps.map((c) => <small key={c}>{WORKER_CAP_LABEL[c]}</small>)}</span>
        <small className={blocked || !w.agentNode ? "t-warn" : "muted"}>{blocked ? "Employer projects may not use jay-server." : w.note}</small></button>; })}
      <div className="worker is-future"><span className="worker-h"><Icon name="plus" size={18} /><b>Future WorkerNodes</b></span><small className="muted">Added by Jay through WorkerNode registration, not from here.</small></div></div>
    <p className="callout"><Icon name="info" size={15} /> Making a machine eligible doesn't grant any agent its capabilities. Each agent still needs its own permission, and the task mode still applies.</p>
  </>;
}

function TeamStep({ d, set, o, agentCheck }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void; o: Org; agentCheck: (a: AgentDraft) => { errors: Issue[] } }) {
  const active = o.agents.filter((a) => a.life !== "offboarded");
  const roster = [...new Set([d.lead, ...d.members].filter(Boolean))];
  const covered = new Set([...d.planned.map((a) => a.template), ...roster.map((id) => o.agents.find((a) => a.id === id)?.template ?? ({ claude: "lead", iris: "research", nova: "impl", atlas: "reviewer", pixel: "ui", orion: "devops" } as Record<string, string>)[id])]);
  const plan = (tpl: string, existing?: AgentDraft) => { setStoredNow({ ...d, touched: true }); startPlannedAgent(tpl, d, existing); };
  const setStoredNow = (x: ProjectDraft) => putView(PROJECT_VIEW, "draft", x);
  return <>
    <div className="fld-grid">
      <Field label="Project lead" hint="The lead reports to Jay and coordinates the team.">{(id) => <select id={id} value={d.lead} onChange={(e) => set({ lead: e.target.value, members: d.members.filter((m) => m !== e.target.value) })}>
        <option value="">No lead yet</option>{active.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.role}{a.life === "paused" ? " (paused)" : ""}</option>)}
        {d.planned.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.title} (planned)</option>)}</select>}</Field>
    </div>
    <Field label="Assign existing agents" wide hint="They join this project's team as well. Their permissions here are limited by this project's rules.">{() =>
      <Chips label="Assign existing agents" value={d.members} onChange={(v) => set({ members: v.filter((x) => x !== d.lead) })}
        options={active.filter((a) => a.id !== d.lead).map((a) => ({ id: a.id, label: <><Avatar id={a.id} size={18} /> {a.name}</> }))} />}</Field>
    {d.planned.length > 0 && <><h3 className="wz-sub">Planned new agents</h3><ul className="planned">{d.planned.map((a) => { const bad = agentCheck(a).errors[0];
      return <li key={a.id}><DraftAvatar color={a.color} glyph={a.glyph} size={34} /><span><b>{a.name}</b><small>{a.title} · {modelLabel(a.model)}</small>{bad && <small className="t-bad">{bad.msg}</small>}</span>
        <Pill tone="info">Planned</Pill><span className="sp" /><button type="button" className="btn btn-sm" onClick={() => plan(a.template, a)}>Edit</button>
        <button type="button" className="btn btn-sm" onClick={() => set({ planned: d.planned.filter((x) => x.id !== a.id), lead: d.lead === a.id ? "" : d.lead })}>Remove</button></li>; })}</ul></>}
    <h3 className="wz-sub">Suggested roles</h3>
    <div className="sugg">{AGENT_TEMPLATES.filter((t) => t.core).map((t) => { const have = covered.has(t.id);
      return <div key={t.id} className={cx("sugg-i", have && "is-have")}><DraftAvatar color={t.color} glyph={t.glyph} size={30} /><span><b>{t.title}</b><small>{have ? "Covered" : t.blurb}</small></span>
        {!have && <button type="button" className="btn btn-sm" onClick={() => plan(t.id)}><Icon name="plus" size={13} /> Plan a new agent</button>}</div>; })}
      <div className="sugg-i"><DraftAvatar color="#5d6a85" glyph="gear" size={30} /><span><b>Other role</b><small>Specialist or custom</small></span><button type="button" className="btn btn-sm" onClick={() => plan("")}><Icon name="plus" size={13} /> Plan a new agent</button></div>
    </div>
    <p className="muted small">Planning an agent opens the New Agent flow. Your project draft is kept; you come back here after.</p>
  </>;
}

function ProfileStep({ d, set }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void }) {
  const allowed = (id: string) => d.type !== "employer" || ["restricted", "controlled_production", "paused"].includes(id);
  const R = { manual: 0, assisted: 1, autonomous: 2 } as const;
  return <>
    <div className="onb-banner"><Icon name="eye" size={22} /><div><b>Starts in Onboarding / Observation</b><p>Whatever you choose below, agents only observe this project at first. The target mode applies after the fingerprint, first audit and admission review, and only when you approve it.</p></div></div>
    <Lifecycle at={1} />
    <Field label="Target operating mode" wide hint="Applies only after admission review and your approval.">{() => <div className="mode-grid" role="radiogroup" aria-label="Target operating mode">{TARGET_MODES.map((m) =>
      <button key={m.id} type="button" role="radio" aria-checked={d.target === m.id} disabled={!allowed(m.id)} className={cx("mode-card", d.target === m.id && "is-on")}
        onClick={() => set({ target: m.id, taskMode: R[d.taskMode] > R[MAX_TASK_MODE[m.id]] ? MAX_TASK_MODE[m.id] : d.taskMode })}>
        <b>{m.label}</b><small>{allowed(m.id) ? m.hint : "Not available for employer projects."}</small></button>)}</div>}</Field>
    <Field label="Default task execution mode" wide hint="A task can be made more restrictive than this, never more permissive.">{() => <div className="mode-grid is-3" role="radiogroup" aria-label="Default task execution mode">{TASK_MODES.map((m) => { const over = R[m.id] > R[MAX_TASK_MODE[d.target]];
      return <button key={m.id} type="button" role="radio" aria-checked={d.taskMode === m.id} disabled={over} className={cx("mode-card", d.taskMode === m.id && "is-on")} onClick={() => set({ taskMode: m.id })}>
        <b>{m.label}</b><small>{over ? `Not allowed with a ${TARGET_MODES.find((x) => x.id === d.target)?.label} target.` : m.hint}</small></button>; })}</div>}</Field>
  </>;
}

function BudgetStep({ d, set }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void }) {
  const b = d.budget; const sb = (p: Partial<typeof b>) => set({ budget: { ...b, ...p } });
  return <>
    <p className="callout t-warn"><Icon name="info" size={15} /> Warnings only. Nothing here is enforced by the prototype or by ccd today.</p>
    <div className="fld-grid">
      <Field label="Monthly AI cost warning">{(id) => <Money id={id} label="Monthly AI cost warning" v={b.monthlyWarnUsd} onChange={(v) => sb({ monthlyWarnUsd: v })} />}</Field>
      <Field label="Per-task cost warning">{(id) => <Money id={id} label="Per-task cost warning" v={b.costWarnUsd} onChange={(v) => sb({ costWarnUsd: v })} />}</Field>
      <Field label="Monthly infrastructure warning">{(id) => <Money id={id} label="Infrastructure warning" v={b.infraWarnUsd} onChange={(v) => sb({ infraWarnUsd: v })} />}</Field>
      <Field label="Maximum parallel agents">{(id) => <input id={id} type="number" min={1} max={12} value={b.maxParallelAgents} onChange={(e) => sb({ maxParallelAgents: Number(e.target.value) })} />}</Field>
      <Field label="Preferred model">{(id) => <select id={id} value={b.preferredModel} onChange={(e) => sb({ preferredModel: e.target.value })}>{PROVIDERS.flatMap((p) => p.models).map((m) =>
        <option key={m} value={m}>{modelLabel(m)} · ${MODEL_PRICE[m][0]}/${MODEL_PRICE[m][1]} per M</option>)}</select>}</Field>
      <Field label="Paid tools and APIs">{() => <GrantPick label="Paid tools and APIs" value={b.paidTools} ceiling="approval" limit="Paid tools always need Jay's approval." onChange={(v) => sb({ paidTools: v })} />}</Field>
    </div>
  </>;
}

const RULES: { id: keyof Omit<DeployRules, "preset" | "windows" | "tz" | "reviewers">; label: string; ceiling: Grant; note?: string }[] = [
  { id: "merge", label: "Merge pull requests", ceiling: "approval", note: "Jay merges every PR in a new project." },
  { id: "deploy", label: "Deploy", ceiling: "approval" },
  { id: "prodWrite", label: "Write to production", ceiling: "approval" },
  { id: "migrations", label: "Database migrations", ceiling: "approval" },
  { id: "downtime", label: "Changes that need downtime", ceiling: "approval" },
  { id: "browserProd", label: "Production changes through a browser", ceiling: "deny", note: "Never available to agents." },
  { id: "database", label: "Production database access", ceiling: "deny", note: "Never available to agents." },
];
function DeployStep({ d, set }: { d: ProjectDraft; set: (p: Partial<ProjectDraft>) => void }) {
  const [adv, setAdv] = useViewState(PROJECT_VIEW, "deployAdv", false);
  const r = d.deploy; const sr = (p: Partial<DeployRules>) => set({ deploy: { ...r, ...p, preset: "preset" in p ? p.preset! : "custom" } });
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return <>
    <div className="mode-grid is-3" role="radiogroup" aria-label="Preset">{(["strict", "standard", "custom"] as const).map((p) =>
      <button key={p} type="button" role="radio" aria-checked={r.preset === p} className={cx("mode-card", r.preset === p && "is-on")}
        onClick={() => (p === "custom" ? (sr({ preset: "custom" }), setAdv(true)) : set({ deploy: { ...r, ...DEPLOY_PRESETS[p], preset: p } }))}>
        <b>{p === "strict" ? "Strict" : p === "standard" ? "Standard" : "Custom"}</b>
        <small>{p === "strict" ? "Agents never deploy or migrate. Two reviewers." : p === "standard" ? "Deploys, migrations and downtime need Jay. One reviewer." : "Set each rule yourself."}</small></button>)}</div>
    <ul className="rule-sum">{RULES.map((x) => <li key={x.id}><span>{x.label}</span><GrantBadge g={r[x.id]} /></li>)}<li><span>Required reviewers</span><b>{r.reviewers}</b></li>
      <li><span>Release windows</span><b>{r.windows.length ? r.windows.join(", ") : "None"}</b></li></ul>
    <button type="button" className="ai-expand" aria-expanded={adv} onClick={() => setAdv(!adv)}><Icon name={adv ? "chevdown" : "chevron"} size={14} /> Advanced rules</button>
    {adv && <div className="adv">
      <ul className="perm-rows">{RULES.map((x) => <li key={x.id}><span><b>{x.label}</b>{x.note && <small className="muted"><Icon name="lock" size={11} /> {x.note}</small>}</span>
        <GrantPick label={x.label} value={r[x.id]} ceiling={x.ceiling} limit={x.note ?? "Needs Jay's approval at most"} onChange={(v) => sr({ [x.id]: v })} /></li>)}</ul>
      <div className="fld-grid">
        <Field label="Required reviewers">{(id) => <input id={id} type="number" min={0} max={3} value={r.reviewers} onChange={(e) => sr({ reviewers: Number(e.target.value) })} />}</Field>
        <Field label={`Release windows (${r.tz})`} hint="01:00 on the chosen days.">{() => <Chips label="Release windows" value={r.windows.map((w) => w.slice(0, 3))} onChange={(v) => sr({ windows: DAYS.filter((x) => v.includes(x)).map((x) => `${x} 01:00`) })}
          options={DAYS.map((x) => ({ id: x, label: x }))} />}</Field>
      </div></div>}
    <p className="muted small">{GRANT_LABEL.approval} means Jay approves each use, in the Decision Room.</p>
  </>;
}

function ReviewStep({ d, o, errors, warnings, goTo, applyFix }: { d: ProjectDraft; o: Org; errors: Issue[]; warnings: Issue[]; goTo: (s: string) => void; applyFix: (i: Issue) => void }) {
  const sec = (title: string, step: string, body: React.ReactNode) => <section className="rv-sec"><h4>{title}<span className="sp" /><button type="button" className="link" onClick={() => goTo(step)}>Edit</button></h4>{body}</section>;
  const name = (id: string) => o.agents.find((a) => a.id === id)?.name ?? d.planned.find((a) => a.id === id)?.name ?? id;
  const missing = missingFacts(d);
  return <>
    <IssueList errors={errors} warnings={warnings} goTo={goTo} steps={PSTEPS} applyFix={applyFix} />
    <div className="onb-banner"><Icon name="eye" size={22} /><div><b>Initial state: ONBOARDING / OBSERVATION</b><p>Target {TARGET_MODES.find((m) => m.id === d.target)?.label} applies only after admission review and your approval.</p></div></div>
    <Lifecycle at={1} />
    <div className="rv-grid">
      {sec("Project", "identity", <dl className="kv"><dt>Name</dt><dd>{d.name || "—"}</dd><dt>Key / prefix</dt><dd><code>{d.key}</code> · <code>{d.prefix}</code></dd><dt>Ownership</dt><dd>{PROJECT_TYPES.find((t) => t.id === d.type)?.label}</dd></dl>)}
      {sec("Repository", "repository", <dl className="kv"><dt>{d.repoMode === "existing" ? "Connect" : "Propose"}</dt><dd className="mono">{d.repo || "—"}</dd><dt>Branch</dt><dd className="mono">{d.branch}</dd><dt>Visibility</dt><dd>{d.visibility}</dd>
        {d.repoMode === "proposed" && <><dt>Status</dt><dd className="t-warn">Requires Jay authorisation</dd></>}</dl>)}
      {sec("Environments", "environments", <p>{ENVIRONMENTS.filter((e) => d.envs[e].on).join(" · ") || "None"}{d.discover && <small className="muted"> · rest discovered during onboarding</small>}</p>)}
      {sec("Workers", "workers", <p>{d.workers.map((w) => WORKERS.find((x) => x.id === w)?.label).join(", ") || "None"}</p>)}
      {sec("Team", "team", <dl className="kv"><dt>Lead</dt><dd>{d.lead ? name(d.lead) : <span className="t-warn">None</span>}</dd><dt>Existing</dt><dd>{d.members.map(name).join(", ") || "None"}</dd><dt>Planned</dt><dd>{d.planned.map((a) => a.name).join(", ") || "None"}</dd></dl>)}
      {sec("Operating profile", "profile", <dl className="kv"><dt>Now</dt><dd>Onboarding · observe only</dd><dt>Target</dt><dd>{TARGET_MODES.find((m) => m.id === d.target)?.label}</dd><dt>Task mode</dt><dd>{TASK_MODES.find((m) => m.id === d.taskMode)?.label}</dd></dl>)}
      {sec("Deployment rules", "deploy", <ul className="rule-sum">{RULES.slice(0, 4).map((x) => <li key={x.id}><span>{x.label}</span><GrantBadge g={d.deploy[x.id]} /></li>)}<li><span>Reviewers</span><b>{d.deploy.reviewers}</b></li></ul>)}
      {sec("Budget (warnings only)", "budget", <dl className="kv"><dt>Monthly</dt><dd>${d.budget.monthlyWarnUsd}</dd><dt>Per task</dt><dd>${d.budget.costWarnUsd}</dd><dt>Parallel agents</dt><dd>{d.budget.maxParallelAgents}</dd></dl>)}
      <section className="rv-sec rv-risk"><h4><Icon name="shield" size={15} /> Security and unknowns</h4><ul>
        <li>No repository, runner, DNS, hosting or secret is created.</li><li>Agents can't promote the project out of onboarding. Only Jay can.</li>
        {d.type === "employer" && <li>Employer project: kept off jay-server, restricted modes only.</li>}
        {missing.length ? missing.map((m) => <li key={m} className="t-warn">Unknown: {m}</li>) : <li>No missing facts recorded.</li>}</ul></section>
    </div>
  </>;
}
