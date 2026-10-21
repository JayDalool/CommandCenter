// NEEDS YOU (v2 Phase 1, PR 6; discovery §14.3): one inbox over everything that waits on Jay — gate approvals,
// questions, blockers, blocked agents, flagged tickets, merges, CI. The items ARE the existing Needs Jay queue
// (jayQueue: the same list the dashboard and the bell show), so the three never disagree. What v2 adds per item,
// read-only from GET /api/inbox: the pending Approval (what it is bound to, when it expires), the shadow engine's
// verdict, and earlier answers to the same question. One action per card: it opens the exact place Jay acts
// today. Nothing here approves, answers or merges by itself.
import { useEffect, useMemo, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { jayQueue, type JayItem } from "../tickets/model";
import { jayHref, jayRef, projectName } from "../lib/control";
import type { InboxExtra, InboxState } from "../api/types";
import { Ago, EmptyState, Panel } from "../components/ui";

type Group = "project" | "type";
const GROUP_KEY = "cc.needsGroup";

/** The kind of ask, in Jay's words. */
export function typeOf(j: JayItem): string {
  if (j.kind === "gate") return ({ plan: "Plan approval", merge: "Merge acceptance", ui: "UI review", deploy: "Live deploy",
    failure: "Blocker" } as Record<string, string>)[j.gate ?? ""] ?? "Decision";
  if (j.kind === "questions" && j.flags.includes("stale") && j.questions === 1) return "Task check";
  return ({ questions: "Question", answer: "Blocked agent", ticket: "Flagged task", merge: "Pull request", ci: "Failure",
    task: "Action", actions: "Action" } as Record<string, string>)[j.kind] ?? "Action";
}

/** The card's one action. */
export function actionOf(j: JayItem): string {
  if (j.kind === "gate") return ({ plan: "Review plan", merge: "Review merge", ui: "Review UI", deploy: "Review deploy",
    failure: "Resolve" } as Record<string, string>)[j.gate ?? ""] ?? "Decide";
  if (j.kind === "questions") return "Answer";
  if (j.kind === "answer") return "Answer agent";
  if (j.kind === "merge") return "Open PR";
  return "Open";
}

const TYPE_ORDER = ["Blocked agent", "Blocker", "Failure", "Question", "Task check", "Plan approval", "Merge acceptance", "UI review",
  "Live deploy", "Decision", "Flagged task", "Pull request", "Action"];

function until(at: number): string {
  const s = Math.round(at - Date.now() / 1000);
  if (s <= 0) return "overdue";
  return s < 5400 ? `expires in ${Math.max(1, Math.round(s / 60))}m` : `expires in ${Math.round(s / 3600)}h`;
}

/** Overdue by this browser's clock, so the highlight and order match the card's own "overdue" text between reloads. */
function late(x?: InboxExtra): boolean {
  const a = x?.approval;
  return !!a && (a.overdue || (!!a.expiresAt && a.expiresAt <= Date.now() / 1000));
}

function day(at: number): string {
  return new Date(at * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Card({ j, x }: { j: JayItem; x?: InboxExtra }) {
  const a = x?.approval;
  return <li className={`ny-card${late(x) ? " is-overdue" : ""}`}>
    <div className="ny-main">
      <span className="ny-type">{typeOf(j)}</span>
      <span className="mono ny-ref">{jayRef(j)}</span>
      <span className="ny-text trunc" title={j.text}>{j.text}</span>
      <Ago at={j.since} />
      <a className="btn is-sm ny-act" href={jayHref(j)}>{actionOf(j)}</a>
    </div>
    {(a || x?.engine) && <div className="ny-meta mono-xs">
      {a && <span title={`Approval #${a.id}, bound to ${a.subjectHash}`}>approval #{a.id} · bound to {a.subjectHash.slice(0, 8) || "—"} ·{" "}
        <span className={late(x) ? "ny-overdue" : "muted"}>{a.expiresAt ? until(a.expiresAt) : "no expiry"}</span></span>}
      {x?.engine && <span className="muted" title={x.engine.rule}>engine (shadow) would: <b>{x.engine.engine === "auto" ? "go ahead" : x.engine.engine === "jay" ? "ask you" : "refuse"}</b>
        {x.engine.agree ? "" : " · differs from today"} · as of <Ago at={x.engine.at} /></span>}
    </div>}
    {x?.precedents?.map((p) => <div key={p.questionId} className="ny-prec">
      <span className="muted">Asked before:</span> “{p.precedents[0].question}” → <b>{p.precedents[0].decision}</b>
      <span className="muted"> ({p.precedents[0].key ?? "an archived task"}, {day(p.precedents[0].decidedAt)}{p.precedents.length > 1 ? `, +${p.precedents.length - 1} more` : ""})</span>
    </div>)}
  </li>;
}

export function NeedsYou() {
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const items = useMemo(() => jayQueue(st, undefined, tickets), [st, tickets]);
  const ids = items.map((i) => i.id).join("|");
  const [inbox, setInbox] = useState<InboxState | null>(null);
  const [failed, setFailed] = useState(false);
  const [group, setGroup] = useState<Group>(() => { try { return localStorage.getItem(GROUP_KEY) === "type" ? "type" : "project"; } catch { return "project"; } });
  // Re-read when the queue changes and every minute (overdue, engine verdicts); only the newest answer counts.
  useEffect(() => {
    let live = true, n = 0;
    const load = () => {
      const mine = ++n;
      app.api.inbox().then((d) => { if (live && mine === n) { setInbox(d); setFailed(false); } })
        .catch(() => { if (live && mine === n) setFailed(true); });
    };
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, [ids]);
  const pick = (g: Group) => { setGroup(g); try { localStorage.setItem(GROUP_KEY, g); } catch { /* convenience only */ } };

  const groups = useMemo(() => {
    const extra = inbox?.items ?? {};
    const rank = (j: JayItem) => [late(extra[j.id]) ? 0 : 1, TYPE_ORDER.indexOf(typeOf(j)), j.since ?? Infinity];
    const sorted = [...items].sort((a, b) => {
      const [x, y] = [rank(a), rank(b)];
      return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
    });
    const m = new Map<string, JayItem[]>();
    for (const j of sorted) {
      const k = group === "project" ? j.project : typeOf(j);
      m.set(k, [...(m.get(k) ?? []), j]);
    }
    // Overdue first across groups too; then by type order, or by the project's shown name.
    const lateGroup = (list: JayItem[]) => list.some((j) => late(extra[j.id])) ? 0 : 1;
    const name = (k: string) => projectName(st, k) || k;
    return [...m.entries()].sort(([a, la], [b, lb]) => lateGroup(la) - lateGroup(lb)
      || (group === "type" ? TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b) : name(a).localeCompare(name(b))));
  }, [items, inbox, group, st]);

  const c = inbox?.counts ?? {};
  return <div className="stack ny">
    <div className="ny-head">
      <p className="text2">{items.length ? `${items.length} thing${items.length === 1 ? "" : "s"} need${items.length === 1 ? "s" : ""} you.` : "Nothing needs you."}
        {inbox?.available && <span className="muted"> {c.approvals ?? 0} approval{c.approvals === 1 ? "" : "s"} pending
          {c.overdue ? <>, <span className="ny-overdue">{c.overdue} overdue</span></> : null}
          {c.precedentHits ? `, ${c.precedentHits} asked before` : ""}.</span>}</p>
      <div className="seg" role="group" aria-label="Group by">
        <button type="button" aria-pressed={group === "project"} onClick={() => pick("project")}>By project</button>
        <button type="button" aria-pressed={group === "type"} onClick={() => pick("type")}>By type</button>
      </div>
    </div>
    {((inbox && !inbox.available && inbox.error) || failed) && <p className="muted mono-xs">
      {failed ? "Could not read the approval and engine details" : inbox?.error}; the list below is still complete.</p>}
    {!items.length && <EmptyState title="Nothing waits on you." hint="plan approvals, questions, blockers and merges land here" />}
    {groups.map(([k, list]) => <Panel key={k} title={group === "project" ? projectName(st, k) || k : k} count={list.length}>
      <ul className="ny-list">{list.map((j) => <Card key={j.id} j={j} x={inbox?.items[j.id]} />)}</ul>
    </Panel>)}
    {!!inbox?.orphans.length && <Panel title="Approvals with no open gate" count={inbox.orphans.length}>
      <p className="text2">These Approval records are pending, but their gate is no longer in the queue. They should clear at
        the ticket's next step; if they stay, the record and the gates disagree.</p>
      <ul className="ny-list">{inbox.orphans.map((o) => <li key={o.id} className="mono-xs">{o.key} · {o.gate} · approval #{o.id}</li>)}</ul>
    </Panel>}
    <p className="muted mono-xs">Each card opens the place you act today. Approving several at once comes later, when the
      engine leaves shadow mode.</p>
  </div>;
}
