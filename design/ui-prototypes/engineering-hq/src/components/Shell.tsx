import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Store, useStore } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import { Icon, Logo } from "./Icon";
import { cx } from "./ui";
import { focusWindow, notices, owners, popOut, returnHere } from "../windows/manager";
import { PopButton, useOwner } from "../windows/Detachable";
import { useNeedsSummary } from "../data/needs";
import { viewById, viewForRoute, type ViewDef } from "../windows/views";
import { WIN_ID } from "../lib/shared";
import { AGENTS, CONVERSATIONS, PROJECTS, TASKS } from "../data/seed";
import { useOrg } from "../data/org";
import { Popover, openMenu, setSlowDemo, slowDemo, useContextMenu, type MenuItem } from "./overlay";
import { motionPref, setMotionPref } from "../lib/motion";
import { setThemePref, themePref } from "../lib/theme";
import { Demo } from "./ui";
import { gov } from "../data/governance";

export const NAV = [
  { page: "office", label: "My Office", icon: "home", badge: 0 },
  { page: "messages", label: "Messages", icon: "message", badge: 3 },
  { page: "decisions", label: "Decisions", icon: "shield", badge: 2 },
  { page: "teams", label: "Teams", icon: "users", badge: 0 },
  { page: "agents", label: "Agents", icon: "spark", badge: 0 },
  { page: "topology", label: "Company", icon: "cube", badge: 0 },
  { page: "engineering", label: "Engineering", icon: "wrench", badge: 0 },
  { page: "revenue", label: "Revenue", icon: "receipt", badge: 0 },
] as const;

// ---------- this window's open tabs (window-local; popped views are added from the shared owner list) ----------
const TAB_KEY = "hq.tabs";
function loadTabs(): string[] {
  try { const v: unknown = JSON.parse(sessionStorage.getItem(TAB_KEY) ?? "[]"); if (Array.isArray(v)) return v.filter((x) => typeof x === "string" && viewById(x)); } catch { /* none */ }
  return [];
}
export const tabs = new Store<string[]>(loadTabs());
tabs.subscribe(() => { try { sessionStorage.setItem(TAB_KEY, JSON.stringify(tabs.get())); } catch { /* ignore */ } });
export function openTab(id: string) { tabs.set((t) => (t.includes(id) ? t : [...t, id])); }
export function closeTab(id: string) { tabs.set((t) => t.filter((x) => x !== id)); }

function NavItem({ n, current }: { n: (typeof NAV)[number]; current: boolean }) {
  const id = `page:${n.page}`;
  const o = useOwner(id);
  const needsNow = useNeedsSummary().total;
  const badge = n.page === "decisions" ? needsNow : n.badge;
  const out = !!o && o.win !== WIN_ID;
  const menu = useContextMenu(() => out
    ? [{ label: "Focus its window", icon: "popout", run: () => focusWindow(id) }, { label: "Return to this window", icon: "returnin", run: () => returnHere(id) }]
    : [{ label: `Open ${n.label}`, icon: n.icon, run: () => go(n.page) }, { label: "Open in new window", icon: "popout", hint: "⌥⇧O", run: () => popOut(id) }], n.label);
  return <div className={cx("nav-item", current && "is-current", out && "is-out")} {...menu}>
    <a href={href(n.page)} aria-current={current ? "page" : undefined} title={out ? `${n.label} — open in another window` : n.label}
      onClick={() => { if (out) focusWindow(id); }}>
      <Icon name={n.icon} size={21} /><span className="nav-label">{n.label}</span>
      {out ? <span className="nav-out" aria-label="open in another window"><Icon name="popout" size={14} /></span>
        : badge ? <span className="nav-badge">{badge}</span> : null}
    </a>
    {!out && <PopButton id={id} compact />}
  </div>;
}

/** The navigation section a route belongs to (a Task Room is part of Engineering, and so on). */
export function sectionOf(screen: string): string {
  return screen === "task" ? "engineering" : screen === "onboard" ? "agents" : screen === "newproject" ? "teams" : screen;
}

