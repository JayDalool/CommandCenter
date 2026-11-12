import { Component, Suspense, lazy, useEffect, useMemo, useState, type ReactNode } from "react";
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
import { HqPreviewTag } from "./HqPreview";
import { hasUnsavedWork, staleBuild } from "../lib/stale";
import { TITLES } from "../lib/titles";
import { hqMedia } from "../hq/layout";

// The six primary destinations of the control room (spec §3), in Jay's order. Everything that used to
// be primary (Projects, Development, Agents, Server, Alerts, Pull requests) keeps its route and is one
// click away under Settings → Diagnostics or Activity / Logs; old links keep working.
const ICONS: Record<string, React.ReactNode> = {
  dashboard: <><rect x="3.5" y="3.5" width="7" height="7" rx="1" /><rect x="13.5" y="3.5" width="7" height="7" rx="1" /><rect x="3.5" y="13.5" width="7" height="7" rx="1" /><rect x="13.5" y="13.5" width="7" height="7" rx="1" /></>,
  needs: <><path d="M4 13.5l2.5-8h11l2.5 8v5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5z" /><path d="M4 13.5h4.5l1 2h5l1-2H20" /></>,
  workspace: <><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M12 4.5v15M3.5 12h17" /></>,
  tasks: <><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M7 9h2M11 9h6M7 13h2M11 13h6M7 17h2M11 17h4" /></>,
  activity: <><path d="M6 3.5h9l3.5 3.5v13.5h-12.5z" /><path d="M9 11h6M9 14.5h6M9 18h4" /></>,
  files: <><path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2H19a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
};
// `key` is the digit that opens the screen. Needs You (v2) took 0 so the digits Jay already uses did not move.
export const NAV: { id: (typeof SCREENS)[number]; label: string; title: string; key: string }[] = [
  { id: "dashboard", label: "Dashboard", title: "Dashboard", key: "1" },
  { id: "needs", label: "Needs You", title: "Needs You", key: "0" },
  { id: "workspace", label: "Workspace", title: "Workspace", key: "2" },
  { id: "tasks", label: "Task Manager", title: "Task Manager", key: "3" },
  { id: "activity", label: "Activity / Logs", title: "Activity / Logs", key: "4" },
  { id: "files", label: "Files", title: "Files", key: "5" },
  { id: "settings", label: "Settings", title: "Settings", key: "6" },
];

/** Keys typed into a field belong to the field. */
export function typing(e: KeyboardEvent | React.KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable) return true;
  // Monaco in Chrome types into a div with an EditContext, which is neither a field nor contentEditable.
  return (t as HTMLElement & { editContext?: unknown }).editContext != null || !!t.closest?.(".monaco-editor");
}

export function useTick(ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => { const t = setInterval(() => set((n) => n + 1), ms); return () => clearInterval(t); }, [ms]);
}

