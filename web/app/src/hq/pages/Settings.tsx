// Settings (roadmap P1.3), laid out as in the approved prototype: eleven sections in a list on the left, grouped rows on
// the right. On a phone the list comes first, then one section with a link back. Every row is a real preference, a
// fact about something real, or one of Classic's settings panels shown as it is (Desktop app, Task migration preview,
// Policies, Decisions, Workers, Audit, Usage). The prototype's Demo controls have no place in production, where nothing
// is demo data, so that slot holds Audit and usage. Classic's section ids still work: each opens the HQ section that
// holds it, scrolled to that part.
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import "./office.css";
import "./settings.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { href } from "../../lib/router";
import { commands, prefs, usePrefs, type Prefs } from "../../lib/prefs";
import { isRemembered } from "../../api/auth";
import { jayQueue } from "../../tickets/model";
import { lockDevMode, unlockDialogOpen, useDevActive } from "../../components/DevMode";
import { Command } from "../../components/ui";
import { Policies } from "../../components/Policies";
import { Decisions as DecisionRecords } from "../../components/Decisions";
import { Workers as WorkerNodes } from "../../components/Workers";
import { Audit } from "../../components/Audit";
import { Usage } from "../../components/Usage";
import { DIAGNOSTICS, DesktopApp, ImportPreviewView } from "../../screens/Settings";
import { Icon } from "../frame/icons";
import { HQ_NAV, HQ_NAV_LOW, hqTitle } from "../frame/nav";
import { canPickScreen, focusView, forgetPlaces, isPopView, listScreens, popOut, popped, returnView, savedPlace, screenPermission,
  POP_VIEWS, type PopView, type ScreenInfo } from "../windows/manager";
import { usePageNav } from "./route";
import { Pill, cx, plural } from "./ui";
import { ApiError } from "../../api/client";
import type { NotifySettings, NotifyState } from "../../api/types";

// ---------- building blocks ----------

/** A titled group of rows, like an inset list in System Settings. */
function Group({ id, title, foot, children }: { id?: string; title?: string; foot?: ReactNode; children: ReactNode }) {
  const h = useId();
  return <section className="hq-set-group" id={id && `set-${id}`} aria-labelledby={title ? h : undefined}>
    {title && <h4 id={h}>{title}</h4>}
    <div className="hq-set-rows">{children}</div>
    {foot && <p className="hq-set-foot">{foot}</p>}
  </section>;
}

function Row({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children?: ReactNode }) {
  return <div className="hq-set-row">
    <div className="hq-set-row-t"><b>{label}</b>{hint && <small>{hint}</small>}</div>
    {children != null && <div className="hq-set-row-v">{children}</div>}
  </div>;
}

/** One of Classic's settings panels, unchanged markup; inside HQ it takes HQ's colours (frame/classic-bridge.css). */
function Classic({ id, children }: { id: string; children: ReactNode }) {
  return <div className="hq-set-classic" id={`set-${id}`}>{children}</div>;
}

function Seg<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: [T, string][]; onChange: (v: T) => void;
}) {
  return <div className="hq-seg" role="group" aria-label={label}>{options.map(([v, l]) =>
    <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}>{l}</button>)}</div>;
}

function useMedia(q: string): boolean {
  const [on, setOn] = useState(() => typeof matchMedia === "function" && matchMedia(q).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const m = matchMedia(q);
    const change = () => setOn(m.matches);
    m.addEventListener?.("change", change);
    return () => m.removeEventListener?.("change", change);
  }, [q]);
  return on;
}

// ---------- the sections ----------

function General() {
  const p = usePrefs((x) => x);
  return <>
    <Group title="Interface" foot="HQ preview is the new design, rolled out page by page. Every page and control works the same, and you can switch back at any time.">
      <Row label="Interface"><Seg label="Interface" value={p.ui} onChange={(v) => prefs.patch({ ui: v })}
        options={[["classic", "Classic"], ["hq", "HQ preview"]]} /></Row>
      <Row label="SSH host" hint="The alias used in the commands you copy">
        <input className="hq-input" value={p.sshHost} spellCheck={false} aria-label="SSH host alias used in copied commands"
          onChange={(e) => prefs.patch({ sshHost: e.target.value.replace(/[^A-Za-z0-9@._-]/g, "") })} /></Row>
    </Group>
    <Classic id="import"><ImportPreviewView /></Classic>
  </>;
}

