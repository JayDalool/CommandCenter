import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Store, useStore } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import { Icon, Logo } from "./Icon";
import { cx } from "./ui";
import { focusWindow, notices, owners, popOut, returnHere } from "../windows/manager";
import { PopButton, useOwner } from "../windows/Detachable";
import { viewById, viewForRoute, type ViewDef } from "../windows/views";
import { WIN_ID } from "../lib/shared";
import { AGENTS, CONVERSATIONS, PROJECTS, TASKS } from "../data/seed";
import { useOrg } from "../data/org";

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
  const out = !!o && o.win !== WIN_ID;
  return <div className={cx("nav-item", current && "is-current", out && "is-out")}>
    <a href={href(n.page)} aria-current={current ? "page" : undefined} title={out ? `${n.label} — open in another window` : n.label}
      onClick={() => { if (out) focusWindow(id); }}>
      <Icon name={n.icon} size={21} /><span className="nav-label">{n.label}</span>
      {out ? <span className="nav-out" aria-label="open in another window"><Icon name="popout" size={14} /></span>
        : n.badge ? <span className="nav-badge">{n.badge}</span> : null}
    </a>
    {!out && <PopButton id={id} compact />}
  </div>;
}

export function Sidebar() {
  const route = useRoute();
  const cur = route.screen === "task" ? "engineering" : route.screen === "onboard" ? "agents" : route.screen === "newproject" ? "teams" : route.screen;
  return <aside className="side" aria-label="Navigation">
    <a className="brand" href="#/office"><Logo /><span><b>Command<em>Center</em></b><small>AI Engineering Company</small></span></a>
    <nav className="nav" aria-label="Pages">{NAV.map((n) => <NavItem key={n.page} n={n} current={cur === n.page} />)}</nav>
    <div className="side-fill" />
    <nav className="nav nav-low" aria-label="More">
      <div className={cx("nav-item", cur === "more" && "is-current")}><a href="#/more"><Icon name="gear" size={21} /><span className="nav-label">Settings &amp; more</span></a></div>
      <div className="nav-item"><a href="#/more"><Icon name="help" size={21} /><span className="nav-label">Help &amp; Support</span></a></div>
    </nav>
    <div className="side-proto"><b>Design prototype</b><span>Mock data · not connected to ccd</span></div>
  </aside>;
}

function Palette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
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
      { id: "more", label: "Releases, Fleet, Activity, AI Usage, Settings…", sub: "More", run: () => go("more") },
    ];
    const s = q.toLowerCase();
    return all.filter((i) => !s || i.label.toLowerCase().includes(s)).slice(0, 9);
  }, [q, v]);
  return <div className="palette-veil" onClick={onClose}>
    <div className="palette" role="dialog" aria-label="Search" onClick={(e) => e.stopPropagation()}>
      <div className="palette-in"><Icon name="search" /><input ref={ref} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search projects, agents, tasks, conversations…"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); if (e.key === "Enter" && items[0]) { items[0].run(); onClose(); } }} aria-label="Search" /></div>
      <ul>{items.map((i) => <li key={i.sub + i.id}><button type="button" onClick={() => { i.run(); onClose(); }}><span>{i.label}</span><small>{i.sub}</small></button></li>)}</ul>
    </div>
  </div>;
}

export function TopBar({ status }: { status?: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  return <header className="top">
    <button type="button" className="search" onClick={() => setOpen(true)}><Icon name="search" size={19} />
      <span>Search projects, agents, decisions, people, or ask CommandCenter…</span><kbd>Ctrl</kbd><kbd>K</kbd></button>
    {status ?? <div className="sys-pill"><i /><div><b>Production · Untouched</b><small>Prototype · no live changes</small></div></div>}
    <button type="button" className="bell" aria-label="Notifications (demo)"><Icon name="bell" size={21} /><span>1</span></button>
    <div className="me"><span className="av av-jay" style={{ width: 34, height: 34 }}>J</span><div><b>Jay</b><small>Engineering Director</small></div><Icon name="chevdown" size={16} /></div>
    {open && <Palette onClose={() => setOpen(false)} />}
  </header>;
}

function Tab({ def, active }: { def: ViewDef; active: boolean }) {
  const o = useOwner(def.id);
  const out = !!o && o.win !== WIN_ID;
  const [menu, setMenu] = useState(false);
  const isPage = def.kind === "page";
  return <div role="tab" aria-selected={active} className={cx("tab", active && "is-active", out && "is-out")} data-testid={`tab-${def.id}`}
    title={out ? `${def.title} — open in another window` : def.title}
    onContextMenu={(e) => { e.preventDefault(); setMenu(true); }}>
    <a href={def.hash} onClick={() => { if (out) focusWindow(def.id); }}
      onKeyDown={(e) => { if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); setMenu(true); } }}>
      {def.color ? <i className="tab-dot" style={{ background: def.color }} /> : <Icon name={isPage ? "doc" : "message"} size={13} />}
      <span>{def.title}</span>
      {out && <span className="tab-out" aria-label="open in another window"><Icon name="popout" size={12} /></span>}
    </a>
    {!out && <PopButton id={def.id} compact />}
    {!out && !(isPage && active) && <button type="button" className="tab-x" aria-label={`Close ${def.title} tab`} onClick={() => closeTab(def.id)}><Icon name="x" size={12} /></button>}
    {menu && <div className="tab-menu" role="menu" onMouseLeave={() => setMenu(false)}>
      {out ? <>
        <button role="menuitem" type="button" onClick={() => { focusWindow(def.id); setMenu(false); }}>Focus window</button>
        <button role="menuitem" type="button" onClick={() => { returnHere(def.id); setMenu(false); }}>Return here</button>
      </> : <button role="menuitem" type="button" onClick={() => { popOut(def.id); setMenu(false); }}>Pop out to new window</button>}
      <button role="menuitem" type="button" onClick={() => setMenu(false)}>Cancel</button>
    </div>}
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
  return <div className="notices" aria-live="polite">{list.map((n) => <div key={n.id} className={`notice t-${n.tone}`}>{n.text}
    {n.action && <button type="button" className="btn btn-sm" onClick={n.action.run}>{n.action.label}</button>}</div>)}</div>;
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
