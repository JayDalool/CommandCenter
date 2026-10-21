// SETTINGS → POLICIES — the Project Operating Profiles (policy/*.toml) and Jay's decisions, read-only.
// "Today" is what Command Center enforces now (it mirrors the registry); "Agreed target" is Jay's decided policy,
// which nothing enforces yet: the Autonomy Engine only compares against it (shadow mode, decision D-008).
// Policy is changed in the repository by Jay, never from this page.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { projectName } from "../lib/control";
import type { PolicyState, PolicyValue } from "../api/types";
import { Panel, DetailRow, EmptyState } from "./ui";

const MODE_LABEL: Record<string, string> = {
  experimental_autonomy: "Experimental full autonomy", autonomous_product: "Autonomous product",
  controlled_production: "Controlled production", restricted: "Restricted (laptop only)", paused: "Paused",
};

function show(v: PolicyValue): string {
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v && typeof v === "object") return Object.entries(v).map(([k, x]) => `${k}: ${show(x)}`).join(" · ");
  return v === "" ? "—" : String(v);
}

export function Policies() {
  const st = useSelector(app.store, (d) => d.state);
  const [data, setData] = useState<PolicyState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { app.api.profiles().then(setData).catch((e) => setErr((e as Error).message)); }, []);
  if (err) return <EmptyState title="Policies unavailable">{err}</EmptyState>;
  if (!data) return <p className="muted">Loading…</p>;
  return <div className="stack">
    <Panel title="Project policies" pad meta={<span className="mono-xs muted" title={data.fingerprint}>policy {data.fingerprint.slice(0, 12)}</span>}>
      <p className="text2">How much each project's agents may do on their own. <b>Today</b> is what Command Center enforces now.
        <b> Agreed target</b> is the policy you decided; it is <b>not enforced yet</b>: the autonomy engine only compares
        against it and records disagreements. Policy changes are made in the repository's <code>policy/</code> folder and need you.</p>
      {data.problems.length > 0
        ? <ul className="pol-problems" aria-label="Policy problems">{data.problems.map((p) => <li key={p} className="tc-bad mono-xs">{p}</li>)}</ul>
        : <p className="tc-ok mono-xs">All policy files are valid and match what Command Center does today.</p>}
    </Panel>
    {Object.entries(data.projects).map(([key, p]) => <Panel key={key} title={p.name || projectName(st, key)}
      meta={<span className="mono-xs muted" title={p.sha256 ?? ""}>{p.file}</span>}>
      <dl className="pol-dl">
        <DetailRow label="mode">{p.mode ? (MODE_LABEL[p.mode] ?? p.mode) : "—"}{!p.valid && <span className="tc-bad"> · invalid</span>}</DetailRow>
        <DetailRow label="decisions">{p.decisions.length ? p.decisions.map((d) =>
          <span key={d} className="mono-xs pol-dec" title={data.decisions[d]?.question}>{d}</span>) : "—"}</DetailRow>
        <DetailRow label="today">{Object.entries(p.enforced).map(([k, v]) => <span key={k} className="pol-kv"><b>{k}</b> {show(v)}</span>)}</DetailRow>
        {Object.keys(p.target).length
          ? Object.entries(p.target).map(([k, v]) => <DetailRow key={k} label={`target · ${k.replace(/_/g, " ")}`}>{show(v)}</DetailRow>)
          : <DetailRow label="target">none yet</DetailRow>}
        <DetailRow label="capabilities">{Object.entries(p.capabilities).map(([k, v]) =>
          <span key={k} className="pol-kv"><b>{k.replace(/_/g, " ")}</b> {v ? "ready" : "not built"}</span>)}</DetailRow>
        {p.errors.map((e) => <DetailRow key={e} label="error"><span className="tc-bad">{e}</span></DetailRow>)}
      </dl>
    </Panel>)}
    <Panel title="Your decisions" count={Object.keys(data.decisions).length}>
      <dl className="pol-dl">
        {Object.values(data.decisions).map((d) => <DetailRow key={d.id} label={`${d.id} · ${d.date}`}>
          <b>{d.question}</b><br />{d.decision}
          {d.reconsider && <><br /><span className="muted">Reconsider: {d.reconsider}</span></>}
        </DetailRow>)}
      </dl>
    </Panel>
  </div>;
}
