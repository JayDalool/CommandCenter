// CC-100: a ticket's acceptance criteria, requirements, size and due date on its HQ page, and the editor for them.
// It saves through the existing criteria work op (POST /api/tasks/{key}/work/criteria); ccd stays the only enforcer
// and the checks here are a convenience in front of it: they stop a save that ccd would refuse and say why.
// Priority is not here: the pane's own Priority select already changes it (it needs no Developer Unlock).
import { useEffect, useRef, useState } from "react";
import { app } from "../store/app";
import { ApiError } from "../api/client";
import { developer } from "../api/developer";
import { devOr, useDevActive } from "../components/DevMode";
import { useWork } from "./useWork";
import type { Criterion, TicketDetail, TicketSize } from "../api/types";

const MAX_CRITERIA = 20;      // ccd's flow.MAX_CRITERIA and MAX_REQUIREMENTS
const MAX_REQUIREMENTS = 20;
const SIZES: TicketSize[] = ["small", "standard", "risky"];
const CLOSED = ["DONE", "CANCELLED", "DENIED"];
const STATE_WORD = { open: "Not checked", pass: "Passed", fail: "Failed" } as const;

interface Row { k: number; id: string | null; text: string }
let seq = 0;
const rowOf = (id: string | null, text: string): Row => ({ k: ++seq, id, text });