export function Sidebar() {
  const route = useRoute();
  const cur = sectionOf(route.screen);
  const g = useStore(gov);
  const pending = g.requests.filter((r) => !g.decisions[r.id] && r.expires > Date.now()).length;
  return <aside className="side" aria-label="Navigation">
    <a className="brand" href="#/office"><Logo /><span><b>Command<em>Center</em></b><small>AI Engineering Company</small></span></a>
    <nav className="nav" aria-label="Pages">{NAV.map((n) => <NavItem key={n.page} n={n} current={cur === n.page} />)}</nav>
    <div className="side-fill" />
    <nav className="nav nav-low" aria-label="More">
      <div className={cx("nav-item", cur === "approvals" && "is-current")}><a href="#/approvals" title="Approvals" aria-current={cur === "approvals" ? "page" : undefined}><Icon name="check" size={21} /><span className="nav-label">Approvals</span>{pending > 0 && <span className="nav-badge">{pending}</span>}</a></div>
      <div className={cx("nav-item", cur === "budgets" && "is-current")}><a href="#/budgets" title="Budgets" aria-current={cur === "budgets" ? "page" : undefined}><Icon name="receipt" size={21} /><span className="nav-label">Budgets</span></a></div>
      <div className={cx("nav-item", (cur === "settings" && route.id !== "help" || cur === "more") && "is-current")}><a href="#/settings" title="Settings &amp; more" aria-current={cur === "settings" && route.id !== "help" ? "page" : undefined}><Icon name="gear" size={21} /><span className="nav-label">Settings &amp; more</span></a></div>
      <div className={cx("nav-item", cur === "settings" && route.id === "help" && "is-current")}><a href="#/settings/help" title="Help &amp; Support" aria-current={cur === "settings" && route.id === "help" ? "page" : undefined}><Icon name="help" size={21} /><span className="nav-label">Help &amp; Support</span></a></div>
    </nav>
    <div className="side-proto"><b>Design prototype</b><span>Mock data · not connected to ccd</span></div>
  </aside>;
}

function Palette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const { v } = useOrg();
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const items = useMemo(() => {
    const all: { id: string; label: string; sub: string; run: () => void }[] = [
      ...NAV.map((n) => ({ id: n.page, label: n.label, sub: "Page", run: () => go(n.page) })),
      ...PROJECTS.map((p) => ({ id: p.key, label: `${p.name} team`, sub: "Team", run: () => go("teams", p.key) })),
      ...TASKS.map((t) => ({ id: t.key, label: `${t.key} ${t.title}`, sub: "Task Room", run: () => go("task", t.key) })),
      ...AGENTS.filter((a) => a.life !== "offboarded").map((a) => ({ id: `a:${a.id}`, label: `${a.name} — ${a.role}`, sub: "Agent", run: () => go("agents") })),
      { id: "new-agent", label: "New Agent", sub: "Onboarding", run: () => go("onboard") },
      { id: "new-project", label: "New Project", sub: "Onboarding", run: () => go("newproject") },
      ...CONVERSATIONS.filter((c) => !c.archived).map((c) => ({ id: c.id, label: `${c.title} — ${c.sub}`, sub: "Conversation", run: () => go("messages", c.id) })),
      { id: "settings", label: "Settings", sub: "Preferences", run: () => go("settings") },
      { id: "shortcuts", label: "Keyboard shortcuts", sub: "Help", run: () => go("settings", "help") },
      { id: "more", label: "Releases, Fleet, Activity, AI Usage…", sub: "Other destinations", run: () => go("settings", "more") },
      { id: "design", label: "Design system", sub: "Reference", run: () => go("design") },
      { id: "approvals", label: "Approvals (Slack requests, approval screen)", sub: "Governance", run: () => go("approvals") },
      { id: "budgets", label: "Budgets (agent, project, company)", sub: "Governance", run: () => go("budgets") },
    ];
    const s = q.toLowerCase();
    return all.filter((i) => !s || i.label.toLowerCase().includes(s)).slice(0, 9);
  }, [q, v]);
  const at = Math.min(sel, Math.max(0, items.length - 1));
  return <div className="palette-veil" onClick={onClose}>
    <div className="palette" role="dialog" aria-label="Search" onClick={(e) => e.stopPropagation()}>
      <div className="palette-in"><Icon name="search" /><input ref={ref} value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} placeholder="Search projects, agents, tasks, conversations…"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          else if (e.key === "ArrowDown") { e.preventDefault(); setSel((at + 1) % Math.max(1, items.length)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((at - 1 + items.length) % Math.max(1, items.length)); }
          else if (e.key === "Enter" && items[at]) { items[at].run(); onClose(); }
        }} aria-label="Search" aria-activedescendant={items[at] ? `pal-${at}` : undefined} /><kbd>esc</kbd></div>
      <ul role="listbox" aria-label="Results">{items.map((i, k) => <li key={i.sub + i.id}><button type="button" id={`pal-${k}`} role="option" aria-selected={k === at} className={cx(k === at && "is-sel")}
        onMouseMove={() => setSel(k)} onClick={() => { i.run(); onClose(); }}><span>{i.label}</span><small>{i.sub}</small></button></li>)}
        {!items.length && <li className="palette-empty">No matches for “{q}”.</li>}</ul>
    </div>
  </div>;
}

