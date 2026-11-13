// My Office › Briefing: what happened while Jay was away, from ccd's own event log (GET /api/briefing). Counts are
// ccd's; a project with nothing counted and no events is named in one line, not padded out. Spend shows only when the
// meter has data. Client projects arrive from ccd already cut down to ids.
import { useCallback, useMemo, useState } from "react";
import "./hqnext.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { href } from "../../lib/router";
import type { BriefingCounts, BriefingHighlight, BriefingProject } from "../../api/types";
import { ProjectLogo } from "../logos";
import { loadMessage, useLoad, usePulse } from "./load";
import { Pill, cx, plural } from "./ui";

const WINDOWS: [number, string][] = [[12, "12 hours"], [24, "24 hours"], [72, "3 days"]];
/** Events that can change a count or a highlight. */
const KINDS = ["pipeline.", "ticket.", "pr.", "ci.", "milestone.", "chat.", "question."];
const CHECKS: Record<BriefingProject["mainChecks"], [string, string]> = {
  passing: ["Main passing", "ok"], failing: ["Main failing", "bad"], unknown: ["Main unknown", "idle"],
};
const STATS: [keyof BriefingCounts, string, string?][] = [
  ["merged", "Merged"], ["done", "Done"], ["opened", "PRs opened"], ["failedChecks", "Checks failed", "bad"],
  ["deploys", "Deploys"], ["questionsAsked", "Questions asked"], ["questionsAnswered", "Answered"],
];
const SHOWN = 3;

/** "05:12" for today, "Thu 22:14" for another day. */
function when(at: number, now: Date): string {
  const d = new Date(at * 1000);
  const t = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toDateString() === now.toDateString() ? t : `${d.toLocaleDateString(undefined, { weekday: "short" })} ${t}`;
}

/** What was counted for a project, in words: "2 merged · 1 PR opened". */
function counted(p: BriefingCounts): string {
  const parts = [p.merged && `${p.merged} merged`, p.done && `${p.done} done`, p.opened && `${plural(p.opened, "PR")} opened`,
    p.failedChecks && `${plural(p.failedChecks, "check")} failed`, p.deploys && plural(p.deploys, "deploy"),
    p.questionsAsked && `${plural(p.questionsAsked, "question")} asked`, p.questionsAnswered && `${p.questionsAnswered} answered`];
  return parts.filter(Boolean).join(" · ");
}
const active = (p: BriefingProject) => p.highlights.length > 0 || counted(p) !== "";

function Highlight({ h, now, tickets }: { h: BriefingHighlight; now: Date; tickets: ReadonlySet<string> }) {
  const body = <><time dateTime={new Date(h.at * 1000).toISOString()}>{when(h.at, now)}</time>
    <span>{h.ref && !h.text.includes(h.ref) && <code>{h.ref} </code>}{h.text}</span></>;
  return <li>{h.ref && tickets.has(h.ref) ? <a href={href("tasks", h.ref)}>{body}</a> : <span className="hq-brief-row">{body}</span>}</li>;
}

function Project({ p, now, tickets }: { p: BriefingProject; now: Date; tickets: ReadonlySet<string> }) {
  const [all, setAll] = useState(false);
  const [label, tone] = CHECKS[p.mainChecks];
  const more = p.highlights.length - SHOWN;
  return <li className="hq-brief-proj" style={{ ["--pj" as string]: `var(--hq-pj-${p.key}, var(--hq-accent))` }}>
    <div className="hq-brief-top">
      <a className="hq-brief-name hq-with-logo" href={href("projects", p.key)}><ProjectLogo project={p.key} />{p.name}</a>
      <Pill tone={tone}>{label}</Pill>
      <span className="hq-brief-counts">{counted(p) || "Nothing counted"}</span>
      {p.needsYou > 0 && <a className="hq-brief-needs" href={href("needs")}>{p.needsYou} waiting on you</a>}
      {/* null: the meter has no data. A measured zero is true but says nothing, so it is left out too. */}
      {p.spendUsd != null && p.spendUsd >= 0.005 && <span className="hq-dim">${p.spendUsd.toFixed(2)} spent</span>}
    </div>
    {p.highlights.length > 0 && <ol className="hq-brief-hl">
      {(all ? p.highlights : p.highlights.slice(0, SHOWN)).map((h, i) => <Highlight key={`${h.at}-${i}`} h={h} now={now} tickets={tickets} />)}</ol>}
    {more > 0 && <button type="button" className="hq-brief-more" aria-expanded={all} onClick={() => setAll(!all)}>
      {all ? "Show fewer" : `Show ${more} more`}</button>}
  </li>;
}

export function Briefing({ now }: { now: Date }) {
  const [hours, setHours] = useState(12);
  // The answer carries the window it was asked for, so figures are never shown under another window's name.
  const get = useCallback(async () => ({ hours, b: await app.api.briefing(Date.now() / 1000 - hours * 3600) }), [hours]);
  const { data: got, error } = useLoad(get, usePulse(KINDS));
  const keys = useSelector(app.store, (d) => d.tickets);
  const tickets = useMemo(() => new Set(keys.map((t) => t.key)), [keys]);
  const data = got?.b ?? null, waiting = !!got && got.hours !== hours;
  const busy = data?.projects.filter(active) ?? [], still = data?.projects.filter((p) => !active(p)) ?? [];
  const span = WINDOWS.find(([h]) => h === (got?.hours ?? hours))![1];
  return <section className="hq-panel hq-brief" aria-labelledby="hq-office-brief" aria-busy={waiting || undefined}>
    <header><h3 id="hq-office-brief">Briefing {data && <small>since {when(data.since, now)}</small>}</h3>
      <div className="hq-seg" role="group" aria-label="Briefing window">
        {WINDOWS.map(([h, l]) => <button key={h} type="button" aria-pressed={hours === h} onClick={() => setHours(h)}>{l}</button>)}
      </div></header>
    {error && data && <p className="hq-note" role="status">Not updated just now ({error.message}). Showing ccd's last answer, for the last {span}.</p>}
    {waiting && !error && <p className="hq-note" role="status">Loading the last {WINDOWS.find(([h]) => h === hours)![1]}…</p>}
    {error && !data ? <p className="hq-note" role={error.status === 404 ? undefined : "alert"}>{loadMessage(error, "the briefing")}</p>
      : !data ? <p className="hq-empty">Loading…</p> : <>
        <ul className="hq-brief-stats" aria-label={`Totals for the last ${span}`}>
          {STATS.map(([k, l, tone]) => <li key={k} className={cx(!data.totals[k] && "is-zero")}>
            <b className={data.totals[k] && tone ? `t-${tone}` : undefined}>{data.totals[k]}</b><small>{l}</small></li>)}
        </ul>
        {data.quiet ? <p className="hq-empty">Nothing happened in the last {span}.</p>
          : <ul className="hq-brief-projects">{busy.map((p) => <Project key={p.key} p={p} now={now} tickets={tickets} />)}</ul>}
        {!data.quiet && still.length > 0 && <p className="hq-note">No activity: {still.map((p) => p.name).join(", ")}</p>}
      </>}
  </section>;
}
