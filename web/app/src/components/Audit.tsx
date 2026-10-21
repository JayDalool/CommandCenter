// SETTINGS → AUDIT (v2 Phase 1, PR 7): every write that reached ccd, who claimed it and how far that is verified —
// Developer Unlock (Jay), an actor token (an agent), or nothing — plus what ccd itself did (system:ccd). Recorded,
// not enforced: nothing is refused yet. The summary measures what enforcing verified identity would refuse.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import type { ActorsState, AuditState } from "../api/types";
import { Ago, EmptyState, Panel } from "./ui";
import { unlockDialogOpen, useDevActive } from "./DevMode";

const VIA: Record<string, string> = { developer: "Developer Unlock", token: "actor token", none: "not verified", system: "ccd itself" };

export function Audit() {
  const dev = useDevActive();
  const [data, setData] = useState<AuditState | null>(null);
  const [actors, setActors] = useState<ActorsState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"" | "0" | "1">("");
  const [issued, setIssued] = useState<{ actor: string; token: string; fingerprint: string } | null>(null);
  const load = () => Promise.all([app.api.audit(filter ? `?verified=${filter}` : ""), app.api.actors()])
    .then(([a, t]) => { setData(a); setActors(t); setErr(null); }).catch((e) => setErr((e as Error).message));
  useEffect(() => { void load(); const t = setInterval(() => void load(), 30_000); return () => clearInterval(t); }, [filter]);

  const issue = async () => {
    if (!dev) { unlockDialogOpen(); return; }
    const name = window.prompt("Issue an actor token for which agent? (agent:<name>, e.g. agent:coordinator)", "agent:");
    if (!name) return;
    try { const out = await app.api.actorIssue(name.trim(), 30, ""); setIssued(out); await load(); }
    catch (e) { app.toast((e as Error).message, "bad"); }
  };
  const revoke = async (id: number, actor: string) => {
    if (!dev) { unlockDialogOpen(); return; }
    if (!window.confirm(`Revoke the actor token for ${actor}? Writes that send it stop counting as verified.`)) return;
    try { await app.api.actorRevoke(id); app.toast("token revoked"); await load(); }
    catch (e) { app.toast((e as Error).message, "bad"); }
  };

  if (err && !data) return <EmptyState title="Audit trail unavailable">{err}</EmptyState>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.available) return <EmptyState title="No audit trail">The task system is off.</EmptyState>;
  const s = data.summary;
  return <div className="stack">
    <Panel title="Who did what" count={s.total ?? 0}>
      <p className="text2 led-note">Every write to Command Center in the last 30 days, with how far its author is proven. Nothing is
        refused yet; this shows what turning that on would mean.</p>
      <ul className="mono-xs au-sum">
        {Object.entries(s.byVia ?? {}).map(([k, n]) => <li key={k}>{VIA[k] ?? k}: <b>{n}</b></li>)}
        <li>would be refused if identity were required: <b>{s.wouldRefuse ?? 0}</b></li>
        <li>claimed to be you without Developer Unlock: <b>{s.unverifiedJay ?? 0}</b></li>
        <li>token named a different actor: <b className={s.mismatch ? "ny-overdue" : ""}>{s.mismatch ?? 0}</b></li>
        <li>hash chain: <b className={data.chain.ok ? "" : "ny-overdue"}>{data.chain.ok ? `intact (${data.chain.checked} rows)` : `broken at row ${data.chain.brokenAt}`}</b></li>
      </ul>
      <div className="au-pad"><div className="seg" role="group" aria-label="Show">
        <button type="button" aria-pressed={filter === ""} onClick={() => setFilter("")}>All</button>
        <button type="button" aria-pressed={filter === "0"} onClick={() => setFilter("0")}>Not verified</button>
        <button type="button" aria-pressed={filter === "1"} onClick={() => setFilter("1")}>Verified</button>
      </div></div>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>when</th><th>actor</th><th>proof</th><th>request</th><th>status</th><th>task</th><th>fields</th></tr></thead>
        <tbody>{data.events.map((e) => <tr key={e.id}>
          <td><Ago at={e.at} /></td>
          <td className="mono">{e.actor}</td>
          <td className={e.verified ? "" : "muted"} title={e.summary || undefined}>{VIA[e.via] ?? e.via}{e.tokenActor && e.tokenActor !== e.actor ? ` (token is ${e.tokenActor})` : ""}</td>
          <td className="mono-xs trunc" title={e.path}>{e.method} {e.path}</td>
          <td className="mono-xs">{e.status || ""}</td>
          <td className="mono-xs">{e.ref ?? e.project ?? ""}</td>
          <td className="mono-xs muted trunc">{e.bodyKeys.join(", ")}</td>
        </tr>)}</tbody></table></div>
      {!data.events.length && <p className="muted led-note">Nothing recorded yet.</p>}
    </Panel>
    <Panel title="Actor tokens" count={actors?.tokens.length ?? 0}>
      <p className="text2 led-note">A token you give one agent so its writes count as verified. The agent sends it as
        <span className="mono"> {actors?.header ?? "X-CCD-Actor-Token"}</span>. Shown once; Command Center keeps only a fingerprint.
        Issuing and revoking need Developer Mode.</p>
      {issued && <div className="au-issued">
        <p>Token for <b className="mono">{issued.actor}</b> (fingerprint <span className="mono">{issued.fingerprint}</span>). Copy it now; it is not shown again.</p>
        <code className="mono-xs au-token">{issued.token}</code>{" "}
        <button type="button" className="btn is-sm" onClick={() => setIssued(null)}>Done</button>
      </div>}
      <div className="au-pad"><button type="button" className="btn is-sm" onClick={() => void issue()}>Issue a token</button></div>
      {!!actors?.tokens.length && <div className="tbl-wrap"><table className="tbl"><thead><tr><th>agent</th><th>fingerprint</th><th>status</th><th>expires</th><th></th></tr></thead>
        <tbody>{actors.tokens.map((t) => <tr key={t.id}>
          <td className="mono">{t.actor}</td><td className="mono">{t.fingerprint}</td><td>{t.status}</td>
          <td className="mono-xs">{new Date(t.expiresAt * 1000).toLocaleDateString()}</td>
          <td>{t.status === "active" && <button type="button" className="btn is-sm" onClick={() => void revoke(t.id, t.actor)}>Revoke</button>}</td>
        </tr>)}</tbody></table></div>}
    </Panel>
  </div>;
}