const localDay = (at: number | null | undefined) => (at ? new Date(at * 1000).toLocaleDateString("en-CA") : "");
const today = () => new Date().toLocaleDateString("en-CA");
const same = (a: unknown[], b: unknown[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** ccd's rule for "past investigation" (pipeline.define: not INBOX/PROPOSED, not a plan still in investigation). */
const early = (status: string, stage: string | null | undefined) =>
  status === "INBOX" || status === "PROPOSED" || (status === "RESEARCHING" && stage === "investigate");

const PAST_LINE = "This ticket is past investigation. Only you change its scope now, with Developer Unlock. Nothing was saved.";
const LOWER_LINE = "Lowering a risky ticket needs Developer Unlock. Nothing was saved.";

export function ScopeEditor({ t }: { t: TicketDetail }) {
  const [work, setWork] = useWork(t.key);
  const unlocked = useDevActive();
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [reqs, setReqs] = useState<Row[]>([]);
  const [size, setSize] = useState<TicketSize | "">("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // CC-100: the ticket the draft was made for. The pane reuses this component when Jay moves to another ticket, and a
  // draft once went to the wrong ticket; the mount is keyed by ticket and every send names this key and re-checks it.
  const draftKey = useRef(t.key);
  const editBtn = useRef<HTMLButtonElement>(null);
  const focusRow = useRef<number | null>(null);
  const refocus = useRef(false);
  const inputs = useRef(new Map<number, HTMLInputElement>());

  useEffect(() => {
    if (focusRow.current != null) { inputs.current.get(focusRow.current)?.focus(); focusRow.current = null; }
  });
  useEffect(() => { if (!editing && refocus.current) { refocus.current = false; editBtn.current?.focus(); } }, [editing]);

  if (!work || CLOSED.includes(work.status)) return null;
  const crit: Criterion[] = work.criteria ?? [];
  const wReqs = work.requirements ?? [];
  const isEarly = early(work.status, work.flow?.stage);
  const dueNow = localDay(t.dueAt);

  const open = () => {
    setRows(crit.map((c) => rowOf(c.id, c.text)));
    setReqs(wReqs.map((r) => rowOf(null, r)));
    setSize(work.size ?? "");
    setDue(dueNow);
    setNote(null);
    draftKey.current = t.key;
    setEditing(true);
  };
  const close = () => { refocus.current = true; setEditing(false); setNote(null); };

  // Small only exists before investigation (ccd 409s past intake); a ticket already small keeps its own option.
  const sizes = SIZES.filter((s) => s !== "small" || work.status === "INBOX" || work.status === "PROPOSED" || work.size === "small");

  const addRow = (list: Row[], set: (r: Row[]) => void, max: number) => {
    if (list.length >= max) return;
    const r = rowOf(null, "");
    set([...list, r]);
    focusRow.current = r.k;
  };

  const save = () => {
    const kept = rows.map((r) => ({ ...r, text: r.text.trim() })).filter((r) => r.text);
    const newReqs = reqs.map((r) => r.text.trim()).filter(Boolean);
    if (!kept.length && work.size) { setNote("A ticket keeps at least one acceptance criterion."); return; }
    if (due && due < today()) { setNote("The due date cannot be in the past."); return; }
    const body: Record<string, unknown> = {};
    const criteriaChanged = kept.length !== crit.length || kept.some((r, i) => r.id !== crit[i].id || r.text !== crit[i].text);
    if (criteriaChanged) body.criteria = kept.map((r) => (r.id ? { id: r.id, text: r.text } : r.text));
    if (!same(newReqs, wReqs)) body.requirements = newReqs;
    const sizeChanged = !!size && size !== work.size;
    if (sizeChanged) body.size = size;
    if (due && due !== dueNow) body.due = due;     // no way to clear a due date: ccd takes a date or nothing
    if (!Object.keys(body).length) { close(); return; }

    const touchesScope = criteriaChanged || "requirements" in body || sizeChanged;
    const lowersRisky = sizeChanged && work.size === "risky" && size !== "risky";
    const needsUnlock = (touchesScope && !isEarly) || lowersRisky;
    // Nothing is sent without Unlock; once Jay unlocks, the same save runs again, once.
    if (needsUnlock && !developer.get().active) {
      setNote(lowersRisky && isEarly ? LOWER_LINE : PAST_LINE);
      devOr(() => void send(body));
      return;
    }
    void send(body);
  };

  const send = async (body: Record<string, unknown>) => {
    const key = draftKey.current;
    if (key !== t.key) { setNote("This draft was made for another ticket and was not sent."); return; }
    setBusy(true);
    try {
      const next = await app.api.workOp(key, "criteria", body);
      setWork(next);
      app.toast(`${key}: scope saved`);
      close();
    } catch (e) {
      // ccd writes nothing on a refusal, and Jay's edits stay in the form so he can retry or copy them.
      const m = e instanceof Error ? e.message : String(e);
      setNote(e instanceof ApiError && e.status === 403 && m.startsWith("Developer Unlock") ? PAST_LINE : `${m}. Nothing was saved.`);
    } finally { setBusy(false); }
  };

  if (!editing) {
    return <section aria-label="Acceptance criteria" className="td-crit">
      <div className="td-sec-title">Acceptance criteria <button type="button" ref={editBtn} className="btn is-quiet is-sm" onClick={open}>Edit</button></div>
      {crit.length ? <ol className="td-crit-list" aria-label="Criteria">{crit.map((c) => <li key={c.id}>
        <span className="mono-xs muted">{c.id}</span><span className="td-crit-text">{c.text}</span>
        <span className={`mono-xs ${c.state === "pass" ? "ok-t" : c.state === "fail" ? "bad-t" : "faint"}`}>{STATE_WORD[c.state]}</span></li>)}</ol>
        : <p className="muted">No acceptance criteria yet.</p>}
      {wReqs.length > 0 && <><div className="td-sec-title" style={{ marginTop: 10 }}>Requirements</div>
        <ul className="td-crit-list is-plain">{wReqs.map((r, i) => <li key={i}><span className="td-crit-text">{r}</span></li>)}</ul></>}
      <div className="mono-xs muted" style={{ marginTop: 8 }}>Size {work.size ?? "not set"} · Due {dueNow || "not set"}</div>
    </section>;
  }

  const rowInputs = (list: Row[], set: (r: Row[]) => void, max: number, label: (r: Row, i: number) => string, len: number) =>
    list.map((r, i) => <div className="td-crit-row" key={r.k}>
      {r.id && <span className="mono-xs muted td-crit-id">{r.id}</span>}
      <input className="input grow" value={r.text} maxLength={len} aria-label={label(r, i)}
        ref={(el) => { if (el) inputs.current.set(r.k, el); else inputs.current.delete(r.k); }}
        onChange={(e) => set(list.map((x) => (x.k === r.k ? { ...x, text: e.target.value } : x)))}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {      // Enter walks to the next row, or adds one at the end
            e.preventDefault();
            const nxt = list[i + 1];
            if (nxt) inputs.current.get(nxt.k)?.focus(); else addRow(list, set, max);
          }
        }} />
      <button type="button" className="btn is-sm" aria-label={`Remove ${label(r, i)}`}
        onClick={() => set(list.filter((x) => x.k !== r.k))}>Remove</button>
    </div>);

  return <section aria-label="Acceptance criteria" className="td-crit">
    <div className="td-sec-title">Acceptance criteria</div>
    <form className="stack" style={{ gap: 8 }} noValidate data-scope-editing=""
      onSubmit={(e) => { e.preventDefault(); if (!busy) save(); }}
      onKeyDown={(e) => {
        if (e.key === "Escape") { e.stopPropagation(); close(); }
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); (e.currentTarget as HTMLFormElement).requestSubmit(); }
      }}>
      {rowInputs(rows, setRows, MAX_CRITERIA, (r, i) => (r.id ? `Criterion ${r.id}` : `New criterion ${i + 1}`), 300)}
      <div><button type="button" className="btn is-sm" disabled={rows.length >= MAX_CRITERIA}
        onClick={() => addRow(rows, setRows, MAX_CRITERIA)}>Add criterion</button>
        <span className="muted mono-xs" style={{ marginLeft: 8 }}>{rows.length} of {MAX_CRITERIA}</span></div>
      <div className="muted mono-xs">Changing a criterion's text marks it Not checked again.</div>

      <div className="td-sec-title" style={{ marginTop: 6 }}>Requirements</div>
      {rowInputs(reqs, setReqs, MAX_REQUIREMENTS, (_r, i) => `Requirement ${i + 1}`, 500)}
      <div><button type="button" className="btn is-sm" disabled={reqs.length >= MAX_REQUIREMENTS}
        onClick={() => addRow(reqs, setReqs, MAX_REQUIREMENTS)}>Add requirement</button></div>

      <div className="td-crit-pair">
        <label className="stack" style={{ gap: 2 }}><span className="mono-xs muted">Size</span>
          <select className="select" value={size} aria-label="Size" onChange={(e) => setSize(e.target.value as TicketSize)}>
            {!size && <option value="">Not set</option>}
            {sizes.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
        <label className="stack" style={{ gap: 2 }}><span className="mono-xs muted">Due date</span>
          <input className="input" type="date" value={due} min={today()} aria-label="Due date" onChange={(e) => setDue(e.target.value)} />
          {!due && <span className="mono-xs muted">{dueNow ? `Left empty: the due date stays ${dueNow}.` : "Left empty: no due date is set."}</span>}</label>
      </div>

      {note && <div role="status" className="td-crit-note">{note}</div>}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button type="submit" className="btn is-primary is-sm" disabled={busy}>Save</button>
        <button type="button" className="btn is-sm" onClick={close}>Cancel</button>
        {note && !unlocked && <button type="button" className="btn is-jay is-sm" onClick={() => { if (devOr(save)) save(); }}>Developer Unlock</button>}
        <span className="muted mono-xs">Ctrl+Enter save · Esc cancel</span>
      </div>
    </form>
  </section>;
}
