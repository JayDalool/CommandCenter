import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import { prefs, usePrefs, commands } from "../lib/prefs";
import { isRemembered } from "../api/auth";
import type { ImportPreview, LauncherInfo } from "../api/types";
import { DevBadge } from "../components/DevMode";
import { Decisions } from "../components/Decisions";
import { Policies } from "../components/Policies";
import { Panel, Seg, Command, DetailRow, EmptyState, Project } from "../components/ui";
import { stamp } from "../lib/time";

export function Settings() {
  const route = useRoute();
  const tab = route.params.get("tab") ?? "general";
  return <div className="stack">
    <Seg label="Settings section" value={tab} onChange={(v) => go("settings", null, { tab: v === "general" ? undefined : v })}
      options={[{ v: "general", label: "General" }, { v: "desktop", label: "Desktop app" }, { v: "developer", label: "Developer mode" },
        { v: "connection", label: "Connection" }, { v: "policies", label: "Policies" }, { v: "decisions", label: "Decisions" }, { v: "import", label: "Task migration preview" }, { v: "diagnostics", label: "Diagnostics" }]} />
    {tab === "general" && <General />}
    {tab === "desktop" && <DesktopApp />}
    {tab === "developer" && <DeveloperMode />}
    {tab === "connection" && <Connection />}
    {tab === "policies" && <Policies />}
    {tab === "decisions" && <Decisions />}
    {tab === "import" && <ImportPreviewView />}
    {tab === "diagnostics" && <Diagnostics />}
  </div>;
}

/** Server and agent diagnostics: out of the primary navigation (spec §3), never gone. */
function Diagnostics() {
  return <Panel title="Diagnostics" pad>
    <p className="text2">Ops views for when something needs looking into. Every old link still works.</p>
    <div className="row" style={{ flexWrap: "wrap", gap: 8, marginTop: 10 }}>
      {([["projects", "Projects"], ["development", "Development"], ["agents", "Agents"], ["server", "Server"], ["alerts", "Alerts"],
        ["prs", "Pull requests"], ["workspaces", "herdr layout"]] as [string, string][]).map(([id, label]) =>
        <a key={id} className="btn is-sm" href={href(id)}>{label}</a>)}
    </div>
  </Panel>;
}

function DesktopApp() {
  const [info, setInfo] = useState<LauncherInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { app.api.launcher().then(setInfo).catch((e) => setErr((e as Error).message)); }, []);
  return <div className="grid-2">
    <Panel title="Desktop app — Windows launcher" pad>
      {err ? <div className="bad-t">{err}</div> : !info ? <div className="muted">Loading…</div> : !info.available
        ? <div className="muted">The launcher has not been built on this server yet (scripts/build-launcher.sh).</div>
        : <div className="stack" style={{ gap: 10 }}>
          <button type="button" className="btn is-jay" onClick={() => void app.api.download("/api/desktop/launcher/download", "CommandCenter.exe")
            .then(() => app.toast("Downloading CommandCenter.exe")).catch((e) => app.toast((e as Error).message, "bad"))}>Download Windows launcher</button>
          <dl style={{ display: "grid", gap: 6 }}>
            <DetailRow label="Version"><span className="mono">{info.version}</span></DetailRow>
            <DetailRow label="Build commit"><span className="mono">{info.commit}</span></DetailRow>
            <DetailRow label="Built"><span className="mono-xs">{info.built_at}</span></DetailRow>
            <DetailRow label="Size"><span className="mono-xs">{info.size?.toLocaleString()} bytes</span></DetailRow>
            <DetailRow label="SHA-256"><span className="mono-xs" style={{ wordBreak: "break-all" }}>{info.sha256}</span></DetailRow>
          </dl>
          <div className="mono-xs muted">Check it in PowerShell: Get-FileHash .\CommandCenter.exe</div>
        </div>}
    </Panel>
    <Panel title="Once, then every day" pad>
      <ol className="text2" style={{ display: "grid", gap: 6, paddingLeft: 18 }}>
        <li>Download it once and put it on your Desktop.</li>
        <li>Double-click it. It starts a hidden SSH tunnel to <span className="mono">jay-server</span> (your existing alias and
          key), waits for ccd, then opens Command Center in its own Edge app window.</li>
        <li>First time only: paste the ccd token and tick “Remember on this browser” — the window keeps its own browser profile.</li>
        <li>Closing the window stops only the tunnel it started. Developer Mode always starts locked.</li>
        <li>Version 0.3.0 adds native terminals: Workspace's “Open Claude / repo / server terminal” buttons open Windows Terminal
          tabs over your SSH. The first click asks to open CommandCenter.exe — allow it.</li>
      </ol>
      <div className="mono-xs faint" style={{ marginTop: 8 }}>The launcher contains no token, key or password. Built and unit-tested on Linux;
        Windows CI builds it too.</div>
    </Panel>
  </div>;
}

