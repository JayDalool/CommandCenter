// NIGHT SHIFT on the Dashboard: each project's line (running / last night), its morning report — a release
// candidate — and the two decisions that are Jay's: End night shift, and Go Live (the coordinator deploys main by
// the repository's own runbook; ccd runs no deploy itself).
import { useCallback, useEffect, useState } from "react";
import { app } from "../store/app";
import type { NightProject, NightShiftState } from "../api/types";
import { ago, nowS } from "../lib/time";
import { Dialog } from "./Dialog";
import { unlockDialogOpen, useDevActive } from "./DevMode";

/** Every project's night shift, refreshed each minute (and after End / Go Live). */
export function useNightShift(): [NightShiftState | null, () => void] {
  const [st, setSt] = useState<NightShiftState | null>(null);
  const load = useCallback(() => { app.api.nightShiftState().then(setSt).catch(() => {}); }, []);
  useEffect(() => { load(); const id = window.setInterval(load, 60_000); return () => window.clearInterval(id); }, [load]);
  return [st, load];
}

const COORD: Record<string, string> = { working: "working", idle: "idle", done: "idle", blocked: "waiting on a prompt for you" };

export function NightLine({ project, name, n, onChanged }: {
  project: string; name: string; n: NightProject | undefined; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  if (n?.paused) return <div className="dash-night is-paused"><span aria-hidden>⏸</span>
    <span className="trunc" title={n.paused}>Paused — {n.paused.replace(/^Jay paused \S+ /, "")}</span></div>;
  if (!n || (!n.active && !n.report)) return null;
  const rep = n.report;
  const text = n.active
    ? `Night shift running · Claude ${COORD[n.coordinator.status ?? ""] ?? "not reachable"}${n.nudges ? ` · ${n.nudges} reminder${n.nudges === 1 ? "" : "s"}` : ""}`
    : `Last night: ${rep?.status === "complete" || n.endReason === "complete" ? "complete" : n.endReason ?? "report"}${rep ? ` · ${ago(rep.mtime, nowS())}` : ""}`;
  return <div className={`dash-night${n.active ? " is-on" : ""}${n.coordinator.status === "blocked" && n.active ? " is-jay" : ""}`}>
    <span aria-hidden>☾</span><span className="trunc" title={text}>{text}</span>
    <button type="button" className="btn is-quiet is-xs" onClick={() => setOpen(true)}>{rep ? "Report" : "Details"}</button>
    {open && <NightReportDialog project={project} name={name} n={n} onClose={() => setOpen(false)} onChanged={onChanged} />}
  </div>;
}

export function NightReportDialog({ project, name, n, onClose, onChanged }: {
  project: string; name: string; n: NightProject; onClose: () => void; onChanged: () => void;
}) {
  const dev = useDevActive();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<string>) => {
    if (!dev) { unlockDialogOpen(); return; }
    setBusy(true);
    try { app.toast(await fn()); onChanged(); onClose(); }
    catch (e) { app.toast((e as Error).message, "bad"); }
    finally { setBusy(false); }
  };
  const rep = n.report;
  return <Dialog title={`${name} · night shift`} onClose={onClose}>
    <p className="mono-xs muted">
      {n.active ? `Running since ${n.startedAt ? new Date(n.startedAt * 1000).toLocaleTimeString() : "—"}`
        : n.endedAt ? `Ended ${new Date(n.endedAt * 1000).toLocaleString()}${n.endReason ? ` — ${n.endReason}` : ""}` : "Not running"}
      {n.goLiveAt ? ` · Go Live sent ${ago(n.goLiveAt, nowS())}` : ""}
    </p>
    {rep ? <pre className="night-report" aria-label="Morning report">{rep.text}</pre>
      : <p className="muted">No morning report yet.</p>}
    {confirm ? <div className="night-confirm" role="alertdialog" aria-label="Confirm Go Live">
      <b>Deploy {name} to production now?</b>
      <p className="text2">Claude deploys <b>main as it is now</b> by the repository's deploy runbook, runs its checks and rolls
        back by the runbook if one fails. Pending live-deploy requests in {name} are approved by this.</p>
      <div className="row">
        <button type="button" className="btn is-primary" disabled={busy} data-autofocus
          onClick={() => void act(async () => { const r = await app.api.goLive(project);
            return `Go Live sent to ${r.coordinator}${r.approved.length ? ` · approved ${r.approved.join(", ")}` : ""}`; })}>
          Yes, go live</button>
        <button type="button" className="btn is-quiet" onClick={() => setConfirm(false)}>Cancel</button>
      </div>
    </div>
      : <div className="row" style={{ marginTop: 12 }}>
        <button type="button" className="btn is-primary" disabled={busy || n.active} onClick={() => setConfirm(true)}
          title={n.active ? "End the night shift first" : "Deploy the merged batch by the repo's runbook"}>Go Live…</button>
        {n.active && <button type="button" className="btn" disabled={busy}
          onClick={() => void act(async () => { const r = await app.api.nightShiftEnd(project);
            return r.told ? `${name} night shift ended` : `${name} night shift ended — Claude was not reached; stop it in its pane`; })}>
          End night shift</button>}
        <button type="button" className="btn is-quiet" onClick={onClose}>Close</button>
        {!dev && <span className="mono-xs muted">Go Live and End need Developer Mode.</span>}
      </div>}
  </Dialog>;
}
