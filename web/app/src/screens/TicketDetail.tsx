// The ticket, large: properties, description, relations, PR, agent, notes and a
// timeline where system events and human notes look different.
import { useEffect, useMemo, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
const NO_TYPES: string[] = [];
import { href } from "../lib/router";
import type { TicketDetail, TicketStatus, Priority, TimelineEvent } from "../api/types";
import { PRIORITIES, ROLES, FLAGS } from "../api/types";
import { ALL_STATUSES, STATUS_META, PRIORITY_META, FLAG_LABEL, assigneeLabel } from "../tickets/model";
import { StateText, Assignee, Project, Ci, DetailRow, EmptyState, Ago, AgentState, Kbd, Command } from "../components/ui";
import { AttachmentsPanel } from "../components/Attachments";
import { DevTrail } from "../components/DevTrail";
import { NewTicket } from "../components/NewTicket";
import { stamp } from "../lib/time";
import { openAgent } from "../lib/openAgent";
import { WorkPanel } from "../tickets/WorkPanel";

const DISPATCH_VERBS = ["plan", "implement", "review", "verify", "continue"] as const;

export function TicketDetailPane({ ticketKey, onClose }: { ticketKey: string; onClose: () => void }) {
  const t = useSelector(app.store, (d) => d.details[ticketKey]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setErr(null);
    app.loadTicket(ticketKey).catch((e) => setErr((e as Error).message));
  }, [ticketKey]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.key === "Escape" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag) && !document.querySelector("[role=dialog]")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (err && !t) return <aside className="td" aria-label="Ticket"><EmptyState title={`Cannot open ${ticketKey}`} hint={err} /></aside>;
  if (!t) return <aside className="td" aria-label="Ticket"><EmptyState title={`Loading ${ticketKey}…`} /></aside>;
  return <Detail t={t} onClose={onClose} />;
}