function meMenu(): MenuItem[] {
  const m = motionPref.get(), slow = slowDemo.get(), t = themePref.get();
  return [
    { label: "Settings", icon: "gear", run: () => go("settings") },
    { label: "Help & shortcuts", icon: "help", run: () => go("settings", "help") },
    { label: "Design system", icon: "layers", run: () => go("design") },
    { sep: true },
    { label: "Dark (default)", checked: t === "dark", run: () => setThemePref("dark") },
    { label: "Light", checked: t === "light", run: () => setThemePref("light") },
    { label: "Follow system appearance", checked: t === "system", run: () => setThemePref("system") },
    { sep: true },
    { label: "Motion: follow system", checked: m === "system", run: () => setMotionPref("system") },
    { label: "Reduce motion", checked: m === "reduce", run: () => setMotionPref("reduce") },
    { label: "Simulate slow loading (demo)", checked: slow, run: () => setSlowDemo(!slow) },
    { sep: true },
    { label: "Sign out", icon: "lock", hint: "Prototype", disabled: true },
  ];
}

// ---------- phone: a native-style tab bar at the bottom, with everything else in a More sheet ----------
const PHONE_TABS = [
  { page: "office", label: "Office", icon: "home" },
  { page: "messages", label: "Messages", icon: "message" },
  { page: "decisions", label: "Decisions", icon: "shield" },
  { page: "approvals", label: "Approvals", icon: "check" },
] as const;
const MORE_GROUPS: { title: string; items: { label: string; sub: string; icon: string; tint: string; go: () => void; page?: string }[] }[] = [
  { title: "Company", items: [
    { label: "Teams", sub: "Project Leads and their teams", icon: "users", tint: "#3f7bff", page: "teams", go: () => go("teams") },
    { label: "Agents", sub: "Directory and management", icon: "spark", tint: "#a77bff", page: "agents", go: () => go("agents") },
    { label: "Operations Topology", sub: "The whole company as a graph", icon: "cube", tint: "#6d5cff", page: "topology", go: () => go("topology") },
    { label: "Engineering", sub: "Workbench and Task Rooms", icon: "wrench", tint: "#ff8a3d", page: "engineering", go: () => go("engineering") },
    { label: "Revenue", sub: "Not connected", icon: "chart", tint: "#2fe08c", page: "revenue", go: () => go("revenue") },
    { label: "Budgets", sub: "Agent, project and company limits", icon: "receipt", tint: "#ffb020", page: "budgets", go: () => go("budgets") },
  ] },
  { title: "Create", items: [
    { label: "New Agent", sub: "Onboarding, mock only", icon: "plus", tint: "#5a4dff", page: "onboard", go: () => go("onboard") },
    { label: "New Project", sub: "Onboarding, mock only", icon: "plus", tint: "#3f7bff", page: "newproject", go: () => go("newproject") },
  ] },
  { title: "", items: [
    { label: "Settings", sub: "Appearance, notifications, security", icon: "gear", tint: "#8a95b0", page: "settings", go: () => go("settings") },
    { label: "Help & shortcuts", sub: "Where things are", icon: "help", tint: "#8fa2ff", go: () => go("settings", "help") },
    { label: "Design system", sub: "Tokens and components", icon: "layers", tint: "#ff4fa0", page: "design", go: () => go("design") },
  ] },
];

