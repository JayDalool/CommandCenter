// The development trail of one ticket: branch → commits → PR → CI → review →
// merge → verify → deploy. Shared by the Development screen and the ticket's
// own DEVELOPMENT section, so both show the same evidence and say the same
// "—" where ccd genuinely does not know.
import { useState } from "react";
import type { DevCommits, DevRow } from "../api/types";
import { app } from "../store/app";
import { stamp } from "../lib/time";
import { DetailRow, StatusDot } from "./ui";

/** The commits on the ticket's branch, fetched only when Jay expands them. */
function Commits({ ticket }: { ticket: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<DevCommits | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !data) {
      try { setData(await app.api.devCommits(ticket)); setErr(null); } catch (e) { setErr((e as Error).message); }
    }
  };
  return <span className="stack" style={{ gap: 4 }}>
    <button type="button" className="btn is-quiet is-sm" aria-expanded={open} onClick={() => void toggle()}>
      {open ? "Hide commits" : "Show commits"}</button>
    {open && (err ? <span className="bad-t mono-xs">{err}</span> : !data ? <span className="muted mono-xs">reading git…</span>
      : data.commits.length === 0 ? <span className="muted mono-xs">{data.error ?? "no commits ahead of " + data.base}</span>
        : <table className="tbl dev-commits"><tbody>{data.commits.map((c) => <tr key={c.sha}>
          <td>{c.url ? <a className="mono link" href={c.url} target="_blank" rel="noopener noreferrer">{c.short}</a>
            : <span className="mono">{c.short}</span>}</td>
          <td className="is-title"><span className="t trunc" title={c.message}>{c.message}</span></td>
          <td className="mono-xs muted">{c.author}</td>
          <td className="mono-xs faint">{c.at ? stamp(c.at) : ""}</td></tr>)}</tbody></table>)}
  </span>;
}

const CI_TONE: Record<string, string> = { PASS: "ok-t", FAIL: "bad-t", PENDING: "warn-t", NONE: "faint" };
const REVIEW_WORD: Record<string, string> = { APPROVED: "APPROVED", CHANGES_REQUESTED: "CHANGES REQUESTED",
  REVIEW_REQUIRED: "PENDING", PENDING: "PENDING" };

export function Dash({ why }: { why?: string }) {
  return <span className="faint" title={why}>—</span>;
}

/** A stage word with a dot, in the terminal register: PASS, WAITING FOR JAY, PENDING. */
export function Stage({ word, tone, title }: { word: string | null; tone: string; title?: string }) {
  if (!word) return <Dash why={title} />;
  return <span className={`stage tone-${tone}`} title={title}>
    <StatusDot tone={tone as never} shape={tone === "blocked" ? "square" : tone === "idle" ? "ring" : "fill"} />
    <span className="stage-word">{word}</span></span>;
}

export function ciStage(ci: DevRow["ci"]) {
  if (!ci || ci === "NONE") return <Dash why="no checks reported" />;
  return <span className={CI_TONE[ci]}>{ci}</span>;
}

export function mergeStage(row: DevRow) {
  if (row.merge === "MERGED") return <Stage word="MERGED" tone="done" />;
  if (row.merge === "WAITING FOR JAY") return <Stage word="WAITING FOR JAY" tone="jay" title="Jay merges in GitHub; Command Center has no merge button" />;
  if (row.merge === "BLOCKED") return <Stage word="BLOCKED" tone="blocked" />;
  return <Dash why="not ready to merge yet" />;
}

/** The full trail as a definition list — the ticket detail's DEVELOPMENT section. */
export function DevTrail({ row, repo }: { row: DevRow | null; repo?: string | null }) {
  if (!row) {
    return <div className="dev-empty">
      <div className="empty-title">No development work found yet</div>
      <div className="mono-xs muted">A branch whose name leads with the key, or a PR linked to this ticket,
        appears here. Nothing is inferred from a key mentioned in passing.</div>
    </div>;
  }
  const b = row.branch;
  const pr = row.pr;
  return <dl className="dev-trail">
    <DetailRow label="Branch">{b
      ? <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="mono">{b.name}</span>
        {!b.exists && <span className="label" title="not a local branch on jay-server">remote only</span>}
        <span className="mono-xs faint">{b.evidence}</span></span>
      : <Dash why="no branch names this ticket" />}</DetailRow>
    <DetailRow label="Commits">{b && b.commits != null && b.countOk
      ? <span className="row" style={{ gap: 8 }}><span className="mono">{b.commits}</span>
        <span className="mono-xs faint">ahead of the default branch{b.head ? ` · ${b.head}` : ""}</span>
        <Commits ticket={row.key} /></span>
      : <Dash why={b ? "ccd could not count commits against the default branch" : "no branch"} />}</DetailRow>
    <DetailRow label="PR">{pr && pr.number != null
      ? <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {pr.url ? <a className="mono link" href={pr.url} target="_blank" rel="noopener noreferrer">#{pr.number}</a>
          : <span className="mono">#{pr.number}</span>}
        <span className={`label${pr.state === "MERGED" ? " is-done" : ""}`}>{pr.state}</span>
        {repo && <span className="mono-xs faint">{repo}</span>}
        {row.prs.length > 1 && <span className="mono-xs faint">+{row.prs.length - 1} more linked</span>}</span>
      : <Dash why="no PR linked to this ticket" />}</DetailRow>
    <DetailRow label="CI">{ciStage(row.ci)}</DetailRow>
    <DetailRow label="Review">{row.review
      ? <span className={row.review === "APPROVED" ? "ok-t" : row.review === "CHANGES_REQUESTED" ? "warn-t" : "muted"}>
        {REVIEW_WORD[row.review] ?? row.review}</span>
      : <Dash why="no PR to review" />}</DetailRow>
    <DetailRow label="Merge">{mergeStage(row)}</DetailRow>
    <DetailRow label="Verify">{row.verify
      ? <Stage word={row.verify} tone={row.verify === "DONE" ? "done" : "review"} />
      : <Dash why="verification starts when the PR is merged" />}</DetailRow>
    <DetailRow label="Deploy"><Dash why="ccd observes no deployments" /></DetailRow>
  </dl>;
}
