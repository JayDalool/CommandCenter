// Approvals (roadmap P4.2, the read-only part). What waits for Jay's approval today: the merges and deploys in the
// Needs-Jay queue (hq/data/decisions.ts, kind Approval), each with the approval record it is bound to and its expiry
// from GET /api/inbox, as on Decisions. Agent approval requests (D-032: risk tiers, Developer Unlock with the typed
// agent ID, hash binding, expiry) need an approval-request service that does not exist yet, so that part says Not
// enabled. Nothing here approves, merges or deploys.
import { useMemo } from "react";
import "./office.css";
import "./decisions.css";
import "./governance.css";
import { projectName } from "../../lib/control";
import { href } from "../../lib/router";
import { late } from "../../screens/NeedsYou";
import { buildDecisions } from "../data";
import { useHqData } from "./live";
import { Item, useInbox } from "./Decisions";
import { Pill, cx } from "./ui";

export function Approvals() {
  const { src, ev } = useHqData();
  const v = useMemo(() => buildDecisions(src), [src]);
  const { inbox, failed } = useInbox(v.items.map((i) => i.id).join("|"));
  const extra = inbox?.items ?? {};
  // Overdue first, then oldest first.
  const mine = v.items.filter((d) => d.kind === "Approval").sort((a, b) =>
    Number(late(extra[b.id])) - Number(late(extra[a.id])) || (a.since ?? Number.MAX_SAFE_INTEGER) - (b.since ?? Number.MAX_SAFE_INTEGER));
  const overdue = mine.filter((d) => late(extra[d.id])).length;
  const names = new Map(src.taskProjects.map((p) => [p.key, p.name]));

  return <div className="hq-page hq-approvals">
    <header className="hq-hero"><div><h2>Approvals</h2>
      <p>Merges and deploys waiting for you, with the approval record each is bound to. Each opens the place you approve
        today. Nothing here approves, merges or deploys.</p></div></header>

    <div className="hq-office-grid">
      <section className="hq-panel" aria-labelledby="hq-appr-list">
        <header><h3 id="hq-appr-list">Waiting for your approval <small>{mine.length}</small></h3>
          <a className="hq-link" href={href("needs")}>Everything in Decisions</a></header>
        {mine.length ? <ul className="hq-dec-list">{mine.map((d) => <Item key={d.id} d={d} x={extra[d.id]} now={ev.now}
          project={names.get(d.project) ?? (projectName(src.state, d.project) || d.project)} />)}</ul>
          : <p className="hq-empty">No merge or deploy is waiting for you.</p>}
        {((inbox && !inbox.available && inbox.error) || failed) && <p className="hq-note">
          {failed ? "Could not read the approval records" : inbox?.error}; the list is still complete.</p>}
      </section>

      <div className="hq-office-side">
        <section className="hq-panel" aria-labelledby="hq-appr-sum">
          <header><h3 id="hq-appr-sum">Summary</h3></header>
          <dl className="hq-dl">
            <dt>Merges</dt><dd>{mine.filter((d) => d.pill[0] === "Merge").length}</dd>
            <dt>Deploys</dt><dd>{mine.filter((d) => d.pill[0] === "Deploy").length}</dd>
            {inbox?.available && <>
              <dt>Approval records pending</dt><dd>{inbox.counts.approvals ?? 0}</dd>
              <dt>Overdue</dt><dd className={cx(overdue > 0 && "t-bad")}>{overdue}</dd></>}
          </dl>
        </section>
        <section className="hq-panel hq-off" aria-labelledby="hq-appr-req">
          <header><h3 id="hq-appr-req">Agent approval requests</h3><Pill tone="idle">Not enabled</Pill></header>
          <p>When an agent asks for something only you can allow, the request will wait here with its risk tier, what it is
            bound to and when it expires. High-risk requests will need Developer Unlock and the agent's ID typed in.</p>
          <p className="hq-note">Not enabled: it needs an approval-request service on the server, which has not been built.
            Approving from Slack stays off.</p>
        </section>
      </div>
    </div>
  </div>;
}
