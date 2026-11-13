// My Office › Where we are: each project's milestones on two tracks (GET /api/milestones). Technical is engineering
// work; Real life is the work outside the code (contact the lawyer, send the email to the client). One line per track
// says how far along it is and what is in hand; Edit opens the lists. Jay changes anything; a project's lead adds and
// moves its own technical ones through scripts/cc-milestone, and they appear here by themselves. Nothing here decides
// a state: it shows what was set.
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import "./hqnext.css";
import { app } from "../../store/app";
import { ApiError } from "../../api/client";
import type { Milestone, MilestoneState, MilestoneTrack, ProjectMilestones } from "../../api/types";
import { ago } from "../../lib/time";
import { dueLabel, isoDay, trackSummary, type TrackSummary } from "../data";
import { Icon } from "../frame/icons";
import { ProjectLogo } from "../logos";
import { loadMessage, useLoad, usePulse } from "./load";
import { cx } from "./ui";

const TRACKS: { track: MilestoneTrack; title: string; hint: string; example: string }[] = [
  { track: "technical", title: "Technical", hint: "Engineering work", example: "Set up the back end" },
  { track: "business", title: "Real life", hint: "Outside the code", example: "Contact the lawyer" },
];
const STATES: [MilestoneState, string][] = [["todo", "To do"], ["doing", "Doing"], ["done", "Done"]];

function TrackLine({ title, s }: { title: string; s: TrackSummary }) {
  return <div className="hq-ms-track">
    <small>{title}</small>
    {s.total === 0 ? <span className="hq-dim">No milestones yet</span> : <>
      <span className="hq-ms-bar" role="img" aria-label={`${s.done} of ${s.total} done`}><i style={{ width: `${(s.done / s.total) * 100}%` }} /></span>
      <span className="hq-ms-count" aria-hidden>{s.done} of {s.total}</span>
      <span className="hq-ms-now hq-ellip" title={s.current?.title}>
        {s.current ? <><em>{s.label}</em> {s.current.title}
          {s.current.due && <span className={s.overdue ? "t-bad" : "hq-dim"}> · {s.overdue ? "overdue" : "due"} {dueLabel(s.current.due)}</span>}</>
          : "All done"}</span>
    </>}
  </div>;
}

/** A milestone with the project it belongs to, so a row can name its own route. */
type Row = Milestone & { projectKey: string };
type Patch = Parameters<typeof app.api.milestoneChange>[2];

/** A control that cannot act right now stays focusable: aria-disabled, never disabled. A write disables the row's
 *  controls while it runs, and a disabled control drops the keyboard's focus to the top of the page. */
const off = (is: boolean) => ({ "aria-disabled": is || undefined });

