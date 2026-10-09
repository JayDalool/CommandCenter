import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { Panel, EmptyState, Ago, StaleIndicator, StatusDot } from "../components/ui";
import { bytes, dur } from "../lib/time";
import { LIMITS } from "../lib/freshness";
import type { Host } from "../api/types";

function Meter({ label, value, unit = "%", pct, sub, warn, bad }: { label: string; value: string | number | null; unit?: string;
  pct?: number | null; sub?: string; warn?: number; bad?: number }) {
  const lvl = pct == null ? "" : bad != null && pct >= bad ? " is-bad" : warn != null && pct >= warn ? " is-warn" : "";
  return <div className={`meter${lvl}`} role="group" aria-label={`${label} ${value ?? "unknown"}${unit}`}>
    <div className="meter-top"><span className="caps muted">{label}</span><span className="meter-v">{value ?? "—"}<small>{value != null ? unit : ""}</small></span></div>
    {pct != null && <div className="meter-track" aria-hidden><div className="meter-fill" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>}
    {sub && <div className="meter-sub trunc">{sub}</div>}
  </div>;
}

export function hostMeters(h: Host) {
  const mem = h.memTotal ? Math.round((100 * (h.memUsed ?? 0)) / h.memTotal) : null;
  const loadPct = h.load && h.cpus ? Math.round((100 * h.load[0]) / h.cpus) : null;
  return [
    { label: "CPU", value: h.cpuPct != null ? Math.round(h.cpuPct) : null, pct: h.cpuPct ?? null, warn: 80, bad: 95, sub: `${h.cpus ?? "—"} cores` },
    { label: "RAM", value: mem, pct: mem, warn: 85, bad: 95, sub: `${bytes(h.memUsed)} / ${bytes(h.memTotal)}` },
    { label: "Swap", value: h.swapPct != null ? Math.round(h.swapPct) : null, pct: h.swapPct ?? null, warn: 60, bad: 85, sub: `${bytes(h.swapUsed)} / ${bytes(h.swapTotal)}` },
    { label: "Disk", value: h.disk ?? null, pct: h.disk ?? null, warn: 78, bad: 90, sub: "/" },
    { label: "Load", value: h.load ? h.load[0].toFixed(2) : null, unit: "", pct: loadPct, warn: 80, bad: 120, sub: h.load ? h.load.map((x) => x.toFixed(2)).join(" ") : "" },
    { label: "Uptime", value: h.uptimeS != null ? dur(h.uptimeS) : null, unit: "", pct: null, sub: `OOM 24h: ${h.oomKills24h ?? "—"}` },
  ];
}

export function ServerMeters({ compact = false }: { compact?: boolean }) {
  const h = useSelector(app.store, (d) => d.state?.host ?? null);
  if (!h) return <EmptyState title="No host data yet" />;
  const ms = hostMeters(h);
  return <div className={compact ? "meters" : "vitals"}>{ms.map((m) => <Meter key={m.label} {...m} />)}</div>;
}

