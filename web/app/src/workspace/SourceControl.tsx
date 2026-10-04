// SOURCE CONTROL — status, diff, stage, unstage, discard (confirmed), commit
// (message + file list + confirm), and a ticket branch. Plain git through ccd:
// no push, pull, reset, force or history rewriting exists here or in ccd.
import { useCallback, useEffect, useState } from "react";
import { app } from "../store/app";
import type { ScmDiff, ScmFile, ScmStatus } from "../api/types";
import { EmptyState } from "../components/ui";
import { Dialog } from "../components/Dialog";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";

function DiffView({ d }: { d: ScmDiff | null }) {
  if (!d) return <EmptyState title="Select a changed file" hint="Its diff shows here." />;
  if (d.binary) return <EmptyState title="Binary file changed" />;
  if (!d.diff) return <EmptyState title="No textual difference" />;
  return <pre className="diff" aria-label={`Diff of ${d.path}`}>{d.diff.split("\n").map((l, i) =>
    <div key={i} className={l.startsWith("@@") ? "d-hunk" : l.startsWith("+") && !l.startsWith("+++") ? "d-add"
      : l.startsWith("-") && !l.startsWith("---") ? "d-del" : l.startsWith("diff ") || l.startsWith("index ") || l.startsWith("+++") || l.startsWith("---") ? "d-meta" : ""}>{l || " "}</div>)}
    {d.truncated && <div className="d-meta">… diff truncated</div>}</pre>;
}

