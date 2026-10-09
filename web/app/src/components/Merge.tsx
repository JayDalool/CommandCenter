// MERGE — one press for everything that is ready. Per project: the tickets whose review approved the PR's exact
// current head with green CI, in merge order (blockers first, then oldest PR). Jay approves exactly those heads;
// each repository's coordinator merges them one at a time, waits for CI on main between merges and stops if main
// goes red (ccd: POST /api/jay/merge). Nothing is deployed; ccd merges nothing itself.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { byProjectOrder, initials, pjVar, taskHref } from "../lib/control";
import type { MergeReady } from "../api/types";
import { Dialog } from "./Dialog";
import { unlockDialogOpen, useDevActive } from "./DevMode";

type Result = { ok: boolean; text: string };

export function MergeButton({ className = "btn" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className={className} onClick={() => setOpen(true)}
      title="Merge every reviewed, green PR — one at a time per repository">⇉ Merge ready</button>
    {open && <MergeDialog onClose={() => setOpen(false)} />}
  </>;
}

export function MergeDialog({ onClose }: { onClose: () => void }) {
  const dev = useDevActive();
  const taskProjects = useSelector(app.store, (d) => d.taskProjects);
  const [data, setData] = useState<MergeReady | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, Result>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string[] | null>(null);
  useEffect(() => { app.api.mergeReady().then(setData).catch((e) => setErr((e as Error).message)); }, []);

  const rows = byProjectOrder(taskProjects).map((p) => ({ p, d: data?.projects[p.key] }))
    .filter(({ d }) => d && (d.ready.length || d.skipped.length || d.paused));
  const mergeable = rows.filter(({ d }) => d && !d.paused && d.ready.length).map(({ p }) => p.key);
  const count = (keys: string[]) => keys.reduce((n, k) => n + (data?.projects[k]?.ready.length ?? 0), 0);

  const run = async (keys: string[]) => {
    if (!dev) { unlockDialogOpen(); return; }
    setConfirm(null);
    for (const k of keys) {
      setBusy(k);
      try {
        const r = await app.api.merge(k);
        setRes((m) => ({ ...m, [k]: { ok: true, text: `${r.coordinator} is merging ${r.merging.map((x) => x.key).join(" → ")}`
          + (r.skipped.length ? ` · skipped ${r.skipped.map((x) => x.key).join(", ")}` : "") } }));
      } catch (e) {
        setRes((m) => ({ ...m, [k]: { ok: false, text: (e as Error).message } }));
      }
    }
    setBusy(null);
  };

  return <Dialog title="Merge ready" onClose={onClose}>
    <p className="text2">Each repository's Claude merges its PRs <b>one at a time, in this order</b>: it checks the head is still
      the reviewed one and CI is green, merges the way that repo merges, waits for CI on main, and stops if main goes red.
      It never rebases or pushes to a branch, and <b>nothing is deployed</b> — that stays Go Live.</p>
    {err && <p className="tc-bad mono-xs">{err}</p>}
    {!data && !err && <p className="muted">Loading…</p>}
    {data && !rows.length && <p className="muted">Nothing is ready to merge.</p>}
    <div className="tc-list">
      {rows.map(({ p, d }) => {
        const r = res[p.key];
        return <div key={p.key} className="mg-proj" style={pjVar(p.key)}>
          <div className="tc-row">
            <span className="pj-badge is-sm" aria-hidden>{initials(p.prefix, p.name)}</span>
            <span className="tc-name"><b>{p.name}</b>
              <span className={`mono-xs ${r ? (r.ok ? "tc-ok" : "tc-bad") : "muted"}`}>
                {d!.paused ? `Paused — ${d!.paused}` : r ? r.text : `${d!.ready.length} ready${d!.skipped.length ? ` · ${d!.skipped.length} not mergeable` : ""}`}</span></span>
            <button type="button" className="btn is-sm" disabled={busy !== null || !!d!.paused || !d!.ready.length || !!r?.ok}
              onClick={() => setConfirm([p.key])}>{busy === p.key ? "Sending…" : r?.ok ? "Sent ✓" : `Merge ${d!.ready.length}`}</button>
          </div>
          {!d!.paused && <ol className="mg-list">
            {d!.ready.map((m) => <li key={m.key}><a className="key" href={taskHref(m.key, null, false)}>{m.key}</a>
              <span className="trunc">{m.title}</span><span className="mono-xs muted">{m.pr.replace(/^.*#/, "#")} · {m.head.slice(0, 7)}</span>
              {m.gate === "merge" && <span className="mg-ok">your OK</span>}</li>)}
            {d!.skipped.map((x) => <li key={x.key} className="is-skip"><span className="key">{x.key}</span>
              <span className="muted trunc">not mergeable: {x.reason}</span></li>)}
          </ol>}
        </div>;
      })}
    </div>
    {confirm ? <div className="night-confirm" role="alertdialog" aria-label="Confirm merge">
      <b>Merge {count(confirm)} PR{count(confirm) === 1 ? "" : "s"} in {confirm.length} repositor{confirm.length === 1 ? "y" : "ies"}?</b>
      <p className="text2">You approve exactly the heads listed. Each repository merges one at a time and stops if main goes red.
        Nothing is deployed.</p>
      <div className="row">
        <button type="button" className="btn is-primary" data-autofocus onClick={() => void run(confirm)}>Yes, merge</button>
        <button type="button" className="btn is-quiet" onClick={() => setConfirm(null)}>Cancel</button>
      </div>
    </div>
      : <div className="row" style={{ marginTop: 14 }}>
        <button type="button" className="btn is-primary" disabled={busy !== null || !mergeable.filter((k) => !res[k]?.ok).length}
          onClick={() => setConfirm(mergeable.filter((k) => !res[k]?.ok))}>
          Merge all ready ({count(mergeable.filter((k) => !res[k]?.ok))})</button>
        <button type="button" className="btn is-quiet" onClick={onClose}>Close</button>
        {!dev && <span className="mono-xs muted">Needs Developer Mode.</span>}
      </div>}
  </Dialog>;
}
