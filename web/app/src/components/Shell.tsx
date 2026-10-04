import { useEffect, useMemo, useState, type ReactNode } from "react";
import { app } from "../store/app";
import { useSelector, shallowEqual } from "../lib/store";
import { prefs, usePrefs } from "../lib/prefs";
import { href, go, useRoute, SCREENS } from "../lib/router";
import { freshness, type FreshRow } from "../lib/freshness";
import { dur, hms, nowS } from "../lib/time";
import { jayQueue } from "../tickets/model";
import { Kbd } from "./ui";
import { QuickConsole } from "./QuickConsole";
import { CommandPalette } from "./CommandPalette";
import { NewTicket } from "./NewTicket";
import { UnlockDialog } from "./DevMode";
import { hasUnsavedWork, staleBuild } from "../lib/stale";

// One list, in Jay's order (go-live revision). Pull requests live inside
// Development; the old Console route opens Workspace, which absorbed it. Old
// links keep working.
export const NAV: { id: (typeof SCREENS)[number]; label: string; title: string }[] = [
  { id: "overview", label: "Overview", title: "Overview" },
  { id: "projects", label: "Projects", title: "Projects" },
  { id: "tasks", label: "Tasks", title: "Tasks" },
  { id: "development", label: "Development", title: "Development" },
  { id: "workspace", label: "Workspace", title: "Workspace" },
  { id: "agents", label: "Agents", title: "Agents" },
  { id: "server", label: "Server", title: "Server" },
  { id: "activity", label: "Activity", title: "Activity" },
  { id: "alerts", label: "Alerts", title: "Alerts" },
  { id: "settings", label: "Settings", title: "Settings" },
];

/** Keys typed into a field belong to the field. */
export function typing(e: KeyboardEvent | React.KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable;
}

export function useTick(ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => { const t = setInterval(() => set((n) => n + 1), ms); return () => clearInterval(t); }, [ms]);
}

function Rail() {
  const route = useRoute();
  const counts = useSelector(app.store, (d) => {
    const st = d.state;
    return {
      jay: jayQueue(st).length,
      agents: st?.agents.length ?? 0,
      blocked: st?.blocked.length ?? 0,
      prs: st?.projects.reduce((n, p) => n + p.prs.length, 0) ?? 0,
      alerts: st?.alerts.filter((a) => !a.ack).length ?? 0,
      tasks: d.tickets.filter((t) => !t.archived && !["DONE", "DENIED", "CANCELLED"].includes(t.status)).length,
    };
  }, shallowEqual);
  const projects = useSelector(app.store, (d) => d.state?.projects ?? null);
  const needsBy = useSelector(app.store, (d) => {
    const m: Record<string, number> = {};
    jayQueue(d.state).forEach((j) => { m[j.project] = (m[j.project] ?? 0) + 1; });
    return JSON.stringify(m);
  });
  const nb = JSON.parse(needsBy) as Record<string, number>;
  const n: Partial<Record<string, ReactNode>> = {
    overview: counts.jay ? <span className="nav-n is-jay" title="waiting on Jay">{counts.jay}</span> : null,
    agents: <span className={`nav-n${counts.blocked ? " is-warn" : ""}`}>{counts.blocked ? `${counts.blocked}!` : counts.agents}</span>,
    tasks: <span className="nav-n">{counts.tasks || ""}</span>,
    development: <span className="nav-n">{counts.prs || ""}</span>,
    alerts: counts.alerts ? <span className="nav-n is-warn">{counts.alerts}</span> : null,
  };
  return <aside className="rail" aria-label="Navigation">
    <div className="brand"><span className="brand-mark" aria-hidden><i /><i /><i /><i /></span>
      <span style={{ display: "grid", lineHeight: 1.2 }}><span className="brand-name">Command Center</span>
        <span className="brand-host">jay-server</span></span></div>
    <nav className="nav" aria-label="Screens">
      {NAV.map((s, i) => <a key={s.id} href={href(s.id)} aria-current={route.screen === s.id ? "page" : undefined}
        aria-keyshortcuts={i < 9 ? String(i + 1) : "0"}>
        <span className="nav-key" aria-hidden>{i < 9 ? i + 1 : 0}</span><span>{s.label}</span>{n[s.id] ?? <span />}</a>)}
    </nav>
    <div className="rail-sec rail-projects">
      <div className="rail-head caps muted">Projects</div>
      {projects?.map((p) => {
        const live = p.panes.length;
        const blocked = p.panes.filter((a) => a.status === "blocked").length;
        const working = p.panes.filter((a) => a.status === "working").length;
        return <a key={p.key} className="rp" href={href("projects", p.key)}
          aria-current={route.screen === "projects" && route.id === p.key ? "page" : undefined}>
          <span className="pj" style={{ ["--pj" as string]: `var(--pj-${p.key})` }}><i className="pj-mark" aria-hidden /></span>
          <span className="trunc">{p.name}</span>
          <span className="row" style={{ gap: 6 }}>
            <span className={`rp-state${blocked ? " is-attn" : ""}`}>{blocked ? `${blocked} blocked` : working ? `${working} working`
              : live ? `${live} idle` : "quiet"}</span>
            {nb[p.key] ? <span className="badge-jay" title={`${nb[p.key]} waiting on Jay`}>{nb[p.key]}</span> : null}
          </span>
        </a>;
      })}
    </div>
    <div className="rail-foot"><button type="button" className="btn is-quiet is-sm" onClick={() => window.dispatchEvent(new Event("cc:palette"))}>
      <Kbd>Ctrl</Kbd><Kbd>K</Kbd><span>Commands</span></button></div>
  </aside>;
}

