// The one decision a ticket is waiting on, in manager language first (spec §11, §22):
//
//   blocked   "SV-071 cannot continue" — what happened · why it matters · recommended action ·
//             estimated impact; [Fix and continue] [Re-plan] [Show technical details]
//   plan      the plan needs approval              [Approve plan] [Re-plan]
//   merge     reviewed and green, needs acceptance [Accept — allow merge] [Request changes]
//   ui        UI review ready                      [UI accepted] [Needs fixes]
//   deploy    Ready for live deployment — what will go live · verification completed  [Approve live deploy]
//             on a live project it waits for the weekly release; a risky one can go as urgent  [Approve as urgent]
//
// Every button is an existing pipeline step recorded as Jay; the ones that close a gate need
// Developer Unlock (ccd checks it too). The task's Claude session is told what Jay decided.
import { useState } from "react";
import { app } from "../store/app";
import type { TicketWork } from "../api/types";
import { devOr } from "../components/DevMode";
import { Ago } from "../components/ui";
import { useRelease, windowText } from "../hq/release";

/** When a held deploy can go out, in this browser's own time: "Wed, Nov 18, 10:00 PM". */
export const releaseAt = (at: number) => new Date(at * 1000)
  .toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function GateCard({ ticketKey, work, onDone }: { ticketKey: string; work: TicketWork; onDone: (w: TicketWork) => void }) {
  const [busy, setBusy] = useState(false);
  const [tech, setTech] = useState(false);
  const gate = work.gate;
  const blocked = work.status === "BLOCKED" || gate === "failure";
  const deploying = work.deploy?.approvedAt && !work.deploy?.result && work.deploy?.env === "live";
  if (!gate && !blocked && !deploying) return null;

  const run = async (op: string, body: Record<string, unknown>, ok: string, needsDev = true) => {
    if (needsDev && !devOr(() => void run(op, body, ok, needsDev))) return;
    setBusy(true);
    try {
      const w = await app.api.workOp(ticketKey, op, body);
      onDone(w);
      app.toast(w.nudge && !w.nudge.delivered ? `${ok} — Claude not reached: ${w.nudge.reason}` : ok, w.nudge && !w.nudge.delivered ? "bad" : "ok");
    } catch (e) { app.toast((e as Error).message, "bad"); } finally { setBusy(false); }
  };
  const ask = (q: string, dflt: string) => window.prompt(q, dflt)?.trim();
  const rework = (dflt: string) => { const r = ask("What needs fixing? (Claude gets this)", dflt); if (r) void run("rework", { reason: r }, `${ticketKey} back to implementation`); };
  const replan = (dflt: string) => { const r = ask("Why does it go back to planning? (Claude gets this)", dflt); if (r) void run("replan", { reason: r }, `${ticketKey} back to planning`); };
  const confirm = (g: string, ok: string, more: Record<string, unknown> = {}) => void run("confirm", { gate: g, ...more }, ok);

  if (blocked) {
    const b = work.blocked;
    return <section className="gate is-blocked" aria-label={`${ticketKey} is blocked`} id="gate">
      <h3>{ticketKey} cannot {b?.stage === "MERGE" || b?.stage === "REVIEW" ? "merge yet" : "continue"}</h3>
      <dl className="gate-dl">
        <dt>What happened</dt><dd>{b?.what || b?.reason || work.gateReason || "Blocked."}</dd>
        {b?.why && <><dt>Why it matters</dt><dd>{b.why}</dd></>}
        {b?.action && <><dt>Recommended action</dt><dd>{b.action}</dd></>}
        {b?.impact && <><dt>Estimated impact</dt><dd>{b.impact}</dd></>}
      </dl>
      <div className="gate-actions">
        <button type="button" className="btn is-primary" disabled={busy} onClick={() => rework(b?.action || b?.reason || "")}>Fix and continue</button>
        <button type="button" className="btn" disabled={busy} onClick={() => replan(b?.reason || "")}>Re-plan</button>
        <button type="button" className="btn is-quiet" aria-expanded={tech} onClick={() => setTech(!tech)}>{tech ? "Hide" : "Show"} technical details</button>
      </div>
      {tech && <div className="gate-tech mono-xs">
        <div>stage {b?.stage ?? "—"} · status {work.status} · <Ago at={b?.at} /></div>
        <div>reason: {b?.reason ?? work.gateReason ?? "—"}</div>
        {b?.technical && <pre>{b.technical}</pre>}
        {work.review?.head && <div>review {work.review.verdict ?? "—"} at {work.review.head.slice(0, 12)} · cycles {work.review.cycles}</div>}
        {gate === "failure" && <button type="button" className="btn is-sm" disabled={busy}
          onClick={() => confirm("failure", "Blocker cleared")}>Clear blocker and resume at {b?.stage ?? "its stage"}</button>}
      </div>}
    </section>;
  }
  if (deploying) {
    return <section className="gate is-deploy" aria-label="Deploying" id="gate">
      <h3>Approved — confirm the deploy in Claude's pane</h3>
      <p className="muted">You approved it <Ago at={work.deploy!.approvedAt} />. Claude prepares the deploy (steps, checks, rollback) and waits for you there; then it deploys, verifies and records it.</p>
      {work.deploy!.heldUntil != null && <p className="muted">Held for the weekly release: it can go out from {releaseAt(work.deploy!.heldUntil)}. ccd does not record it as deployed before then.</p>}
      {work.deploy!.urgent && <p className="muted">Approved as urgent: it does not wait for the release window.</p>}
    </section>;
  }
  if (gate === "deploy") {
    return <DeployGate work={work} busy={busy} onRework={() => rework("not ready to go live: ")}
      onApprove={(urgent) => urgent
        ? confirm("deploy", "Urgent live deploy approved: no release window. Confirm in Claude's pane", { urgent: true })
        : confirm("deploy", "Live deploy approved — Claude prepares; confirm in its pane")} />;
  }
  if (gate === "plan") {
    return <section className="gate is-plan" aria-label="Plan needs approval" id="gate">
      <h3>The plan needs your approval</h3>
      <p>{work.plan?.summary || work.gateReason}</p>
      {work.policy?.planReasons?.length ? <p className="muted mono-xs">why you: {work.policy.planReasons.join(", ")}</p> : null}
      <div className="gate-actions">
        <button type="button" className="btn is-primary" disabled={busy} onClick={() => confirm("plan", "Plan approved")}>Approve plan</button>
        <button type="button" className="btn" disabled={busy} onClick={() => replan("")}>Re-plan</button>
      </div>
    </section>;
  }
  if (gate === "merge") {
    return <section className="gate is-merge" aria-label="Ready to merge" id="gate">
      <h3>Reviewed and green — your acceptance</h3>
      <p className="muted">A fresh reviewer approved the exact head {work.review?.head ? <span className="mono">{work.review.head.slice(0, 7)}</span> : null}
        {work.review?.pr ? <> on {work.review.pr}</> : null}. Accepting lets Claude merge this head (a new commit needs a new review).</p>
      <div className="gate-actions">
        <button type="button" className="btn is-primary" disabled={busy} onClick={() => confirm("merge", "Merge accepted for this head")}>Accept — allow merge</button>
        <button type="button" className="btn" disabled={busy} onClick={() => rework("")}>Request changes</button>
      </div>
    </section>;
  }
  if (gate === "ui") {
    const shots = (work.evidence ?? []).filter((e) => e.kind === "screenshot" || e.kind === "image");
    return <section className="gate is-ui" aria-label="UI review ready" id="gate">
      <h3>UI review ready</h3>
      <p className="muted">Verified{work.verification?.evidence ? `: ${work.verification.evidence}` : "."} Check the screens, then decide.</p>
      {shots.length > 0 && <ul className="gate-ev">{shots.map((e) => <li key={e.id} className="mono-xs">{e.ref}{e.note ? ` — ${e.note}` : ""}</li>)}</ul>}
      <div className="gate-actions">
        <button type="button" className="btn is-primary" disabled={busy} onClick={() => confirm("ui", "UI accepted")}>UI accepted</button>
        <button type="button" className="btn" disabled={busy} onClick={() => rework("")}>Needs fixes</button>
      </div>
    </section>;
  }
  return null;
}

