// NEW AGENT — guided onboarding: template → identity → intelligence → organisation → capabilities →
// access → permissions → instructions → budget → review. Also used to edit an agent (same steps).
// MOCK ONLY: approving adds the agent to the prototype's organisation store. No credentials, sessions,
// policies or ccd records are created.
import { useState } from "react";
import { useViewState } from "../../data/live";
import { useOrg, activateAgent, agentDraftFrom, agentDraftOf, blankAgentDraft, idFromName, projectProfile, saveDraft, updateAgent, type AgentDraft, type Org, type ProjectDraft } from "../../data/org";
import {
  AGENT_COLORS, AGENT_TEMPLATES, AVATAR_GLYPHS, CUSTOM_TEMPLATE, GRANT_LABEL, HARD_NEVER, INSTRUCTION_FIELDS, MCP_SERVERS, MODEL_PRICE, MODEL_TIER, PERMISSIONS, PERM_GROUPS,
  PROVIDERS, REASONING, SKILLS, TASK_MODES, TOOLS, WORKERS, WORKER_CAP_LABEL, effective, projectRules, templateOf, worker,
  type AgentTemplate, type Grant, type Grants, type TaskMode,
} from "../../data/catalog";
import { validateAgent, capabilitySentences, scrubSecrets, type DraftProjectCtx, type Issue } from "../../data/validate";
import { MODELS, modelLabel, type IconName } from "../../data/seed";
import { Icon } from "../../components/Icon";
import { Chips, Field, GrantBadge, GrantPick, Modal, Money, Seg } from "../../components/form";
import { Pill, cx, plural } from "../../components/ui";
import { useOpenAgent } from "../../components/agent";
import { notify } from "../../windows/manager";
import { go } from "../../lib/router";
import { Hierarchy, IssueList, Wizard, leavePopout, peekView, putView, showPage, type StepDef } from "./Wizard";

export const AGENT_VIEW = "page:onboard";
export const STEPS: StepDef[] = [
  { id: "template", label: "Template", icon: "layers", hint: "Start from a proven role, or from a safe blank." },
  { id: "identity", label: "Identity", icon: "users", hint: "How Jay and the team will know this agent." },
  { id: "intelligence", label: "Intelligence", icon: "cpu", hint: "The model behind the persona. The persona stays when the model changes." },
  { id: "organization", label: "Organisation", icon: "graph", hint: "Which project it serves, whom it reports to and whom it supervises." },
  { id: "capabilities", label: "Skills & tools", icon: "wrench", hint: "What it knows how to do, and what it is authorised to use." },
  { id: "access", label: "Repos & machines", icon: "server", hint: "Where it may work. Identity, machine and permission are separate things." },
  { id: "permissions", label: "Permissions", icon: "shield", hint: "Allowed, needs approval, or denied. Some limits can never be changed here." },
  { id: "instructions", label: "Instructions", icon: "doc", hint: "Its mission and working rules. Mock text only." },
  { id: "budget", label: "Budget", icon: "receipt", hint: "Cost warnings. They warn; the prototype cannot enforce them." },
  { id: "review", label: "Review & activate", icon: "check", hint: "Check everything, then approve. Approving only changes this prototype." },
];
export const STAGES = ["Coordinates", "1. Plan", "2. Build", "3. Review", "4. Test", "5. Verify"];
const SECONDARY = ["Release notes", "On-call triage", "Documentation", "Mentors new agents", "Dependency updates", "Accessibility checks"];

// ---------------------------------------------------------------- entry points
/** Open the New Agent wizard. Resumes an unfinished new-agent draft if there is one. */
export function startNewAgent(project?: string, template?: string) {
  const cur = peekView<AgentDraft>(AGENT_VIEW, "draft");
  if (cur && cur.touched && cur.mode !== "new") keepUnfinished();   // an unsaved edit or plan is saved, never dropped
  if (!(cur && cur.mode === "new" && cur.touched)) {
    const d = template ? agentDraftFrom(template, project ?? "samvision") : blankAgentDraft(project ?? "samvision");
    putView(AGENT_VIEW, "draft", { ...d, step: template ? 1 : 0 });
  }
  showPage("onboard");
}
/** Edit an existing agent, optionally at one step (Change model → Intelligence). */
export function startAgentEdit(id: string, stepId?: string) {
  keepUnfinished();
  const d = agentDraftOf(id);
  putView(AGENT_VIEW, "draft", { ...d, step: Math.max(1, STEPS.findIndex((s) => s.id === stepId)) });
  showPage("onboard");
}
/** "Plan a new agent" from the New Project wizard: the agent joins the project draft, not the organisation. */
export function startPlannedAgent(template: string, p: ProjectDraft, existing?: AgentDraft) {
  keepUnfinished();
  const base = existing ?? { ...agentDraftFrom(template, p.key, "plan"), reportsTo: template === "lead" ? "jay" : p.lead || "jay", repos: p.repo ? [p.repo] : [], machines: [...p.workers] };
  putView(AGENT_VIEW, "draft", { ...base, mode: "plan", project: p.key, step: existing ? 1 : template ? 1 : 0 });
  showPage("onboard");
}
function keepUnfinished() {
  const cur = peekView<AgentDraft>(AGENT_VIEW, "draft");
  if (cur && cur.touched) { saveDraft(cur); notify(`Your unfinished agent “${cur.name || "Untitled"}” was saved to Drafts.`, "warn"); }
}

