// Decisions (roadmap P3.6): everything waiting for Jay. The items are Classic's Needs You queue (jayQueue, labelled by
// hq/data/decisions.ts), in Classic's order, with the same read-only extras from GET /api/inbox: the pending approval
// and when it expires, the shadow engine's verdict, and earlier answers to the same question. Each item opens the
// place Jay acts today (jayHref). Nothing here answers, approves, merges or deploys.
import { useEffect, useMemo, useState } from "react";
import "./office.css";
import "./decisions.css";
import { app } from "../../store/app";
import { ago } from "../../lib/time";
import { jayHref, jayRef, projectName } from "../../lib/control";
import { TYPE_ORDER, actionOf, day, late, typeOf, until } from "../../screens/NeedsYou";
import type { InboxExtra, InboxState } from "../../api/types";
import { buildDecisions, type DecisionItem, type DecisionKind } from "../data";
import { useHqData } from "./live";
import { Pill, cx, plural } from "./ui";

const KINDS: { k: DecisionKind; label: string; hint: string }[] = [
  { k: "Decision", label: "Decisions", hint: "Plans, blockers, flagged tasks" },
  { k: "Question", label: "Questions", hint: "Someone is waiting on an answer" },
  { k: "Review", label: "Reviews", hint: "UI to look at" },
  { k: "Approval", label: "Approvals", hint: "Merges and deploys you do" },
  { k: "Action", label: "Actions", hint: "Failing checks and to-dos" },
];
const VERDICT = { auto: "go ahead", jay: "ask you", refuse: "refuse" } as const;

/** GET /api/inbox, re-read when the queue changes and every minute (expiry, engine verdicts), as Classic's Needs You
 *  does. Only the newest answer counts. A failure leaves the list complete; it only lacks these details. */
export function useInbox(ids: string) {
  const [inbox, setInbox] = useState<InboxState | null>(null);
  const [failed, setFailed] = useState(false);
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
  return { inbox, failed };
}

export function Item({ d, x, now, project }: { d: DecisionItem; x?: InboxExtra; now: number; project: string }) {
  const j = d.source, a = x?.approval, overdue = late(x), to = jayHref(j);
  const out = /^https?:/.test(to) ? { target: "_blank", rel: "noopener noreferrer" } : {};
  return <li className={cx("hq-dec", overdue && "is-late")}>
    <div className="hq-dec-main">
      <Pill tone={d.tone}>{d.pill[0]}</Pill>
      <span className="hq-attn-body"><span className="hq-ellip" title={d.title}><code>{jayRef(j)}</code> {d.title}</span>
        <small>{typeOf(j)} · {project}{d.since ? ` · ${ago(d.since, now)}` : ""}</small></span>
      <a className="hq-btn" href={to} {...out}>{actionOf(j)}</a>
    </div>
    {(a || x?.engine) && <p className="hq-dec-meta">
      {a && <span title={`Approval #${a.id}, bound to ${a.subjectHash}`}>Approval #{a.id} · bound to {a.subjectHash.slice(0, 8) || "—"} ·{" "}
        <span className={overdue ? "t-bad" : undefined}>{a.expiresAt ? until(a.expiresAt) : "no expiry"}</span></span>}
      {x?.engine && <span title={x.engine.rule}>Engine (shadow) would {VERDICT[x.engine.engine]}{x.engine.agree ? "" : " · differs from today"}</span>}
    </p>}
    {x?.precedents?.map((p) => <p key={p.questionId} className="hq-dec-meta">
      Asked before: “{p.precedents[0].question}” → <b>{p.precedents[0].decision}</b>{" "}
      ({p.precedents[0].key ?? "an archived task"}, {day(p.precedents[0].decidedAt)}{p.precedents.length > 1 ? `, +${p.precedents.length - 1} more` : ""})
    </p>)}
  </li>;
}

