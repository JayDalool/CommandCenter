// One ticket in flight, opened in place on Teams: who is on it now, every stage with who did it and when, the
// history of handoffs, its acceptance criteria, and the way into its room, where its session runs. Read from the
// ticket's work state (GET /api/tasks/{key}/work). A ccd from before the new flow has five stages and no history
// line; nothing is filled in for it. This panel changes nothing.
import type { FlowStage, Handoff, PipelineStage, TicketWork } from "../../api/types";
import { taskHref } from "../../lib/control";
import { href } from "../../lib/router";
import { useEffect, useState } from "react";
import { useSelector } from "../../lib/store";
import { ago, stamp } from "../../lib/time";
import { loadWork, works } from "../../tickets/useWork";
import { PRESENCE_LABEL, SEAT_LABEL, STAGE_LABEL, type FlightRow, type RailStep } from "../data";
import { Pill, PRESENCE_TONE, cx } from "./ui";

interface Step { label: string; state: string; who: string | null; at: number | null }

/** A stage or seat this build has no word for (a newer ccd) shows as ccd names it, never as nothing. */
const stageName = (s: FlowStage) => STAGE_LABEL[s] ?? s;
const seatName = (s: keyof typeof SEAT_LABEL) => SEAT_LABEL[s] ?? s;

const STATE_WORD: Record<string, string> = { done: "Done", active: "Now", todo: "Not started", skipped: "Not on this route",
  blocked: "Blocked" };
/** ccd's five stages before the new flow, in the new words, with the role that reports at each. */
const OLD: [PipelineStage, FlowStage, "planner" | "implementer" | "reviewer" | "verifier" | null][] = [
  ["PLAN", "investigate", "planner"], ["BUILD", "build", "implementer"], ["REVIEW", "codeReview", "reviewer"],
  ["MERGE", "merge", null], ["VERIFY", "release", "verifier"]];
const OLD_SEAT = { planner: SEAT_LABEL.investigator, implementer: SEAT_LABEL.developer, reviewer: SEAT_LABEL.codeReviewer,
  verifier: SEAT_LABEL.verifier };

/** `rail` is where the ticket's status puts it: a ticket with no work recorded yet still has that. */
export function stepsOf(w: TicketWork, rail: RailStep[]): Step[] {
  if (w.flow) return w.flow.stages.map((s) => ({ label: stageName(s.stage), state: s.state, at: s.at,
    who: [s.seat ? seatName(s.seat) : null, s.session].filter(Boolean).join(" · ") || null }));
  return OLD.map(([stage, flow, role]) => {
    const r = role ? w.roles[role] : undefined;
    return { label: STAGE_LABEL[flow],
      state: w.stages.find((s) => s.stage === stage)?.state ?? rail.find((s) => s.stage === flow)?.state ?? "todo",
      who: role && r ? [OLD_SEAT[role], r.session].filter(Boolean).join(" · ") : null,
      at: role ? r?.at ?? null : w.merge?.at ?? null };
  });
}

export function handoffText(h: Handoff): string {
  const from = h.from ? seatName(h.from) : null, to = h.to ? seatName(h.to) : null, at = stageName(h.stage);
  const what = h.kind === "blocked" ? `Blocked at ${at}` : h.kind === "resumed" ? `Resumed at ${at}`
    : h.kind === "sentBack" ? `${from ?? at} sent it back${to ? ` to ${to}` : ""}` : `${from ?? "Start"} to ${to ?? at}`;
  return h.note ? `${what} · ${h.note}` : what;
}

const MARK = { pass: "Passed", fail: "Failed", open: "Not checked" } as const;

export function TicketFlowPanel({ r, now }: { r: FlightRow; now: number }) {
  const key = r.t.key;
  const w = useSelector(works, (d) => d[key]);
  // Loaded when the ticket is opened and again whenever it changes. loadWork records a ticket with no work as
  // "missing" and keeps what it had on any other failure, so "nothing yet" after it settles means it failed.
  const [failed, setFailed] = useState(false);
  const [tries, setTries] = useState(0);
  useEffect(() => {
    let on = true;
    setFailed(false);
    void loadWork(key).then(() => { if (on && works.get()[key] === undefined) setFailed(true); });
    return () => { on = false; };
  }, [key, r.t.updatedAt, tries]);
  const links = <p className="hq-tf-links">
    <a className="hq-btn" href={taskHref(r.t.key)}>Watch the live session</a>
    <a className="hq-btn" href={href("tasks", r.t.key)}>Open ticket</a></p>;
  const people = r.on.length > 0 && <ul className="hq-tf-on" aria-label={`On ${r.t.key} now`}>
    {r.on.map(({ who, seat }) => <li key={who.id}>
      <b>{seat ? SEAT_LABEL[seat] : "Session"}</b> <a href={href("agents", who.id)}>{who.name}</a>
      <Pill tone={PRESENCE_TONE[who.presence]}>{PRESENCE_LABEL[who.presence]}</Pill></li>)}</ul>;
  if (w === undefined) return <div className="hq-tf">{people}
    {failed ? <p className="hq-note" role="alert">Could not load the stages.{" "}
      <button type="button" className="hq-link" onClick={() => setTries(tries + 1)}>Try again</button></p>
      : <p className="hq-note" role="status">Loading the stages…</p>}{links}</div>;
  if (w === "missing") return <div className="hq-tf">{people}
    <p className="hq-note">No work is recorded for this ticket yet, so there are no stages to show.</p>{links}</div>;
  const steps = stepsOf(w, r.rail);
  const waiting = w.flow?.waitingOn;
  return <div className="hq-tf">
    {people}
    {!r.on.length && <p className="hq-note">{waiting === "jay" || r.needsJay ? <>Nobody is on it: it is waiting for you.{" "}
      <a className="hq-link" href={href("needs")}>Open Decisions</a></>
      : waiting === "lead" ? "Nobody is on it: it is waiting for the lead."
      : waiting === "reviewer" ? "Nobody is on it: it is waiting for a reviewer." : "Nobody is on it right now."}</p>}
    <ol className="hq-tf-steps" aria-label={`Stages of ${r.t.key}`}>
      {steps.map((s) => <li key={s.label} className={cx(`is-${s.state}`)} aria-current={s.state === "active" ? "step" : undefined}>
        <i aria-hidden /><b>{s.label}</b>
        <small>{STATE_WORD[s.state] ?? s.state}{s.who ? ` · ${s.who}` : ""}{s.at ? ` · ${ago(s.at, now)}` : ""}</small></li>)}
    </ol>
    {w.flow?.stale && <p className="hq-note t-jay">No step recorded for 48 hours. The lead has to move it, send it back or cancel it.</p>}
    {w.criteria && w.criteria.length > 0 && <><h5>Acceptance criteria</h5>
      <ul className="hq-tf-crit">{w.criteria.map((c) => <li key={c.id} className={`is-${c.state}`}>
        <i aria-hidden /><span>{c.text}</span><small>{MARK[c.state]}</small></li>)}</ul></>}
    {w.handoffs && w.handoffs.length > 0 && <><h5>History</h5>
      <ol className="hq-tf-hist">{w.handoffs.map((h, i) => <li key={`${h.at}:${i}`}>
        <time dateTime={new Date(h.at * 1000).toISOString()}>{stamp(h.at)}</time><span>{handoffText(h)}</span></li>)}</ol></>}
    {w.closing && <><h5>Closing note</h5><p className="hq-tf-close">{w.closing.note}</p></>}
    {links}
  </div>;
}