// ---------------------------------------------------------------- helpers
export function DraftAvatar({ color, glyph, size = 40 }: { color: string; glyph: string; size?: number }) {
  return <span className="av" style={{ width: size, height: size, ["--c" as string]: color }}><Icon name={glyph} size={size * 0.56} stroke={2} /></span>;
}
const tierLabel = (m: string) => ({ frontier: "Frontier", balanced: "Balanced", fast: "Fast" })[MODEL_TIER[m] ?? "balanced"];
export function grantSummary(g: Grants) {
  const n = { allow: 0, approval: 0, deny: 0 };
  for (const p of PERMISSIONS) n[g[p.id] ?? "deny"]++;
  return n;
}
function typicalPerms(t: AgentTemplate) {
  const g = t.config.grants;
  const on = PERMISSIONS.filter((p) => g[p.id] === "allow" && p.group === "Repository").map((p) => p.label.replace(/ .*/, "").toLowerCase());
  const appr = PERMISSIONS.filter((p) => g[p.id] === "approval").length;
  return `${on.length ? on.join(", ") : "read-only"}${appr ? ` · ${appr} with approval` : ""} · never merges`;
}
/** What the wizard knows about the project the agent will join (an existing one, or the New Project draft). */
interface ProjCtx { key: string; name: string; color: string; repo: string; workers: string[]; rules: Record<string, Grant>; taskMode: TaskMode; type: string;
  team: { id: string; reportsTo: string; name: string; role: string; color: string; glyph: string }[]; draft?: DraftProjectCtx }
function projCtx(d: AgentDraft, o: Org, pd: ProjectDraft | undefined): ProjCtx | null {
  if (d.mode === "plan" && pd) {
    const team = [...new Set([pd.lead, ...pd.members].filter(Boolean))].map((id) => { const a = o.agents.find((x) => x.id === id) ?? pd.planned.find((x) => x.id === id);
      return a ? { id, reportsTo: id === pd.lead ? "jay" : pd.lead || "jay", name: a.name, role: "role" in a ? a.role : a.title, color: a.color, glyph: a.glyph } : null; })
      .filter((x): x is NonNullable<typeof x> => !!x);
    for (const a of pd.planned) if (a.id !== d.id && !team.some((t) => t.id === a.id)) team.push({ id: a.id, reportsTo: a.reportsTo, name: a.name, role: a.title, color: a.color, glyph: a.glyph });
    return { key: pd.key, name: pd.name || "New project", color: pd.color, repo: pd.repo, workers: pd.workers, rules: projectRules(pd.deploy), taskMode: pd.taskMode, type: pd.type, team,
      draft: { key: pd.key, name: pd.name, repo: pd.repo, workers: pd.workers, type: pd.type, deploy: pd.deploy, taskMode: pd.taskMode, members: team.map((t) => t.id), planned: pd.planned } };
  }
  const p = o.projects.find((x) => x.key === d.project);
  if (!p) return null;
  const pp = projectProfile(p.key, o);
  return { key: p.key, name: p.name, color: p.color, repo: p.repo, workers: p.machines, rules: projectRules(pp.deploy), taskMode: pp.taskMode, type: pp.type,
    team: p.team.map((m) => { const a = o.agents.find((x) => x.id === m.id)!; return { ...m, name: a?.name ?? m.id, role: a?.role ?? "", color: a?.color ?? "#5d6a85", glyph: a?.glyph ?? "help" }; }) };
}