function TopBar() {
  const route = useRoute();
  const c = useSelector(app.store, (d) => ({
    jay: jayQueue(d.state).length,
    blocked: d.state?.blocked.length ?? 0,
    working: d.state?.agents.filter((a) => a.status === "working").length ?? 0,
    prs: d.state?.projects.reduce((n, p) => n + p.prs.length, 0) ?? 0,
  }), shallowEqual);
  const theme = usePrefs((p) => p.theme);
  const title = NAV.find((s) => s.id === route.screen)?.title ?? "Overview";
  const projName = useSelector(app.store, (d) => d.state?.projects.find((p) => p.key === route.id)?.name ?? null);
  return <header className="top">
    <div className="top-title"><span className="crumb">Command Center{route.id ? ` / ${title}` : ""}</span>
      <h1 className="page-title">{route.screen === "projects" && projName ? projName : route.id && route.screen === "tasks" ? route.id : title}</h1></div>
    <div className="top-right">
      <a className="chip is-jay" href={href("overview")}><b>{c.jay}</b> needs Jay</a>
      {c.blocked > 0 && <a className="chip is-blocked" href={href("agents")}><b>{c.blocked}</b> blocked</a>}
      <a className="chip" href={href("agents")}><b>{c.working}</b> working</a>
      <a className="chip" href={href("development")}><b>{c.prs}</b> open PRs</a>
      <span className="vsep" aria-hidden />
      <button type="button" className="btn is-quiet is-sm" onClick={() => window.dispatchEvent(new Event("cc:new-task"))}
        aria-keyshortcuts="n"><Kbd>N</Kbd> New task</button>
      <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ theme: theme === "dark" ? "light" : "dark" })}
        aria-label="Toggle light and dark">{theme === "dark" ? "Light" : "Dark"}</button>
    </div>
  </header>;
}

/** OFFLINE / reconnecting: the screen keeps its data and says how old it is. */
/** "Command Center was updated": shown when this window's build is gone from the server. */
export function UpdatedBanner() {
  const s = useSelector(staleBuild, (d) => d);
  if (!s.updated) return null;
  return <div className="banner is-warn" role="alert">
    <span className="caps">Updated</span>
    <span>Command Center was updated while this window was open. {hasUnsavedWork()
      ? "Save your open files, then reload." : "Reload to load the new version."}</span>
    <button type="button" className="btn is-sm is-jay" onClick={() => location.reload()}>Reload</button>
  </div>;
}

export function OfflineBanner() {
  useTick(1000);
  const { status, stateAt, attempt, error } = useSelector(app.store, (d) => ({ status: d.conn.status, stateAt: d.stateAt,
    attempt: d.conn.attempt, error: d.error }), shallowEqual);
  const auth = useSelector(app.store, (d) => d.auth);
  if (auth !== "ok" || status === "live") return null;
  const last = stateAt ? hms(stateAt / 1000) : "never";
  return <div className={`banner ${status === "offline" ? "is-offline" : "is-warn"}`} role="status" aria-live="polite">
    <span className="caps">{status === "offline" ? "Offline" : "Reconnecting"}</span>
    <span>Showing last known data · last update <span className="mono">{last}</span>
      {stateAt ? <span className="muted"> ({dur(nowS() - stateAt / 1000)} ago)</span> : null}</span>
    {attempt > 1 && <span className="muted mono-xs">attempt {attempt}</span>}
    {error && <span className="muted trunc">{error}</span>}
    <button type="button" className="btn is-sm" style={{ marginLeft: "auto" }} onClick={() => void app.resync()}>Retry now</button>
  </div>;
}