function Detail({ t, onClose }: { t: TicketDetail; onClose: () => void }) {
  const types = useSelector(app.store, (d) => d.meta?.types ?? NO_TYPES);
  const st = useSelector(app.store, (d) => d.state);
  const [editTitle, setEditTitle] = useState(false);
  const [title, setTitle] = useState(t.title);
  const [editDesc, setEditDesc] = useState(false);
  const [desc, setDesc] = useState(t.description);
  const [note, setNote] = useState("");
  const [rel, setRel] = useState({ kind: "blocked_by", target: "" });
  const [pr, setPr] = useState("");
  const [labels, setLabels] = useState(t.labels.join(" "));
  const [sub, setSub] = useState(false);
  useEffect(() => { setTitle(t.title); setDesc(t.description); setLabels(t.labels.join(" ")); }, [t.key, t.title, t.description, t.labels.join(" ")]);

  const upd = (fields: Record<string, unknown>, msg?: string) => app.mutate(() => app.api.updateTask(t.key, fields), msg).catch(() => {});
  const proj = st?.projects.find((p) => p.key === t.project);
  const prRow = t.prNumber != null ? proj?.prs.find((p) => p.number === t.prNumber) : undefined;
  const agent = st?.agents.find((a) => (t.agentPaneId && a.id === t.agentPaneId)
    || (t.assignee?.startsWith("agent:") && (a.agent_name === t.assignee.slice(6) || a.id === t.assignee.slice(6))));
  const coord = st?.coordinators[t.project];
  const dispatchable = !!coord?.paneId && ["samvision", "gauzemate"].includes(t.project);
  const items = useMemo(() => timeline(t), [t]);
  // The Jira-like DEVELOPMENT section: the same trail the Development screen shows.
  const devRow = useSelector(app.store, (d) => d.development?.rows.find((r) => r.key === t.key) ?? null);
  const devLoaded = useSelector(app.store, (d) => d.development !== null);
  useEffect(() => { if (!devLoaded) void app.refreshDevelopment(); else app.scheduleDevelopment(); }, [t.key, devLoaded]);

  return <aside className="td" aria-label={`Ticket ${t.key}`}>
    <header className="td-head">
      <div className="row"><span className="key">{t.key}</span><Project k={t.project} name={proj?.name} />
        {t.archived && <span className="label">archived</span>}
        <span style={{ marginLeft: "auto" }} className="row">
          <a className="btn is-quiet is-sm" href={href("tasks", t.key)} title="Permalink">Link</a>
          <button type="button" className="btn is-quiet is-sm" onClick={onClose} aria-label="Close detail"><Kbd>Esc</Kbd></button></span></div>
      {editTitle ? <form onSubmit={(e) => { e.preventDefault(); if (title.trim() && title !== t.title) void upd({ title }); setEditTitle(false); }}>
        <input className="input td-title-input" value={title} autoFocus onChange={(e) => setTitle(e.target.value)} maxLength={300}
          onBlur={() => { if (title.trim() && title !== t.title) void upd({ title }); setEditTitle(false); }}
          onKeyDown={(e) => { if (e.key === "Escape") { setTitle(t.title); setEditTitle(false); } }} aria-label="Title" /></form>
        : <h2 className="td-title" onDoubleClick={() => setEditTitle(true)}>{t.title}
          <button type="button" className="btn is-quiet is-sm" onClick={() => setEditTitle(true)} style={{ marginLeft: 6 }}>Edit</button></h2>}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <StateText status={t.status} />
        {FLAGS.map((f) => <button key={f} type="button" className="fchip is-jay" aria-pressed={t.flags.includes(f)}
          onClick={() => upd({ [f]: !t.flags.includes(f) }, `${FLAG_LABEL[f]} ${t.flags.includes(f) ? "cleared" : "set"}`)}>{FLAG_LABEL[f]}</button>)}
      </div>
    </header>
    <div className="td-body">
      <dl className="td-props">
        <DetailRow label="Status"><select className="select" value={t.status} aria-label="Status"
          onChange={(e) => upd({ status: e.target.value as TicketStatus })}>
          {ALL_STATUSES.map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}</select></DetailRow>
        <DetailRow label="Priority"><select className="select" value={t.priority} aria-label="Priority"
          onChange={(e) => upd({ priority: e.target.value as Priority })}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}</select></DetailRow>
        <DetailRow label="Assignee"><div className="row"><Assignee value={t.assignee} compact />
          <select className="select grow" value={t.assignee ?? ""} aria-label="Assignee" onChange={(e) => upd({ assignee: e.target.value || null })}>
            <option value="">Unassigned</option><option value="jay">Jay — human</option>
            <optgroup label="Agent role">{ROLES.map((r) => <option key={r} value={`role:${r}`}>{r.toLowerCase()}</option>)}</optgroup>
            <optgroup label="Specific agent">{st?.agents.filter((a) => a.agent_name).map((a) =>
              <option key={a.id} value={`agent:${a.agent_name}`}>{a.agent_name} ({a.id})</option>)}
              {t.assignee?.startsWith("agent:") && !st?.agents.some((a) => `agent:${a.agent_name}` === t.assignee)
                && <option value={t.assignee}>{assigneeLabel(t.assignee)} (not live)</option>}</optgroup>
          </select></div></DetailRow>
        <DetailRow label="Type"><select className="select" value={t.type ?? ""} aria-label="Type" onChange={(e) => upd({ type: e.target.value || null })}>
          <option value="">—</option>{types.map((x) => <option key={x} value={x}>{x.toLowerCase().replace("_", " ")}</option>)}</select></DetailRow>
        <DetailRow label="Branch"><BranchField value={t.branch} onSave={(v) => upd({ branch: v })} /></DetailRow>
        <DetailRow label="Labels"><input className="input" value={labels} aria-label="Labels, space separated" onChange={(e) => setLabels(e.target.value)}
          onBlur={() => { const next = labels.split(/\s+/).filter(Boolean); if (next.join(" ") !== t.labels.join(" ")) void upd({ labels: next }); }}
          placeholder="ui tasks…" /></DetailRow>
        <DetailRow label="Created"><span className="mono-xs">{stamp(t.createdAt)}</span> <span className="muted mono-xs">{t.creator}</span></DetailRow>
        <DetailRow label="Updated"><span className="mono-xs">{stamp(t.updatedAt)}</span></DetailRow>
        {t.startedAt && <DetailRow label="Started"><span className="mono-xs">{stamp(t.startedAt)}</span></DetailRow>}
        {t.completedAt && <DetailRow label="Completed"><span className="mono-xs">{stamp(t.completedAt)}</span></DetailRow>}
      </dl>

      <section aria-label="Description">
        <div className="td-sec-title">Description {!editDesc && <button type="button" className="btn is-quiet is-sm" onClick={() => setEditDesc(true)}>Edit</button>}</div>
        {editDesc ? <div style={{ display: "grid", gap: 6 }}>
          <textarea className="textarea" rows={8} value={desc} autoFocus onChange={(e) => setDesc(e.target.value)} aria-label="Description"
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { void upd({ description: desc }); setEditDesc(false); } if (e.key === "Escape") { setDesc(t.description); setEditDesc(false); } }} />
          <div className="row"><button type="button" className="btn is-primary is-sm" onClick={() => { void upd({ description: desc }); setEditDesc(false); }}>Save</button>
            <button type="button" className="btn is-sm" onClick={() => { setDesc(t.description); setEditDesc(false); }}>Cancel</button>
            <span className="muted mono-xs">Ctrl+Enter save</span></div></div>
          : <p className={`desc${t.description ? "" : " is-empty"}`}>{t.description || "No description."}</p>}
      </section>

      <WorkPanel t={t} />

      <section aria-label="Development">
        <div className="td-sec-title">Development</div>
        <DevTrail row={devRow} repo={proj?.repo ?? null} />
        <div className="row" style={{ gap: 8 }}>
          <a className="btn is-sm" href={href("development")}>All development</a>
          <a className="btn is-sm" href={href("workspace", null, { project: t.project, ticket: t.key })}>Workspace</a>
        </div>
      </section>

      <AttachmentsPanel owner="ticket" ownerKey={t.key} />

      <section aria-label="Pull request and agent">
        <div className="td-sec-title">Code</div>
        {t.links.filter((l) => l.kind === "pr").map((l) => {
          const row = proj?.prs.find((p) => p.number === l.number);
          return <div key={l.ref} className="rel">
            <span className="caps muted">PR</span>
            {l.url ? <a className="mono link" href={l.url} target="_blank" rel="noopener noreferrer">#{l.number}</a> : <span className="mono">#{l.number}</span>}
            <span className="row trunc">{row ? <>{row.ci !== "–" && <Ci mark={row.ci} />}<span className="text2 trunc">{row.title}</span>
              <span className="mono-xs muted">{row.review?.toLowerCase().replace("_", " ") ?? "no review"}</span>
              {row.mergeable && <span className="mono-xs muted">{row.mergeable.toLowerCase()}</span>}
              {row.ready && <span className="flag">JAY MUST MERGE</span>}</> : <span className="muted">closed or merged</span>}</span>
            <button type="button" className="btn is-quiet is-sm" onClick={() => app.mutate(() => app.api.link(t.key, { provider: l.provider, kind: "pr", ref: l.ref, remove: true }))}>Unlink</button>
          </div>;
        })}
        {prRow && <div className="mono-xs muted">head {prRow.sha} · {prRow.branch}</div>}
        <form className="row" onSubmit={(e) => {
          e.preventDefault(); const n = pr.replace(/^#/, "").trim();
          if (!/^\d+$/.test(n) || !proj) return;
          // ccd builds the PR's URL from the project's one GitHub identity; the UI never does.
          void app.mutate(() => app.api.link(t.key, { provider: "github", kind: "pr", ref: `${proj.repo}#${n}` }),
            `PR #${n} linked`).then(() => setPr(""));
        }}>
          <input className="input" style={{ width: 110 }} value={pr} onChange={(e) => setPr(e.target.value)} placeholder="#PR" aria-label="Link PR number" disabled={!proj} />
          <button type="submit" className="btn is-sm" disabled={!proj || !pr.trim()}>Link PR</button>
          {!proj && <span className="muted mono-xs">this project has no repo in ccd</span>}
        </form>
        {t.links.filter((l) => l.kind !== "pr").map((l) => <div key={`${l.provider}:${l.ref}`} className="rel">
          <span className="caps muted">{l.kind.replace("_", " ")}</span><span className="mono">{l.ref}</span>
          <span className="muted trunc">{l.provider}</span><span /></div>)}
        <div className="rel"><span className="caps muted">Agent</span>
          {agent ? <><span className="mono">{agent.agent_name || agent.id}</span><AgentState status={agent.status} />
            <button type="button" className="btn is-sm" onClick={() => openAgent(agent.id)}>Open</button></>
            : <><span className="muted">none linked</span><span /><span /></>}</div>
        {dispatchable && <Dispatch t={t} coordinatorStatus={coord!.status} name={coord!.name} />}
      </section>

      <section aria-label="Relations">
        <div className="td-sec-title">Relations</div>
        {t.parent && <div className="rel"><span className="caps muted">Parent</span><a className="key" href={href("tasks", t.parent)}>{t.parent}</a><span /><span /></div>}
        {(["blocked_by", "blocks", "related", "duplicates", "duplicated_by"] as const).flatMap((k) => t.relations[k].map((r) =>
          <div key={`${k}:${r.key}`} className="rel"><span className="caps muted">{k.replace("_", " ")}</span>
            <a className="key" href={href("tasks", r.key)}>{r.key}</a><span className="row trunc"><StateText status={r.status} /><span className="trunc text2">{r.title}</span></span>
            {k !== "duplicated_by" && <button type="button" className="btn is-quiet is-sm" aria-label={`Remove ${k} ${r.key}`}
              onClick={() => app.mutate(() => app.api.relate(t.key, k, r.key, true))}>×</button>}</div>))}
        <form className="row" style={{ marginTop: 6 }} onSubmit={(e) => { e.preventDefault(); const target = rel.target.trim().toUpperCase(); if (!target) return;
          void app.mutate(() => app.api.relate(t.key, rel.kind, target), `${rel.kind.replace("_", " ")} ${target}`).then(() => setRel({ ...rel, target: "" })); }}>
          <select className="select" value={rel.kind} onChange={(e) => setRel({ ...rel, kind: e.target.value })} aria-label="Relation">
            <option value="blocked_by">blocked by</option><option value="blocks">blocks</option><option value="related">related to</option>
            <option value="duplicates">duplicates</option><option value="parent">child of</option></select>
          <input className="input" style={{ width: 120 }} value={rel.target} placeholder="KEY-123" aria-label="Other ticket key"
            onChange={(e) => setRel({ ...rel, target: e.target.value })} />
          <button type="submit" className="btn is-sm" onClick={(e) => { if (rel.kind === "parent") { e.preventDefault();
            const target = rel.target.trim().toUpperCase(); if (target) void upd({ parent: target }, `parent ${target}`); } }}>Add</button>
          {t.parent && <button type="button" className="btn is-quiet is-sm" onClick={() => upd({ parent: null })}>Clear parent</button>}
        </form>
      </section>

      <section aria-label="Subtasks">
        <div className="td-sec-title">Subtasks <span className="mono-xs">{t.subtasks.done}/{t.subtasks.total}</span>
          <button type="button" className="btn is-quiet is-sm" onClick={() => setSub(true)}>+ Subtask</button></div>
        {t.subtaskList.map((s) => <div key={s.key} className="rel"><StateText status={s.status} code /><a className="key" href={href("tasks", s.key)}>{s.key}</a>
          <span className="trunc">{s.title}</span><Assignee value={s.assignee} compact /></div>)}
        {!t.subtaskList.length && <div className="faint mono-xs">none</div>}
      </section>

      <section aria-label="Activity and notes">
        <div className="td-sec-title">Activity</div>
        <ol className="tl">{items.map((it) => it.kind === "comment"
          ? <li key={it.id} className="comment"><div className="comment-head"><span className={`av ${it.actor === "jay" ? "av-human" : "av-agent"}`} aria-hidden>{it.actor === "jay" ? "J" : "◆"}</span>
              <b>{it.actor === "jay" ? "Jay" : it.actor}</b><span className="muted">noted</span><span style={{ marginLeft: "auto" }}><Ago at={it.at} /></span></div>
              <div className="comment-body">{it.body}</div></li>
          : <li key={it.id} className={`tl-item${it.ev!.actor.startsWith("system:") ? " is-auto" : ""}`}><span className="tick" aria-hidden />
              <span className="tl-sys"><span className="who">{who(it.ev!.actor)}</span> {describe(it.ev!)}
                {it.ev!.trigger && <span className="tl-trigger">trigger: {it.ev!.trigger}</span>}</span><Ago at={it.at} /></li>)}</ol>
        <form style={{ display: "grid", gap: 6, marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); if (!note.trim()) return;
          void app.mutate(() => app.api.comment(t.key, note), "Note added").then(() => setNote("")); }}>
          <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note…" aria-label="Add a note"
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); (e.currentTarget.form as HTMLFormElement).requestSubmit(); } }} />
          <div className="row"><button type="submit" className="btn is-sm" disabled={!note.trim()}>Add note</button><span className="muted mono-xs">Ctrl+Enter</span>
            <span style={{ marginLeft: "auto" }}><button type="button" className="btn is-quiet is-sm" onClick={() => upd({ archived: !t.archived }, t.archived ? "Restored" : "Archived")}>
              {t.archived ? "Restore" : "Archive"}</button></span></div>
        </form>
      </section>
    </div>
    {sub && <NewTicket onClose={() => setSub(false)} defaults={{ parent: t.key, project: t.project }} />}
  </aside>;
}