function MoreSheet({ onClose, returnTo }: { onClose: () => void; returnTo: React.RefObject<HTMLButtonElement | null> }) {
  const ref = useRef<HTMLDivElement>(null);
  const route = useRoute();
  useEffect(() => {
    ref.current?.focus();
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } };
    window.addEventListener("keydown", k);
    const back = returnTo.current;
    return () => { window.removeEventListener("keydown", k); back?.focus(); };
  }, [onClose, returnTo]);
  const pick = (f: () => void) => { onClose(); f(); };
  return <div className="sheet-veil" onClick={onClose}>
    <div className="sheet" role="dialog" aria-modal="true" aria-label="More" tabIndex={-1} ref={ref} onClick={(e) => e.stopPropagation()}>
      <span className="sheet-grab" aria-hidden="true" />
      <header className="sheet-h"><b>More</b><button type="button" className="sheet-done" onClick={onClose}>Done</button></header>
      {MORE_GROUPS.map((g, gi) => <section key={gi} className="sheet-group">{g.title && <h3>{g.title}</h3>}
        <div className="set-rows">{g.items.map((i) => { const on = !!i.page && sectionOf(route.screen) === i.page;
          return <button key={i.label} type="button" className={cx("sheet-row", on && "is-current")} aria-current={on ? "page" : undefined} onClick={() => pick(i.go)}>
            <span className="set-ico" style={{ ["--c" as string]: i.tint }}><Icon name={i.icon} size={15} /></span>
            <span className="sheet-row-t"><b>{i.label}</b><small>{i.sub}</small></span><Icon name="chevron" size={14} /></button>; })}</div></section>)}
      <p className="sheet-foot">Design prototype · mock data · not connected to ccd</p>
    </div>
  </div>;
}

/** Shown instead of the sidebar on phones (≤ 760 px). The desktop sidebar is unchanged. */
export function BottomNav() {
  const route = useRoute();
  const cur = sectionOf(route.screen);
  const needs = useNeedsSummary().total;
  const g = useStore(gov);
  const pending = g.requests.filter((r) => !g.decisions[r.id] && r.expires > Date.now()).length;
  const [more, setMore] = useState(false);
  const moreRef = useRef<HTMLButtonElement>(null);
  const inTabs = PHONE_TABS.some((t) => t.page === cur);
  const badge: Record<string, number> = { messages: 3, decisions: needs, approvals: pending };
  return <>
    <nav className="tabbar" aria-label="Tab bar">
      {PHONE_TABS.map((t) => <a key={t.page} href={href(t.page)} className={cx("tabbar-i", cur === t.page && !more && "is-current")} aria-current={cur === t.page ? "page" : undefined}>
        <span className="tabbar-ico"><Icon name={t.icon} size={23} />{badge[t.page] ? <em>{badge[t.page]}</em> : null}</span><span>{t.label}</span></a>)}
      <button type="button" ref={moreRef} className={cx("tabbar-i", (more || !inTabs) && "is-current")} aria-haspopup="dialog" aria-expanded={more} onClick={() => setMore((m) => !m)}>
        <span className="tabbar-ico"><Icon name="grid" size={23} /></span><span>More</span></button>
    </nav>
    {more && <MoreSheet onClose={() => setMore(false)} returnTo={moreRef} />}
  </>;
}