// ---------------------------------------------------------------- the page
export function Onboard() {
  const o = useOrg();
  const [stored, setStored] = useViewState<AgentDraft | null>(AGENT_VIEW, "draft", null);
  const [pd, setPd] = useViewState<ProjectDraft | null>("page:newproject", "draft", null);
  const [approving, setApproving] = useState(false);
  const openAgent = useOpenAgent();
  const d = stored ?? blankAgentDraft();
  const set = (patch: Partial<AgentDraft>) => { const { value, hit } = scrubSecrets({ ...d, ...patch, touched: true }); if (hit) notify("That looked like a token or password, so it was removed. Never paste secrets here.", "bad"); setStored(value); };
  const setStep = (i: number) => setStored({ ...d, step: Math.max(0, Math.min(STEPS.length - 1, i)) });
  const ctx = projCtx(d, o, pd ?? undefined);
  const result = validateAgent(d, o, ctx?.draft);
  const editing = d.mode === "edit" ? o.agents.find((a) => a.id === d.editing) : null;
  const close = (to?: () => void) => { setStored(null); (to ?? (() => go(d.mode === "plan" ? "newproject" : "agents")))(); leavePopout(AGENT_VIEW); };
  const applyFix = (i: Issue) => { if (i.fix) setStored({ ...i.fix.apply(d), touched: true }); };
  const goTo = (id: string) => setStep(STEPS.findIndex((s) => s.id === id));

  const doApprove = () => {
    if (validateAgent(d, o, ctx?.draft).errors.length) return;
    if (d.mode === "plan" && pd) {
      const planned = [...pd.planned.filter((x) => x.id !== d.id && x.id !== d.editing), { ...d, step: 0, touched: false }];
      const lead = d.reportsTo === "jay" ? d.id : pd.lead;
      setPd({ ...pd, planned, lead, touched: true });
      notify(`${d.name} is planned for ${pd.name || "the new project"}. It will be added only when you approve the project.`);
      setStored(null); showPage("newproject"); return;
    }
    if (d.mode === "edit") { updateAgent(d); notify(`${d.name}: changes approved (mock). Config version saved; the ID ${d.editing} is unchanged.`); }
    else { activateAgent(d); notify(`${d.name} added to the prototype (mock). Status: Not started. No credentials or sessions were created.`); }
    const id = d.mode === "edit" ? d.editing! : d.id;
    setApproving(false); setStored(null); go("teams", d.project); openAgent(id); leavePopout(AGENT_VIEW);
  };

  const title = d.mode === "edit" ? <>Edit <em>{editing?.name ?? d.name}</em></> : d.mode === "plan" ? <>Plan a new agent <small className="muted">for {pd?.name || "the new project"}</small></> : <>New <em>Agent</em></>;
  const sub = d.mode === "edit" ? "Same steps as onboarding. Approving saves a new config version; the agent's ID and history stay." :
    d.mode === "plan" ? "This agent becomes part of the project plan. Nothing is added until you approve the project." :
      "Hire a new AI team member in ten short steps. You approve before anything changes.";
  return <Wizard viewId={AGENT_VIEW} title={title} sub={sub} steps={STEPS} step={d.step} setStep={setStep} result={result} mode={d.mode}
    dirty={d.touched} onSave={d.mode === "plan" ? undefined : () => { const id = saveDraft(d); setStored({ ...d, savedId: id, touched: false }); notify("Draft saved. Resume it any time from Agents → Drafts."); }}
    onCancelConfirmed={() => close()}
    approve={{ label: d.mode === "edit" ? "Approve changes" : d.mode === "plan" ? "Add to project plan" : "Approve & Add Agent", run: () => (d.mode === "plan" ? doApprove() : setApproving(true)), icon: d.mode === "plan" ? "plus" : "shield" }}
    preview={<AgentPreview d={d} ctx={ctx} />}
    banner={d.mode === "plan" && !pd ? <p className="callout t-warn"><Icon name="info" size={16} /> The project draft this agent was planned for is gone. Cancel to leave.</p> : undefined}>
    {d.step === 0 && <TemplateStep d={d} setStored={setStored} />}
    {d.step === 1 && <IdentityStep d={d} set={set} />}
    {d.step === 2 && <IntelligenceStep d={d} set={set} />}
    {d.step === 3 && <OrgStep d={d} set={set} o={o} ctx={ctx} />}
    {d.step === 4 && <CapStep d={d} set={set} goTo={goTo} />}
    {d.step === 5 && <AccessStep d={d} set={set} o={o} ctx={ctx} />}
    {d.step === 6 && <PermStep d={d} set={set} ctx={ctx} />}
    {d.step === 7 && <InstrStep d={d} set={set} />}
    {d.step === 8 && <BudgetStep d={d} set={set} />}
    {d.step === 9 && <ReviewStep d={d} ctx={ctx} errors={result.errors} warnings={result.warnings} goTo={goTo} applyFix={applyFix} />}
    {approving && <Modal title={d.mode === "edit" ? `Approve changes to ${d.name}?` : `Approve and add ${d.name}?`} onClose={() => setApproving(false)}
      footer={<><button type="button" className="btn" onClick={() => setApproving(false)}>Not yet</button>
        <button type="button" className="btn btn-primary" onClick={doApprove}><Icon name="shield" size={15} /> {d.mode === "edit" ? "Approve changes" : "Approve & Add Agent"}</button></>}>
      <ul className="checks">
        <li>{d.mode === "edit" ? `Saves config version ${(o.profiles[d.editing!]?.length ?? 0) + 1} for ${d.name}. The ID “${d.editing}” and all history stay.` : `Adds ${d.name} (${d.title}) to ${ctx?.name} in this prototype's mock organisation.`}</li>
        <li>{d.mode === "edit" ? "Its current status is unchanged." : "Its status starts as Not started: no session, nothing running."}</li>
        <li>No credentials, tokens or provider accounts are created. Nothing is sent to ccd, GitHub or any machine.</li>
        <li>You are recorded as the approver in the prototype's audit log.</li>
      </ul>
    </Modal>}
  </Wizard>;
}

// ---------------------------------------------------------------- preview
function AgentPreview({ d, ctx }: { d: AgentDraft; ctx: ProjCtx | null }) {
  const n = grantSummary(d.grants);
  return <div className="pv-card">
    <small className="pv-k">{d.mode === "edit" ? "Editing" : "Hiring summary"}</small>
    <div className="pv-id"><DraftAvatar color={d.color} glyph={d.glyph} size={54} /><div><b>{d.name || "Unnamed agent"}</b><span>{d.title || "Role not set"}</span><code>{d.id || "id-pending"}</code></div></div>
    <dl className="pv-kv">
      <dt>Project</dt><dd>{ctx ? <span className="am-proj"><i style={{ background: ctx.color }} />{ctx.name}</span> : "—"}</dd>
      <dt>Model</dt><dd>{modelLabel(d.model)}<small className="muted"> · {d.reasoning}</small></dd>
      <dt>Reports to</dt><dd>{d.reportsTo === "jay" ? "Jay (as project lead)" : ctx?.team.find((t) => t.id === d.reportsTo)?.name ?? "—"}</dd>
      <dt>Machines</dt><dd>{d.machines.map((m) => worker(m)?.label).join(", ") || "—"}</dd>
      <dt>Status after</dt><dd>{d.mode === "edit" ? "Unchanged" : d.mode === "plan" ? "Planned (not created)" : "Not started"}</dd>
    </dl>
    <div className="pv-perm" aria-label="Permissions summary">
      <span className="g-allow" style={{ flex: n.allow }} /><span className="g-approval" style={{ flex: n.approval }} /><span className="g-deny" style={{ flex: n.deny }} />
    </div>
    <p className="pv-legend"><GrantBadge g="allow">{n.allow} allowed</GrantBadge><GrantBadge g="approval">{n.approval} approval</GrantBadge><GrantBadge g="deny">{n.deny} denied</GrantBadge></p>
    <p className="pv-note"><Icon name="lock" size={13} /> Merge, production writes, secrets and infrastructure are always denied.</p>
  </div>;
}