function DeveloperMode() {
  return <Panel title="Developer mode" pad>
    <div className="stack" style={{ gap: 10 }}>
      <DevBadge />
      <p className="text2">The ccd token lets this browser read and steer metadata. Terminals, Claude, answers to Claude's
        questions, saving or uploading repository files and attachments also need Developer Unlock, a separate token kept in
        <span className="mono"> ~/.config/command-center/developer.token</span> on jay-server. Unlock once per app session:
        reloads and Command Center's own pop-out windows keep it. It ends when you lock it, close the browser, two idle hours
        pass, eight hours pass, or ccd restarts. The token itself is never stored; only the session id, in this browser session.</p>
    </div>
  </Panel>;
}

function General() {
  const p = usePrefs((x) => x);
  return <Panel title="Display" pad>
    <dl style={{ display: "grid", gap: 8 }}>
      <DetailRow label="Theme"><Seg label="Theme" value={p.theme} onChange={(v) => prefs.patch({ theme: v })}
        options={[{ v: "dark", label: "Dark" }, { v: "light", label: "Light" }, { v: "system", label: "System" }]} /></DetailRow>
      <DetailRow label="Rows"><Seg label="Row density" value={p.density} onChange={(v) => prefs.patch({ density: v })}
        options={[{ v: "comfortable", label: "30 px" }, { v: "compact", label: "28 px compact" }]} /></DetailRow>
      <DetailRow label="SSH host"><input className="input mono" value={p.sshHost} onChange={(e) => prefs.patch({ sshHost: e.target.value.replace(/[^A-Za-z0-9@._-]/g, "") })}
        aria-label="SSH host alias used in copied commands" /> <span className="muted">used in copied commands</span></DetailRow>
    </dl>
  </Panel>;
}

function Connection() {
  const host = usePrefs((p) => p.sshHost);
  const st = useSelector(app.store, (d) => d.state);
  return <div className="grid-2">
    <Panel title="This browser" pad>
      <dl>
        <DetailRow label="ccd">{st ? <span className="mono">v{st.version} · {location.host}</span> : "—"}</DetailRow>
        <DetailRow label="token">{isRemembered() ? "remembered in this browser profile" : "this tab only (sessionStorage)"}</DetailRow>
      </dl>
      <button type="button" className="btn" style={{ marginTop: 10 }} onClick={() => app.logout()}>Forget token and disconnect</button>
    </Panel>
    <Panel title="From Windows" pad>
      <div style={{ display: "grid", gap: 8 }}>
        <div className="muted">Easiest: Settings → Desktop app. Or by hand:</div>
        <div className="muted">1. Tunnel (leave it running)</div><Command cmd={commands.tunnel(host)} />
        <div className="muted">2. Token to the clipboard, once</div><Command cmd={commands.token(host)} />
        <div className="muted">3. Open <span className="mono">http://127.0.0.1:7777</span> and paste it.</div>
      </div>
    </Panel>
  </div>;
}

