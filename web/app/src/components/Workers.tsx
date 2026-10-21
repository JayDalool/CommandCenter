// SETTINGS → WORKERS — the machines that can run agent work (v2 Phase 1). The server registers itself; another node
// (the laptop) enrols, waits for Jay, and heartbeats with its own token. Nothing is scheduled on a node yet (Phase 2).
// Approving or revoking needs Developer Mode; revoking is final.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import type { WorkerNode, WorkersState } from "../api/types";
import { Panel, EmptyState } from "./ui";
import { unlockDialogOpen, useDevActive } from "./DevMode";

const STATUS: Record<WorkerNode["status"], string> = { online: "online", offline: "offline", pending: "waiting for you", revoked: "revoked" };

function ago(at: number | null): string {
  if (!at) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - at));
  return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
}

export function Workers() {
  const dev = useDevActive();
  const [data, setData] = useState<WorkersState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = () => app.api.workers().then(setData).catch((e) => setErr((e as Error).message));
  useEffect(() => { void load(); }, []);
  const act = async (op: "approve" | "revoke", id: string) => {
    if (!dev) { unlockDialogOpen(); return; }
    if (op === "revoke" && !window.confirm(`Revoke ${id}? Its token stops working for good; it would have to enrol again under a new name.`)) return;
    setBusy(id);
    try { await app.api.workerAct(op, id); app.toast(`${id} ${op === "approve" ? "approved" : "revoked"}`); await load(); }
    catch (e) { app.toast((e as Error).message, "bad"); }
    finally { setBusy(null); }
  };
  if (err) return <EmptyState title="Workers unavailable">{err}</EmptyState>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.available) return <EmptyState title="No workers">The task system is off.</EmptyState>;
  return <div className="stack">
    <Panel title="Worker nodes" count={data.nodes.length}>
      <p className="text2 led-note">Machines that can run agent work. The server registers itself; a new machine asks to join and
        waits for you. Nothing is scheduled on them yet: today's agents still run in the server's panes.</p>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>node</th><th>kind</th><th>status</th><th>last seen</th>
        <th>tools</th><th>repos</th><th>version</th><th></th></tr></thead><tbody>
        {data.nodes.map((n) => <tr key={n.id}>
          <td className="key">{n.id}</td><td>{n.kind}</td>
          <td className={n.status === "online" ? "ok-t" : n.status === "pending" ? "warn-t" : "muted"}>{STATUS[n.status]}</td>
          <td className="mono-xs">{ago(n.lastHeartbeat)}</td>
          <td className="mono-xs">{(n.capabilities.tools ?? []).join(", ") || "—"}</td>
          <td className="mono-xs">{(n.capabilities.repos ?? []).join(", ") || "—"}</td>
          <td className="mono-xs">{n.version ?? "—"}</td>
          <td>{n.state === "pending" && <button type="button" className="btn is-primary is-sm" disabled={busy !== null}
                onClick={() => void act("approve", n.id)}>Approve</button>}
              {n.state !== "revoked" && n.kind !== "server" && <button type="button" className="btn is-sm is-quiet" disabled={busy !== null}
                onClick={() => void act("revoke", n.id)}>Revoke</button>}</td>
        </tr>)}</tbody></table></div>
      {!dev && <p className="mono-xs muted led-note">Approving or revoking a node needs Developer Mode.</p>}
    </Panel>
    {data.events.length > 0 && <Panel title="Recent" count={data.events.length}>
      <ul className="pol-shadow">{data.events.slice(0, 20).map((e, i) => <li key={i}>
        <span className="mono-xs muted">{new Date(e.at * 1000).toLocaleString()}</span> <b>{e.node}</b> {e.kind} by {e.actor}</li>)}</ul>
    </Panel>}
  </div>;
}