// ---------------------------------------------------------------- steps
function TemplateStep({ d, setStored }: { d: AgentDraft; setStored: (d: AgentDraft) => void }) {
  const pick = (t: AgentTemplate) => {
    const fresh = agentDraftFrom(t.id, d.project, d.mode);
    setStored({ ...fresh, mode: d.mode, editing: d.editing, savedId: d.savedId, name: d.name, id: d.id, idTouched: d.idTouched, step: 0, touched: true,
      reportsTo: d.mode === "plan" ? (t.lead ? "jay" : d.reportsTo) : fresh.reportsTo, repos: d.mode === "plan" ? d.repos : fresh.repos, machines: d.mode === "plan" ? d.machines : fresh.machines });
  };
  const card = (t: AgentTemplate) => <button key={t.id} type="button" className={cx("tpl", d.template === t.id && "is-on")} aria-pressed={d.template === t.id} onClick={() => pick(t)}
    aria-label={`${t.title} template`}>
    <span className="tpl-top"><DraftAvatar color={t.color} glyph={t.glyph} size={38} /><span><b>{t.title}</b><small>{t.blurb}</small></span>{d.template === t.id && <Icon name="check" size={18} className="tpl-tick" />}</span>
    {t.spec && <span className="tpl-spec">{t.spec}</span>}
    <dl className="tpl-kv"><dt><Icon name="cpu" size={12} /> Model</dt><dd>{tierLabel(t.config.model)} · {modelLabel(t.config.model)}</dd>
      <dt><Icon name="shield" size={12} /> Permissions</dt><dd>{typicalPerms(t)}</dd>
      <dt><Icon name="graph" size={12} /> Reports to</dt><dd>{t.reportsTo === "jay" ? "Jay (leads the project)" : "The project lead"}</dd></dl>
  </button>;
  return <>
    <h3 className="wz-sub">Core team roles</h3>
    <div className="tpl-grid">{AGENT_TEMPLATES.filter((t) => t.core).map(card)}</div>
    <h3 className="wz-sub">Specialists</h3>
    <div className="tpl-grid">{AGENT_TEMPLATES.filter((t) => !t.core).map(card)}{card(CUSTOM_TEMPLATE)}</div>
  </>;
}

function IdentityStep({ d, set }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void }) {
  const [editId, setEditId] = useState(d.idTouched && d.mode !== "edit");
  const r = validateAgent(d, useOrg());
  const err = (f: string) => r.errors.find((e) => e.step === "identity" && e.field === f)?.msg;
  const warn = (f: string) => r.warnings.find((e) => e.step === "identity" && e.field === f)?.msg;
  return <div className="fld-grid">
    <Field label="Display name" error={err("name")} hint={warn("name") ?? "What Jay and the team call it. You can rename it later; its ID and history stay."}>
      {(id) => <input id={id} value={d.name} maxLength={32} placeholder="e.g. Mira" autoComplete="off"
        onChange={(e) => set({ name: e.target.value, id: d.idTouched || d.mode === "edit" ? d.id : idFromName(e.target.value) })} />}</Field>
    <Field label="Internal ID" error={err("id")} hint={d.mode === "edit" ? "IDs never change. Every task, message, review and audit record points at it." : "Permanent. It is never reused, even after offboarding."}>
      {(id) => d.mode === "edit" || !editId
        ? <span className="id-prev"><code id={id}>{d.id || "type a name first"}</code>{d.mode === "edit" ? <Pill tone="idle"><Icon name="lock" size={12} /> Locked</Pill>
          : <button type="button" className="link" onClick={() => setEditId(true)}>Change</button>}</span>
        : <input id={id} value={d.id} maxLength={32} className="mono" onChange={(e) => set({ id: e.target.value.toLowerCase().trim(), idTouched: true })} />}</Field>
    <Field label="Role title" error={err("title")}>{(id) => <input id={id} value={d.title} placeholder="e.g. Implementation Agent" onChange={(e) => set({ title: e.target.value })} />}</Field>
    <Field label="Specialisation" hint={warn("spec")}>{(id) => <input id={id} value={d.spec} placeholder="What to hand this agent" onChange={(e) => set({ spec: e.target.value })} />}</Field>
    <Field label="Short description" wide optional>{(id) => <textarea id={id} rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} />}</Field>
    <Field label="Avatar">{() => <div className="glyphs" role="radiogroup" aria-label="Avatar">{AVATAR_GLYPHS.map((g) =>
      <button key={g} type="button" role="radio" aria-checked={d.glyph === g} aria-label={g} onClick={() => set({ glyph: g as IconName })}><Icon name={g} size={18} stroke={2} /></button>)}</div>}</Field>
    <Field label="Colour" hint="Agent colours are separate from project colours.">{() => <div className="swatches" role="radiogroup" aria-label="Colour">{AGENT_COLORS.map((c) =>
      <button key={c} type="button" role="radio" aria-checked={d.color === c} aria-label={`Colour ${c}`} style={{ background: c }} onClick={() => set({ color: c })} />)}</div>}</Field>
  </div>;
}

