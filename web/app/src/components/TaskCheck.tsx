// THE TASK CHECK — "are the tasks in Command Center the actual tasks left?" One click asks each project's
// coordinator Claude (ccd: POST /api/tasks/check, a fixed message) to compare its open tasks with the repo and
// every .md file that held tasks: stale ones come back as "Cancel it / Keep it" questions in Needs Jay, missing
// ones land in the Inbox. Claude never cancels anything itself.
import { useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { byProjectOrder, initials, isActive, pjVar } from "../lib/control";
import { Dialog } from "./Dialog";
import { useNightShift } from "./NightShift";
import { unlockDialogOpen, useDevActive } from "./DevMode";

type Result = { ok: boolean; text: string };
/** check: the task check. night: night shift — each coordinator works its open tasks until morning, never deploys. */
type Mode = "check" | "night";

export function TaskCheckButton({ className = "btn" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className={className} onClick={() => setOpen(true)}
      title="Ask each project's Claude to find stale tasks and tasks missing from Command Center">Check tasks</button>
    {open && <TaskCheckDialog onClose={() => setOpen(false)} />}
  </>;
}

export function NightShiftButton({ className = "btn" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className={className} onClick={() => setOpen(true)}
      title="Away mode: each project's Claude works its open tasks until morning (no deploys)">☾ Night shift</button>
    {open && <TaskCheckDialog mode="night" onClose={() => setOpen(false)} />}
  </>;
}

export function TaskCheckDialog({ onClose, mode = "check" }: { onClose: () => void; mode?: Mode }) {
  const night = mode === "night";
  const send = (k: string, copy = false) => (night ? app.api.nightShift(k, copy) : app.api.taskCheck(k, copy));
  const dev = useDevActive();
  const st = useSelector(app.store, (d) => d.state);
  const taskProjects = useSelector(app.store, (d) => d.taskProjects);
  const [res, setRes] = useState<Record<string, Result>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const live = new Set((st?.projects ?? []).map((p) => p.key));
  // The Dashboard's projects: a registered repository, or open tasks.
  const projects = byProjectOrder(taskProjects.filter((p) => !live.size || live.has(p.key)
    || tickets.some((t) => t.project === p.key && isActive(t))));
  const [copied, setCopied] = useState<string | null>(null);
  const [nightState] = useNightShift();
  const paused = (k: string) => nightState?.projects[k]?.paused ?? null;
  // No coordinator Claude to send it to: the same message, to paste into any Claude working in that repo.
  const copy = async (k: string) => {
    if (!dev) { unlockDialogOpen(); return; }
    try {
      const r = await send(k, true);
      await navigator.clipboard.writeText(r.text ?? "");
      setCopied(k);
    } catch (e) { app.toast((e as Error).message, "bad"); }
  };

  const run = async (keys: string[]) => {
    if (!dev) { unlockDialogOpen(); return; }
    for (const k of keys) {
      setBusy(k);
      try {
        const r = await send(k);
        setRes((m) => ({ ...m, [k]: { ok: true, text: night ? `${r.coordinator} is on the night shift`
          : `Sent to ${r.coordinator} · ${r.openTasks} open tasks to check` } }));
      } catch (e) {
        setRes((m) => ({ ...m, [k]: { ok: false, text: (e as Error).message } }));
      }
    }
    setBusy(null);
  };

  return <Dialog title={night ? "Night shift" : "Check tasks"} onClose={onClose}>
    {night ? <p className="text2">Each project's Claude works every task that doesn't wait for you, end to end: plan, build,
      fresh review, <b>merge where no gate is open</b> (SamVision and GauzeMate stop at Ready to Merge for you), verify. With
      nothing free left it looks for showstoppers only. It <b>never deploys or goes live</b>. Command Center keeps it going
      until its report says complete; the report is a release candidate for Go Live. In any Claude you can also type
      <code> /night-shift</code>.</p>
      : <p className="text2">Each project's Claude compares its open tasks with the repo and every .md file that held tasks.
      Stale tasks come back to you as <b>Cancel it / Keep it</b> in Needs Jay; work missing from Command Center lands in
      the Inbox. Claude changes no code and cancels nothing itself.</p>}
    <p className="mono-xs muted">A task waits for you only while it, or a task it is blocked by, has an open question or
      decision for you. Everything else keeps moving.</p>
    <div className="tc-list">
      {projects.map((p) => {
        const c = st?.coordinators?.[p.key];
        const r = res[p.key];
        return <div key={p.key} className="tc-row" style={pjVar(p.key)}>
          <span className="pj-badge is-sm" aria-hidden>{initials(p.prefix, p.name)}</span>
          <span className="tc-name"><b>{p.name}</b>
            <span className={`mono-xs ${r ? (r.ok ? "tc-ok" : "tc-bad") : "muted"}`}>
              {paused(p.key) ? `Paused — ${paused(p.key)}` : r ? r.text
                : `${c?.paneId ? `Claude ${c.name} · ${c.status}` : "no coordinator Claude identified"}${
                  nightState?.projects[p.key]?.mode === "careful" ? " · careful mode: research first, Jay merges" : ""}`}</span></span>
          <span className="row" style={{ gap: 4 }}>
            {!paused(p.key) && ((r && !r.ok) || !c?.paneId) && <button type="button" className="btn is-sm is-quiet" onClick={() => void copy(p.key)}
              title="Copy the message to paste into a Claude working in this repo">
              {copied === p.key ? "Copied ✓" : "Copy prompt"}</button>}
            <button type="button" className="btn is-sm" disabled={busy !== null || !!paused(p.key)} onClick={() => void run([p.key])}>
              {busy === p.key ? "Sending…" : r?.ok ? "Sent ✓" : night ? "Start" : "Check"}</button></span>
        </div>;
      })}
    </div>
    <div className="row" style={{ marginTop: 14 }}>
      <button type="button" className="btn is-primary" data-autofocus disabled={busy !== null}
        onClick={() => void run(projects.map((p) => p.key).filter((k) => !res[k]?.ok && !paused(k)))}>
        {night ? "Start night shift in all projects" : "Check all projects"}</button>
      <button type="button" className="btn is-quiet" onClick={onClose}>Close</button>
      {!dev && <span className="mono-xs muted">Needs Developer Mode (it sends a message to Claude).</span>}
    </div>
  </Dialog>;
}
