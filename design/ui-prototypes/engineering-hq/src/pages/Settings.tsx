// SETTINGS — laid out like macOS System Settings: a list of sections on the left, grouped rows on the right.
// Mock only. Nothing here reaches ccd, Slack, GitHub or a billing provider, and no token or password is ever asked for.
// Preferences that are real in the prototype (motion, slow-loading demo, feed outage demo) change this browser only.
import { useState, type ReactNode } from "react";
import { Icon, type IconId } from "../components/Icon";
import { Avatar, Demo, Pill, cx } from "../components/ui";
import { Seg } from "../components/form";
import { useRoute, go } from "../lib/router";
import { useStore } from "../lib/store";
import { motionPref, setMotionPref } from "../lib/motion";
import { resolvedTheme, setThemePref, themePref, type ThemePref } from "../lib/theme";
import { setSlowDemo, slowDemo } from "../components/overlay";
import { feed, setOutage } from "../data/live";
import { resetShared } from "../lib/shared";
import { useOrg } from "../data/org";
import { PROJECTS } from "../data/seed";
import { WORKERS, WORKER_CAP_LABEL } from "../data/catalog";
import { focusWindow, owners, popOut, returnHere } from "../windows/manager";
import { viewById } from "../windows/views";
import { DEST } from "./More";

export const SETTINGS_SECTIONS: { id: string; label: string; icon: IconId; tint: string; sub: string }[] = [
  { id: "general", label: "General", icon: "gear", tint: "#8a95b0", sub: "Account and region" },
  { id: "appearance", label: "Appearance", icon: "layers", tint: "#6d5cff", sub: "Dark, Light or System, colour and motion" },
  { id: "notifications", label: "Notifications", icon: "bell", tint: "#ff4f6d", sub: "What reaches you, and where" },
  { id: "windows", label: "Windows & monitors", icon: "popout", tint: "#3f7bff", sub: "Pop-out windows" },
  { id: "security", label: "Security", icon: "lock", tint: "#2fe08c", sub: "Developer Unlock and identity" },
  { id: "connections", label: "Connections", icon: "plug", tint: "#ffb020", sub: "ccd, Slack, GitHub, billing" },
  { id: "projects", label: "Operating profiles", icon: "shield", tint: "#a77bff", sub: "Each project's mode and merge rule" },
  { id: "workers", label: "Workers", icon: "server", tint: "#58a6ff", sub: "Machines that can run agent work" },
  { id: "demo", label: "Demo controls", icon: "spark", tint: "#ff4fa0", sub: "Review honest states" },
  { id: "more", label: "Other destinations", icon: "more", tint: "#7c88a6", sub: "Screens of the current app" },
  { id: "help", label: "Help & shortcuts", icon: "help", tint: "#8fa2ff", sub: "Keyboard and where things are" },
];

/** A titled group of rows, like a macOS inset list. */
function Group({ title, foot, children }: { title?: string; foot?: ReactNode; children: ReactNode }) {
  return <section className="set-group">{title && <h3>{title}</h3>}<div className="set-rows">{children}</div>{foot && <p className="set-foot">{foot}</p>}</section>;
}
function Row({ label, hint, children, icon }: { label: ReactNode; hint?: ReactNode; children?: ReactNode; icon?: ReactNode }) {
  return <div className="set-row">{icon}<div className="set-row-t"><b>{label}</b>{hint && <small>{hint}</small>}</div>{children && <div className="set-row-v">{children}</div>}</div>;
}
function Toggle({ label, checked, onChange, disabled, title }: { label: string; checked: boolean; onChange?: (v: boolean) => void; disabled?: boolean; title?: string }) {
  return <label className="switch set-switch" title={title}><input type="checkbox" aria-label={label} checked={checked} disabled={disabled} onChange={(e) => onChange?.(e.target.checked)} /></label>;
}