export function SourceControl({ project, ticket, githubUrl, prUrl, onOpenFile }: {
  project: string; ticket: { key: string; title: string; branch: string | null } | null;
  githubUrl: string | null; prUrl: string | null; onOpenFile: (path: string) => void;
}) {
  const dev = useDevActive();
  const [st, setSt] = useState<ScmStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<{ path: string; staged: boolean } | null>(null);
  const [diff, setDiff] = useState<ScmDiff | null>(null);
  const [msg, setMsg] = useState("");
  const [confirmCommit, setConfirmCommit] = useState(false);
  const [suggest, setSuggest] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setSt(await app.api.scmStatus(project)); setErr(null); } catch (e) { setErr((e as Error).message); }
  }, [project]);
  useEffect(() => { setSt(null); setSel(null); setDiff(null); void refresh(); }, [refresh]);
  useEffect(() => {
    if (!sel) { setDiff(null); return; }
    let live = true;  // a slow answer for a file Jay already left is dropped
    app.api.scmDiff(project, sel.path, sel.staged).then((d) => { if (live) setDiff(d); })
      .catch((e) => { if (live) app.toast((e as Error).message, "bad"); });
    return () => { live = false; };
  }, [sel, project, st]);
  const tKey = ticket?.key, tBranch = ticket?.branch;
  useEffect(() => {
    setSuggest(null);
    if (tKey && !tBranch) app.api.scmTicketBranch(tKey).then((r) => setSuggest(r.suggested)).catch(() => undefined);
  }, [tKey, tBranch]);

  const run = async (op: Parameters<typeof app.api.scm>[0], body: Record<string, unknown>, ok: string) => {
    if (!dev) { unlockDialogOpen(); return false; }
    const done = await app.action(() => app.api.scm(op, { project, ...body }), ok);
    await refresh();
    return done;
  };

  if (err) return <div className="scm"><EmptyState title="Source control unavailable" hint={err} /></div>;
  if (!st) return <div className="scm"><EmptyState title="Reading git status…" /></div>;
  const head = st.branch.head;
  const row = (f: ScmFile, staged: boolean) => <li key={`${staged}:${f.path}`}
    className={`scm-row${sel?.path === f.path && sel.staged === staged ? " is-sel" : ""}`}>
    <button type="button" className="scm-file" onClick={() => setSel({ path: f.path, staged })} title={f.orig ? `${f.orig} → ${f.path}` : f.path}>
      <span className={`scm-code is-${f.code === "?" ? "new" : f.code === "D" ? "del" : f.code === "A" ? "new" : "mod"}`}>{f.code === "?" ? "U" : f.code}</span>
      <span className="trunc">{f.path}</span><span className="mono-xs faint">{f.status}</span>
      {f.protected && <span title="protected file: no diff, never staged by Stage all">🔒</span>}
    </button>
    <span className="scm-acts">
      {f.code !== "D" && <button type="button" className="btn is-quiet is-sm" onClick={() => onOpenFile(f.path)}>Open</button>}
      {staged ? <button type="button" className="btn is-quiet is-sm" onClick={() => void run("unstage", { paths: [f.path] }, `Unstaged ${f.path}`)}>Unstage</button>
        : <button type="button" className="btn is-quiet is-sm" disabled={f.protected} onClick={() => void run("stage", { paths: [f.path] }, `Staged ${f.path}`)}>Stage</button>}
      {!staged && <button type="button" className="btn is-quiet is-sm" onClick={() => {
        if (window.confirm(f.code === "?" ? `Delete the untracked file ${f.path}? This cannot be undone.` : `Discard your changes to ${f.path}? This cannot be undone.`))
          void run("discard", { path: f.path, confirm: true }, `Discarded ${f.path}`);
      }}>Discard</button>}
    </span>
  </li>;
  const changes = [...st.conflicts, ...st.unstaged];
  return <div className="scm">
    <div className="scm-list">
      <div className="scm-branch">
        <span className="caps muted">Branch</span><b className="mono">{head ?? "(detached)"}</b>
        {st.branch.upstream && <span className="mono-xs faint">↑{st.branch.ahead} ↓{st.branch.behind} {st.branch.upstream}</span>}
        <button type="button" className="btn is-quiet is-sm" onClick={() => head && void navigator.clipboard?.writeText(head).then(() => app.toast("Branch copied"))}>Copy</button>
        {githubUrl && <a className="btn is-quiet is-sm" href={githubUrl} target="_blank" rel="noopener noreferrer">GitHub ↗</a>}
        {prUrl && <a className="btn is-quiet is-sm" href={prUrl} target="_blank" rel="noopener noreferrer">PR ↗</a>}
        <span className="sl-fill" />
        <button type="button" className="btn is-quiet is-sm" onClick={() => void refresh()}>Refresh</button>
      </div>
      {ticket && (ticket.branch
        ? <div className="scm-ticket mono-xs"><span className="key">{ticket.key}</span> branch <b>{ticket.branch}</b>
          {head && head !== ticket.branch && <span className="warn-t"> · you are on {head}, not the ticket's branch</span>}</div>
        : suggest && <div className="scm-ticket">
          <span className="key">{ticket.key}</span><span className="mono-xs">has no branch. Create</span><span className="mono-xs">{suggest}</span>
          {!st.clean && <span className="warn-t mono-xs" title="git switch -c keeps your changes; nothing is overwritten">working tree has changes (they come along)</span>}
          <button type="button" className="btn is-sm is-jay" onClick={() => {
            if (window.confirm(`Create branch ${suggest} from ${head ?? "HEAD"} and switch to it?${st.clean ? "" : "\n\nYour uncommitted changes come along; nothing is lost."}`))
              void run("branch", { name: suggest, ticket: ticket.key }, `On ${suggest}`);
          }}>Create branch</button></div>)}
      <div className="scm-sec"><span className="caps muted">Staged</span><span className="mono-xs">{st.staged.length}</span></div>
      <ul>{st.staged.map((f) => row(f, true))}</ul>
      <div className="scm-sec"><span className="caps muted">Changes</span><span className="mono-xs">{changes.length + st.untracked.length}</span>
        <span className="sl-fill" />
        <button type="button" className="btn is-quiet is-sm" disabled={!changes.length && !st.untracked.length}
          onClick={() => void run("stage-all", {}, "Staged all (protected files skipped)")}>Stage all</button></div>
      <ul>{changes.map((f) => row(f, false))}{st.untracked.map((f) => row(f, false))}</ul>
      {st.clean && <div className="muted mono-xs" style={{ padding: "6px 10px" }}>Working tree clean.</div>}
      <form className="scm-commit" onSubmit={(e) => { e.preventDefault(); if (!dev) { unlockDialogOpen(); return; } if (msg.trim() && st.staged.length) setConfirmCommit(true); }}>
        <textarea className="input" rows={3} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder={ticket ? `${ticket.key}: …` : "Commit message"}
          aria-label="Commit message" />
        <button type="submit" className="btn is-sm" disabled={!msg.trim() || !st.staged.length}>Commit {st.staged.length} staged…</button>
        <span className="mono-xs faint">A normal git commit. Nothing is pushed.</span>
      </form>
    </div>
    <div className="scm-diff"><div className="scm-diff-head mono-xs">{sel ? `${sel.path}${sel.staged ? " (staged)" : ""}` : ""}</div><DiffView d={diff} /></div>
    {confirmCommit && <Dialog title="Commit these files?" onClose={() => setConfirmCommit(false)}>
      <p className="text2">On <b className="mono">{head}</b>. Message:</p>
      <pre className="mono-xs" style={{ whiteSpace: "pre-wrap" }}>{msg}</pre>
      <ul className="mono-xs">{st.staged.map((f) => <li key={f.path}>{f.code} {f.path}</li>)}</ul>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn is-jay" data-autofocus onClick={async () => {
          setConfirmCommit(false);
          if (await run("commit", { message: msg, files: st.staged.map((f) => f.path) }, "Committed")) setMsg("");
        }}>Commit</button>
        <button type="button" className="btn is-quiet" onClick={() => setConfirmCommit(false)}>Cancel</button>
      </div>
    </Dialog>}
  </div>;
}