function ImportPreviewView() {
  const [pv, setPv] = useState<ImportPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setPv(await app.api.importPreview()); setErr(null); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); } };
  return <div className="stack">
    <Panel title="Task migration preview" meta="read-only — nothing is written, no GitHub issue is touched" pad
      tools={<button type="button" className="btn is-primary is-sm" onClick={run} disabled={busy}>{busy ? "Reading…" : pv ? "Run again" : "Run preview"}</button>}>
      <p className="text2">Reads docs/tasks/INDEX.md, per-task files, cached GitHub issues, MY_ACTIONS.md and handoff notes, and shows what an import would do.
        Applying it is a separate step that Jay approves; it is not in this build.</p>
      {err && <p className="bad-t">{err}</p>}
    </Panel>
    {pv && <>
      <section className="panel"><div className="pv-sum">
        {([["would create", pv.summary.wouldCreate], ["would update", pv.summary.wouldUpdate], ["ambiguous", pv.summary.ambiguous],
          ["duplicates", pv.summary.duplicates], ["skipped", pv.summary.skipped]] as const).map(([k, n]) =>
          <div key={k}><span className="caps muted">{k}</span><span className="pipe-n">{n}</span></div>)}</div>
        <div className="panel-body is-pad mono-xs muted">generated {stamp(pv.generatedAt)} in {pv.tookMs} ms · {pv.notes.join(" ")}</div></section>
      <Panel title="Sources" count={pv.sources.length}><table className="tbl"><tbody>{pv.sources.map((s) =>
        <tr key={s.project + s.kind}><td><Project k={s.project} /></td><td className="mono-xs">{s.kind}</td><td className="mono-xs text2">{s.ref}</td>
          <td className="is-num mono">{s.count}</td><td className="bad-t mono-xs">{s.error ?? ""}</td></tr>)}</tbody></table></Panel>
      {pv.ambiguous.length > 0 && <Panel title="Ambiguous — Jay decides" count={pv.ambiguous.length} jay><table className="tbl"><tbody>{pv.ambiguous.map((a) =>
        <tr key={a.source + a.ref}><td><Project k={a.project} /></td><td className="mono-xs">{a.ref}</td><td className="is-title"><span className="t">{a.title}</span></td>
          <td className="warn-t">{a.reason}</td><td className="muted">{a.suggestion}</td></tr>)}</tbody></table></Panel>}
      {pv.duplicates.length > 0 && <Panel title="Duplicates" count={pv.duplicates.length}><table className="tbl"><tbody>{pv.duplicates.map((d) =>
        <tr key={d.key}><td className="key">{d.key}</td><td className="mono-xs text2">{d.sources.map((s) => `${s.kind} ${s.ref}`).join(" + ")}</td><td className="muted">{d.resolution}</td></tr>)}</tbody></table></Panel>}
      <Panel title="Would create" count={pv.wouldCreate.length}><div className="tbl-wrap" style={{ maxHeight: 520 }}><table className="tbl">
        <thead><tr><th>Key</th><th>Title</th><th>Status</th><th>Priority</th><th>Flags</th><th>From</th></tr></thead>
        <tbody>{pv.wouldCreate.map((c) => <tr key={c.proposedKey}><td className="key">{c.proposedKey}{c.keepsId ? "" : " *"}</td>
          <td className="is-title"><span className="t">{c.title}</span></td><td className="mono-xs">{c.status}</td><td className="mono-xs">{c.priority}</td>
          <td className="mono-xs jay-t">{c.flags.join(" ")}</td><td className="mono-xs muted">{c.sources.map((s) => s.kind).join("+")}</td></tr>)}</tbody></table></div>
        <div className="panel-body is-pad mono-xs muted">* new key; the old ID is kept as a legacy link.</div></Panel>
      {pv.wouldUpdate.length > 0 && <Panel title="Would update" count={pv.wouldUpdate.length}><table className="tbl"><tbody>{pv.wouldUpdate.map((u) =>
        <tr key={u.key}><td className="key">{u.key}</td><td className="mono-xs">{u.changes.map((c) => `${c.field}: ${String(c.from)} → ${String(c.to)}`).join("; ")}</td></tr>)}</tbody></table></Panel>}
      <Panel title="Skipped" count={pv.skipped.length}><table className="tbl"><tbody>{pv.skipped.map((s, i) =>
        <tr key={i}><td className="mono-xs">{s.project}</td><td className="mono-xs">{s.source}</td><td className="mono-xs">{s.ref}</td><td className="muted">{s.reason}</td></tr>)}</tbody></table></Panel>
    </>}
    {!pv && !err && <EmptyState title="Not run yet." hint="Run preview reads files on jay-server; it changes nothing." />}
  </div>;
}
