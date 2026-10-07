// QUESTIONS FOR JAY (spec §9): Claude's open questions, one field each, and one Submit. The last
// answer resumes the SAME task Claude session (ccd: POST /api/tasks/{key}/answers); a tick says the
// answers change scope / architecture / security, which sends the ticket back to Planning first.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import type { AnswersResult, Question, TicketWork } from "../api/types";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";
import { Ago } from "../components/ui";

export function QuestionsForm({ ticketKey, work, onDone, compact = false }: {
  ticketKey: string; work: TicketWork; onDone: (w: TicketWork) => void; compact?: boolean;
}) {
  const dev = useDevActive();
  const open = (work.questions ?? []).filter((q) => q.answer === null);
  const [vals, setVals] = useState<Record<number, string>>({});
  const [other, setOther] = useState<Record<number, boolean>>({});
  const [scope, setScope] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AnswersResult | null>(null);
  useEffect(() => { setResult(null); }, [ticketKey]);

  const set = (id: number, v: string) => setVals((m) => ({ ...m, [id]: v }));
  const value = (q: Question) => (other[q.id] ? `Other: ${vals[q.id] ?? ""}`.trim() : (vals[q.id] ?? "")).trim();
  const filled = open.filter((q) => value(q) && value(q) !== "Other:");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!dev) { unlockDialogOpen(); return; }
    setBusy(true);
    try {
      const r = await app.api.answers(ticketKey, filled.map((q) => ({ id: q.id, answer: value(q) })), scope);
      // The scope tick belongs to the batch: it stays until the last answer goes in with it.
      setResult(r); setVals({}); setOther({}); if (r.complete) setScope(false);
      onDone(r.work);
      app.toast(r.complete ? (r.delivered ? `Answers sent — ${ticketKey.toLowerCase()} continues${r.replanned ? " (back to planning)" : ""}`
        : "Answers saved — Claude was not reached") : `${filled.length} answer${filled.length === 1 ? "" : "s"} saved`, r.complete && !r.delivered ? "bad" : "ok");
    } catch (ex) {
      app.toast((ex as Error).message, "bad");
    } finally { setBusy(false); }
  };

  const resend = async () => {
    if (!dev) { unlockDialogOpen(); return; }
    setBusy(true);
    try { const r = await app.api.answers(ticketKey, []); setResult(r); onDone(r.work);
      app.toast(r.delivered ? "Answers sent to Claude" : `Not delivered: ${r.reason}`, r.delivered ? "ok" : "bad"); }
    catch (ex) { app.toast((ex as Error).message, "bad"); } finally { setBusy(false); }
  };

  if (!open.length) {
    return <div className="qs-done">
      {result && !result.delivered && result.complete ? <div className="qs-undelivered" role="status">
        <b>Answers saved.</b> <span className="muted">Claude was not reached: {result.reason}.</span>
        <button type="button" className="btn is-sm" disabled={busy} onClick={() => void resend()}>Resend to Claude</button>
      </div> : <span className="muted">No open questions.</span>}
    </div>;
  }
  return <form className={`qs${compact ? " is-compact" : ""}`} onSubmit={submit} aria-label={`Questions on ${ticketKey}`}>
    <div className="qs-head"><b>Claude needs {open.length} answer{open.length === 1 ? "" : "s"}</b></div>
    {open.map((q, i) => <div key={q.id} className="qs-item">
      <label className="qs-q" htmlFor={`q-${q.id}`}><span className="qs-n">{i + 1}</span>{q.text}</label>
      {q.kind === "choice" ? <select id={`q-${q.id}`} className="select" value={vals[q.id] ?? ""} onChange={(e) => set(q.id, e.target.value)}>
        <option value="">Select an option…</option>{q.options.map((o) => <option key={o} value={o}>{o}</option>)}</select>
        : q.kind === "yesno" ? <div className="qs-yn" role="radiogroup" aria-label={q.text}>
          {["Yes", "No"].map((o) => <label key={o} className="qs-radio"><input type="radio" name={`q-${q.id}`} checked={!other[q.id] && vals[q.id] === o}
            onChange={() => { setOther((m) => ({ ...m, [q.id]: false })); set(q.id, o); }} />{o}</label>)}
          <label className="qs-radio"><input type="radio" name={`q-${q.id}`} checked={!!other[q.id]}
            onChange={() => { setOther((m) => ({ ...m, [q.id]: true })); set(q.id, ""); }} />Other (specify)</label>
          {other[q.id] && <input id={`q-${q.id}`} className="input" value={vals[q.id] ?? ""} onChange={(e) => set(q.id, e.target.value)}
            placeholder="Your answer…" aria-label={`${q.text} — other`} />}
        </div>
          : <textarea id={`q-${q.id}`} className="input qs-text" rows={2} value={vals[q.id] ?? ""} placeholder="Type your answer…"
            onChange={(e) => set(q.id, e.target.value)} />}
    </div>)}
    <label className="qs-scope"><input type="checkbox" checked={scope} onChange={(e) => setScope(e.target.checked)} />
      These answers change the approved scope, architecture, security, data model, auth or major UX direction</label>
    <button type="submit" className="btn is-primary qs-submit" disabled={busy || !filled.length}>
      {filled.length && filled.length < open.length ? `Save ${filled.length} answer${filled.length === 1 ? "" : "s"}` : "Submit Answers"}</button>
    {!dev && <div className="mono-xs muted">Sending answers to Claude needs Developer Mode (once per session).</div>}
  </form>;
}

export function AnsweredList({ questions }: { questions: Question[] }) {
  const done = questions.filter((q) => q.answer !== null);
  if (!done.length) return null;
  return <ul className="qs-history" aria-label="Answered questions">
    {done.map((q) => <li key={q.id}><div>{q.text}</div><div className="qs-a">→ {q.answer} <Ago at={q.answeredAt} /></div></li>)}
  </ul>;
}