function General() {
  const [week, setWeek] = useState("mon");
  const [clock, setClock] = useState<"24" | "12">("24");
  return <>
    <Group title="Account">
      <Row icon={<Avatar id="jay" size={40} />} label="Jay" hint="Engineering Director · the only person who approves"><Pill tone="idle">Prototype · no sign-in</Pill></Row>
    </Group>
    <Group title="Region" foot="Release windows and quiet hours use this time zone.">
      <Row label="Time zone" hint="From the project profiles"><span className="mono">America/Winnipeg</span></Row>
      <Row label="Week starts on"><select aria-label="Week starts on" value={week} onChange={(e) => setWeek(e.target.value)}><option value="mon">Monday</option><option value="sun">Sunday</option></select></Row>
      <Row label="Clock" hint={`Release windows read ${clock === "24" ? "Thu 01:00" : "Thu 1:00 AM"}`}><Seg label="Clock" size="sm" value={clock} onChange={setClock} options={[{ id: "24", label: "24-hour" }, { id: "12", label: "12-hour" }]} /></Row>
    </Group>
  </>;
}

const THEMES: { id: ThemePref; label: string; sub: string }[] = [
  { id: "dark", label: "Dark", sub: "Default" },
  { id: "light", label: "Light", sub: "Optional" },
  { id: "system", label: "System", sub: "Follows your OS" },
];
const thumbWin = (cls: string) => <span className={`at-win ${cls}`}><i className="at-side" /><i className="at-top" /><i className="at-card" /><i className="at-card is-2" /><i className="at-acc" /></span>;
/** macOS-style appearance picker: a small window in each theme. Arrow keys move between the three. */
function ThemePicker() {
  const pref = useStore(themePref);
  const move = (e: React.KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = THEMES[(i + d + THEMES.length) % THEMES.length];
    setThemePref(n.id);
    (e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=radio]")[THEMES.indexOf(n)])?.focus();
  };
  return <div className="appear" role="radiogroup" aria-label="Appearance">
    {THEMES.map((t, i) => <button key={t.id} type="button" role="radio" aria-checked={pref === t.id} tabIndex={pref === t.id ? 0 : -1}
      className={cx("appear-i", pref === t.id && "is-on")} onClick={() => setThemePref(t.id)} onKeyDown={(e) => move(e, i)}>
      <span className={`appear-thumb is-${t.id}`} aria-hidden="true">{t.id === "system" ? <>{thumbWin("is-dark")}{thumbWin("is-light is-half")}</> : thumbWin(t.id === "light" ? "is-light" : "is-dark")}</span>
      <b>{t.label}</b><small>{t.sub}</small></button>)}
  </div>;
}

function Appearance() {
  const motion = useStore(motionPref);
  const pref = useStore(themePref);
  const { v } = useOrg();
  void v;
  return <>
    <Group title="Appearance" foot={<>Dark navy and purple is the approved default. Light is an optional variant with the same layout, project colours, status colours and graphs. System follows the Windows or macOS setting and switches when it does. Every open window follows the choice.</>}>
      <div className="set-row is-block"><ThemePicker /></div>
      {pref === "system" && <Row label="Showing now" hint="From your operating system"><span>{resolvedTheme(pref) === "light" ? "Light" : "Dark"}</span></Row>}
    </Group>
    <Group title="Colour" foot="Project colours and agent personas are approved. They come from the project and agent records and look the same in both themes.">
      <Row label="Accent" hint="Purple for focus and selection, blue for links and information"><span className="set-theme" aria-label="Accent colours"><i style={{ background: "var(--accent)" }} /><i style={{ background: "var(--accent-2)" }} /><i style={{ background: "var(--ok)" }} /><i style={{ background: "var(--warn)" }} /><i style={{ background: "var(--bad)" }} /></span></Row>
      <Row label="Project colours" hint="One source: the project records. Task IDs carry them everywhere.">
        <span className="set-swatches">{PROJECTS.map((p) => <span key={p.key} title={p.name}><i style={{ background: p.color }} />{p.prefix}</span>)}</span></Row>
    </Group>
    <Group title="Motion" foot="Reduce motion turns slides, scales and shimmer into instant changes. It also follows your system setting.">
      <Row label="Animations"><Seg label="Animations" size="sm" value={motion} onChange={setMotionPref} options={[{ id: "system", label: "Follow system" }, { id: "reduce", label: "Reduce motion" }]} /></Row>
    </Group>
  </>;
}