/** The deploy gate. On a live project a live deploy waits for the weekly release (flow contract §5), and only a risky
 *  ticket can skip the wait, when Jay approves it as urgent. Its own component so that only a ticket at this gate
 *  asks ccd for the release settings. */
function DeployGate({ work, busy, onApprove, onRework }: { work: TicketWork; busy: boolean; onApprove: (urgent: boolean) => void; onRework: () => void }) {
  const rel = useRelease();
  const d = work.deploy;
  const held = d?.heldUntil ?? null;
  // A ticket that only needs a deploy has none yet: this approval creates it, and ccd then places it by when it
  // was approved. So on a live project it will wait for a window, and urgent has to be chosen now.
  const willWait = !d?.requestedAt && !!work.project && rel.data?.projects[work.project]?.live === true ? rel.data.window : null;
  const urgent = work.size === "risky" && (held !== null || willWait !== null);
  // Until ccd has said whether the project is live, a risky ticket may still get the urgent choice: hold both
  // approvals so a quick press cannot skip it. A failed or missing release route lets them go.
  const deciding = work.size === "risky" && !d?.requestedAt && !!work.project && (rel.state === "idle" || rel.state === "loading");
  return <section className="gate is-deploy" aria-label="Ready for live deployment" id="gate">
    <h3>Ready for live deployment</h3>
    <dl className="gate-dl">
      <dt>What will go live</dt><dd>{d?.what || work.gateReason || "This ticket's merged change."}</dd>
      <dt>Verification completed</dt><dd>{d?.verification || work.verification?.evidence || "—"}</dd>
      {held !== null && <><dt>Release window</dt><dd>Held for the weekly release. It can go out from {releaseAt(held)}.</dd></>}
      {willWait && <><dt>Release window</dt><dd>This project is live, so the deploy goes out in the weekly release ({windowText(willWait)}).</dd></>}
    </dl>
    <div className="gate-actions">
      <button type="button" className="btn is-primary" disabled={busy || deciding} onClick={() => onApprove(false)}>Approve live deploy</button>
      {urgent && <button type="button" className="btn" disabled={busy} onClick={() => onApprove(true)}>Approve as urgent</button>}
      <button type="button" className="btn" disabled={busy} onClick={onRework}>Not yet — fix first</button>
    </div>
    {urgent && <p className="muted">Urgent is for a risky change that cannot wait: its deploy does not wait for the release window.</p>}
  </section>;
}
