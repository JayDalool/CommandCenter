// Answering a ticket's questions in place, in Decisions (contracts.md §4). Each open question shows its options as
// cards with the agent's recommended one first-class (marked, its reason under it, and picked to start with), plus two
// choices HQ always adds: "Something else" (Jay's own words) and "Talk it through" (a note to the project's lead in
// Messages naming the ticket, never the agent's text; nothing is answered). Sending is the same POST /api/tasks/{key}/answers as the Task
// Room's form, so Developer Unlock is needed as today. ccd delivers to the task's session, or to the lead when none
// is running, and the result says which.
import { useEffect, useState } from "react";
import { app } from "../../store/app";
import type { AnswersResult, Question } from "../../api/types";
import { unlockDialogOpen, useDevActive } from "../../components/DevMode";
import { useWork } from "../../tickets/useWork";
import { usePageNav } from "./route";
import { cx } from "./ui";

/** The question as ccd sends it. `recommended`/`why` arrived with multiple-choice questions; older ccds omit them. */
export type AskedQuestion = Question & { recommended?: number | null; why?: string | null };
type Result = AnswersResult & { deliveredTo?: "task" | "lead" | null };

const OTHER = -1;     // "Something else"
const TALK = -2;      // "Talk it through"

/** The choices a question offers, in order: the agent's options (choice) or Yes / No (yesno); a text question has none. */
export function choicesOf(q: AskedQuestion): string[] {
  return q.kind === "choice" ? q.options : q.kind === "yesno" ? ["Yes", "No"] : [];
}

/** The answer ccd stores for a pick. A yes/no question takes "Other: …" for Jay's own words. */
export function answerOf(q: AskedQuestion, pick: number | undefined, text: string): string {
  const own = text.trim();
  if (pick === undefined || pick === TALK) return "";
  if (pick === OTHER || !choicesOf(q).length) return own && q.kind === "yesno" ? `Other: ${own}` : own;
  return choicesOf(q)[pick] ?? "";
}

export function deliveredText(r: Result, project: string): string {
  if (!r.complete) return "Saved. Another question on this task is still open.";
  if (r.delivered) return r.deliveredTo === "lead" ? `Sent to the ${project} lead in Messages (no task session is running).`
    : "Sent to the task's Claude session.";
  return `Saved, not delivered yet: ${r.reason ?? "no session was reached"}.`;
}

