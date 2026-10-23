// APPROVALS (D-032) — what reaches Jay's phone and where he approves it. Slack carries the request and a secure
// link (an opaque request ID, never a credential); the approval happens on this authenticated screen. High-risk
// items need Developer Unlock and a typed confirmation here; in-Slack approval is a later, separate step and is off.
// MOCK DATA: nothing connects to Slack or ccd, and ccd is never exposed publicly.
import { useState } from "react";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Pill, cx } from "../components/ui";
import { PopButton } from "../windows/Detachable";
import { notify } from "../windows/manager";
import { useStore } from "../lib/store";
import { go, useRoute } from "../lib/router";
import { AGENTS, agent } from "../data/seed";
import {
  SLACK_STEP_2, TIER_LABEL, TIER_TONE, amendRequest, approvableIn, budgetLines, canApprove, confirmText, decide, gov, reqHash, tierOf, type Req, type Tier,
} from "../data/governance";

const known = (id?: string) => !!id && AGENTS.some((a) => a.id === id);
const who = (id: string) => (id === "jay" ? "Jay" : agent(id).name);
const ago = (at: number) => { const m = Math.max(0, Math.round((Date.now() - at) / 60_000)); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const left = (ms: number) => (ms <= 0 ? "expired" : ms < 3600_000 ? `${Math.max(1, Math.round(ms / 60_000))} min left` : `${Math.round(ms / 3600_000)} h left`);

function useTier(r: Req): Tier {
  const g = useStore(gov);
  const line = r.override ? budgetLines(g.scenario).find((l) => l.scope === r.override!.scope && l.key === r.override!.key) : undefined;
  return tierOf(r, line?.limit.usd);
}

/** The Slack message as Jay would see it on his phone. A preview: nothing is sent. */
export function SlackPreview({ r, tier, onOpen }: { r: Req; tier: Tier; onOpen: () => void }) {
  const hash = reqHash(r);
  const slackOk = approvableIn(tier, "slack");
  return <div className="slack-phone" aria-label="Slack message preview">
    <div className="slack-top"><Icon name="slack" size={15} /><b>#approvals</b><span className="sp" /><small>Preview · not sent</small></div>
    <div className="slack-msg">
      <span className="slack-bot"><Icon name="spark" size={16} /></span>
      <div className="slack-body">
        <div className="slack-from"><b>CommandCenter</b><span className="slack-app">APP</span><small>now</small></div>
        <p className="slack-title">Onboarding request · {r.title}</p>
        <dl className="slack-kv">
          {r.agent && <><dt>Agent</dt><dd>{known(r.agent) ? agent(r.agent).name : r.agent[0].toUpperCase() + r.agent.slice(1)} <code>agent:{r.agent}</code></dd></>}
          {r.project && <><dt>Project</dt><dd>{r.project}</dd></>}
          <dt>Risk</dt><dd><span className={cx("slack-tier", `t-${TIER_TONE[tier]}`)}>{TIER_LABEL[tier]}</span></dd>
          <dt>Asked by</dt><dd>{who(r.requestedBy)}</dd>
          <dt>Change</dt><dd>{r.changes.map((c) => c.field).join(", ")}</dd>
          <dt>Request</dt><dd><code>{hash}</code> · {left(r.expires - Date.now())}</dd>
        </dl>
        <div className="slack-acts">
          <button type="button" className="slack-btn is-primary" onClick={onOpen}>Open in CommandCenter</button>
          {tier === "low" && <button type="button" className="slack-btn" disabled={!slackOk} title="Approving inside Slack is a later step of D-032 and is not turned on">Approve</button>}
        </div>
        <p className="slack-foot">Link: <code>…/approve/{r.id}</code> · an opaque request ID, not a credential. It opens only over your private, signed-in path.
          {tier === "high" ? " High-risk: approve in CommandCenter only." : !SLACK_STEP_2 && tier === "low" ? " In-Slack approval: later step, off." : ""}</p>
      </div>
    </div>
  </div>;
}

function Screen({ r }: { r: Req }) {
  const g = useStore(gov);
  const tier = useTier(r);
  const [unlocked, setUnlocked] = useState(false);
  const [typed, setTyped] = useState("");
  const [seen] = useState(() => reqHash(r));          // the hash this screen was opened with
  const hash = reqHash(r);
  const changed = hash !== seen;
  const rec = g.decisions[r.id];
  const expired = r.expires <= Date.now();
  const expected = confirmText(r);
  const allowed = !changed && canApprove(tier, { unlocked, typed, expected, expired });
  const record = (d: "approved" | "declined") => {
    decide(r.id, d, tier === "high" ? "screen + Developer Unlock" : "screen");
    notify(d === "approved" ? `Approved: ${r.title}` : `Declined: ${r.title}`, d === "approved" ? "ok" : "warn");
  };
  return <section className="panel appr-screen" aria-label="Approval screen" data-testid="approval-screen">
    <header className="appr-head">
      <div>{known(r.agent) ? <Avatar id={r.agent!} size={40} /> : <span className="appr-ico"><Icon name={r.kind === "budget_override" ? "receipt" : r.kind === "policy_change" ? "doc" : "spark"} size={20} /></span>}</div>
      <div className="appr-t"><h2>{r.title}</h2>
        <p className="muted">Asked by {who(r.requestedBy)} · {ago(r.at)}{r.agent && <> · <code>agent:{r.agent}</code></>}</p></div>
      <Pill tone={TIER_TONE[tier]} dot>{TIER_LABEL[tier]}</Pill>
    </header>
    <div className="appr-grid">
      <div><h3>The change</h3>
        <table className="appr-diff"><thead><tr><th>Field</th><th>Now</th><th>After</th></tr></thead>
          <tbody>{r.changes.map((c, i) => <tr key={i}><td>{c.field}</td><td className="muted">{c.from}</td><td>{c.to}</td></tr>)}</tbody></table></div>
      <div><h3>Approving does</h3><ul className="appr-list is-does">{r.does.map((d) => <li key={d}><Icon name="tick" size={13} />{d}</li>)}</ul>
        <h3>It does not</h3><ul className="appr-list is-not">{r.doesNot.map((d) => <li key={d}><Icon name="x" size={13} />{d}</li>)}</ul></div>
    </div>
    <dl className="kv appr-kv"><dt>Request</dt><dd><code>{r.id}</code> · hash <code>{hash}</code></dd><dt>Expires</dt><dd>{left(r.expires - Date.now())}</dd>
      <dt>Where</dt><dd>{tier === "high" ? "CommandCenter only, with Developer Unlock" : tier === "low" ? "This screen (in Slack later, once that step is approved)" : "This screen"}</dd></dl>
    {rec ? <div className={cx("callout", rec.decision === "approved" ? "t-ok" : "t-warn")} data-testid="approval-recorded"><Icon name={rec.decision === "approved" ? "check" : "x"} size={16} />
      <span><b>{rec.decision === "approved" ? "Approved" : "Declined"}</b> · bound to hash <code>{rec.hash}</code> · via {rec.via}. Recorded once; a changed request would need a new approval.</span></div>
      : expired ? <div className="callout t-warn"><Icon name="clock" size={16} /><span>This request expired. Ask for a fresh one; an expired request can’t be approved.</span></div>
      : <>
        {changed && <div className="callout t-warn" role="alert"><Icon name="info" size={16} /><span>This request changed after you opened it (hash {seen} → {hash}). Reload to review the new version; the old one can’t be approved.</span></div>}
        {tier === "high" && <div className="appr-strong" data-testid="strong-confirm">
          <p><b>Stronger confirmation.</b> High-risk changes need your Developer Unlock session and the exact ID typed below.</p>
          <div className="row-gap"><button type="button" className={cx("btn btn-sm", unlocked && "btn-outline")} aria-pressed={unlocked} onClick={() => setUnlocked(!unlocked)}>
            <Icon name="lock" size={14} /> {unlocked ? "Developer Unlock active (demo)" : "Use Developer Unlock (demo)"}</button>
            <label className="appr-type"><span className="muted small">Type <code>{expected}</code> to confirm</span>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label={`Type ${expected} to confirm`} autoComplete="off" spellCheck={false} /></label></div>
        </div>}
        <div className="row-gap end">
          <button type="button" className="btn btn-sm" onClick={() => amendRequest(r.id)} title="Demo: the requester changes the request after it was sent">Simulate a change (demo)</button>
          <span className="sp" />
          <button type="button" className="btn" onClick={() => record("declined")} disabled={changed}>Decline</button>
          <button type="button" className="btn btn-primary" disabled={!allowed} onClick={() => record("approved")}>Approve</button>
        </div>
      </>}
  </section>;
}

export function Approvals() {
  const g = useStore(gov);
  const route = useRoute();
  const sel = g.requests.find((r) => r.id === route.id) ?? g.requests[0];
  return <div className="page page-approvals">
    <div className="page-head"><div><h1>Approvals</h1><p>Requests reach your phone in Slack with a secure link. You approve here, on a signed-in screen; high-risk changes need stronger confirmation.</p></div>
      <div className="row-gap"><Demo /><PopButton id="page:approvals" /></div></div>
    <div className="shadow-note" role="note"><Icon name="info" size={18} /><div><b>Slack is not connected</b>
      <p>This is a preview of D-032. ccd connects out to Slack, so nothing on the internet can reach it, and the local API is never made public. Slack stays off until you approve it.</p></div></div>
    <div className="appr-layout">
      <nav className="panel appr-queue" aria-label="Requests">
        <h2>Requests</h2>
        <ul>{g.requests.map((r) => <ReqItem key={r.id} r={r} on={r.id === sel?.id} done={g.decisions[r.id]?.decision} />)}</ul>
      </nav>
      {sel ? <Screen key={`${sel.id}`} r={sel} /> : <section className="panel pad"><p className="muted">No requests.</p></section>}
      {sel && <SlackSide r={sel} />}
    </div>
  </div>;
}

function ReqItem({ r, on, done }: { r: Req; on: boolean; done?: "approved" | "declined" }) {
  const tier = useTier(r);
  const expired = r.expires <= Date.now();
  return <li><button type="button" className={cx("appr-item", on && "is-sel")} aria-current={on ? "true" : undefined} onClick={() => go("approvals", r.id)} data-testid={`req-${r.id}`}>
    <span className="appr-item-t"><b>{r.title}</b><small className="muted">{who(r.requestedBy)} · {ago(r.at)}</small></span>
    <span className="appr-item-s"><Pill tone={TIER_TONE[tier]}>{TIER_LABEL[tier]}</Pill>
      {done ? <small className={done === "approved" ? "t-ok" : "t-warn"}>{done === "approved" ? "Approved" : "Declined"}</small> : expired ? <small className="muted">Expired</small> : <small className="muted">Waiting</small>}</span>
  </button></li>;
}

function SlackSide({ r }: { r: Req }) {
  const tier = useTier(r);
  return <aside className="appr-slack" aria-label="On your phone">
    <h2 className="muted small">On your phone</h2>
    <SlackPreview r={r} tier={tier} onOpen={() => { go("approvals", r.id); document.querySelector<HTMLElement>("[data-testid=approval-screen] h2")?.focus?.(); }} />
  </aside>;
}
