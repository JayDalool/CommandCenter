// The Autonomy Engine in SHADOW MODE (decision D-008), read-only. For each decision Command Center made (accept a plan,
// merge, deploy) it shows what the agreed target policy would have done and where the two disagree. The engine decides
// nothing; this is the evidence for switching any of the target policy on later.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import type { AutonomyOutcome, AutonomyState } from "../api/types";
import { Panel, DetailRow } from "./ui";

const DID: Record<AutonomyOutcome, string> = { auto: "acted on its own", jay: "asked you", refuse: "refused" };
const WOULD: Record<AutonomyOutcome, string> = { auto: "would have acted on its own", jay: "would have asked you", refuse: "would have refused" };

function when(at: number): string {
  return new Date(at * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function AutonomyShadow({ names }: { names: Record<string, string> }) {
  const [data, setData] = useState<AutonomyState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { app.api.autonomy().then(setData).catch((e) => setErr((e as Error).message)); }, []);
  if (err) return <Panel title="Autonomy engine (shadow)" pad><p className="muted">Unavailable: {err}</p></Panel>;
  if (!data) return null;
  const missing = Object.entries(data.missing).sort((a, b) => b[1] - a[1]);
  return <Panel title="Autonomy engine (shadow)" pad count={data.total}
    meta={<span className="mono-xs muted">engine v{data.engine} · not enforced</span>}>
    <p className="text2">For each plan, merge and deploy decision, what your agreed target policy <b>would</b> have done,
      next to what Command Center did. It <b>changes nothing</b>; disagreements are the evidence before any of it is switched on.</p>
    {!data.available
      ? <p className="muted">Not recorded: the task system is off.</p>
      : data.total === 0
      ? <p className="muted">No decisions recorded yet.</p>
      : <>
        <p className="mono-xs"><span className="tc-ok">{data.agree} agree</span> · <span className={data.disagree ? "" : "muted"}>{data.disagree} disagree</span></p>
        <dl className="pol-dl">
          {Object.entries(data.counts).map(([p, acts]) => <DetailRow key={p} label={names[p] ?? p}>
            {Object.entries(acts).map(([a, c]) => <span key={a} className="pol-kv"><b>{a}</b> {c.agree}/{c.total} agree</span>)}
          </DetailRow>)}
          {missing.length > 0 && <DetailRow label="could not tell">
            {missing.map(([m, n]) => <span key={m} className="pol-kv"><b>{m}</b> {n}×</span>)}
          </DetailRow>}
        </dl>
        {data.disagreements.length > 0 && <ul className="pol-shadow" aria-label="Recent disagreements">
          {data.disagreements.slice(0, 12).map((d) => <li key={d.id}>
            <span className="mono-xs muted">{when(d.at)}</span> <b>{d.key ?? names[d.project] ?? d.project}</b> {d.action}:
            {" "}Command Center {DID[d.observed]}; target policy {WOULD[d.engine]}
            <span className="muted"> ({d.reasons[0] ?? d.rule}{d.missing.length ? `; unknown: ${d.missing.join(", ")}` : ""})</span>
          </li>)}
        </ul>}
      </>}
  </Panel>;
}