const THEMES: [Prefs["theme"], string, string][] = [
  ["dark", "Dark", "The default"], ["light", "Light", "Same layout and colours"], ["system", "Match system", "Follows Windows or macOS"]];

/** A small window drawn in each theme. Arrow keys move between the three, as in any radio group. */
function ThemePicker() {
  const theme = usePrefs((p) => p.theme);
  const box = useRef<HTMLDivElement>(null);
  const keys = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + THEMES.length) % THEMES.length;
    prefs.patch({ theme: THEMES[n][0] });
    box.current?.querySelectorAll<HTMLElement>("[role=radio]")[n]?.focus();
  };
  const win = (t: "dark" | "light") => <span className={`hq-theme-win is-${t}`}><i className="s" /><i className="b" /><i className="c" /><i className="a" /></span>;
  return <div className="hq-theme" role="radiogroup" aria-label="Theme" ref={box}>
    {THEMES.map(([v, label, sub], i) => <button key={v} type="button" role="radio" aria-checked={theme === v}
      tabIndex={theme === v ? 0 : -1} onClick={() => prefs.patch({ theme: v })} onKeyDown={(e) => keys(e, i)}>
      <span className="hq-theme-thumb" aria-hidden>{v === "system" ? <>{win("dark")}{win("light")}</> : win(v)}</span>
      <b>{label}</b><small>{sub}</small></button>)}
  </div>;
}

function Appearance() {
  const p = usePrefs((x) => x);
  const dark = useMedia("(prefers-color-scheme: dark)");
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  return <>
    <Group title="Theme" foot="Every open window follows the choice, pop-outs included.">
      <div className="hq-set-row is-block"><ThemePicker /></div>
      {p.theme === "system" && <Row label="Showing now" hint="From your operating system">{dark ? "Dark" : "Light"}</Row>}
    </Group>
    <Group title="Density">
      <Row label="Table rows" hint="In the Classic screens and panels"><Seg label="Row density" value={p.density}
        onChange={(v) => prefs.patch({ density: v })} options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} /></Row>
    </Group>
    <Group title="Motion" foot="Command Center has no motion setting of its own. Turn on Reduce motion in the operating system (on Windows, Animation effects off) and every window follows.">
      <Row label="Animations" hint="Follows your operating system">{reduced ? "Reduced" : "On"}</Row>
    </Group>
  </>;
}

function Notifications() {
  const waiting = useSelector(app.store, (d) => jayQueue(d.state, undefined, d.tickets).length);
  return <>
    <Group title="What notifies you" foot="Only what needs you. Ordinary commits, passing tests and routine stage moves never notify. The list is the Decisions queue, so the bell and Decisions always agree.">
      <Row label="Questions waiting for you" />
      <Row label="A gate to decide" hint="Plan, merge acceptance, UI review, live deploy" />
      <Row label="A blocked task or agent" />
      <Row label="A major failure" />
      <Row label="Waiting now"><a className="hq-link" href={href("needs")}>{waiting ? `${plural(waiting, "item")} in Decisions` : "Nothing"}</a></Row>
    </Group>
    <Group title="In Command Center">
      <Row label="The bell" hint="In the top bar"><Pill tone="ok">On</Pill></Row>
      <Row label="A tone and a short message" hint="Once per new item, while Command Center is open">
        <Pill tone="ok">On</Pill></Row>
    </Group>
    <SlackAndPhone />
  </>;
}

type NotifyLoad = { s: "loading" } | { s: "ok"; d: NotifyState } | { s: "off"; why: string };

const notifyOff = (e: unknown) => e instanceof ApiError && e.status === 404 ? "This ccd has no Slack or phone alerts yet."
  : e instanceof ApiError && e.status === 503 ? "Alerts are not set up in this ccd." : "Could not read the alert settings.";

/** Slack and ntfy, from ccd's notifier (GET /api/notify). Changing anything is Jay's and needs Developer Unlock; ccd
 *  checks both. Tokens and the ntfy address never reach the browser, only whether each is set up. */