function BranchField({ value, onSave }: { value: string | null; onSave: (v: string | null) => void }) {
  const [v, setV] = useState(value ?? "");
  useEffect(() => setV(value ?? ""), [value]);
  return <input className="input mono" value={v} onChange={(e) => setV(e.target.value)} aria-label="Branch" placeholder="—"
    onBlur={() => { if ((v || null) !== value) onSave(v || null); }} />;
}

function Dispatch({ t, coordinatorStatus, name }: { t: TicketDetail; coordinatorStatus: string; name: string }) {
  const [verb, setVerb] = useState<(typeof DISPATCH_VERBS)[number]>("plan");
  const [confirm, setConfirm] = useState(false);
  const [note, setNote] = useState("");
  const idle = ["idle", "done"].includes(coordinatorStatus);
  return <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
    <div className="rel"><span className="caps muted">Dispatch</span><span className="mono">{name}</span><AgentState status={coordinatorStatus} /><span /></div>
    {!confirm ? <div className="row">
      <select className="select" value={verb} onChange={(e) => setVerb(e.target.value as typeof verb)} aria-label="Dispatch verb">
        {DISPATCH_VERBS.map((v) => <option key={v} value={v}>{v}</option>)}</select>
      <button type="button" className="btn is-sm" disabled={!idle} onClick={() => setConfirm(true)}>Dispatch {t.key}…</button>
      {!idle && <span className="muted mono-xs">coordinator is {coordinatorStatus}; dispatch waits for idle</span>}
    </div> : <div className="panel" style={{ padding: 10, display: "grid", gap: 6 }}>
      <div>Send <b>{verb} {t.key}</b> to <span className="mono">{name}</span>. The message says it does not authorize merge, deploy, production, --apply, secrets or rule changes.</div>
      <input className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Optional one-line note" aria-label="Dispatch note" />
      <div className="row"><button type="button" className="btn is-primary is-sm" onClick={async () => {
        await app.action(() => app.api.dispatch(t.project, t.key, verb, note), `${verb} ${t.key} → ${name}`);
        setConfirm(false); void app.refreshTicket(t.key);
      }}>Send</button><button type="button" className="btn is-sm" onClick={() => setConfirm(false)}>Cancel</button></div>
    </div>}
    <Command cmd={`curl -s -H "X-CCD-Token: $(cat ~/.config/command-center/ccd.token)" -H "Host: 127.0.0.1:7777" http://127.0.0.1:7777/api/tasks/${t.key}/context`} />
  </div>;
}

