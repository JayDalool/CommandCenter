import { useEffect, useMemo, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { href, useRoute } from "../lib/router";
import type { CcdEvent } from "../api/types";
import { ActivityRow, categorize, meaningful, type FeedCat } from "../components/Feed";
import { Panel, Seg, EmptyState } from "../components/ui";
import { mergeActivity } from "../store/app";

type F = "ALL" | "AGENTS" | "TASKS" | "PRS" | "CI" | "JAY" | "HOST";
const MAP: Record<F, FeedCat[] | null> = { ALL: null, AGENTS: ["AGENT"], TASKS: ["TASK"], PRS: ["PR"], CI: ["CI"], JAY: ["JAY"], HOST: ["HOST", "ALERT"] };

export function Activity() {
  const route = useRoute();
  const live = useSelector(app.store, (d) => d.activity);
  const [older, setOlder] = useState<CcdEvent[]>([]);
  const [f, setF] = useState<F>("ALL");
  const [busy, setBusy] = useState(false);
  const [withClosed, setWithClosed] = useState(false);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const project = route.params.get("project");
  // Closed tickets leave the active view at once (spec §25); their history stays in Task History.
  const closed = useMemo(() => new Set(tickets.filter((t) => ["DONE", "DENIED", "CANCELLED"].includes(t.status) || t.archived).map((t) => t.key)), [tickets]);
  const all = useMemo(() => mergeActivity(live, older, Infinity), [live, older]);
  const rows = all.filter((e) => meaningful(e) && (!project || e.project === project) && (!MAP[f] || MAP[f]!.includes(categorize(e.kind)))
    && (withClosed || !e.ref || !closed.has(e.ref)));
  const more = async () => {
    setBusy(true);
    try { const r = await app.api.activity({ limit: 200, before: all[all.length - 1]?.seq }); setOlder((o) => [...o, ...r.events]); }
    finally { setBusy(false); }
  };
  useEffect(() => setOlder([]), [project]);
  return <div className="stack">
  <Panel title="Activity" count={rows.length} meta={project ? `project ${project}` : "meaningful events, newest first"}
    tools={<span className="row"><label className="row mono-xs muted"><input type="checkbox" checked={withClosed}
      onChange={(e) => setWithClosed(e.target.checked)} />closed tasks</label>
      <Seg<F> label="Filter" value={f} onChange={setF} options={(Object.keys(MAP) as F[]).map((k) => ({ v: k, label: k }))} /></span>}>
    <ul aria-label="Events">{rows.map((e) => <ActivityRow key={e.seq} e={e} />)}</ul>
    {!rows.length && <EmptyState title="Nothing here yet." />}
    <div className="panel-body is-pad"><button type="button" className="btn is-sm" onClick={more} disabled={busy}>{busy ? "Loading…" : "Load older"}</button></div>
  </Panel>
  <Panel title="Logs and diagnostics" pad>
    <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
      {([["alerts", "Alerts"], ["server", "Server"], ["agents", "Agents"], ["development", "Development"], ["prs", "Pull requests"],
        ["workspaces", "herdr layout"]] as [string, string][]).map(([id, label]) => <a key={id} className="btn is-sm" href={href(id)}>{label}</a>)}
    </div>
  </Panel>
  </div>;
}