function IntelligenceStep({ d, set }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void }) {
  const prov = PROVIDERS.find((p) => p.id === d.provider)!;
  const all = PROVIDERS.flatMap((p) => p.models);
  return <>
    <div className="explain"><span className="explain-ico"><Icon name="users" size={18} /></span><p><b>{d.name || "The persona"}</b> is the identity: name, role, instructions and history. The <b>model</b> is the engine for a session. Changing the model never changes who {d.name || "the agent"} is.</p></div>
    <Field label="Provider">{() => <Seg label="Provider" value={d.provider} options={PROVIDERS.map((p) => ({ id: p.id, label: p.label }))}
      onChange={(v) => { const p = PROVIDERS.find((x) => x.id === v)!; set({ provider: v, model: p.models.includes(d.model) ? d.model : p.models[0], fallback: d.fallback === p.models[0] ? "" : d.fallback }); }} />}</Field>
    <div className="model-grid" role="radiogroup" aria-label="Model">{prov.models.map((m) => { const [i, out] = MODEL_PRICE[m];
      return <button key={m} type="button" role="radio" aria-checked={d.model === m} className={cx("model-card", d.model === m && "is-on")} onClick={() => set({ model: m, fallback: d.fallback === m ? "" : d.fallback })}>
        <b>{MODELS[m].label}</b><code>{m}</code><span><Pill tone={MODEL_TIER[m] === "frontier" ? "violet" : MODEL_TIER[m] === "fast" ? "ok" : "info"}>{tierLabel(m)}</Pill><small className="muted">${i} / ${out} per M tokens</small></span></button>; })}</div>
    <div className="fld-grid">
      <Field label="Reasoning">{() => <Seg label="Reasoning" value={d.reasoning} options={REASONING.map((r) => ({ id: r.id, label: r.label, title: r.hint }))} onChange={(v) => set({ reasoning: v })} />}</Field>
      <Field label="Context and runtime">{() => <Seg label="Context" value={d.context} options={[{ id: "standard", label: "Standard" }, { id: "long", label: "Long context" }]} onChange={(v) => set({ context: v })} />}</Field>
      <Field label="Fallback model" optional hint="Used only if policy allows and the primary is unavailable.">{(id) => <select id={id} value={d.fallback} onChange={(e) => set({ fallback: e.target.value })}>
        <option value="">No fallback</option>{all.filter((m) => m !== d.model).map((m) => <option key={m} value={m}>{MODELS[m].label}</option>)}</select>}</Field>
    </div>
    <p className="callout"><Icon name="lock" size={15} /> The prototype does not provision or sign in to providers. Provider keys stay in ccd's server-side configuration; no browser or agent ever sees them.</p>
  </>;
}

function OrgStep({ d, set, o, ctx }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void; o: Org; ctx: ProjCtx | null }) {
  const r = validateAgent(d, o, ctx?.draft);
  const err = (f: string) => r.errors.find((e) => e.step === "organization" && e.field === f)?.msg;
  const team = (ctx?.team ?? []).filter((m) => m.id !== d.editing && m.id !== d.id);
  const lead = team.find((m) => m.reportsTo === "jay");
  const chain: Parameters<typeof Hierarchy>[0]["chain"] = [{ key: "jay", name: "Jay", role: "Engineering Director", color: "", glyph: "", jay: true }];
  const up: typeof team = []; let cur = d.reportsTo; let hops = 0;
  while (cur && cur !== "jay" && hops++ < 10) { const m = team.find((x) => x.id === cur); if (!m) break; up.unshift(m); cur = m.reportsTo; }
  for (const m of up) chain.push({ key: m.id, name: m.name, role: m.role, color: m.color, glyph: m.glyph });
  chain.push({ key: "me", name: d.name || "New agent", role: d.title || "Role not set", color: d.color, glyph: d.glyph, me: true });
  const below = team.filter((m) => d.supervises.includes(m.id)).map((m) => ({ key: m.id, name: m.name, color: m.color, glyph: m.glyph }));
  return <div className="org-split">
    <div>
      {d.mode === "plan" ? <Field label="Project">{() => <p className="id-prev"><span className="am-proj"><i style={{ background: ctx?.color }} />{ctx?.name}</span><Pill tone="info">Being created</Pill></p>}</Field>
        : <Field label="Project" error={err("project")} hint="Agents belong to a project. Working on several projects needs Jay's policy and isn't available here.">{() =>
          <div className="proj-pick" role="radiogroup" aria-label="Project">{o.projects.map((p) => <button key={p.key} type="button" role="radio" aria-checked={d.project === p.key} style={{ ["--c" as string]: p.color }}
            onClick={() => { const l = p.team.find((m) => m.reportsTo === "jay" && m.id !== d.editing)?.id; set({ project: p.key, reportsTo: d.reportsTo === "jay" && !l ? "jay" : l ?? "jay", supervises: [], repos: p.repoState === "connected" ? [p.repo] : [], machines: d.machines.filter((m) => p.machines.includes(m)).length ? d.machines.filter((m) => p.machines.includes(m)) : [p.machines[0]] }); }}>
            <i />{p.name}{p.health === "paused" && <small> · paused</small>}{p.health === "onboarding" && <small> · onboarding</small>}</button>)}</div>}</Field>}
      <Field label="Team">{() => <p className="id-prev">{ctx ? `${ctx.name} team` : "—"} <small className="muted">· {plural(team.length, "member")}</small></p>}</Field>
      <Field label="Reports to" error={err("reportsTo")} hint={d.reportsTo === "jay" ? "Reporting to Jay makes this agent the project lead." : undefined}>{(id) =>
        <select id={id} value={d.reportsTo} onChange={(e) => set({ reportsTo: e.target.value, supervises: d.supervises.filter((x) => x !== e.target.value) })}>
          <option value="jay">{lead ? "Jay (only if it replaces the lead)" : "Jay — make it the project lead"}</option>
          {team.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}</select>}</Field>
      <Field label="Supervises" optional error={err("supervises")} hint="Team members who will report to this agent.">{() =>
        <Chips label="Supervises" value={d.supervises} onChange={(v) => set({ supervises: v })}
          options={team.filter((m) => m.id !== d.reportsTo && m.reportsTo !== "jay").map((m) => ({ id: m.id, label: m.name }))} />}</Field>
      <Field label="Pipeline stage">{(id) => <select id={id} value={d.stage} onChange={(e) => set({ stage: e.target.value })}>{STAGES.map((s) => <option key={s}>{s}</option>)}</select>}</Field>
      <Field label="Secondary responsibilities" optional>{() => <Chips label="Secondary responsibilities" value={d.secondary} onChange={(v) => set({ secondary: v })} options={SECONDARY.map((s) => ({ id: s, label: s }))} />}</Field>
    </div>
    <div className="org-prev"><h4>Reporting line</h4><Hierarchy chain={chain} below={below} />
      <p className="muted small">Agents never create or authorise other agents. Only Jay approves who joins a team.</p></div>
  </div>;
}

