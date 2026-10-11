import { useCallback, useEffect, useState } from "react";
import { app } from "../store/app";
import { Store, useSelector } from "../lib/store";
import type { ScmDiff, ScmFile, ScmStatus } from "../api/types";
import { EmptyState } from "../components/ui";
import { ConfirmDialog, Dialog } from "../components/Dialog";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";

/** Bumped after every status refresh, so an open diff tab re-reads its diff after a stage/unstage/commit. */
export const bumpScm = () => scmRev.patch({ rev: scmRev.get().rev + 1 });
const scmRev = new Store<{ rev: number }>({ rev: 0 });

/** The diff of one file, read-only, for a tab in the main area. */
export function DiffView({ project, path, staged }: { project: string; path: string; staged: boolean }) {
  const rev = useSelector(scmRev, (d) => d.rev);
  const [d, setD] = useState<ScmDiff | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;  // a slow answer for a file Jay already left is dropped
    app.api.scmDiff(project, path, staged).then((r) => { if (live) { setD(r); setErr(null); } })
      .catch((e) => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [project, path, staged, rev]);
  const body = err ? <EmptyState title="Diff unavailable" hint={err} /> : !d ? <EmptyState title="Reading diff…" />
    : d.binary ? <EmptyState title="Binary file changed" /> : !d.diff ? <EmptyState title="No textual difference" />
    : <pre className="diff" aria-label={`Diff of ${d.path}`}>{d.diff.split("\n").map((l, i) =>
      <div key={i} className={l.startsWith("@@") ? "d-hunk" : l.startsWith("+") && !l.startsWith("+++") ? "d-add"
        : l.startsWith("-") && !l.startsWith("---") ? "d-del" : l.startsWith("diff ") || l.startsWith("index ") || l.startsWith("+++") || l.startsWith("---") ? "d-meta" : ""}>{l || " "}</div>)}
      {d.truncated && <div className="d-meta">… diff truncated</div>}</pre>;
  return <div className="scm-diff"><div className="scm-diff-head mono-xs">{path}{staged ? " (staged)" : ""} · read-only diff</div>{body}</div>;
}

/** Source control for the sidebar: branch, ticket branch, file lists, commit. A file click opens its diff in the main area. */
export function ScmSidebar({ project, ticket, githubUrl, prUrl, onOpenFile, onOpenDiff, selected }: {
  project: string; ticket: { key: string; title: string; branch: string | null } | null;
  githubUrl: string | null; prUrl: string | null; onOpenFile: (path: string) => void;
  onOpenDiff: (path: string, staged: boolean) => void; selected: { path: string; staged: boolean } | null;
}) {
  const dev = useDevActive();
  const [st, setSt] = useState<ScmStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [confirmCommit, setConfirmCommit] = useState(false);
  const [ask, setAsk] = useState<{ title: string; body: string; label: string; danger?: boolean; run: () => void } | null>(null);
  const [suggest, setSuggest] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setSt(await app.api.scmStatus(project)); setErr(null); bumpScm(); } catch (e) { setErr((e as Error).message); }
  }, [project]);
  useEffect(() => { setSt(null); void refresh(); }, [refresh]);
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
    className={`scm-row${selected?.path === f.path && selected.staged === staged ? " is-sel" : ""}`}>
    <button type="button" className="scm-file" onClick={() => onOpenDiff(f.path, staged)} title={f.orig ? `${f.orig} → ${f.path}` : f.path}>
      <span className={`scm-code is-${f.code === "?" ? "new" : f.code === "D" ? "del" : f.code === "A" ? "new" : "mod"}`}>{f.code === "?" ? "U" : f.code}</span>
      <span className="trunc">{f.path}</span><span className="mono-xs faint">{f.status}</span>
      {f.protected && <span title="protected file: no diff, never staged by Stage all">🔒</span>}
    </button>
    <span className="scm-acts">
      {f.code !== "D" && <button type="button" className="btn is-quiet is-sm" onClick={() => onOpenFile(f.path)}>Open</button>}
      {staged ? <button type="button" className="btn is-quiet is-sm" onClick={() => void run("unstage", { paths: [f.path] }, `Unstaged ${f.path}`)}>Unstage</button>
        : <button type="button" className="btn is-quiet is-sm" disabled={f.protected} onClick={() => void run("stage", { paths: [f.path] }, `Staged ${f.path}`)}>Stage</button>}
      {!staged && <button type="button" className="btn is-quiet is-sm" onClick={() => setAsk({
        title: f.code === "?" ? "Delete untracked file?" : "Discard changes?", label: f.code === "?" ? "Delete" : "Discard", danger: true,
        body: f.code === "?" ? `Delete the untracked file ${f.path}? This cannot be undone.` : `Discard your changes to ${f.path}? This cannot be undone.`,
        run: () => void run("discard", { path: f.path, confirm: true }, `Discarded ${f.path}`) })}>Discard</button>}
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
          <button type="button" className="btn is-sm is-jay" onClick={() => setAsk({
            title: "Create branch?", label: "Create branch",
            body: `Create branch ${suggest} from ${head ?? "HEAD"} and switch to it?${st.clean ? "" : " Your uncommitted changes come along; nothing is lost."}`,
            run: () => void run("branch", { name: suggest, ticket: ticket.key }, `On ${suggest}`) })}>Create branch</button></div>)}
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
    {ask && <ConfirmDialog title={ask.title} confirmLabel={ask.label} danger={ask.danger} onConfirm={ask.run} onClose={() => setAsk(null)}>{ask.body}</ConfirmDialog>}
  </div>;
}