function SlackAndPhone() {
  const active = useDevActive();
  const [st, setSt] = useState<NotifyLoad>({ s: "loading" });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  useEffect(() => {
    let live = true;
    app.api.notify().then((d) => { if (live) setSt({ s: "ok", d }); }).catch((e: unknown) => { if (live) setSt({ s: "off", why: notifyOff(e) }); });
    return () => { live = false; };
  }, []);
  if (st.s !== "ok") {
    return <Group title="Slack and phone">
      <Row label={st.s === "loading" ? "Reading the alert settings…" : st.why} />
    </Group>;
  }
  const { settings: v, status, configured: c } = st.d;
  const run = (job: () => Promise<NotifyState | { status: NotifyState["status"] }>, done?: string) => {
    if (!active) { unlockDialogOpen(); return; }
    setBusy(true); setNote(null);
    job().then((r) => {
      setSt((was) => was.s !== "ok" ? was : { s: "ok", d: "settings" in r ? r : { ...was.d, status: r.status } });
      if (done) setNote({ tone: "ok", text: done });
    }).catch((e: unknown) => setNote({ tone: "bad", text: e instanceof Error ? e.message : String(e) }))
      .finally(() => setBusy(false));
  };
  const save = (patch: Partial<NotifySettings>) => run(() => app.api.setNotify(patch));
  const slackWhy = !c.slackTokens ? (c.slackTokensError ?? "Tokens not set up on jay-server (slack.env)")
    : !c.jayMemberId ? "Your Slack member ID is not in config.json" : `Connection: ${status.slack}`;
  return <Group id="slack" title="Slack and phone" foot={active ? undefined
    : <>Changing these needs Developer Unlock. <button type="button" className="hq-link" onClick={unlockDialogOpen}>Unlock…</button></>}>
    <Row label="Slack" hint={slackWhy}>
      <Seg label="Slack" value={v.slack ? "on" : "off"} options={[["off", "Off"], ["on", "On"]]}
        onChange={(x) => x === (v.slack ? "on" : "off") || save({ slack: x === "on" })} /></Row>
    <Row label="Phone alerts (ntfy)" hint={c.ntfy ? `Connection: ${status.ntfy}` : "No ntfy topic in config.json"}>
      <Seg label="Phone alerts" value={v.ntfy ? "on" : "off"} options={[["off", "Off"], ["on", "On"]]}
        onChange={(x) => x === (v.ntfy ? "on" : "off") || save({ ntfy: x === "on" })} /></Row>
    <Row label="Your Slack replies" hint={v.replyScope === "answers" ? "Answer agents' questions. Approvals open Command Center."
      : "Answers, plus clearing a blocker or accepting a UI review. Never a plan, merge or deploy."}>
      <Seg label="Your Slack replies" value={v.replyScope} options={[["answers", "Answers only"], ["answers_low_risk", "Answers and low-risk"]]}
        onChange={(x) => x === v.replyScope || save({ replyScope: x })} /></Row>
    <Row label="Quiet hours" hint={`${v.timezone}${st.d.quietNow ? " · quiet now" : ""}${st.d.held ? ` · ${plural(st.d.held, "alert")} held` : ""}`}>
      <TimeBox label="Quiet hours start" value={v.quietStart} onSave={(t) => save({ quietStart: t })} />
      <span aria-hidden>to</span>
      <TimeBox label="Quiet hours end" value={v.quietEnd} onSave={(t) => save({ quietEnd: t })} /></Row>
    <Row label="Daily summaries" hint="An owner's summary and a technical summary, in Slack">
      <TimeBox label="Daily summaries at" value={v.summaryAt} onSave={(t) => save({ summaryAt: t })} /></Row>
    <Row label="Test" hint={status.lastError ? `Last error: ${status.lastError}`
      : status.lastSentAt ? `Last sent ${new Date(status.lastSentAt * 1000).toLocaleString()}` : "Nothing sent yet"}>
      <button type="button" className="hq-btn" disabled={busy || !(v.slack || v.ntfy)}
        onClick={() => run(() => app.api.notifyTest(), "Test sent. Check Slack and your phone.")}>Send a test</button></Row>
    {note && <p className={cx("hq-note", note.tone === "ok" ? "t-ok" : "t-bad")} role="status">{note.text}</p>}
  </Group>;
}

