// Engineering HQ's frame (roadmap P1.1): sidebar, top bar and tab strip around today's screens. It is its own chunk,
// loaded only when this browser has the HQ preview on (components/Shell.tsx), so Classic never downloads or runs it.
// Everything inside the frame is Classic's: the screens, the banners, the palette, the dialogs, the keys. The frame
// adds no data source and no action of its own; each control here calls the same code as its Classic counterpart.
import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import "./frame.css";
import { app } from "../../store/app";
import { useSelector, shallowEqual } from "../../lib/store";
import { prefs, usePrefs } from "../../lib/prefs";
import { href, useRoute } from "../../lib/router";
import { jayQueue } from "../../tickets/model";
import { Kbd } from "../../components/ui";
import { DevDot } from "../../components/DevMode";
import { NotificationBell } from "../../components/Notifications";
import { HqPreviewTag } from "../../components/HqPreview";
import { HqBoundary } from "../../components/Shell";
import { HQ_PAGES } from "../pages";
import { HQ_NAV, HQ_NAV_LOW, hqTitle, sectionOf, viewKey, type HqNavItem } from "./nav";
import { tabs, visit, close } from "./tabs";
import { Icon, Logo } from "./icons";
import { hqMedia } from "../layout";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/** The prototype's sidebar shows icons only in windows up to 1440px wide (hq/layout.ts). */
function useNarrow(): boolean {
  return useSyncExternalStore((cb) => {
    const m = hqMedia();
    m?.addEventListener("change", cb);
    return () => m?.removeEventListener("change", cb);
  }, () => hqMedia()?.matches ?? false, () => false);
}

/** The theme on screen: System resolves to what the OS asks for, so the toggle always offers the other one. */
const looksDark = (theme: string) => theme === "dark"
  || (theme === "system" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches);
/** Icons only: a narrow window, or the sidebar's own toggle (Ctrl+\, the same preference as Classic's rail). */
function useIconsOnly(): { icons: boolean; narrow: boolean; collapsed: boolean } {
  const collapsed = usePrefs((p) => p.railCollapsed);
  const narrow = useNarrow();
  return { icons: collapsed || narrow, narrow, collapsed };
}

function NavLink({ n, current, badge }: { n: HqNavItem; current: boolean; badge?: ReactNode }) {
  return <a className={cx("hq-nav-item", current && "is-current")} href={href(n.id)} aria-current={current ? "page" : undefined}
    aria-keyshortcuts={n.key} title={`${n.label} (${n.key})`}>
    <Icon name={n.icon} size={20} /><span className="hq-nav-label">{n.label}</span>{badge}</a>;
}

export function HqSide() {
  const route = useRoute();
  const { icons: mini, narrow } = useIconsOnly();
  // The same counts as Classic's rail.
  const counts = useSelector(app.store, (d) => ({
    jay: jayQueue(d.state).length,
    tasks: d.tickets.filter((t) => !t.archived && !["DONE", "DENIED", "CANCELLED"].includes(t.status)).length,
    alerts: d.state?.alerts.filter((a) => !a.ack).length ?? 0,
  }), shallowEqual);
  const cur = sectionOf(route.screen);
  const badge: Partial<Record<string, ReactNode>> = {
    needs: counts.jay ? <span className="hq-badge is-jay" title="needs you">{counts.jay}</span> : null,
    tasks: counts.tasks ? <span className="hq-badge is-quiet" title="open tasks">{counts.tasks}</span> : null,
    activity: counts.alerts ? <span className="hq-badge is-warn" title="unacknowledged alerts">{counts.alerts}</span> : null,
  };
  return <aside className="hq-side" aria-label="Navigation">
    <a className="hq-brand" href={href("dashboard")} aria-label="Command Center, My Office">
      <Logo size={mini ? 28 : 32} /><span className="hq-brand-t"><b>Command<em>Center</em></b><small>Engineering HQ</small></span></a>
    <nav className="hq-nav" aria-label="Screens">
      {HQ_NAV.map((n) => <NavLink key={n.id} n={n} current={cur === n.id} badge={badge[n.id]} />)}</nav>
    <div className="hq-side-fill" />
    <nav className="hq-nav hq-nav-low" aria-label="More">
      {HQ_NAV_LOW.map((n) => <NavLink key={n.id} n={n} current={cur === n.id} />)}</nav>
    <HqPreviewTag mini={mini} />
    {/* In a narrow window the sidebar is icons only either way, so there is nothing to toggle. */}
    {!narrow && <div className="hq-side-foot">
      <button type="button" className="hq-icon-btn" onClick={() => prefs.patch({ railCollapsed: !mini })}
        aria-label={mini ? "Expand navigation" : "Collapse navigation"} title={`${mini ? "Expand" : "Collapse"} navigation (Ctrl+\\)`}>
        <Icon name={mini ? "chevron" : "chevl"} size={16} /></button>
    </div>}
  </aside>;
}

