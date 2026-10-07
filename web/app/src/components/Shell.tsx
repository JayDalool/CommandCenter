import { useEffect, useMemo, useState, type ReactNode } from "react";
import { app } from "../store/app";
import { useSelector, shallowEqual } from "../lib/store";
import { prefs, usePrefs } from "../lib/prefs";
import { href, go, useRoute, SCREENS } from "../lib/router";
import { freshness, type FreshRow } from "../lib/freshness";
import { dur, hms, nowS } from "../lib/time";
import { jayQueue } from "../tickets/model";
import { Kbd } from "./ui";
import { CommandPalette } from "./CommandPalette";
import { NewTicket } from "./NewTicket";
import { DevDot, UnlockDialog } from "./DevMode";
import { NotificationBell } from "./Notifications";
import { hasUnsavedWork, staleBuild } from "../lib/stale";

// The six primary destinations of the control room (spec §3), in Jay's order. Everything that used to
// be primary (Projects, Development, Agents, Server, Alerts, Pull requests) keeps its route and is one
// click away under Settings → Diagnostics or Activity / Logs; old links keep working.
const ICONS: Record<string, React.ReactNode> = {
  dashboard: <><rect x="3.5" y="3.5" width="7" height="7" rx="1" /><rect x="13.5" y="3.5" width="7" height="7" rx="1" /><rect x="3.5" y="13.5" width="7" height="7" rx="1" /><rect x="13.5" y="13.5" width="7" height="7" rx="1" /></>,
  workspace: <><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M12 4.5v15M3.5 12h17" /></>,
  tasks: <><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M7 9h2M11 9h6M7 13h2M11 13h6M7 17h2M11 17h4" /></>,
  activity: <><path d="M6 3.5h9l3.5 3.5v13.5h-12.5z" /><path d="M9 11h6M9 14.5h6M9 18h4" /></>,
  files: <><path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2H19a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
};
export const NAV: { id: (typeof SCREENS)[number]; label: string; title: string }[] = [
  { id: "dashboard", label: "Dashboard", title: "Dashboard" },
  { id: "workspace", label: "Workspace", title: "Workspace" },
  { id: "tasks", label: "Task Manager", title: "Task Manager" },
  { id: "activity", label: "Activity / Logs", title: "Activity / Logs" },
  { id: "files", label: "Files", title: "Files" },
  { id: "settings", label: "Settings", title: "Settings" },
];
/** Screens reached from Settings / Activity (diagnostics) and the routes old links use. */
const TITLES: Record<string, string> = { overview: "Dashboard", projects: "Projects", development: "Development",
  agents: "Agents", server: "Server", alerts: "Alerts", prs: "Pull requests", workspaces: "herdr layout", console: "Files" };

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
  const counts = useSelector(app.store, (d) => ({
    jay: jayQueue(d.state).length,
    tasks: d.tickets.filter((t) => !t.archived && !["DONE", "DENIED", "CANCELLED"].includes(t.status)).length,
    alerts: d.state?.alerts.filter((a) => !a.ack).length ?? 0,
  }), shallowEqual);
  const current = route.screen === "overview" ? "dashboard" : route.screen === "console" ? "files" : route.screen;
  const n: Partial<Record<string, ReactNode>> = {
    dashboard: counts.jay ? <span className="nav-n is-jay" title="needs Jay">{counts.jay}</span> : null,
    tasks: <span className="nav-n">{counts.tasks || ""}</span>,
    activity: counts.alerts ? <span className="nav-n is-warn" title="unacknowledged alerts">{counts.alerts}</span> : null,
  };
  return <aside className="rail" aria-label="Navigation">
    <div className="brand"><span className="brand-mark" aria-hidden><i /><i /><i /><i /></span>
      <span className="brand-name">Command Center</span></div>
    <nav className="nav" aria-label="Screens">
      {NAV.map((s, i) => <a key={s.id} href={href(s.id)} aria-current={current === s.id ? "page" : undefined}
        aria-keyshortcuts={String(i + 1)} title={`${s.label} (${i + 1})`}>
        <svg className="nav-ico" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.6"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden>{ICONS[s.id]}</svg>
        <span>{s.label}</span>{n[s.id] ?? <span />}</a>)}
    </nav>
    <div className="sl-fill" />
    <div className="rail-foot"><button type="button" className="btn is-quiet is-sm" onClick={() => window.dispatchEvent(new Event("cc:palette"))}>
      <Kbd>Ctrl</Kbd><Kbd>K</Kbd><span>Commands</span></button></div>
  </aside>;
}