function Item({ m, i, last, busy, today, now, run, move, onGone }: {
  m: Row; i: number; last: boolean; busy: boolean; today: string; now: number;
  run: (fn: () => Promise<unknown>) => Promise<boolean>; move: (i: number, by: -1 | 1) => void; onGone: () => void;
}) {
  const [edit, setEdit] = useState(false);
  const [sure, setSure] = useState(false);
  const [title, setTitle] = useState(m.title), [due, setDue] = useState(m.due ?? ""), [note, setNote] = useState(m.note ?? "");
  /** The milestone as it was when the form opened: what Jay's changes are measured against. */
  const base = useRef(m);
  const pencil = useRef<HTMLButtonElement>(null), wasEdit = useRef(false);
  // closing the form puts focus back on the button that opened it
  useEffect(() => { if (wasEdit.current && !edit) pencil.current?.focus(); wasEdit.current = edit; }, [edit]);
  const open = () => { if (busy) return; base.current = m; setTitle(m.title); setDue(m.due ?? ""); setNote(m.note ?? ""); setEdit(true); };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !title.trim()) return;
    // Only what Jay changed in this form. A field he left alone may have been changed by the lead since it opened.
    const was = base.current, patch: Patch = {};
    if (title.trim() !== was.title) patch.title = title.trim();
    if ((due || null) !== was.due) patch.due = due || null;
    if ((note.trim() || null) !== was.note) patch.note = note.trim() || null;
    if (!Object.keys(patch).length || await run(() => app.api.milestoneChange(m.projectKey, m.id, patch))) setEdit(false);
  };
  if (edit) return <li className="hq-ms-item is-edit">
    <form onSubmit={save}>
      <input className="hq-ms-in" aria-label="Title" maxLength={140} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
      <input className="hq-ms-in is-date" type="date" aria-label="Due date" value={due} onChange={(e) => setDue(e.target.value)} />
      <textarea className="hq-ms-in" aria-label="Note" maxLength={500} rows={2} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <span className="hq-ms-acts"><button type="submit" className="hq-btn is-primary" {...off(busy || !title.trim())}>Save</button>
        <button type="button" className="hq-btn" onClick={() => setEdit(false)}>Cancel</button></span>
    </form>
  </li>;
  const late = m.state !== "done" && !!m.due && m.due < today;
  return <li className={cx("hq-ms-item", `is-${m.state}`)} data-ms={m.id}>
    <select aria-label={`State of ${m.title}`} value={m.state} {...off(busy)}
      onChange={(e) => { if (!busy) void run(() => app.api.milestoneChange(m.projectKey, m.id, { state: e.target.value as MilestoneState })); }}>
      {STATES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    <span className="hq-ms-text"><b>{m.title}</b>
      {(m.due || m.doneAt || m.by.startsWith("agent:")) && <small>
        {[m.state === "done" && m.doneAt ? (now - m.doneAt < 60 ? "Done just now" : `Done ${ago(m.doneAt, now)} ago`) : null,
          m.state !== "done" && m.due ? `${late ? "Overdue" : "Due"} ${dueLabel(m.due)}` : null,
          m.by.startsWith("agent:lead-") ? "Added by the lead" : m.by.startsWith("agent:") ? "Added by an agent" : null]
          .filter(Boolean).map((t, k) => <span key={k} className={late && t!.startsWith("Overdue") ? "t-bad" : undefined}>{t}</span>)}</small>}
      {m.note && <small className="hq-ms-note">{m.note}</small>}</span>
    <span className="hq-ms-acts">
      <button type="button" className="hq-icon-btn" data-act="up" aria-label={`Move ${m.title} up`} {...off(busy || i === 0)}
        onClick={() => { if (!busy && i > 0) move(i, -1); }}><Icon name="up" size={16} /></button>
      <button type="button" className="hq-icon-btn" data-act="down" aria-label={`Move ${m.title} down`} {...off(busy || last)}
        onClick={() => { if (!busy && !last) move(i, 1); }}><Icon name="down" size={16} /></button>
      <button type="button" ref={pencil} className="hq-icon-btn" aria-label={`Edit ${m.title}`} {...off(busy)} onClick={open}><Icon name="pencil" size={16} /></button>
      {/* One button for both steps, so the second press needs no hunting and focus never leaves it. */}
      <button type="button" className={sure ? "hq-btn is-danger" : "hq-icon-btn"} {...off(busy)} onBlur={() => setSure(false)}
        aria-label={sure ? `Confirm: remove ${m.title}` : `Remove ${m.title}`}
        onClick={() => {
          if (busy) return;
          if (!sure) return setSure(true);
          void run(() => app.api.milestoneRemove(m.projectKey, m.id)).then((ok) => { if (ok) onGone(); });
        }}>{sure ? "Remove?" : <Icon name="trash" size={16} />}</button>
    </span>
  </li>;
}