interface TlItem { id: string; at: number; kind: "event" | "comment"; actor: string; body?: string; ev?: TimelineEvent }
function timeline(t: TicketDetail): TlItem[] {
  const out: TlItem[] = t.timeline.filter((e) => e.kind !== "commented").map((e) => ({ id: `e${e.id}`, at: e.at, kind: "event", actor: e.actor, ev: e }));
  t.comments.forEach((c) => out.push({ id: `c${c.id}`, at: c.at, kind: "comment", actor: c.author, body: c.body }));
  return out.sort((a, b) => a.at - b.at);
}
function who(actor: string) {
  return actor === "jay" ? "Jay" : actor === "system:automation" ? "automation" : actor.replace(/^agent:/, "");
}
export function describe(e: TimelineEvent): string {
  const v = (x: string | null) => (x == null || x === "" ? "—" : x.replace(/^"|"$/g, ""));
  switch (e.kind) {
    case "created": return `created ${e.to}`;
    case "status": return `status ${STATUS_META[e.from as TicketStatus]?.label ?? v(e.from)} → ${STATUS_META[e.to as TicketStatus]?.label ?? v(e.to)}`;
    case "assigned": return `assignee ${assigneeLabel(e.from)} → ${assigneeLabel(e.to)}`;
    case "flag": return `${FLAG_LABEL[e.field ?? ""] ?? e.field} ${e.to === "true" ? "set" : "cleared"}`;
    case "label_added": return `label +${v(e.to)}`;
    case "label_removed": return `label −${v(e.from)}`;
    case "relation_added": return `${(e.field ?? "").replace("_", " ")} ${v(e.to)}`;
    case "relation_removed": return `removed ${(e.field ?? "").replace("_", " ")} ${v(e.from)}`;
    case "linked": return `linked ${e.field} ${v(e.to)}`;
    case "unlinked": return `unlinked ${e.field} ${v(e.from)}`;
    case "parent": return e.to ? `parent → ${v(e.to)}` : "parent cleared";
    case "archived": return e.to === "true" ? "archived" : "restored";
    case "attachment_added": return `attached ${v(e.to)}`;
    case "attachment_removed": return `removed attachment ${v(e.from)}`;
    default:
      // Every pipeline step records its own sentence (ccd/pipeline.py), including ones added later.
      if (e.kind.startsWith("pipeline.")) return e.trigger ?? e.kind.slice(9).replaceAll("_", " ");
      if (e.field === "description") return "edited the description";
      if (e.field === "title") return `renamed to “${v(e.to)}”`;
      return `${e.field} ${v(e.from)} → ${v(e.to)}`;
  }
}