export function Decisions() {
  const { src, ev } = useHqData();
  const v = useMemo(() => buildDecisions(src), [src]);
  const { inbox, failed } = useInbox(v.items.map((i) => i.id).join("|"));
  const [kind, setKind] = useState<DecisionKind | null>(null);
  const extra = inbox?.items ?? {};
  // Classic's order: overdue first, then by type, then oldest first.
  const rank = (d: DecisionItem) => [late(extra[d.id]) ? 0 : 1, TYPE_ORDER.indexOf(typeOf(d.source)), d.source.since ?? Number.MAX_SAFE_INTEGER];
  const sorted = [...v.items].sort((a, b) => { const [x, y] = [rank(a), rank(b)]; return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
  const shown = sorted.filter((d) => !kind || d.kind === kind);
  const overdue = v.items.filter((d) => late(extra[d.id])).length;
  const c = inbox?.counts ?? {};
  const s = v.summary;
  const names = new Map(src.taskProjects.map((p) => [p.key, p.name]));

  return <div className="hq-page hq-decisions">
    <header className="hq-hero"><div><h2>Needs your attention</h2>
      <p>Decisions, questions, reviews and approvals waiting for you. Each opens the place you act today. Nothing here answers, merges or deploys.</p></div></header>

    <section className="hq-kpis" role="group" aria-label="Filter by kind">
      {KINDS.map(({ k, label, hint }) => <button key={k} type="button" className="hq-kpi" aria-pressed={kind === k} onClick={() => setKind(kind === k ? null : k)}>
        <small>{label}</small><b>{v.items.filter((d) => d.kind === k).length}</b><em>{hint}</em></button>)}
    </section>

    <div className="hq-office-grid">
      <section className="hq-panel" aria-labelledby="hq-dec-list">
        <header><h3 id="hq-dec-list">Waiting for you <small>{kind ? `${shown.length} of ${s.total}` : s.total} · overdue first, then by type and age</small></h3>
          {kind && <button type="button" className="hq-btn" onClick={() => setKind(null)}>Show all</button>}</header>
        {shown.length ? <ul className="hq-dec-list">{shown.map((d) => <Item key={d.id} d={d} x={extra[d.id]} now={ev.now}
          project={names.get(d.project) ?? (projectName(src.state, d.project) || d.project)} />)}</ul>
          : <p className="hq-empty">{s.total ? "Nothing of this kind is waiting." : "Nothing waits on you."}</p>}
      </section>
      <div className="hq-office-side">
        <section className="hq-panel" aria-labelledby="hq-dec-sum">
          <header><h3 id="hq-dec-sum">Summary</h3></header>
          <dl className="hq-dl">
            <dt>Blocking someone</dt><dd className={cx(s.blockers > 0 && "t-bad")}>{s.blockers}</dd>
            <dt>Urgent</dt><dd className={cx(s.urgent > 0 && "t-warn")}>{s.urgent}</dd>
            {inbox?.available && <>
              <dt>Approvals pending</dt><dd>{c.approvals ?? 0}</dd>
              <dt>Overdue</dt><dd className={cx(overdue > 0 && "t-bad")}>{overdue}</dd>
              <dt>Asked before</dt><dd>{c.precedentHits ?? 0}</dd></>}
          </dl>
          {((inbox && !inbox.available && inbox.error) || failed) && <p className="hq-note">
            {failed ? "Could not read the approval and engine details" : inbox?.error}; the list is still complete.</p>}
          <p className="hq-note">Approving several at once comes later, when the engine leaves shadow mode.</p>
        </section>
        {!!inbox?.orphans.length && <section className="hq-panel" aria-labelledby="hq-dec-orphans">
          <header><h3 id="hq-dec-orphans">Approvals with no open gate <small>{plural(inbox.orphans.length, "record")}</small></h3></header>
          <p className="hq-note">These approval records are pending, but their gate is no longer in the queue. They should clear at the
            task's next step; if they stay, the record and the gates disagree.</p>
          <ul className="hq-dec-orphans">{inbox.orphans.map((o) => <li key={o.id}><code>{o.key}</code> · {o.gate} · approval #{o.id}</li>)}</ul>
        </section>}
      </div>
    </div>
  </div>;
}