function Track({ project, t, list, revision, today, now, onChange }: {
  project: string; t: typeof TRACKS[number]; list: Milestone[]; revision: number; today: string; now: number; onChange: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState(""), [due, setDue] = useState("");
  const col = useRef<HTMLElement>(null), newTitle = useRef<HTMLInputElement>(null);
  /** The move button to put focus back on once ccd's list is on the page: reordering moves the row in the DOM. */
  const refocus = useRef<string | null>(null);
  useEffect(() => {
    if (!refocus.current) return;
    col.current?.querySelector<HTMLElement>(refocus.current)?.focus();
    refocus.current = null;
  }, [list]);
  /** One write, then ccd's list again whether it worked or not, so the page never shows a change ccd did not make. */
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); setError(null); return true; }
    catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? "This list changed somewhere else. It has been reloaded; try again."
        : (e as Error).message);
      return false;
    } finally { await onChange(); setBusy(false); }
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !title.trim()) return;
    if (await run(() => app.api.milestoneAdd(project, { track: t.track, title: title.trim(), due: due || null }))) {
      setTitle(""); setDue("");
      newTitle.current?.focus();   // ready for the next one; the Add button is about to be disabled (nothing typed)
    }
  };
  const move = (i: number, by: -1 | 1) => {
    const ids = list.map((m) => m.id);
    refocus.current = `[data-ms="${ids[i]}"] [data-act="${by < 0 ? "up" : "down"}"]`;
    [ids[i], ids[i + by]] = [ids[i + by], ids[i]];
    void run(() => app.api.milestoneOrder(project, t.track, ids, revision));
  };
  const rows: Row[] = list.map((m) => ({ ...m, projectKey: project }));
  return <section className="hq-ms-col" aria-label={`${t.title} milestones`} ref={col}>
    <h4>{t.title} <small>{t.hint}</small></h4>
    {rows.length ? <ol>{rows.map((m, i) => <Item key={m.id} m={m} i={i} last={i === rows.length - 1} busy={busy} today={today} now={now}
      run={run} move={move} onGone={() => newTitle.current?.focus()} />)}</ol>
      : <p className="hq-empty">None yet.</p>}
    {error && <p className="hq-note t-bad" role="alert">{error}</p>}
    <form className="hq-ms-add" onSubmit={add}>
      <input ref={newTitle} className="hq-ms-in" aria-label={`New ${t.title.toLowerCase()} milestone`} placeholder={`For example: ${t.example}`} maxLength={140}
        value={title} onChange={(e) => setTitle(e.target.value)} />
      <input className="hq-ms-in is-date" type="date" aria-label="Due date (optional)" value={due} onChange={(e) => setDue(e.target.value)} />
      <button type="submit" className="hq-btn" disabled={!title.trim()} {...off(busy)}>Add</button>
    </form>
  </section>;
}

export function Milestones({ projects, now }: { projects: { key: string; name: string }[]; now: Date }) {
  const get = useCallback(() => app.api.milestones(), []);
  const { data, error, reload } = useLoad(get, usePulse(["milestone."]));
  const [open, setOpen] = useState<string | null>(null);
  const today = isoDay(now), nowS = now.getTime() / 1000;
  // My Office's own project order first, then any other project ccd keeps milestones for.
  const known = new Set(projects.map((p) => p.key));
  const rows: { key: string; name: string; m: ProjectMilestones }[] = data ? [
    ...projects.filter((p) => data.projects[p.key]).map((p) => ({ ...p, m: data.projects[p.key] })),
    ...Object.keys(data.projects).filter((k) => !known.has(k)).map((k) => ({ key: k, name: k, m: data.projects[k] })),
  ] : [];
  return <section className="hq-panel hq-ms" aria-labelledby="hq-office-ms">
    <header><h3 id="hq-office-ms">Where we are <small>Technical and real-life milestones for each project</small></h3></header>
    {error && data && <p className="hq-note" role="status">Not updated just now ({error.message}). Showing ccd's last answer.</p>}
    {error && !data ? <p className="hq-note" role={error.status === 404 ? undefined : "alert"}>{loadMessage(error, "milestones")}</p>
      : !data ? <p className="hq-empty">Loading…</p>
      : !rows.length ? <p className="hq-empty">No projects reported yet.</p>
      : <ul className="hq-ms-list">{rows.map(({ key, name, m }) => {
        const on = open === key, total = m.technical.length + m.business.length;
        return <li key={key} className={cx("hq-ms-proj", on && "is-open")} style={{ ["--pj" as string]: `var(--hq-pj-${key}, var(--hq-accent))` }}>
          <div className="hq-ms-row">
            <b className="hq-ms-name hq-with-logo"><ProjectLogo project={key} /><span className="hq-ellip">{name}</span></b>
            {TRACKS.map((t) => <TrackLine key={t.track} title={t.title} s={trackSummary(m[t.track], today)} />)}
            <button type="button" className="hq-btn" aria-expanded={on} aria-controls={`hq-ms-${key}`}
              aria-label={`${on ? "Close" : total ? "Edit" : "Add"} ${name} milestones`} onClick={() => setOpen(on ? null : key)}>
              {on ? "Close" : total ? "Edit" : "Add"}</button>
          </div>
          {on && <div className="hq-ms-edit" id={`hq-ms-${key}`}>
            {TRACKS.map((t) => <Track key={t.track} project={key} t={t} list={m[t.track]} revision={m.revision} today={today} now={nowS} onChange={reload} />)}
          </div>}
        </li>;
      })}</ul>}
  </section>;
}