/** A 24-hour time that saves when it loses focus, and only a complete, changed value. */
function TimeBox({ label, value, onSave }: { label: string; value: string; onSave: (t: string) => void }) {
  const [t, setT] = useState(value);
  useEffect(() => setT(value), [value]);
  return <input type="time" className="hq-input hq-time" aria-label={label} value={t} onChange={(e) => setT(e.target.value)}
    onBlur={() => { if (/^\d\d:\d\d$/.test(t) && t !== value) onSave(t); else setT(value); }} />;
}

type Perm = Awaited<ReturnType<typeof screenPermission>>;
const POP_HERE: PopView[] = ["dashboard", "needs", "projects"];

function Windows() {
  const out = useSelector(popped, (p) => Object.keys(p).filter(isPopView).sort().join(",")).split(",").filter(isPopView);
  const [perm, setPerm] = useState<Perm | null>(null);
  const [screens, setScreens] = useState<ScreenInfo[] | null>(null);
  const [saved, setSaved] = useState(() => POP_VIEWS.flatMap((v) => { const p = savedPlace(v); return p ? [{ v, p }] : []; }));
  useEffect(() => {
    let live = true;
    void screenPermission().then(async (p) => {
      if (!live) return;
      setPerm(p);
      if (p === "granted") { const s = await listScreens(); if (live) setScreens(s); }
    });
    return () => { live = false; };
  }, []);
  const ask = async () => { const s = await listScreens(); setScreens(s); setPerm(s ? "granted" : await screenPermission()); };
  const open = (v: PopView) => {
    if (!popOut(v)) app.toast("The browser blocked the new window. Allow pop-ups for Command Center and try again.", "bad");
  };
  const name = (v: PopView) => hqTitle(v, null, null);

  return <>
    <Group title="In their own windows" foot="Closing a window brings its page back here. A page shows in one window at a time.">
      {out.length ? out.map((v) => <Row key={v} label={name(v)}>
        <button type="button" className="hq-btn" onClick={() => focusView(v)}>Focus</button>
        <button type="button" className="hq-btn" onClick={() => returnView(v)}>Return here</button></Row>)
        : <Row label="No page is in its own window" hint="Use Pop out, or Alt+Shift+O" />}
    </Group>
    <Group title="Monitors">
      {perm === null ? <Row label="Open a pop-out on a chosen monitor" hint="Checking this browser…" />
        : perm === "unsupported" || !canPickScreen()
          ? <Row label="Open a pop-out on a chosen monitor" hint="Needs Edge or Chrome. Here, drag the window to a monitor.">
            <Pill tone="idle">Not in this browser</Pill></Row>
          : perm === "denied"
            ? <Row label="Open a pop-out on a chosen monitor" hint="Allow “Window management” in this site's browser settings">
              <Pill tone="bad">Blocked</Pill></Row>
            : perm === "prompt" || !screens
              ? <Row label="Open a pop-out on a chosen monitor" hint="The browser asks once">
                <button type="button" className="hq-btn" onClick={() => void ask()}>Allow…</button></Row>
              : <>
                <Row label="Open a pop-out on a chosen monitor" hint="Pop out lists these monitors."><Pill tone="ok">Allowed</Pill></Row>
                {screens.map((s) => <Row key={`${s.left},${s.top}`} label={`${s.label}${s.current ? " (this screen)" : s.primary ? " (main screen)" : ""}`}
                  hint={`${s.width} × ${s.height}`} />)}
              </>}
    </Group>
    <Group title="Remembered places" foot="A pop-out opens where you last left it. The places are kept in this browser only.">
      {saved.length ? saved.map(({ v, p }) => <Row key={v} label={name(v)} hint={`${p.w} × ${p.h} at ${p.x}, ${p.y}`} />)
        : <Row label="None yet" hint="Pop-outs open beside this window" />}
      {saved.length > 0 && <Row label="Forget them" hint="Pop-outs open beside this window again.">
        <button type="button" className="hq-btn" onClick={() => { forgetPlaces(); setSaved([]); app.toast("Forgot the remembered window places"); }}>
          Forget</button></Row>}
    </Group>
    <Group title="Open a page in its own window">
      {POP_HERE.map((v) => <Row key={v} label={name(v)}>{out.includes(v)
        ? <button type="button" className="hq-btn" onClick={() => focusView(v)}>Focus</button>
        : <button type="button" className="hq-btn" onClick={() => open(v)}><Icon name="popout" size={14} />Pop out</button>}</Row>)}
    </Group>
  </>;
}