function Rail() {
  const route = useRoute();
  const collapsed = usePrefs((p) => p.railCollapsed);
  const counts = useSelector(app.store, (d) => ({
    jay: jayQueue(d.state).length,
    tasks: d.tickets.filter((t) => !t.archived && !["DONE", "DENIED", "CANCELLED"].includes(t.status)).length,
    alerts: d.state?.alerts.filter((a) => !a.ack).length ?? 0,
  }), shallowEqual);
  const current = route.screen === "overview" ? "dashboard" : route.screen === "console" ? "files" : route.screen;
  const n: Partial<Record<string, ReactNode>> = {
    needs: counts.jay ? <span className="nav-n is-jay" title="needs you">{counts.jay}</span> : null,
    tasks: <span className="nav-n">{counts.tasks || ""}</span>,
    activity: counts.alerts ? <span className="nav-n is-warn" title="unacknowledged alerts">{counts.alerts}</span> : null,
  };
  return <aside className="rail" aria-label="Navigation">
    <div className="brand"><span className="brand-mark" aria-hidden><i /><i /><i /><i /></span>
      <span className="brand-name">Command Center</span></div>
    <nav className="nav" aria-label="Screens">
      {NAV.map((s) => <a key={s.id} href={href(s.id)} aria-current={current === s.id ? "page" : undefined}
        aria-keyshortcuts={s.key} title={`${s.label} (${s.key})`}>
        <svg className="nav-ico" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.6"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden>{ICONS[s.id]}</svg>
        <span>{s.label}</span>{n[s.id] ?? <span />}</a>)}
    </nav>
    <div className="sl-fill" />
    <HqPreviewTag mini={collapsed} />
    <div className="rail-foot">
      {!collapsed && <button type="button" className="btn is-quiet is-sm" onClick={() => window.dispatchEvent(new Event("cc:palette"))}>
        <Kbd>Ctrl</Kbd><Kbd>K</Kbd><span>Commands</span></button>}
      <button type="button" className="btn is-quiet is-sm rail-toggle" onClick={() => prefs.patch({ railCollapsed: !collapsed })}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} title={`${collapsed ? "Expand" : "Collapse"} navigation (Ctrl+\\)`}>
        {collapsed ? "»" : "«"}</button>
    </div>
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
      // Ctrl+. focus (Workspace alone) · Ctrl+\ collapse the navigation rail. Neither is a shell key.
      if ((e.ctrlKey || e.metaKey) && e.key === ".") { e.preventDefault(); prefs.patch({ wsFocus: !prefs.get().wsFocus }); return; }
      if ((e.ctrlKey || e.metaKey) && e.key === "\\" && !(e.target as HTMLElement | null)?.closest?.(".xterm")) {
        e.preventDefault();
        // HQ's sidebar is icons only in a window up to 1440px wide either way: nothing to toggle there.
        if (prefs.get().ui === "hq" && hqMedia()?.matches) return;
        prefs.patch({ railCollapsed: !prefs.get().railCollapsed }); return;
      }
      // Inside a real terminal, Ctrl+K is the shell's (kill to end of line); the palette opens from anywhere else.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && !(e.target as HTMLElement | null)?.closest?.(".xterm")) {
        e.preventDefault(); setPalette((v) => !v); return;
      }
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector("[role=dialog]")) return;
      if (e.key === "n" || e.key === "N") { e.preventDefault(); setNewProject(undefined); setNewTask(true); }
      else if (e.key === "/") { e.preventDefault(); window.dispatchEvent(new Event("cc:focus-search")); }
      else if (/^[0-9]$/.test(e.key)) {
        const to = NAV.find((s) => s.key === e.key);
        if (to) { e.preventDefault(); go(to.id); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("cc:palette", openPal);
      window.removeEventListener("cc:new-task", openNew); window.removeEventListener("cc:dev-unlock", openUnlock); };
  }, []);
  const route = useRoute();
  const railCollapsed = usePrefs((p) => p.railCollapsed);
  const wsFocus = usePrefs((p) => p.wsFocus);
  // Focus (the Workspace only): no rail, no top bar — the tree and the terminals get the whole window.
  const focus = wsFocus && route.screen === "workspace";
  const noChrome = bare || focus;
  const ui = usePrefs((p) => p.ui);
  // Chosen once per mount: switching from the lazy wrapper to the loaded component later would be a new element type
  // and remount the screen (and its terminals). A resolved lazy renders without suspending.
  const [Frame] = useState(() => hqFrameLoaded ?? HqFrameLazy);
  const banners = <><UpdatedBanner /><OfflineBanner /></>;
  const screen = <main id="main" className={`screen${flush ? " is-flush" : ""}`} tabIndex={-1}>{children}</main>;
  const overlays = <>
    {!bare && <FreshnessBar />}
    <Toast />
    {palette && <CommandPalette onClose={() => setPalette(false)} onNewTask={() => { setPalette(false); setNewProject(undefined); setNewTask(true); }} />}
    {newTask && <NewTicket onClose={() => setNewTask(false)} defaults={newProject ? { project: newProject } : undefined} />}
    {unlock && <UnlockDialog onClose={() => setUnlock(false)} />}
  </>;
  const classic = <div className={`shell${noChrome ? " is-bare" : ""}${chrome === "dash" ? " is-dash" : ""}${railCollapsed ? " is-rail-mini" : ""}`}>
    <a className="sr" href="#main">Skip to content</a>
    {!noChrome && <Rail />}
    <div className="main">
      {!noChrome && chrome !== "dash" && <TopBar />}
      {banners}
      {screen}
    </div>
    {overlays}
  </div>;
  // The HQ preview puts its own frame around the same screen. Pop-outs have no frame in either mode. Workspace Focus
  // keeps the frame mounted with its chrome hidden, so the screen (and every live terminal in it) is not remounted.
  if (ui !== "hq" || bare) return classic;
  return <HqBoundary fallback={classic}>
    <Suspense fallback={null}><Frame dash={chrome === "dash"} focus={focus} banners={banners}
      screen={<ScreenMark>{screen}</ScreenMark>} overlays={overlays} /></Suspense>
  </HqBoundary>;
}

