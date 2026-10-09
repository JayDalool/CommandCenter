// The one decision a ticket is waiting on, in manager language first (spec §11, §22):
//
//   blocked   "SV-071 cannot continue" — what happened · why it matters · recommended action ·
//             estimated impact; [Fix and continue] [Re-plan] [Show technical details]
//   plan      the plan needs approval              [Approve plan] [Re-plan]
//   merge     reviewed and green, needs acceptance [Accept — allow merge] [Request changes]
//   ui        UI review ready                      [UI accepted] [Needs fixes]
//   deploy    Ready for live deployment — what will go live · verification completed  [Deploy Live]
//
// Every button is an existing pipeline step recorded as Jay; the ones that close a gate need
// Developer Unlock (ccd checks it too). The task's Claude session is told what Jay decided.
import { useState } from "react";
import { app } from "../store/app";
import type { TicketWork } from "../api/types";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";
import { Ago } from "../components/ui";

export function GateCard({ ticketKey, work, onDone }: { ticketKey: string; work: TicketWork; onDone: (w: TicketWork) => void }) {
  const dev = useDevActive();
  const [busy, setBusy] = useState(false);
  const [tech, setTech] = useState(false);
  const gate = work.gate;
  const blocked = work.status === "BLOCKED" || gate === "failure";
  const deploying = work.deploy?.approvedAt && !work.deploy?.result && work.deploy?.env === "live";
  if (!gate && !blocked && !deploying) return null;

  const run = async (op: string, body: Record<string, unknown>, ok: string, needsDev = true) => {
    if (needsDev && !dev) { unlockDialogOpen(); return; }
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
  const confirm = (g: string, ok: string) => void run("confirm", { gate: g }, ok);

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
      <h3>Deploying live</h3>
      <p className="muted">You approved it <Ago at={work.deploy!.approvedAt} />. Claude deploys, verifies live and records the result; then the task closes.</p>
    </section>;
  }
  if (gate === "deploy") {
    const d = work.deploy;
    return <section className="gate is-deploy" aria-label="Ready for live deployment" id="gate">
      <h3>Ready for live deployment</h3>
      <dl className="gate-dl">
        <dt>What will go live</dt><dd>{d?.what || work.gateReason || "This ticket's merged change."}</dd>
        <dt>Verification completed</dt><dd>{d?.verification || work.verification?.evidence || "—"}</dd>
      </dl>
      <div className="gate-actions">
        <button type="button" className="btn is-primary" disabled={busy} onClick={() => confirm("deploy", "Live deployment approved")}>Deploy Live</button>
        <button type="button" className="btn" disabled={busy} onClick={() => rework("not ready to go live: ")}>Not yet — fix first</button>
      </div>
    </section>;
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