function Notifications() {
  const [on, setOn] = useState({ questions: true, gates: true, blocked: true, failures: true });
  const flip = (k: keyof typeof on) => (x: boolean) => setOn((s) => ({ ...s, [k]: x }));
  return <>
    <Group title="What notifies you" foot="Only what needs you. Ordinary commits, passing tests and routine stage moves never notify.">
      <Row label="Questions waiting for you"><Toggle label="Questions waiting for you" checked={on.questions} onChange={flip("questions")} /></Row>
      <Row label="A gate to decide" hint="Plan, merge acceptance, UI review, live deploy"><Toggle label="A gate to decide" checked={on.gates} onChange={flip("gates")} /></Row>
      <Row label="A blocked task or agent"><Toggle label="A blocked task or agent" checked={on.blocked} onChange={flip("blocked")} /></Row>
      <Row label="A major failure"><Toggle label="A major failure" checked={on.failures} onChange={flip("failures")} /></Row>
      <Row label="Routine stage moves"><Toggle label="Routine stage moves" checked={false} disabled title="Never notifies" /></Row>
    </Group>
    <Group title="Where">
      <Row label="In-app bell" hint="Every window"><Pill tone="ok" dot>On</Pill></Row>
      <Row icon={<span className="set-ico" style={{ ["--c" as string]: "#ffb020" }}><Icon name="slack" size={16} /></span>} label="Slack" hint="Requests with a secure link to the signed-in approval screen (D-032). Buttons inside Slack are a later, separate approval.">
        <Pill tone="warn" dot>Off · needs your approval</Pill></Row>
    </Group>
    <Group title="Quiet hours" foot="Only an outage, data at risk or a security incident breaks through.">
      <Row label="Every night" hint="America/Winnipeg"><span className="mono">23:00 – 07:00</span></Row>
    </Group>
  </>;
}

function Windows() {
  const own = useStore(owners);
  const out = Object.keys(own).map(viewById).filter((d): d is NonNullable<typeof d> => !!d);
  return <>
    <Group title="In other windows" foot="Closing a window brings its view back here. Only one window shows a view at a time.">
      {out.length ? out.map((d) => <Row key={d.id} label={d.title} hint={d.sub ?? d.id}>
        <button type="button" className="btn btn-sm" onClick={() => focusWindow(d.id)}><Icon name="popout" size={13} /> Focus</button>
        <button type="button" className="btn btn-sm" onClick={() => returnHere(d.id)}><Icon name="returnin" size={13} /> Return here</button></Row>)
        : <Row label="No views are in other windows" hint="Use ↗ on any tab, panel, conversation or terminal, right-click a tab, or press Alt+Shift+O." />}
    </Group>
    <Group title="Try it" foot="Drag the new window to another monitor. Browsers cannot choose the monitor themselves; a native app could.">
      <Row label="Open My Office in a new window"><button type="button" className="btn btn-sm" onClick={() => popOut("page:office")}><Icon name="popout" size={13} /> Pop out</button></Row>
      <Row label="Open Operations Topology in a new window"><button type="button" className="btn btn-sm" onClick={() => popOut("page:topology")}><Icon name="popout" size={13} /> Pop out</button></Row>
    </Group>
  </>;
}

function Security() {
  return <>
    <Group title="Developer Unlock" foot="Writing files, uploads and every high-risk approval need it. Locking in any window locks every window.">
      <Row label="Status" hint="The prototype never asks for a token or password"><Pill tone="idle" dot>Locked</Pill>
        <button type="button" className="btn btn-sm" disabled title="Prototype: no credentials here">Unlock…</button></Row>
      <Row label="Ends after" hint="Or when the browser session ends, or ccd restarts"><span>2 h idle · 8 h at most · 12 h with SSH sign-in</span></Row>
    </Group>
    <Group title="Who did what" foot="Today an agent's identity is recorded, not enforced. Phase 2 actor tokens make it checkable.">
      <Row label="Agent identity"><Pill tone="warn" dot>Recorded · Phase 2</Pill></Row>
      <Row label="Approvals" hint="Each approval is bound to the exact request it approves"><button type="button" className="link" onClick={() => go("approvals")}>Open Approvals <Icon name="arrowr" size={12} /></button></Row>
    </Group>
  </>;
}

