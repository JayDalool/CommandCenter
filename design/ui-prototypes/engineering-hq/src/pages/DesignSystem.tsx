// DESIGN SYSTEM — the tokens and components every page uses, on one page, so a reviewer can check hover,
// focus, menus, tooltips, popovers, motion and loading states in one place. Nothing here is live data.
import { useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { Avatar, Demo, Panel, Pill } from "../components/ui";
import { Field, Modal, Seg } from "../components/form";
import { Popover, Skel, openMenu, useContextMenu, type MenuItem } from "../components/overlay";
import { notify } from "../windows/manager";
import { PopButton } from "../windows/Detachable";
import { motionPref, setMotionPref } from "../lib/motion";
import { useStore } from "../lib/store";
import { PRESENCE_LABEL, type Presence } from "../data/seed";

const RADII = [["--r-2xs", "5"], ["--r-xs", "7"], ["--r-sm", "9"], ["--r-md", "10"], ["--r", "12"], ["--r-lg", "14"], ["--r-xl", "18"], ["--r-pill", "999"]];
const ELEV = ["--e1", "--e2", "--e3"];
const TYPE = [["--fs-3xl", "Page title", 30], ["--fs-2xl", "Section", 22], ["--fs-xl", "Panel title", 18], ["--fs-lg", "Emphasis", 16], ["--fs-base", "Body", 14], ["--fs-sm", "Secondary", 12.5], ["--fs-xs", "Caption", 11.5]] as const;
const COLORS = ["--bg", "--panel", "--raise", "--line-2", "--accent", "--accent-2", "--ok", "--warn", "--bad", "--info", "--violet"];
const PRES: Presence[] = ["working", "reviewing", "waiting", "blocked", "idle", "paused", "unknown", "notstarted"];
const TONE: Record<string, string> = { working: "ok", reviewing: "violet", waiting: "warn", blocked: "bad", idle: "idle", paused: "idle", unknown: "idle", notstarted: "idle" };

const demoMenu = (): MenuItem[] => [
  { label: "Open", icon: "eye", run: () => notify("Open (demo)") },
  { label: "Open in new window", icon: "popout", hint: "⌥⇧O", run: () => notify("Pop out (demo)") },
  { label: "Message", icon: "message", run: () => notify("Message (demo)") },
  { sep: true },
  { label: "Pause", icon: "clock", run: () => notify("Pause (demo)", "warn") },
  { label: "Offboard…", icon: "x", danger: true, run: () => notify("Offboard (demo)", "bad") },
  { label: "Delete", icon: "lock", disabled: true },
];

export function DesignSystem() {
  const [seg, setSeg] = useState<"day" | "week" | "month">("week");
  const [tab, setTab] = useState("overview");
  const [modal, setModal] = useState(false);
  const [pop, setPop] = useState(false);
  const [text, setText] = useState("Nova");
  const [sel, setSel] = useState("sonnet");
  const popRef = useRef<HTMLButtonElement>(null);
  const motion = useStore(motionPref);
  const ctx = useContextMenu(demoMenu, "Demo card");
  return <div className="page page-design">
    <div className="page-head"><div><h1>Design System</h1><p>Tokens and components shared by every page and pop-out window. Dark navy and purple, refined with native-app detail.</p></div>
      <div className="row-gap"><Demo label="Reference" /><PopButton id="page:design" /></div></div>

    <div className="ds-grid">
      <Panel icon="layers" title="Colour" sub="Surfaces and accents (unchanged palette)">
        <div className="ds-swatches">{COLORS.map((c) => <span key={c} className="ds-sw"><i style={{ background: `var(${c})` }} /><code>{c}</code></span>)}</div>
      </Panel>
      <Panel icon="doc" title="Type scale" sub="Inter, tight display tracking">
        <ul className="ds-type">{TYPE.map(([t, l, px]) => <li key={t}><span style={{ fontSize: `var(${t})` }}>{l}</span><code>{t} · {px}px</code></li>)}</ul>
      </Panel>
      <Panel icon="cube" title="Radius" sub="Small controls → windows">
        <div className="ds-radii">{RADII.map(([t, v]) => <span key={t}><i style={{ borderRadius: `var(${t})` }} /><code>{t}</code><small className="muted">{v}px</small></span>)}</div>
      </Panel>
      <Panel icon="server" title="Elevation" sub="Cards, popovers, modals">
        <div className="ds-elev">{ELEV.map((e) => <span key={e} style={{ boxShadow: `var(${e})` }}><code>{e}</code></span>)}</div>
      </Panel>

      <Panel icon="target" title="Buttons" sub="Hover lifts, press settles, focus ring">
        <div className="row-gap"><button type="button" className="btn btn-primary"><Icon name="plus" size={15} /> Primary</button><button type="button" className="btn">Secondary</button>
          <button type="button" className="btn btn-outline">Outline</button><button type="button" className="btn btn-danger">Danger</button><button type="button" className="btn" disabled>Disabled</button>
          <button type="button" className="btn btn-sm">Small</button><button type="button" className="icon-btn" aria-label="Settings" title="Settings"><Icon name="gear" size={16} /></button></div>
      </Panel>
      <Panel icon="edit" title="Inputs" sub="Text, select, segmented, toggle">
        <div className="ds-form">
          <Field label="Name">{(id) => <input id={id} value={text} onChange={(e) => setText(e.target.value)} />}</Field>
          <Field label="Model">{(id) => <select id={id} value={sel} onChange={(e) => setSel(e.target.value)}><option value="opus">Opus</option><option value="sonnet">Sonnet</option><option value="haiku">Haiku</option></select>}</Field>
          <Field label="Range">{() => <Seg label="Range" value={seg} onChange={setSeg} options={[{ id: "day", label: "Day" }, { id: "week", label: "Week" }, { id: "month", label: "Month" }]} />}</Field>
          <label className="toggle-row"><input type="checkbox" checked={motion === "reduce"} onChange={(e) => setMotionPref(e.target.checked ? "reduce" : "system")} /><span><b>Reduce motion</b><small className="muted">Also follows your system setting</small></span></label>
        </div>
      </Panel>

      <Panel icon="list" title="Tabs" sub="Segmented and underline">
        <div className="seg" role="tablist" aria-label="Demo tabs">{["overview", "activity", "settings"].map((t) => <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}</div>
        <div className="seg seg-under ds-under" role="tablist" aria-label="Demo underline tabs">{["overview", "activity", "settings"].map((t) => <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}</div>
        <p className="muted ds-tabpane" key={tab}>{tab === "overview" ? "Panels fade in when the tab changes." : tab === "activity" ? "Respecting reduced motion, the change is instant." : "Selection slides between segments."}</p>
      </Panel>
      <Panel icon="more" title="Menus, tooltips, popovers" sub="Right-click the card · hover the buttons">
        <div className="ds-card" tabIndex={0} {...ctx}><Avatar id="nova" size={36} /><span><b>Nova</b><small className="muted">Right-click, or Shift+F10, for actions</small></span></div>
        <div className="row-gap"><button type="button" className="btn btn-sm" onClick={(e) => openMenu(e.currentTarget, demoMenu(), "Actions")}>Actions <Icon name="chevdown" size={13} /></button>
          <button type="button" className="btn btn-sm" title="Tooltips appear after a short pause and follow focus">Hover for tooltip</button>
          <button type="button" ref={popRef} className="btn btn-sm" aria-expanded={pop} onClick={() => setPop((p) => !p)}>Popover</button>
          <Popover open={pop} onClose={() => setPop(false)} anchor={popRef} label="Popover demo" align="start"><header className="pop-h"><b>Popover</b></header><p className="muted pop-p">Anchored, dismisses on Escape or outside click.</p></Popover></div>
      </Panel>

      <Panel icon="pulse" title="Status" sub="Circular indicators, no glow unless it matters">
        <div className="ds-pres">{PRES.map((p) => <span key={p} className={`pres t-${TONE[p]}`}><i /><b>{PRESENCE_LABEL[p]}</b></span>)}</div>
        <div className="row-gap"><Pill tone="ok" dot>Healthy</Pill><Pill tone="warn" dot>Needs input</Pill><Pill tone="bad">Blocker</Pill><Pill tone="violet">Review</Pill><Pill>Idle</Pill></div>
        <div className="row-gap">{["claude", "nova", "atlas", "pixel", "orion", "iris"].map((a) => <Avatar key={a} id={a} size={32} />)}<Avatar id="jay" size={32} /></div>
      </Panel>
      <Panel icon="clock" title="Loading" sub="Skeletons shimmer (static under reduced motion)">
        <div className="ds-skel">{[0, 1, 2].map((i) => <div key={i} className="skel-row"><Skel w={36} h={36} r="50%" /><span><Skel w="70%" /><Skel w="40%" h={10} /></span></div>)}</div>
        <p className="muted small">See them on every page with “Simulate slow loading” in Jay’s menu (top right).</p>
      </Panel>
      <Panel icon="bell" title="Toasts and dialogs" sub="Slide in, dismissible">
        <div className="row-gap"><button type="button" className="btn btn-sm" onClick={() => notify("Saved to Drafts.")}>Success toast</button>
          <button type="button" className="btn btn-sm" onClick={() => notify("Status feed is stale.", "warn")}>Warning toast</button>
          <button type="button" className="btn btn-sm" onClick={() => setModal(true)}>Open dialog</button></div>
      </Panel>
    </div>
    {modal && <Modal title="Example dialog" onClose={() => setModal(false)} footer={<><button type="button" className="btn" data-autofocus onClick={() => setModal(false)}>Cancel</button><button type="button" className="btn btn-primary" onClick={() => setModal(false)}>Continue</button></>}>
      <p>Dialogs scale in from 98% over a soft veil. Escape or Cancel closes them.</p></Modal>}
  </div>;
}
