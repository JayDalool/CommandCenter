// SUPPORTING DESTINATIONS — everything that is not one of the seven flagship pages stays reachable.
// These already exist in the production app (web/app); the prototype only links to them by name.
import { Icon } from "../components/Icon";
import { feed, setOutage } from "../data/live";
import { useStore } from "../lib/store";
import { resetShared } from "../lib/shared";

const DEST = [
  ["needs", "Needs You", "Everything waiting for Jay: questions, approvals, blockers.", "info"], ["workspace", "Workspace / Task Rooms", "The terminal wall: rooms, panes, pop-outs (rooms.ts).", "terminal"],
  ["tasks", "Task Manager", "All tickets with filters and the ticket pipeline.", "list"], ["activity", "Activity / Audit", "Audit log, alerts, AI usage and cost.", "pulse"],
  ["files", "Files", "Project files, editor and source control.", "doc"], ["settings", "Settings · Project Operating Profiles", "Policies, autonomy shadow, night shift, workers, Developer Unlock.", "gear"],
  ["prs", "Releases & Pull requests", "Release readiness and merge gates.", "rocket"], ["server", "Fleet / WorkerNodes", "Server and laptop worker nodes.", "server"],
];

export function More() {
  const f = useStore(feed);
  return <div className="page page-more">
    <div className="page-head"><div><h1>Settings &amp; more</h1><p>Supporting destinations. They already exist in the current app and keep their routes and deep links.</p></div></div>
    <div className="more-grid">{DEST.map(([r, t, s, ic]) => <div key={r} className="panel pad more-card"><Icon name={ic} size={26} /><h2>{t}</h2><p>{s}</p><code>current app · #/{r}</code></div>)}</div>
    <section className="panel pad"><h2>Demo controls</h2>
      <p className="muted">For reviewing honest states. These only change this browser's demo data.</p>
      <div className="row-gap"><label className="switch"><input type="checkbox" checked={f.outage} onChange={() => setOutage(!f.outage)} /><span>Simulate a status-feed outage (agents show Unknown / Stale)</span></label>
        <button type="button" className="btn btn-sm" onClick={() => { resetShared(); location.reload(); }}>Reset demo data</button></div></section>
    <p className="muted small">The prototype is not connected to ccd, so these open nothing here. In the migration they keep their existing routes (web/app/src/lib/router.ts) and get the new look one by one.</p>
  </div>;
}