function Connections() {
  return <Group title="Services" foot="The prototype connects to nothing. Production keeps ccd on 127.0.0.1 behind its token, and never exposes it publicly.">
    <Row icon={<span className="set-ico" style={{ ["--c" as string]: "#6d5cff" }}><Icon name="cc" size={16} /></span>} label="ccd" hint="CommandCenter's server"><Pill tone="idle" dot>Not connected · prototype</Pill></Row>
    <Row icon={<span className="set-ico" style={{ ["--c" as string]: "#ffb020" }}><Icon name="slack" size={16} /></span>} label="Slack" hint="Requests and secure links only (D-032)"><Pill tone="warn" dot>Off · needs your approval</Pill></Row>
    <Row icon={<span className="set-ico" style={{ ["--c" as string]: "#8a95b0" }}><Icon name="branch" size={16} /></span>} label="GitHub" hint="Production uses ccd's existing GitHub access"><Pill tone="idle" dot>Not connected · prototype</Pill></Row>
    <Row icon={<span className="set-ico" style={{ ["--c" as string]: "#2fe08c" }}><Icon name="card" size={16} /></span>} label="Billing provider" hint="For Revenue. Read-only, and only after you pick a provider"><Pill tone="idle" dot>Not connected</Pill>
      <button type="button" className="link" onClick={() => go("revenue")}>Revenue <Icon name="arrowr" size={12} /></button></Row>
    <Row icon={<span className="set-ico" style={{ ["--c" as string]: "#58a6ff" }}><Icon name="pulse" size={16} /></span>} label="Usage meter" hint="AI spend estimates, kept apart from revenue"><Pill tone="idle" dot>Demo figures</Pill>
      <button type="button" className="link" onClick={() => go("budgets")}>Budgets <Icon name="arrowr" size={12} /></button></Row>
  </Group>;
}

function Profiles() {
  useOrg();
  return <Group title="Project operating profiles" foot="Read-only. Profiles are policy files; only you change them (D-007).">
    {PROJECTS.map((p) => <Row key={p.key} icon={<span className="set-ico" style={{ ["--c" as string]: p.color }}><Icon name={p.icon} size={16} /></span>} label={p.name}
      hint={`${p.merge}${p.releaseWindows ? ` · release windows ${p.releaseWindows.join(", ")}` : ""}`}>
      <Pill tone={p.health === "paused" ? "idle" : p.health === "onboarding" ? "info" : "violet"}>{p.modeLabel}</Pill></Row>)}
  </Group>;
}

function Workers() {
  return <Group title="Worker nodes" foot="Nothing is scheduled on a node by the prototype. Enrolling or revoking a node needs Developer Unlock.">
    {WORKERS.map((w) => <Row key={w.id} icon={<span className="set-ico" style={{ ["--c" as string]: w.status === "online" ? "#2fe08c" : "#8a95b0" }}><Icon name={w.id === "laptop" ? "laptop" : "server"} size={16} /></span>}
      label={<>{w.label} <span className="muted small">{w.agentNode ? "agent node" : "not an agent node"}</span></>} hint={w.note}>
      <span className="set-caps">{w.caps.map((c) => <span key={c}>{WORKER_CAP_LABEL[c] ?? c}</span>)}</span>
      <Pill tone={w.status === "online" ? "ok" : "idle"} dot>{w.status === "online" ? "Online · demo" : "Unknown"}</Pill></Row>)}
  </Group>;
}

function DemoControls() {
  const f = useStore(feed);
  const slow = useStore(slowDemo);
  return <Group title="Demo controls" foot="These change only this browser's demo data.">
    <Row label="Simulate a status-feed outage" hint="Agents show Unknown or Stale, never Working"><Toggle label="Simulate a status-feed outage" checked={f.outage} onChange={() => setOutage(!f.outage)} /></Row>
    <Row label="Simulate slow loading" hint="Shows the loading skeletons on every page change"><Toggle label="Simulate slow loading" checked={slow} onChange={() => setSlowDemo(!slow)} /></Row>
    <Row label="Reset demo data" hint="Removes agents, projects and drafts you created"><button type="button" className="btn btn-sm" onClick={() => { resetShared(); location.reload(); }}>Reset</button></Row>
  </Group>;
}