function TopBar() {
  const route = useRoute();
  const theme = usePrefs((p) => p.theme);
  const title = NAV.find((s) => s.id === route.screen)?.title ?? TITLES[route.screen] ?? "Dashboard";
  const projName = useSelector(app.store, (d) => d.state?.projects.find((p) => p.key === route.id)?.name ?? null);
  return <header className="top">
    <div className="top-title">
      <h1 className="page-title">{route.screen === "projects" && projName ? projName : route.id && route.screen === "tasks" ? route.id : title}</h1></div>
    <div className="top-right">
      <button type="button" className="btn is-quiet is-sm" onClick={() => window.dispatchEvent(new Event("cc:new-task"))}
        aria-keyshortcuts="n"><Kbd>N</Kbd> New task</button>
      <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ theme: theme === "dark" ? "light" : "dark" })}
        aria-label="Toggle light and dark">{theme === "dark" ? "Light" : "Dark"}</button>
      <DevDot />
      <NotificationBell />
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

export function FreshnessBar({ always = false }: { always?: boolean }) {
  useTick(1000);
  const st = useSelector(app.store, (d) => d.state);
  const conn = useSelector(app.store, (d) => d.conn, shallowEqual);
  const rows = useMemo(() => freshness(st, conn, nowS()), [st, conn, Math.floor(Date.now() / 1000)]);
  // Diagnostics stay out of the way until they matter: the line shows only while a source is stale or down.
  if (!always && rows.every((r) => r.state === "live" || r.state === "off")) return null;
  return <footer className="statusline" aria-label="Source freshness">
    {rows.map((r: FreshRow) => <span key={r.id} className={`sl-seg is-${r.state}`} title={r.detail}>
      <b>{r.label}</b><span className="sl-state">{r.state}</span>
      {r.ageS != null && <span>{dur(r.ageS)}</span>}</span>)}
    <span className="sl-fill" />
    <span className="sl-seg">seq <span className="mono-xs">{st?.seq ?? "—"}</span></span>
    <span className="sl-seg">ccd {st?.version ?? "—"}</span>
    <button type="button" className="sl-btn" onClick={() => window.dispatchEvent(new Event("cc:palette"))}>Ctrl+K</button>
  </footer>;
}

function Toast() {
  const t = useSelector(app.store, (d) => d.toast);
  if (!t) return null;
  return <div className={`toast is-${t.tone}`} role={t.tone === "bad" ? "alert" : "status"}>{t.text}</div>;
}

export function AppShell({ children, flush = false, bare = false, chrome = "full" }: {
  children: ReactNode; flush?: boolean; bare?: boolean; chrome?: "full" | "dash";
}) {
  const [palette, setPalette] = useState(false);
  const [newTask, setNewTask] = useState(false);
  const [newProject, setNewProject] = useState<string | undefined>(undefined);
  const [unlock, setUnlock] = useState(false);
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
      else if (e.key === "/") { e.preventDefault(); window.dispatchEvent(new Event("cc:focus-search")); }
      else if (/^[1-9]$/.test(e.key)) {
        const i = Number(e.key) - 1;
        if (NAV[i]) { e.preventDefault(); go(NAV[i].id); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("cc:palette", openPal);
      window.removeEventListener("cc:new-task", openNew); window.removeEventListener("cc:dev-unlock", openUnlock); };
  }, []);
  return <div className={`shell${bare ? " is-bare" : ""}${chrome === "dash" ? " is-dash" : ""}`}>
    <a className="sr" href="#main">Skip to content</a>
    {!bare && <Rail />}
    <div className="main">
      {!bare && chrome !== "dash" && <TopBar />}
      <UpdatedBanner />
      <OfflineBanner />
      <main id="main" className={`screen${flush ? " is-flush" : ""}`} tabIndex={-1}>{children}</main>
    </div>
    {!bare && <FreshnessBar />}
    <Toast />
    {palette && <CommandPalette onClose={() => setPalette(false)} onNewTask={() => { setPalette(false); setNewProject(undefined); setNewTask(true); }} />}
    {newTask && <NewTicket onClose={() => setNewTask(false)} defaults={newProject ? { project: newProject } : undefined} />}
    {unlock && <UnlockDialog onClose={() => setUnlock(false)} />}
  </div>;
}