export function HqTop({ dash }: { dash: boolean }) {
  const route = useRoute();
  const theme = usePrefs((p) => p.theme);
  const projName = useSelector(app.store, (d) => d.state?.projects.find((p) => p.key === route.id)?.name ?? null);
  return <header className="hq-top">
    <h1 className="page-title">{hqTitle(route.screen, route.id, projName)}</h1>
    <button type="button" className="hq-search" onClick={() => window.dispatchEvent(new Event("cc:palette"))}
      aria-keyshortcuts="Control+K">
      <Icon name="search" size={17} /><span>Search screens, tasks, projects and commands</span><Kbd>Ctrl</Kbd><Kbd>K</Kbd></button>
    <div className="hq-top-right">
      <button type="button" className="btn is-quiet is-sm" onClick={() => window.dispatchEvent(new Event("cc:new-task"))}
        aria-keyshortcuts="n"><Kbd>N</Kbd> New task</button>
      <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ theme: looksDark(theme) ? "light" : "dark" })}
        aria-label="Toggle light and dark">{looksDark(theme) ? "Light" : "Dark"}</button>
      {/* The Dashboard has its own Developer Mode dot and bell in its header: not twice on one screen. */}
      {!dash && <><DevDot /><NotificationBell /></>}
    </div>
  </header>;
}

export function HqTabs() {
  const route = useRoute();
  const list = useSelector(tabs, (t) => t);
  const names = useSelector(app.store, (d) => Object.fromEntries((d.state?.projects ?? []).map((p) => [p.key, p.name])) as Record<string, string>,
    (a, b) => JSON.stringify(a) === JSON.stringify(b));
  const key = viewKey(route);
  const hash = location.hash || "#/dashboard";
  useEffect(() => { tabs.set((l) => visit(l, key, hash)); }, [key, hash]);
  const title = (k: string) => {
    const [screen, ...rest] = k.split("/");
    const id = rest.length ? rest.join("/") : null;
    return hqTitle(screen, id, screen === "projects" && id ? names[id] ?? null : null);
  };
  const shut = (k: string) => {
    const r = close(tabs.get(), k, key);
    tabs.set(r.list);
    if (r.go) location.hash = r.go;
  };
  return <nav className="hq-tabs" aria-label="Open views">
    <ul>{list.map((t) => {
      const on = t.key === key, name = title(t.key);
      return <li key={t.key} className={cx("hq-tab", on && "is-active")}>
        <a href={t.hash} aria-current={on ? "page" : undefined}>{name}</a>
        {(list.length > 1 || !on) && <button type="button" className="hq-tab-x" aria-label={`Close ${name} tab`}
          onClick={() => shut(t.key)}><Icon name="x" size={12} /></button>}
      </li>;
    })}</ul>
  </nav>;
}

/** The whole HQ window around one screen. `banners`, `screen` and `overlays` are Classic's, passed in unchanged. Where
 *  HQ has its own page for the address (hq/pages), that page replaces the Classic screen; if the page throws, the
 *  Classic screen is shown instead and a toast says so. `focus` is Workspace Focus: the sidebar, top bar and tabs go,
 *  and the screen stays where it is in the tree, so it is not remounted (a remount would close every terminal). */
export default function HqFrame({ dash, focus, banners, screen, overlays }: {
  dash: boolean; focus: boolean; banners: ReactNode; screen: ReactNode; overlays: ReactNode;
}) {
  const route = useRoute();
  const { icons } = useIconsOnly();
  const Page = HQ_PAGES[route.screen];
  return <div className={cx("shell hq-shell", icons && "is-icons", focus && "is-focus")}>
    <a className="sr" href="#main">Skip to content</a>
    {!focus && <HqSide />}
    <div className="hq-main">
      {!focus && <HqTop dash={dash && !Page} />}
      {!focus && <HqTabs />}
      {banners}
      {Page
        ? <HqBoundary key={route.screen} fallback={screen}
            message="This HQ page could not be shown, so the Classic screen is shown instead. Reload to try again.">
          <main id="main" className="screen hq-screen" tabIndex={-1}><Page /></main></HqBoundary>
        : screen}
    </div>
    {overlays}
  </div>;
}
