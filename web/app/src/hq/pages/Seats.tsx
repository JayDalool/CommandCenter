// Teams › Seats (hq/data/seats.ts): Teams as a company. Each project is a team with fixed seats; a session sits in
// one while it holds a ticket in that job. Under the seats are the tickets in flight, each with its row of stages
// and its children. A ticket opens in place (TicketFlow.tsx). Nothing here changes anything: Open, Focus, answering
// and the live session stay where they are, one link away.
import { useId, useState } from "react";
import "./seats.css";
import type { FlowSeat, TicketSize } from "../../api/types";
import { href } from "../../lib/router";
import { PRESENCE_LABEL, SEAT_LABEL, STAGE_LABEL, type SeatsTeam, type SeatsView, type FlightRow, type RailStep,
  type SeatRow, type TeamMember } from "../data";
import { Pill, PRESENCE_TONE, cx, plural } from "./ui";
import { Icon } from "../frame/icons";
import { ProjectLogo } from "../logos";
import { Fun, Persona, PRESENCE_EMOJI, useFun } from "../persona/mode";
import { TicketFlowPanel } from "./TicketFlow";

const MONO: Record<FlowSeat, string> = { lead: "LD", investigator: "IN", techReviewer: "TR", developer: "DV", userReviewer: "UR",
  designReviewer: "DR", codeReviewer: "CR", verifier: "VF" };
const SIZE: Record<TicketSize, string> = { small: "Small", standard: "Standard", risky: "Risky" };

/** The row of stages, as one image: a screen reader hears how far the ticket is, not nine dots. The stage's name is
 *  in words right after it, so the label does not repeat it. */
export function Rail({ rail, label }: { rail: RailStep[]; label: string }) {
  return <span className="hq-rail" role="img" aria-label={label}>
    {rail.map((s) => <i key={s.stage} className={`is-${s.state}`} title={STAGE_LABEL[s.stage]} />)}</span>;
}

/** A seat. The face is the seat's own (the lead keeps its character), so it stays the same whoever sits there. */
function SeatCard({ s, project, nth, leadWhy }: { s: SeatRow; project: string; nth: number; leadWhy: string | null }) {
  const fun = useFun();
  const who = s.who;
  return <li className={cx("hq-seat", !who && "is-free", s.seat === "lead" && "is-lead")}>
    <span className="hq-seat-av">{fun
      ? <Persona lead={s.seat === "lead" ? project : null} name={`${project}:${s.seat}${nth ? `:${nth + 1}` : ""}`}
        of={s.seat === "lead" ? undefined : `the ${SEAT_LABEL[s.seat].toLowerCase()} seat`} size={38} />
      : <span className="hq-seat-mono" aria-hidden>{MONO[s.seat]}</span>}</span>
    <span className="hq-seat-body">
      <span className="hq-seat-top"><b>{SEAT_LABEL[s.seat]}</b>
        {who && <Pill tone={PRESENCE_TONE[who.presence]}>{PRESENCE_LABEL[who.presence]}<Fun e={PRESENCE_EMOJI[who.presence]} /></Pill>}</span>
      {who ? <>
        <a className="hq-ellip" href={href("agents", who.id)} title={who.cwd || undefined}>{who.name}</a>
        {s.ticket ? <small>On <a href={href("tasks", s.ticket.key)}>{s.ticket.key}</a>{s.stage ? ` · ${STAGE_LABEL[s.stage]}` : ""}</small>
          : s.seat !== "lead" && <small>No ticket</small>}</>
        : <small>{s.seat === "lead" && leadWhy ? leadWhy : "Free"}</small>}
    </span>
  </li>;
}