function CapStep({ d, set, goTo }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void; goTo: (s: string) => void }) {
  return <>
    <Field label="Skills" wide>{() => <Chips label="Skills" value={d.skills} onChange={(v) => set({ skills: v })} options={SKILLS} />}</Field>
    <Field label="MCP servers" wide hint="Tools it may connect to through ccd. Locked items need Jay's approval first.">{() =>
      <Chips label="MCP servers" value={d.mcp} onChange={(v) => set({ mcp: v })} options={MCP_SERVERS.map((m) => ({ id: m.id, label: m.label, hint: m.hint, locked: m.locked }))} />}</Field>
    <h3 className="wz-sub">Available vs authorised</h3>
    <p className="muted small">Available means a machine it may use has the tool installed. Authorised means its permissions let it use it. It can only use what is both.</p>
    <table className="cap-table"><thead><tr><th>Capability</th><th>Available on its machines</th><th>Authorised</th></tr></thead><tbody>
      {TOOLS.map((t) => { const avail = t.locked ? null : !t.cap || d.machines.some((m) => worker(m)?.caps.includes(t.cap!)); const g = t.locked ? "deny" : (d.grants[t.perm] ?? "deny") as Grant;
        return <tr key={t.id}><td>{t.label}</td>
          <td>{t.locked ? <span className="muted"><Icon name="lock" size={12} /> {t.locked}</span> : avail ? <span className="t-ok"><Icon name="tick" size={13} /> Available</span> : <span className="muted"><Icon name="x" size={13} /> Not on its machines</span>}</td>
          <td><GrantBadge g={g} /></td></tr>; })}</tbody></table>
    <button type="button" className="link" onClick={() => goTo("permissions")}>Change what it's authorised to do in Permissions <Icon name="arrowr" size={12} /></button>
  </>;
}

function AccessStep({ d, set, o, ctx }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void; o: Org; ctx: ProjCtx | null }) {
  const [open, setOpen] = useViewState(AGENT_VIEW, "effOpen", false);
  const repos = [...new Set([...o.projects.filter((p) => p.repoState === "connected").map((p) => p.repo), ...(ctx?.repo ? [ctx.repo] : [])])];
  const elig = ctx?.workers ?? [];
  return <>
    <div className="trio">
      <div><Icon name="users" size={18} /><b>Agent identity</b><small>Who is acting: {d.name || "the agent"} ({d.id || "id"}).</small></div>
      <div><Icon name="server" size={18} /><b>Machine</b><small>Where a session runs: a WorkerNode with its own capabilities.</small></div>
      <div><Icon name="shield" size={18} /><b>Permission</b><small>What it may do there. Granted separately; a machine grants nothing.</small></div>
    </div>
    <Field label="Repositories" wide hint={`Only ${ctx?.name ?? "its project"}'s repository can be granted.`}>{() => <div className="repo-list">{repos.map((r) => {
      const mine = r === ctx?.repo; const on = d.repos.includes(r);
      return <label key={r} className={cx("repo-row", !mine && "is-off")}><input type="checkbox" checked={on} disabled={!mine && !on}
        onChange={() => set({ repos: on ? d.repos.filter((x) => x !== r) : [...d.repos, r] })} /><Icon name="branch" size={14} /><span className="mono">{r}</span>
        {!mine && <small className="muted">Not in its project</small>}{mine && ctx?.draft && <small className="muted">{peekView<ProjectDraft>("page:newproject", "draft")?.repoMode === "proposed" ? "Proposed, not created" : "Connect on approval"}</small>}</label>; })}</div>}</Field>
    <Field label="Machines" wide>{() => <div className="worker-grid">{WORKERS.map((w) => { const on = d.machines.includes(w.id); const eligible = elig.includes(w.id); const blocked = ctx?.type === "employer" && w.id === "server";
      return <button key={w.id} type="button" className={cx("worker", on && "is-on", (!eligible || blocked) && "is-off")} aria-pressed={on} disabled={(!eligible || blocked) && !on}
        onClick={() => set({ machines: on ? d.machines.filter((x) => x !== w.id) : [...d.machines, w.id] })}>
        <span className="worker-h"><Icon name={w.id === "server" ? "server" : "laptop"} size={18} /><b>{w.label}</b>
          <Pill tone={w.status === "online" ? "ok" : "idle"} dot>{w.status === "online" ? "Online" : "Unknown"}</Pill></span>
        <span className="worker-caps">{w.caps.map((c) => <small key={c}>{WORKER_CAP_LABEL[c]}</small>)}</span>
        <small className={w.agentNode ? "muted" : "t-warn"}>{blocked ? "Employer projects may not use jay-server." : !eligible ? `Not eligible for ${ctx?.name ?? "this project"}.` : w.agentNode ? "Agent execution node" : "Requires Jay's approval"}</small></button>; })}</div>}</Field>
    <button type="button" className="ai-expand" aria-expanded={open} onClick={() => setOpen(!open)}><Icon name={open ? "chevdown" : "chevron"} size={14} /> How effective access is worked out</button>
    {open && ctx && <EffectiveTable d={d} rules={ctx.rules} workers={d.machines.filter((m) => elig.includes(m))} mode={ctx.taskMode} />}
  </>;
}