export function TopBar({ status }: { status?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [bell, setBell] = useState(false);
  const bellRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  return <header className="top">
    <a className="top-brand" href="#/office" aria-label="CommandCenter · My Office"><Logo size={30} /></a>
    <button type="button" className="search" onClick={() => setOpen(true)}><Icon name="search" size={19} />
      <span>Search projects, agents, decisions, people, or ask CommandCenter…</span><kbd>Ctrl</kbd><kbd>K</kbd></button>
    {status ?? <div className="sys-pill"><i /><div><b>Production · Untouched</b><small>Prototype · no live changes</small></div></div>}
    <button type="button" ref={bellRef} className={cx("bell", bell && "is-open")} aria-label="Notifications (demo)" aria-expanded={bell} onClick={() => setBell((b) => !b)}><Icon name="bell" size={21} /><span>1</span></button>
    <Popover open={bell} onClose={() => setBell(false)} anchor={bellRef} label="Notifications" className="pop-notes">
      <header className="pop-h"><b>Notifications</b><Demo label="Demo" /></header>
      <button type="button" className="note-row" data-autofocus onClick={() => { setBell(false); go("decisions", "sv-025"); }}>
        <span className="attn-ico t-info"><Icon name="doc" size={16} /></span><span><b>SV-025 is waiting for your decision</b><small className="muted">Rental comparison redesign · 2h ago</small></span></button>
      <footer className="pop-f"><button type="button" className="link" onClick={() => { setBell(false); go("decisions"); }}>Open Decisions <Icon name="arrowr" size={12} /></button></footer>
    </Popover>
    <button type="button" className="me" aria-haspopup="menu" onClick={(e) => openMenu(e.currentTarget, meMenu(), "Jay")}
      onContextMenu={(e) => { e.preventDefault(); openMenu(e.currentTarget, meMenu(), "Jay"); }}>
      <span className="av av-jay" style={{ width: 34, height: 34 }}>J</span><span className="me-t"><b>Jay</b><small>Engineering Director</small></span><Icon name="chevdown" size={16} /></button>
    {open && <Palette onClose={() => setOpen(false)} />}
  </header>;
}

function Tab({ def, active }: { def: ViewDef; active: boolean }) {
  const o = useOwner(def.id);
  const out = !!o && o.win !== WIN_ID;
  const isPage = def.kind === "page";
  const canClose = !out && !(isPage && active);
  const menu = useContextMenu((): MenuItem[] => [
    ...(out ? [{ label: "Focus window", icon: "popout", run: () => focusWindow(def.id) }, { label: "Return here", icon: "returnin", hint: "⌥⇧R", run: () => returnHere(def.id) }]
      : [{ label: "Pop out to new window", icon: "popout", hint: "⌥⇧O", run: () => { popOut(def.id); } }]),
    { sep: true },
    { label: "Close tab", icon: "x", disabled: !canClose, run: () => closeTab(def.id) },
    { label: "Close other tabs", disabled: tabs.get().filter((x) => x !== def.id).length === 0, run: () => tabs.set((t) => t.filter((x) => x === def.id || owners.get()[x])) },
  ], def.title);
  return <div role="tab" aria-selected={active} className={cx("tab", active && "is-active", out && "is-out")} data-testid={`tab-${def.id}`}
    title={out ? `${def.title} — open in another window` : def.title}
    onContextMenu={menu.onContextMenu}>
    <a href={def.hash} onClick={() => { if (out) focusWindow(def.id); }} onKeyDown={menu.onKeyDown}>
      {def.color ? <i className="tab-dot" style={{ background: def.color }} /> : <Icon name={isPage ? "doc" : "message"} size={13} />}
      <span>{def.title}</span>
      {out && <span className="tab-out" aria-label="open in another window"><Icon name="popout" size={12} /></span>}
    </a>
    {!out && <PopButton id={def.id} compact />}
    {canClose && <button type="button" className="tab-x" aria-label={`Close ${def.title} tab`} onClick={() => closeTab(def.id)}><Icon name="x" size={12} /></button>}
  </div>;
}

export function TabStrip() {
  const route = useRoute();
  const local = useStore(tabs);
  const own = useStore(owners);
  const current = viewForRoute(route.screen, route.id);
  useEffect(() => { if (current) openTab(current.id); }, [current?.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const ids = [...local, ...Object.keys(own).filter((id) => !local.includes(id))];
  const defs = ids.map(viewById).filter((d): d is ViewDef => !!d);
  return <div className="tabs" role="tablist" aria-label="Open views">
    {defs.map((d) => <Tab key={d.id} def={d} active={d.id === current?.id} />)}
    <span className="tabs-hint">Right-click a tab, or ↗, to pop it out to another monitor</span>
  </div>;
}

export function Notices() {
  const list = useStore(notices);
  return <div className="notices" aria-live="polite">{list.map((n) => <div key={n.id} className={`notice t-${n.tone}`}>
    <span className="notice-ico"><Icon name={n.tone === "ok" ? "check" : "info"} size={16} /></span><span className="notice-t">{n.text}</span>
    {n.action && <button type="button" className="btn btn-sm" onClick={n.action.run}>{n.action.label}</button>}
    <button type="button" className="icon-btn notice-x" aria-label="Dismiss" onClick={() => notices.set((l) => l.filter((x) => x.id !== n.id))}><Icon name="x" size={13} /></button></div>)}</div>;
}

/** Alt+Shift+O pops out the current tab; Alt+Shift+R returns it. */
export function useWindowKeys() {
  const route = useRoute();
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (!e.altKey || !e.shiftKey) return;
      const v = viewForRoute(route.screen, route.id);
      if (!v) return;
      if (e.code === "KeyO") { e.preventDefault(); popOut(v.id); }
      if (e.code === "KeyR") { e.preventDefault(); returnHere(v.id); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [route.screen, route.id]);
}