// The HQ frame is its own chunk (hq/frame), fetched only while the HQ preview is on, and fetched early so it is
// usually ready before ccd answers. If that early fetch fails, React's own load tries again (a failure is not kept);
// if that fails too, HqBoundary shows Classic until a reload.
type HqFrameModule = typeof import("../hq/frame/Frame");
let hqFrame: Promise<HqFrameModule> | null = null;
let hqFrameLoaded: HqFrameModule["default"] | null = null;
export function loadHqFrame() {
  hqFrame ??= import("../hq/frame/Frame").then((m) => { hqFrameLoaded = m.default; return m; })
    .catch((e: unknown) => { hqFrame = null; throw e; });
  return hqFrame;
}
const HqFrameLazy = lazy(loadHqFrame);
if (typeof window !== "undefined" && prefs.get().ui === "hq") void loadHqFrame().catch(() => { /* HqBoundary shows Classic */ });

/** Errors thrown by the Classic screen inside HQ's frame, so HQ's boundaries pass them on instead of blaming HQ. */
const screenErrors = new Set<unknown>();

/** Around the Classic screen in HQ's frame: marks its errors as the screen's own and lets them go on up, so a broken
 *  screen fails exactly as it does in Classic, not as an HQ failure. Adds no DOM. */
export class ScreenMark extends Component<{ children: ReactNode }, { error: { e: unknown } | null }> {
  state: { error: { e: unknown } | null } = { error: null };
  static getDerivedStateFromError(e: unknown) { screenErrors.add(e); return { error: { e } }; }
  render() { if (this.state.error) throw this.state.error.e; return this.props.children; }
}

/** If the HQ frame (or an HQ page) fails to load or throws, this shows the fallback and says so: Classic, or the Classic
 *  screen at that address. A reload tries HQ again. An error from the Classic screen itself (ScreenMark) is not HQ's:
 *  it is passed on unchanged. */
export class HqBoundary extends Component<{ children: ReactNode; fallback: ReactNode; message?: string; onFail?: () => void },
  { failed: boolean; rethrow: { e: unknown } | null }> {
  state: { failed: boolean; rethrow: { e: unknown } | null } = { failed: false, rethrow: null };
  static getDerivedStateFromError(e: unknown) { return screenErrors.has(e) ? { rethrow: { e } } : { failed: true }; }
  componentDidCatch(e: unknown) {
    if (screenErrors.has(e)) return;
    app.toast(this.props.message ?? "Engineering HQ could not be shown, so this window shows Classic. Reload to try HQ again.", "bad");
    this.props.onFail?.();
  }
  render() {
    if (this.state.rethrow) throw this.state.rethrow.e;
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