export function EffectiveTable({ d, rules, workers, mode }: { d: { grants: Grants }; rules: Record<string, Grant>; workers: string[]; mode: TaskMode }) {
  return <div className="eff">
    <p className="eff-formula"><span>Agent permission</span>∩<span>Project rules</span>∩<span>Worker capability</span>∩<span>Task mode <small>({TASK_MODES.find((m) => m.id === mode)?.label})</small></span>=<b>Effective</b></p>
    <table className="cap-table"><thead><tr><th>Permission</th><th>Agent</th><th>Project</th><th>Worker</th><th>Task mode</th><th>Effective</th></tr></thead><tbody>
      {PERMISSIONS.map((p) => { const e = effective(p.id, d.grants, rules, workers, mode);
        return <tr key={p.id}><td>{p.label}</td><td><GrantBadge g={e.agent}>{" "}</GrantBadge></td><td><GrantBadge g={e.project}>{" "}</GrantBadge></td><td><GrantBadge g={e.worker}>{" "}</GrantBadge></td>
          <td><GrantBadge g={e.mode}>{" "}</GrantBadge></td><td><GrantBadge g={e.result} /></td></tr>; })}</tbody></table>
  </div>;
}

function PermStep({ d, set, ctx }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void; ctx: ProjCtx | null }) {
  const [open, setOpen] = useViewState<string[]>(AGENT_VIEW, "permOpen", []);
  const tpl = templateOf(d.template);
  const fixed = PERMISSIONS.filter((p) => p.ceiling === "deny");
  return <>
    <div className="hard"><h4><Icon name="lock" size={15} /> CommandCenter's fixed boundaries</h4><p>These can't be granted to any agent, from any screen.</p>
      <ul>{fixed.map((p) => <li key={p.id}><GrantBadge g="deny" /> {p.label}<small className="muted"> · {p.boundary}</small></li>)}</ul></div>
    <div className="row-gap"><span className="muted small">Defaults from the {tpl.title} template. Expand a group to adjust it.</span><span className="sp" />
      <button type="button" className="btn btn-sm" onClick={() => set({ grants: { ...tpl.config.grants } })}>Reset to template defaults</button></div>
    {PERM_GROUPS.map((g) => { const list = PERMISSIONS.filter((p) => p.group === g); const isOpen = open.includes(g);
      const n = { allow: 0, approval: 0, deny: 0 }; list.forEach((p) => n[d.grants[p.id] ?? "deny"]++);
      return <section key={g} className={cx("perm-g", isOpen && "is-open")}>
        <button type="button" className="perm-gh" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? open.filter((x) => x !== g) : [...open, g])}>
          <Icon name={isOpen ? "chevdown" : "chevron"} size={14} /><b>{g}</b><span className="sp" />
          {n.allow > 0 && <GrantBadge g="allow">{n.allow} allowed</GrantBadge>}{n.approval > 0 && <GrantBadge g="approval">{n.approval} approval</GrantBadge>}{n.deny > 0 && <GrantBadge g="deny">{n.deny} denied</GrantBadge>}</button>
        {isOpen && <ul className="perm-rows">{list.map((p) => { const lim = ctx?.rules[p.id];
          return <li key={p.id}><span><b>{p.label}</b>{p.boundary && <small className="muted"><Icon name="lock" size={11} /> {p.boundary}</small>}
            {lim && lim !== "allow" && <small className="t-warn">{ctx?.name} allows at most: {GRANT_LABEL[lim]}</small>}</span>
            <GrantPick label={p.label} value={d.grants[p.id] ?? "deny"} ceiling={p.ceiling} limit={p.boundary} onChange={(v) => set({ grants: { ...d.grants, [p.id]: v } })} /></li>; })}</ul>}
      </section>; })}
  </>;
}

function InstrStep({ d, set }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void }) {
  return <>
    <div className="fld-grid">{INSTRUCTION_FIELDS.map((f) => <Field key={f.id} label={f.label} hint={f.hint || undefined} wide={(f.rows ?? 1) > 1}>{(id) =>
      (f.rows ?? 1) > 1 ? <textarea id={id} rows={f.rows} value={d.instructions[f.id]} onChange={(e) => set({ instructions: { ...d.instructions, [f.id]: e.target.value } })} />
        : <input id={id} value={d.instructions[f.id]} onChange={(e) => set({ instructions: { ...d.instructions, [f.id]: e.target.value } })} />}</Field>)}</div>
    <div className="hard"><h4><Icon name="lock" size={15} /> Always applies, whatever the instructions say</h4><ul>{HARD_NEVER.map((x) => <li key={x}><GrantBadge g="deny">Never</GrantBadge> {x}</li>)}</ul></div>
  </>;
}

function BudgetStep({ d, set }: { d: AgentDraft; set: (p: Partial<AgentDraft>) => void }) {
  const b = d.budget; const sb = (p: Partial<typeof b>) => set({ budget: { ...b, ...p } });
  const [i, out] = MODEL_PRICE[d.model] ?? [0, 0];
  const typical = (0.2 * i + 0.04 * out).toFixed(2);
  return <>
    <p className="callout t-warn"><Icon name="info" size={15} /> These are warnings, not limits. The prototype can't enforce budgets. In the real build ccd's usage meter would warn; a hard stop would need the capability broker (not built yet).</p>
    <div className="fld-grid">
      <Field label="Preferred model tier">{() => <Seg label="Preferred model tier" value={b.tier} options={[{ id: "frontier", label: "Frontier" }, { id: "balanced", label: "Balanced" }, { id: "fast", label: "Fast" }]} onChange={(v) => sb({ tier: v })} />}</Field>
      <Field label="Typical task cost" hint={`About 200k input and 40k output tokens on ${modelLabel(d.model)}.`}>{() => <p className="id-prev"><b>≈ ${typical}</b> <small className="muted">estimate</small></p>}</Field>
      <Field label="Daily warning">{(id) => <Money id={id} label="Daily warning" v={b.dailyWarnUsd} onChange={(v) => sb({ dailyWarnUsd: v })} />}</Field>
      <Field label="Weekly warning">{(id) => <Money id={id} label="Weekly warning" v={b.weeklyWarnUsd} onChange={(v) => sb({ weeklyWarnUsd: v })} />}</Field>
      <Field label="Per-task warning">{(id) => <Money id={id} label="Per-task warning" v={b.perTaskWarnUsd} onChange={(v) => sb({ perTaskWarnUsd: v })} />}</Field>
      <Field label="Maximum parallel work">{(id) => <input id={id} type="number" min={1} max={8} value={b.maxParallel} onChange={(e) => sb({ maxParallel: Number(e.target.value) })} />}</Field>
      <Field label="Escalating to a stronger model">{() => <Seg label="Escalation" value={b.escalation} options={[{ id: "never", label: "Never" }, { id: "approval", label: "With approval" }, { id: "allowed", label: "Allowed" }]} onChange={(v) => sb({ escalation: v })} />}</Field>
      <Field label="Ask Jay before a task expected to cost more than">{(id) => <Money id={id} label="Expensive-model approval threshold" v={b.expensiveApprovalUsd} onChange={(v) => sb({ expensiveApprovalUsd: v })} />}</Field>
    </div>
  </>;
}