function Security() {
  const active = useDevActive();
  return <>
    <Group id="unlock" title="Developer Unlock" foot={<>The ccd token lets this browser read and steer metadata. Terminals, Claude, answers to
      Claude's questions, and saving or uploading repository files and attachments also need Developer Unlock: a separate
      token kept in <code>~/.config/command-center/developer.token</code> on jay-server. The token itself is never stored,
      only the session id, in this browser session.</>}>
      <Row label="Status" hint={active ? "Writes to project files are allowed in this app session." : "Browsing works. Saving and uploading need Developer Unlock."}>
        <Pill tone={active ? "warn" : "idle"}>{active ? "Unlocked" : "Locked"}</Pill>
        {active ? <button type="button" className="hq-btn" onClick={() => void lockDevMode()}>Lock</button>
          : <button type="button" className="hq-btn" onClick={unlockDialogOpen}>Unlock…</button>}</Row>
      <Row label="Ends" hint="On lock, closing the browser, 2 idle hours, 8 hours in all, or a ccd restart. Reloads and pop-outs keep it." />
    </Group>
    <Group title="Records">
      <Row label="Approvals" hint="Merges and deploys waiting for you, each bound to what it approves">
        <a className="hq-link" href={href("approvals")}>Open Approvals</a></Row>
      <Row label="Audit" hint="Every write that reached ccd, and who claimed it">
        <a className="hq-link" href={href("settings", null, { tab: "audit" })}>Open Audit</a></Row>
    </Group>
  </>;
}