export function AnswerInPlace({ ticket, project, projectName }: { ticket: string; project: string; projectName: string }) {
  const dev = useDevActive();
  const nav = usePageNav();
  const [work, setWork] = useWork(ticket);
  const qs = ((work?.questions ?? []) as AskedQuestion[]).filter((q) => q.answer === null);
  const stale = qs.filter((q) => q.purpose === "stale");
  const open = qs.filter((q) => q.purpose !== "stale");
  const [pick, setPick] = useState<Record<number, number>>({});
  const [text, setText] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);

  // The recommended option starts picked: when Jay agrees, one press sends it.
  const ids = open.map((q) => q.id).join(",");
  useEffect(() => {
    setPick((m) => {
      const next = { ...m };
      for (const q of open) {
        if (next[q.id] !== undefined) continue;
        if (typeof q.recommended === "number") next[q.id] = q.recommended;
        else if (!choicesOf(q).length) next[q.id] = OTHER;     // a text question: straight to the answer box
      }
      return next;
    });
  }, [ids]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!work) return <p className="hq-ans-note">Loading the questions…</p>;

  const ready = open.filter((q) => answerOf(q, pick[q.id], text[q.id] ?? ""));
  const run = async (fn: () => Promise<void>) => {
    if (!dev) { unlockDialogOpen(); return; }
    setBusy(true);
    try { await fn(); } catch (e) { setSaid({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  };
  const send = () => run(async () => {
    const r = await app.api.answers(ticket, ready.map((q) => ({ id: q.id, answer: answerOf(q, pick[q.id], text[q.id] ?? "") }))) as Result;
    setWork(r.work);
    setSaid({ ok: !r.complete || r.delivered, text: deliveredText(r, projectName) });
  });
  const decide = (q: AskedQuestion, answer: string) => run(async () => {
    const r = await app.api.answers(ticket, [{ id: q.id, answer }]);
    setWork(r.work);
    setSaid({ ok: true, text: r.cancelled ? `${ticket} cancelled.` : `${ticket} kept.` });
  });

  return <div className="hq-ans" aria-label={`Answer ${ticket}`}>
    {stale.map((q) => <div key={q.id} className="hq-ans-q">
      <p className="hq-ans-text">{q.text.replace(/^Task check: /, "")}</p>
      <div className="hq-ans-row">
        <button type="button" className="hq-btn is-primary" disabled={busy} onClick={() => void decide(q, "Cancel it")}>Cancel it</button>
        <button type="button" className="hq-btn" disabled={busy} onClick={() => void decide(q, "Keep it")}>Keep it</button>
      </div>
    </div>)}
    {open.map((q, i) => <Ask key={q.id} q={q} n={open.length > 1 ? i + 1 : null} pick={pick[q.id]} text={text[q.id] ?? ""}
      onPick={(v) => setPick((m) => ({ ...m, [q.id]: v }))} onText={(v) => setText((m) => ({ ...m, [q.id]: v }))}
      ticket={ticket} project={project} projectName={projectName} onTalked={() => nav.go("messages", null, { c: project })} />)}
    {open.length > 0 && <div className="hq-ans-row">
      <button type="button" className="hq-btn is-primary" disabled={busy || !ready.length} onClick={() => void send()}>
        {ready.length && ready.length < open.length ? `Send ${ready.length} of ${open.length} answers` : open.length > 1 ? "Send answers" : "Send answer"}</button>
      {!dev && <small className="hq-ans-note">Sending answers needs Developer Unlock (once per session).</small>}
    </div>}
    {!qs.length && !said && <p className="hq-ans-note">No open questions on {ticket} any more.</p>}
    {said && <p className={cx("hq-ans-note", said.ok ? "t-ok" : "t-bad")} role="status">{said.text}</p>}
  </div>;
}

function Ask({ q, n, pick, text, onPick, onText, ticket, project, projectName, onTalked }: {
  q: AskedQuestion; n: number | null; pick: number | undefined; text: string; onPick: (v: number) => void;
  onText: (v: string) => void; ticket: string; project: string; projectName: string; onTalked: () => void;
}) {
  const choices = choicesOf(q);
  const name = `ans-${q.id}`;
  const card = (v: number, label: string, extra?: React.ReactNode) => <label className={cx("hq-ans-opt", pick === v && "is-on",
    q.recommended === v && "is-rec")}>
    <input type="radio" name={name} checked={pick === v} onChange={() => onPick(v)} />
    <span><b>{label}</b>{extra}</span>
  </label>;
  return <fieldset className="hq-ans-q">
    <legend className="hq-ans-text">{n !== null && <span className="hq-ans-n">{n}</span>}{q.text}</legend>
    <div className="hq-ans-group" role="radiogroup" aria-label={q.text}>
      {choices.length > 0 && <div className="hq-ans-opts">{choices.map((o, j) => card(j, o, q.recommended === j && <>
        <em className="hq-ans-badge">Recommended</em>{q.why && <small>{q.why}</small>}</>))}</div>}
      <div className="hq-ans-more">
        {card(OTHER, choices.length ? "Something else" : "Your answer", <small>Write your own answer</small>)}
        {card(TALK, "Talk it through", <small>Ask the {projectName} lead in Messages first</small>)}
      </div>
    </div>
    {pick === OTHER && <textarea className="hq-ans-input" rows={2} value={text} placeholder="Your answer…"
      aria-label={`Your answer to: ${q.text}`} onChange={(e) => onText(e.target.value)} />}
    {pick === TALK && <Talk q={q} n={n} ticket={ticket} project={project} onSent={onTalked} />}
  </fieldset>;
}

/** A note to the project's lead about one question: fixed text, the ticket and Jay's own words. It answers nothing. */
function Talk({ q, n, ticket, project, onSent }: { q: AskedQuestion; n: number | null; ticket: string; project: string; onSent: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Stored as Jay's message, so it carries only fixed text and Jay's own note: the question and its options were
  // written by an agent and stay in the ticket, where the lead reads them as data.
  const body = [`About the open question${n !== null ? ` ${n}` : ""} on ${ticket} (read it with \`python -m ccd.pipeline_cli work ${ticket}\`):`,
    "", note.trim() || "I'd like to talk this through before I answer."].join("\n");
  const send = async () => {
    setBusy(true); setErr(null);
    try { await app.api.chatSend(project, body); onSent(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return <div className="hq-ans-talk">
    <textarea className="hq-ans-input" rows={2} value={note} placeholder="What do you want to ask or discuss? (optional)"
      aria-label={`Talk through: ${q.text}`} onChange={(e) => setNote(e.target.value)} />
    <div className="hq-ans-row">
      <button type="button" className="hq-btn" disabled={busy} onClick={() => void send()}>Send to the lead and open Messages</button>
      <small className="hq-ans-note">The question stays open until you answer it.</small>
    </div>
    {err && <p className="hq-ans-note t-bad" role="alert">{err}</p>}
  </div>;
}