export function FreshnessBar() {
  useTick(1000);
  const st = useSelector(app.store, (d) => d.state);
  const conn = useSelector(app.store, (d) => d.conn, shallowEqual);
  const consoleOpen = usePrefs((p) => p.consoleOpen);
  const rows = useMemo(() => freshness(st, conn, nowS()), [st, conn, Math.floor(Date.now() / 1000)]);
  return <footer className="statusline" aria-label="Source freshness">
    {rows.map((r: FreshRow) => <span key={r.id} className={`sl-seg is-${r.state}`} title={r.detail}>
      <b>{r.label}</b><span className="sl-state">{r.state}</span>
      {r.ageS != null && <span>{dur(r.ageS)}</span>}</span>)}
    <span className="sl-fill" />
    <span className="sl-seg">seq <span className="mono-xs">{st?.seq ?? "—"}</span></span>
    <span className="sl-seg">ccd {st?.version ?? "—"}</span>
    <button type="button" className="sl-btn" aria-pressed={consoleOpen} aria-keyshortcuts="`"
      onClick={() => prefs.patch({ consoleOpen: !consoleOpen })}>console `</button>
    <button type="button" className="sl-btn" onClick={() => window.dispatchEvent(new Event("cc:palette"))}>Ctrl+K</button>
  </footer>;
}

function Toast() {
  const t = useSelector(app.store, (d) => d.toast);
  if (!t) return null;
  return <div className={`toast is-${t.tone}`} role={t.tone === "bad" ? "alert" : "status"}>{t.text}</div>;
}

export function AppShell({ children, flush = false }: { children: ReactNode; flush?: boolean }) {
  const [palette, setPalette] = useState(false);
  const [newTask, setNewTask] = useState(false);
  const [newProject, setNewProject] = useState<string | undefined>(undefined);
  const [unlock, setUnlock] = useState(false);
  const consoleOpen = usePrefs((p) => p.consoleOpen);
  useEffect(() => {
    const openPal = () => setPalette(true);
    const openNew = (e: Event) => { setNewProject((e as CustomEvent<{ project?: string } | null>).detail?.project); setNewTask(true); };
    window.addEventListener("cc:palette", openPal);
    window.addEventListener("cc:new-task", openNew);
    const openUnlock = () => setUnlock(true);
    window.addEventListener("cc:dev-unlock", openUnlock);
    const onKey = (e: KeyboardEvent) => {
      // Inside a real terminal, Ctrl+K is the shell's (kill to end of line); the palette opens from anywhere else.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && !(e.target as HTMLElement | null)?.closest?.(".xterm")) {
        e.preventDefault(); setPalette((v) => !v); return;
      }
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector("[role=dialog]")) return;
      if (e.key === "n" || e.key === "N") { e.preventDefault(); setNewProject(undefined); setNewTask(true); }
      else if (e.key === "`") { e.preventDefault(); prefs.patch({ consoleOpen: !prefs.get().consoleOpen }); }
      else if (e.key === "/") { e.preventDefault(); window.dispatchEvent(new Event("cc:focus-search")); }
      else if (/^[0-9]$/.test(e.key)) {
        const i = e.key === "0" ? 9 : Number(e.key) - 1;
        if (NAV[i]) { e.preventDefault(); go(NAV[i].id); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("cc:palette", openPal);
      window.removeEventListener("cc:new-task", openNew); window.removeEventListener("cc:dev-unlock", openUnlock); };
  }, []);
  return <div className="shell">
    <a className="sr" href="#main">Skip to content</a>
    <Rail />
    <div className="main">
      <TopBar />
      <UpdatedBanner />
      <OfflineBanner />
      <main id="main" className={`screen${flush ? " is-flush" : ""}`} tabIndex={-1}>{children}</main>
    </div>
    <QuickConsole hidden={!consoleOpen} />
    <FreshnessBar />
    <Toast />
    {palette && <CommandPalette onClose={() => setPalette(false)} onNewTask={() => { setPalette(false); setNewProject(undefined); setNewTask(true); }} />}
    {newTask && <NewTicket onClose={() => setNewTask(false)} defaults={newProject ? { project: newProject } : undefined} />}
    {unlock && <UnlockDialog onClose={() => setUnlock(false)} />}
  </div>;
}