function Connections() {
  const st = useSelector(app.store, (d) => d.state);
  const host = usePrefs((p) => p.sshHost);
  return <>
    <Group id="browser" title="This browser">
      <Row label="ccd" hint="Command Center's server">{st ? <code>v{st.version} · {location.host}</code> : "Not connected"}</Row>
      <Row label="Token" hint={isRemembered() ? "Remembered in this browser profile" : "Kept for this tab only"}>
        <button type="button" className="hq-btn" onClick={() => app.logout()}>Forget token and disconnect</button></Row>
    </Group>
    <Group title="Services" foot="ccd is reached through the SSH tunnel and is never exposed publicly.">
      <Row label="Slack and phone alerts" hint="Set up and switched in Notifications">
        <a className="hq-link" href={href("settings", null, { tab: "notifications" })}>Notifications</a></Row>
      <Row label="Billing provider" hint="For Revenue: read-only, once you choose a provider">
        <Pill tone="idle">Not connected</Pill><a className="hq-link" href={href("revenue")}>Revenue</a></Row>
      <Row label="Model usage" hint="Read from the agents' own session logs on jay-server">
        <a className="hq-link" href={href("budgets")}>Budgets</a></Row>
    </Group>
    <Classic id="desktop"><DesktopApp /></Classic>
    <Group title="From Windows, by hand" foot={<>Then open <code>http://127.0.0.1:7777</code> and paste the token. The desktop app does all three for you.</>}>
      <div className="hq-set-row is-block"><small>1. The tunnel. Leave it running.</small><Command cmd={commands.tunnel(host)} /></div>
      <div className="hq-set-row is-block"><small>2. The token to the clipboard, once.</small><Command cmd={commands.token(host)} /></div>
    </Group>
  </>;
}

function Profiles() {
  return <><Classic id="policies"><Policies /></Classic><Classic id="decisions"><DecisionRecords /></Classic></>;
}

function Workers() {
  return <Classic id="workers"><WorkerNodes /></Classic>;
}

function AuditUsage() {
  return <><Classic id="audit"><Audit /></Classic><Classic id="usage"><Usage /></Classic></>;
}

const MORE_HINT: Record<string, string> = {
  projects: "Every project and how the work connects", development: "Branch, commits, pull request, CI, review, merge and deploy for each task",
  agents: "Each project's lead and members", server: "jay-server: herdr, ccd, Claude, containers and worktrees",
  alerts: "Active alerts, and which you have acknowledged", prs: "Pull requests across the projects", workspaces: "herdr's panes, drawn as a map",
};

function More() {
  return <Group title="Screens outside the sidebar" foot="Every old link still works.">
    {DIAGNOSTICS.map(([id]) => <Row key={id} label={hqTitle(id, null, null)} hint={MORE_HINT[id]}>
      <a className="hq-link" href={href(id)}>Open</a></Row>)}
    <Row label="Approvals" hint="Also in your menu"><a className="hq-link" href={href("approvals")}>Open</a></Row>
    <Row label="Budgets" hint="Also in your menu"><a className="hq-link" href={href("budgets")}>Open</a></Row>
  </Group>;
}

/** Keys pressed together, as "Ctrl Shift F". */
const Keys = ({ k }: { k: string }) => <span className="hq-keys">{k.split(" ").map((x, i) => <kbd key={i}>{x}</kbd>)}</span>;
const DIGITS = [...HQ_NAV, ...HQ_NAV_LOW].filter((i) => i.key).sort((a, b) => Number(a.key === "0") - Number(b.key === "0") || a.key!.localeCompare(b.key!));

function Help() {
  return <>
    <Group title="Anywhere" foot="Single keys work when you are not typing in a field or a terminal.">
      <Row label="Command palette: projects, tasks, pull requests and Workspace commands" hint="Not inside a terminal, where Ctrl+K is the shell's">
        <Keys k="Ctrl K" /></Row>
      <Row label="New task"><Keys k="N" /></Row>
      <Row label="Go to a page" hint={DIGITS.map((i) => `${i.key} ${i.label}`).join(" · ")}>
        <span className="hq-keys"><kbd>1</kbd>to<kbd>6</kbd>,<kbd>0</kbd></span></Row>
      <Row label="Search in a list"><Keys k="/" /></Row>
      <Row label="Close a menu, dialog or the palette"><Keys k="Esc" /></Row>
      <Row label="Pop the page out to its own window" hint="On a page with Pop out at the top"><Keys k="Alt Shift O" /></Row>
      <Row label="Collapse the sidebar to icons" hint="Windows wider than 1440 px"><Keys k={"Ctrl \\"} /></Row>
      <Row label="Workspace focus: the Workspace without the sidebar" hint="On the Workspace"><Keys k="Ctrl ." /></Row>
    </Group>
    <Group title="Workspace" foot="Inside a terminal, Ctrl+K, Ctrl+P, Ctrl+S, Ctrl+B and Ctrl+Shift+F go to the shell.">
      <Row label="Go to file"><Keys k="Ctrl P" /></Row>
      <Row label="Search the files"><Keys k="Ctrl Shift F" /></Row>
      <Row label="Save" hint="Needs Developer Unlock"><Keys k="Ctrl S" /></Row>
      <Row label="Show or hide the sidebar"><Keys k="Ctrl B" /></Row>
      <Row label="Show or hide the terminal panel"><Keys k="Ctrl `" /></Row>
      <Row label="Open the project terminal"><Keys k="Ctrl Shift `" /></Row>
      <Row label="Maximise or restore the dock"><Keys k="Ctrl Shift Enter" /></Row>
    </Group>
    <Group title="Terminals">
      <Row label="Paste" hint="Nothing runs until you press Enter in a shell"><Keys k="Ctrl V" /></Row>
      <Row label="Copy the selection" hint="With nothing selected, Ctrl+C interrupts"><Keys k="Ctrl C" /></Row>
    </Group>
  </>;
}

// ---------- the page ----------

interface Section { id: string; label: string; icon: string; sub: string; Body: () => React.JSX.Element }
export const SECTIONS: Section[] = [
  { id: "general", label: "General", icon: "gear", sub: "Interface, SSH host and the task migration preview", Body: General },
  { id: "appearance", label: "Appearance", icon: "layers", sub: "Theme, density and motion", Body: Appearance },
  { id: "notifications", label: "Notifications", icon: "bell", sub: "What reaches you, and where", Body: Notifications },
  { id: "windows", label: "Windows & monitors", icon: "monitor", sub: "Pop-out windows and where they open", Body: Windows },
  { id: "security", label: "Security", icon: "lock", sub: "Developer Unlock", Body: Security },
  { id: "connections", label: "Connections", icon: "plug", sub: "ccd, the desktop app, Slack and billing", Body: Connections },
  { id: "profiles", label: "Operating profiles", icon: "shield", sub: "Each project's rules, and your decisions", Body: Profiles },
  { id: "workers", label: "Workers", icon: "server", sub: "Machines that can run agent work", Body: Workers },
  { id: "audit", label: "Audit and usage", icon: "list", sub: "Who changed what, and what the models used", Body: AuditUsage },
  { id: "more", label: "Other destinations", icon: "more", sub: "Screens outside the sidebar", Body: More },
  { id: "help", label: "Help & shortcuts", icon: "help", sub: "The keyboard", Body: Help },
];

/** Classic's section ids (screens/Settings.tsx): the HQ section that holds each, and the part to scroll to. */
const FROM_CLASSIC: Record<string, [string, string]> = {
  desktop: ["connections", "desktop"], developer: ["security", "unlock"], connection: ["connections", "browser"],
  policies: ["profiles", "policies"], decisions: ["profiles", "decisions"], usage: ["audit", "usage"],
  import: ["general", "import"], diagnostics: ["more", ""],
};

/** The section an address asks for, or null for none (the list on a phone, General on a wider screen). */
export function settingsSection(tab: string | null): { id: string | null; part: string | null } {
  if (!tab) return { id: null, part: null };
  const c = FROM_CLASSIC[tab];
  if (c) return { id: c[0], part: c[1] || null };
  return { id: SECTIONS.some((s) => s.id === tab) ? tab : "general", part: null };
}

export function Settings() {
  const { route } = usePageNav();
  const { id, part } = settingsSection(route.params.get("tab"));
  const cur = SECTIONS.find((s) => s.id === id) ?? SECTIONS[0];
  const Body = cur.Body;
  const nav = useRef<HTMLElement>(null);
  const head = useRef<HTMLHeadingElement>(null);
  const was = useRef(id);
  useEffect(() => {
    if (part) document.getElementById(`set-${part}`)?.scrollIntoView?.({ block: "start" });
    const prev = was.current;
    was.current = id;
    if (prev === id) return;
    // On a phone the list and a section take turns: focus moves to what replaced the link that was used.
    const listHidden = !nav.current || nav.current.getClientRects().length === 0;
    if (id && listHidden) head.current?.focus();
    else if (!id && prev) nav.current?.querySelector<HTMLElement>(`[data-section="${prev}"]`)?.focus();
  }, [id, part]);

  return <div className={cx("hq-page hq-settings", id ? "is-detail" : "is-index")}>
    <header className="hq-hero hq-set-hero"><div><h2>Settings</h2>
      <p>Preferences, connections and the rules each project runs under.</p></div></header>
    <div className="hq-set">
      <nav className="hq-set-nav" aria-label="Settings sections" ref={nav}><ul>{SECTIONS.map((s) => <li key={s.id}>
        <a data-section={s.id} href={href("settings", null, { tab: s.id })} aria-current={s.id === cur.id ? "page" : undefined}>
          <Icon name={s.icon} size={17} /><span><b>{s.label}</b><small>{s.sub}</small></span>
          <span className="hq-set-go"><Icon name="chevron" size={15} /></span></a></li>)}</ul></nav>
      <section className="hq-set-body" aria-labelledby="hq-set-title">
        <a className="hq-set-back" href={href("settings")} aria-label="Back to Settings"><Icon name="chevl" size={16} />Settings</a>
        <header className="hq-set-head"><span className="hq-set-ico"><Icon name={cur.icon} size={20} /></span>
          <div><h3 id="hq-set-title" ref={head} tabIndex={-1}>{cur.label}</h3><p>{cur.sub}</p></div></header>
        <Body key={cur.id} />
      </section>
    </div>
  </div>;
}