export function Server() {
  const st = useSelector(app.store, (d) => d.state);
  if (!st) return <EmptyState title="Loading…" />;
  const h = st.host;
  const herdr = st.sources.herdr;
  const wt = Object.entries(st.worktrees ?? {}).map(([k, v]) => ({ k, n: Math.max(0, v.length - 1), paths: v.slice(1) }));
  const health = st.health;
  return <div className="stack">
    <section className="panel" aria-label="Vitals"><div className="panel-head"><h2 className="panel-title">jay-server</h2>
      <span className="panel-meta">as of <Ago at={h.asOf} /> <StaleIndicator at={h.asOf} limitS={LIMITS.host} /></span></div>
      <ServerMeters /></section>
    <div className="grid-3">
      <Panel title="herdr" pad>
        <div className="row"><StatusDot tone={herdr.ok ? "working" : "failed"} /><b>{herdr.ok ? "connected" : "unreachable"}</b>
          <span className="mono-xs muted">protocol {herdr.protocol ?? "—"}</span></div>
        <div className="mono-xs muted">last event <Ago at={herdr.lastEventAt} /> · snapshot <Ago at={herdr.lastSnapshotAt} /></div>
        {herdr.error && <div className="bad-t mono-xs">{herdr.error}</div>}
        {herdr.warning && <div className="warn-t mono-xs">{herdr.warning}</div>}
        {!herdr.ok && <div className="muted" style={{ marginTop: 6 }}>Agents keep running only if herdr runs. ccd never starts herdr; Jay does, from a terminal on jay-server.</div>}
      </Panel>
      <Panel title="ccd" pad>
        <div className="row"><StatusDot tone={health.ok ? "working" : "blocked"} /><b>{health.ok ? "healthy" : "degraded"}</b>
          <span className="mono-xs muted">v{health.version} · up {dur(health.uptimeS)}</span></div>
        <div className="mono-xs muted">seq {health.seq} · tasks {health.tasks?.enabled ? `schema v${health.tasks.schemaVersion}` : "off"}</div>
        <div className="mono-xs muted">GitHub {health.gh.ok ? "ok" : "failing"} · {Object.keys(health.gh.projects).length} repos</div>
      </Panel>
      <Panel title="Claude" pad>
        <div className="row"><b className="mono">{h.claudeCount ?? "—"}</b><span className="muted">claude processes</span></div>
        <div className="row"><b className="mono">{st.agents.length}</b><span className="muted">agents herdr sees</span></div>
        <div className="row"><b className="mono">{h.backup_age_h != null ? `${h.backup_age_h}h` : "—"}</b><span className="muted">since last backup marker</span></div>
      </Panel>
    </div>
    <div className="grid-2">
      <Panel title="Containers" count={`${h.containers_up ?? "—"}/${h.containers_total ?? "—"}`} meta={h.down?.length ? <span className="warn-t">down: {h.down.join(", ")}</span> : "all running"}>
        <div className="tbl-wrap" style={{ maxHeight: 360 }}><table className="tbl"><tbody>
          {(h.containers ?? []).map((c) => <tr key={c.name}><td className="mono-xs">{c.name}</td>
            <td><span className={c.state === "running" ? "ok-t mono-xs" : "warn-t mono-xs"}>{c.state}</span></td></tr>)}
          {!h.containers && <tr><td className="muted">Container list arrives with the next host poll.</td></tr>}
        </tbody></table></div>
      </Panel>
      <div className="stack">
        <Panel title="Top processes" meta="by resident memory · names only">
          <table className="tbl"><tbody>{(h.procs ?? []).map((p) => <tr key={p.pid}><td className="mono-xs">{p.name}</td>
            <td className="mono-xs faint">{p.pid}</td><td className="is-num mono-xs">{p.rssMB} MB</td></tr>)}
            {!h.procs && <tr><td className="muted">Arrives with the next host poll.</td></tr>}</tbody></table>
        </Panel>
        <Panel title="Worktrees" meta="lane worktrees per project · a finished ticket's clean, pushed worktree is removed automatically">
          <table className="tbl"><tbody>{wt.map((w) => <tr key={w.k} className={w.n > 6 ? "is-attn" : ""}><td>{w.k}</td>
            <td className={`is-num mono ${w.n > 6 ? "warn-t" : ""}`}>{w.n}</td><td className="muted">{w.n > 6 ? "over the limit of 6 — cleanup is Jay's call" : ""}</td></tr>)}</tbody></table>
        </Panel>
        <Panel title="OOM & stale" pad>
          <div>{h.oomKills24h ? <span className="bad-t">{h.oomKills24h} OOM kill(s) in 24 h</span> : <span className="ok-t">no OOM kills in 24 h</span>}</div>
          {st.stale.map((s) => <div key={s.project + s.text} className="mono-xs warn-t">{s.project}: {s.text}</div>)}
        </Panel>
      </div>
    </div>
  </div>;
}