function MoreDest() {
  return <Group title="Screens of the current app" foot="They keep their routes and deep links, and get the new look one by one during the migration. The prototype opens nothing here.">
    {DEST.map(([r, t, s, ic]) => <Row key={r} icon={<span className="set-ico" style={{ ["--c" as string]: "#8f9bff" }}><Icon name={ic as IconId} size={16} /></span>} label={t} hint={s}><code className="muted small">#/{r}</code></Row>)}
  </Group>;
}

const KEYS: [string, string][] = [
  ["Ctrl K  ·  ⌘ K", "Search projects, agents, tasks and conversations"],
  ["Alt Shift O  ·  ⌥ ⇧ O", "Pop the current tab out to a new window"],
  ["Alt Shift R  ·  ⌥ ⇧ R", "Bring it back to this window"],
  ["Right-click  ·  Shift F10", "Actions for a tab, agent, conversation, row or node"],
  ["↑ ↓  ·  Enter", "Move through menus and search results"],
  ["Esc", "Close a menu, popover, dialog or full-screen topology"],
];
function Help() {
  return <>
    <Group title="Keyboard">{KEYS.map(([k, d]) => <Row key={k} label={d}><kbd className="set-kbd">{k}</kbd></Row>)}</Group>
    <Group title="Where things are">
      <Row label="Waiting for you" hint="Decisions, plus the bell"><button type="button" className="link" onClick={() => go("decisions")}>Decisions <Icon name="arrowr" size={12} /></button></Row>
      <Row label="Every component and token" hint="Buttons, menus, tooltips, loading, dialogs"><button type="button" className="link" onClick={() => go("design")}>Design system <Icon name="arrowr" size={12} /></button></Row>
      <Row label="The whole company as a graph" hint="Full screen with the ⤢ button"><button type="button" className="link" onClick={() => go("topology")}>Operations Topology <Icon name="arrowr" size={12} /></button></Row>
    </Group>
  </>;
}

const BODY: Record<string, () => React.JSX.Element> = { general: General, appearance: Appearance, notifications: Notifications, windows: Windows, security: Security,
  connections: Connections, projects: Profiles, workers: Workers, demo: DemoControls, more: MoreDest, help: Help };

export function Settings() {
  const route = useRoute();
  const cur = SETTINGS_SECTIONS.find((s) => s.id === route.id) ?? SETTINGS_SECTIONS[0];
  const Body = BODY[cur.id];
  // Phones show the section list first, then one section with a back link (desktop always shows both).
  const mode = route.id ? "is-detail" : "is-index";
  return <div className={cx("page page-settings", mode)}>
    <div className="page-head"><div><h1>Settings</h1><p>Preferences, connections and the rules each project runs under. Mock data; nothing here connects anywhere.</p></div><Demo label="Prototype" /></div>
    <div className="set-wrap">
      <nav className="set-nav" aria-label="Settings sections">{SETTINGS_SECTIONS.map((s) => <a key={s.id} href={`#/settings/${s.id}`} className={cx("set-nav-i", s.id === cur.id && "is-current")} aria-current={s.id === cur.id ? "page" : undefined}>
        <span className="set-ico" style={{ ["--c" as string]: s.tint }}><Icon name={s.icon} size={15} /></span><span>{s.label}</span></a>)}</nav>
      <div className="set-body" key={cur.id}>
        <a className="set-back" href="#/settings" aria-label="Back to Settings"><Icon name="chevl" size={16} /> Settings</a>
        <header className="set-h"><span className="set-ico is-lg" style={{ ["--c" as string]: cur.tint }}><Icon name={cur.icon} size={22} /></span><div><h2>{cur.label}</h2><p className="muted">{cur.sub}</p></div></header>
        <Body />
      </div>
    </div>
  </div>;
}