function Flight({ r, now }: { r: FlightRow; now: number }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  // counted along the ticket's own route: a small ticket at code review is at stage 3 of 6, not 6 of 9
  const route = r.rail.filter((s) => s.state !== "skipped");
  const at = route.findIndex((s) => s.state === "active");
  const where = r.blocked ? "Blocked" : r.stage ? STAGE_LABEL[r.stage] : "Not known";
  return <li className={cx("hq-fl", r.needsJay && "is-jay", r.blocked && "is-blocked")}>
    <div className="hq-fl-row">
      <button type="button" className="hq-fl-btn" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen(!open)}>
        <Icon name={open ? "chevdown" : "chevron"} size={14} /><code>{r.t.key}</code><span className="hq-ellip">{r.t.title}</span></button>
      <span className="hq-fl-tags">{r.t.stale && <Pill tone="warn" title="No step recorded for 48 hours">Stale</Pill>}
        {r.notSized ? <small className="hq-fl-size">Not sized</small>
          : r.t.size && <small className={cx("hq-fl-size", r.t.size === "risky" && "is-risky")}>{SIZE[r.t.size]}</small>}</span>
      <span className="hq-fl-stage"><Rail rail={r.rail} label={at >= 0 ? `Stage ${at + 1} of ${route.length}` : "Stage not known"} />
        <b>{where}</b></span>
      <span className="hq-fl-who">
        {r.needsJay && <a className="t-jay" href={href("needs")}>Needs you</a>}
        {r.on.length ? r.on.map(({ who, seat }) => <span key={who.id} className="hq-ellip">{seat ? `${SEAT_LABEL[seat]} · ` : ""}{who.name}</span>)
          : !r.needsJay && <span className="t-none">Nobody on it</span>}
        {r.t.subtasks.total > 0 && <small>{r.t.subtasks.done} of {plural(r.t.subtasks.total, "child", "children")} done</small>}
      </span>
    </div>
    {open && <div id={id}><TicketFlowPanel r={r} now={now} /></div>}
    {r.children.length > 0 && <ul className="hq-fl-kids" aria-label={`Children of ${r.t.key}`}>
      {r.children.map((c) => <Flight key={c.t.key} r={c} now={now} />)}</ul>}
  </li>;
}

function Loose({ list, label }: { list: TeamMember[]; label: string }) {
  return <ul className="hq-loose" aria-label={label}>{list.map((m) => <li key={m.id}>
    <a href={href("agents", m.id)} title={m.cwd || undefined}>{m.name}</a>
    {m.ticket && <small>On <a href={href("tasks", m.ticket)}>{m.ticket}</a></small>}
    <Pill tone={PRESENCE_TONE[m.presence]}>{PRESENCE_LABEL[m.presence]}</Pill></li>)}</ul>;
}

function TeamSeats({ t, now }: { t: SeatsTeam; now: number }) {
  const nth = (i: number) => t.seats.slice(0, i).filter((x) => x.seat === t.seats[i]!.seat).length;
  return <section className="hq-panel hq-team hq-seating" aria-labelledby={`hq-seating-${t.key}`} style={{ ["--pj" as string]: `var(--hq-pj-${t.key}, var(--hq-accent))` }}>
    <header><h3 id={`hq-seating-${t.key}`}><ProjectLogo project={t.key} /> {t.name}
      <small>{plural(t.inFlight, "ticket")} in flight · {t.atIntake} more at intake</small></h3>
      <span className="hq-team-links"><a className="hq-link" href={href("tasks", null, { project: t.key })}>Tasks</a>
        <a className="hq-link" href={href("projects", t.key)}>Project</a></span></header>
    <ul className="hq-seats" aria-label={`${t.name} seats`}>
      {t.seats.map((s, i) => <SeatCard key={`${s.seat}:${s.who?.id ?? "free"}`} s={s} project={t.key} nth={nth(i)} leadWhy={t.leadWhy} />)}</ul>
    <h4 className="hq-seating-h">In flight</h4>
    {t.flight.length ? <ul className="hq-flight" aria-label={`${t.name} tickets in flight`}>
      {t.flight.map((r) => <Flight key={r.t.key} r={r} now={now} />)}</ul>
      : <p className="hq-empty">Nothing in flight.</p>}
    {t.loose.length > 0 && <><h4 className="hq-seating-h">Not in a seat <small>No ticket, or the ticket does not say what they do on it.</small></h4>
      <Loose list={t.loose} label={`${t.name} sessions not in a seat`} /></>}
  </section>;
}

export function Seats({ v, now }: { v: SeatsView; now: number }) {
  return <>
    {/* only tickets can say which flow ccd runs, so with none open there is nothing to say */}
    {!v.flow && v.teams.some((t) => t.openTasks > 0) && <p className="hq-note">This Command Center does not run the nine-stage flow yet,
      so tickets show the seven stages it can tell apart. Technical review and the user check appear once it does.</p>}
    {v.teams.map((t) => <TeamSeats key={t.key} t={t} now={now} />)}
    {v.unassigned.length > 0 && <section className="hq-panel hq-seating" aria-labelledby="hq-seating-none">
      <header><h3 id="hq-seating-none">No project <small>{plural(v.unassigned.length, "session")}</small></h3></header>
      <Loose list={v.unassigned} label="Sessions with no project" /></section>}
  </>;
}