function ReviewStep({ d, ctx, errors, warnings, goTo, applyFix }: { d: AgentDraft; ctx: ProjCtx | null; errors: Issue[]; warnings: Issue[]; goTo: (s: string) => void; applyFix: (i: Issue) => void }) {
  const caps = capabilitySentences(d, ctx?.rules ?? {}, ctx?.workers ?? [], ctx?.taskMode ?? "assisted", ctx?.name ?? "project");
  const sec = (title: string, step: string, body: React.ReactNode) => <section className="rv-sec"><h4>{title}<span className="sp" /><button type="button" className="link" onClick={() => goTo(step)}>Edit</button></h4>{body}</section>;
  const risky = PERMISSIONS.filter((p) => (d.grants[p.id] ?? "deny") !== "deny" && (p.group === "Production" || p.id === "data.dev_write" || p.id === "run.ci" || p.id === "repo.push"));
  return <>
    <IssueList errors={errors} warnings={warnings} goTo={goTo} steps={STEPS} applyFix={applyFix} />
    <div className="rv-caps" aria-label="What this agent can do">{caps.out.map((c) => <span key={c.text} className={`rv-cap t-${c.tone}`}><Icon name={c.tone === "ok" ? "tick" : c.tone === "warn" ? "shield" : "x"} size={13} />{c.text}</span>)}</div>
    <div className="rv-grid">
      {sec("Identity", "identity", <dl className="kv"><dt>Name</dt><dd>{d.name || "—"}</dd><dt>ID</dt><dd><code>{d.id || "—"}</code></dd><dt>Role</dt><dd>{d.title || "—"}</dd><dt>Specialisation</dt><dd>{d.spec || "—"}</dd></dl>)}
      {sec("Model", "intelligence", <dl className="kv"><dt>Provider</dt><dd>{PROVIDERS.find((p) => p.id === d.provider)?.label}</dd><dt>Model</dt><dd>{modelLabel(d.model)} <code>{d.model}</code></dd><dt>Reasoning</dt><dd>{d.reasoning}</dd><dt>Fallback</dt><dd>{d.fallback ? modelLabel(d.fallback) : "None"}</dd></dl>)}
      {sec("Organisation", "organization", <dl className="kv"><dt>Project</dt><dd>{ctx?.name ?? "—"}</dd><dt>Reports to</dt><dd>{d.reportsTo === "jay" ? "Jay (project lead)" : ctx?.team.find((t) => t.id === d.reportsTo)?.name}</dd><dt>Supervises</dt><dd>{d.supervises.map((s) => ctx?.team.find((t) => t.id === s)?.name).join(", ") || "Nobody"}</dd><dt>Stage</dt><dd>{d.stage}</dd></dl>)}
      {sec("Repos & machines", "access", <dl className="kv"><dt>Repositories</dt><dd>{d.repos.join(", ") || "None"}</dd><dt>Machines</dt><dd>{d.machines.map((m) => worker(m)?.label).join(", ") || "None"}</dd></dl>)}
      {sec("Capabilities", "capabilities", <dl className="kv"><dt>Skills</dt><dd>{d.skills.map((s) => SKILLS.find((x) => x.id === s)?.label).join(", ") || "None"}</dd><dt>MCP</dt><dd>{d.mcp.map((s) => MCP_SERVERS.find((x) => x.id === s)?.label).join(", ") || "None"}</dd></dl>)}
      {sec("Permissions", "permissions", <><p className="rv-perm"><b className="t-ok">Can:</b> {caps.can.join(", ") || "nothing"}</p><p className="rv-perm"><b className="t-warn">With Jay's approval:</b> {caps.ask.join(", ") || "nothing"}</p><p className="rv-perm"><b className="t-bad">Cannot:</b> {caps.cannot.length} actions, including merge, production writes and secrets</p></>)}
      {sec("Budget (warnings only)", "budget", <dl className="kv"><dt>Daily / weekly</dt><dd>${d.budget.dailyWarnUsd} / ${d.budget.weeklyWarnUsd}</dd><dt>Per task</dt><dd>${d.budget.perTaskWarnUsd}</dd><dt>Parallel</dt><dd>{d.budget.maxParallel}</dd></dl>)}
      {sec("Instructions", "instructions", <p className="muted">{d.instructions.mission || "No mission yet."}</p>)}
      <section className="rv-sec rv-risk"><h4><Icon name="shield" size={15} /> Risk and security summary</h4>
        <ul>{risky.length ? risky.map((p) => <li key={p.id}><GrantBadge g={d.grants[p.id]} /> {p.label}</li>) : <li>No production, data-write or CI permissions.</li>}
          <li>No credentials are created. Sessions get short-lived tokens from ccd only when a task starts (real build).</li>
          <li>It can't create agents, change its own permissions or approve its own work.</li></ul></section>
    </div>
  </>;
}

