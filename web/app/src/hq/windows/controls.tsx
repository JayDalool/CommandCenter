// The main window's side of HQ's pop-outs (manager.ts has the rules): the Pop out button with its monitor choice, the
// placeholder shown where a popped page was, and the watch that keeps the list of open pop-outs current.
import { useEffect, useRef, useState } from "react";
import "./windows.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import type { Route } from "../../lib/router";
import { hqPageFor } from "../pages";
import { hqTitle } from "../frame/nav";
import { Icon } from "../frame/icons";
import { HEARTBEAT_MS, canPickScreen, focusView, isPopView, listScreens, placeOn, popOut, popped, returnView, screenPermission,
  send, sweep, whereIs, type PopView, type ScreenInfo } from "./manager";

/** The view this address shows, when it is one that can pop out: an HQ page itself, not one task or one project. */
export function viewOfRoute(r: Pick<Route, "screen" | "id" | "params">): PopView | null {
  const s = r.screen === "overview" ? "dashboard" : r.screen;
  return !r.id && isPopView(s) && hqPageFor(r) ? s : null;
}

/** Keep this window's list of open pop-outs current: ask once, then drop any that stop answering. */
export function useWindowsWatch() {
  useEffect(() => {
    send({ t: "who" });
    const t = setInterval(() => sweep(), HEARTBEAT_MS);
    return () => clearInterval(t);
  }, []);
}

export function usePopped(v: PopView | null) {
  return useSelector(popped, (p) => (v ? p[v] ?? null : null));
}
export function usePoppedViews(): PopView[] {
  return useSelector(popped, (p) => Object.keys(p).filter(isPopView).sort().join(",")).split(",").filter(isPopView);
}

function open(v: PopView, s?: ScreenInfo) {
  if (!popOut(v, s ? placeOn(s) : null)) app.toast("The browser blocked the new window. Allow pop-ups for Command Center and try again.", "bad");
}

/** Pop out, with a choice of monitor where the browser can place windows (Edge and Chrome, once Jay allows it). */
export function PopOutButton({ v }: { v: PopView }) {
  const [menu, setMenu] = useState(false);
  const [screens, setScreens] = useState<ScreenInfo[] | null>(null);
  const [perm, setPerm] = useState<Awaited<ReturnType<typeof screenPermission>>>("unsupported");
  const box = useRef<HTMLDivElement>(null);
  const name = hqTitle(v, null, null);
  useEffect(() => {
    if (!menu) return;
    let live = true;
    void screenPermission().then(async (p) => {
      if (!live) return;
      setPerm(p);
      if (p === "granted") { const s = await listScreens(); if (live) setScreens(s); }
    });
    const away = (e: Event) => { if (!box.current?.contains(e.target as Node)) setMenu(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { live = false; document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [menu]);
  // Alt+Shift+O pops the current page out to a new window, as in the prototype.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && e.code === "KeyO") { e.preventDefault(); open(v); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [v]);
  const pick = (s?: ScreenInfo) => { setMenu(false); open(v, s); };
  const ask = async () => { const s = await listScreens(); setScreens(s); setPerm(s ? "granted" : await screenPermission()); };

  return <div className="hq-pop" ref={box}>
    <button type="button" className="btn is-quiet is-sm hq-pop-btn" aria-haspopup="menu" aria-expanded={menu}
      aria-keyshortcuts="Alt+Shift+O" title={`Open ${name} in its own window (Alt+Shift+O)`} onClick={() => setMenu(!menu)}>
      <Icon name="popout" size={15} />Pop out</button>
    {menu && <div className="hq-pop-menu" role="menu" aria-label={`Open ${name} in its own window`}>
      <button type="button" role="menuitem" onClick={() => pick()}><Icon name="popout" size={15} />New window
        <small>Opens beside this one, or where it was last. Drag it to any monitor.</small></button>
      {canPickScreen() && (screens
        ? screens.map((s) => <button key={`${s.left},${s.top}`} type="button" role="menuitem" onClick={() => pick(s)}>
            <Icon name="monitor" size={15} />On {s.label}{s.current ? " (this screen)" : s.primary ? " (main screen)" : ""}
            <small>{s.width} × {s.height}</small></button>)
        : perm === "denied" ? <p className="hq-pop-note">Choosing a monitor is blocked for this site. Allow “Window management” in the
            browser's site settings to choose one here.</p>
        : <button type="button" role="menuitem" onClick={() => void ask()}><Icon name="monitor" size={15} />Choose a monitor…
            <small>The browser asks once to let Command Center place windows on your displays.</small></button>)}
    </div>}
  </div>;
}

/** Where a popped page was: says where it went, with Focus window and Return here. */
export function PoppedPlaceholder({ v }: { v: PopView }) {
  const p = usePopped(v);
  const [hint, setHint] = useState<string | null>(null);
  const name = hqTitle(v, null, null);
  return <div className="hq-detached" role="region" aria-label={`${name} is open in its own window`}>
    <div className="hq-detached-card">
      <span className="hq-detached-ico"><Icon name="popout" size={26} /></span>
      <h3>{name} is open in its own window</h3>
      <p>It shows the same live data{p ? `, ${whereIs(p.place)}` : ""}. This copy is paused so the page has one owner.</p>
      <div className="hq-detached-actions">
        <button type="button" className="hq-btn is-primary" onClick={() => {
          if (focusView(v) === "asked") setHint(p ? `If it did not come forward, it is ${whereIs(p.place)}. Look for “${name} · Command Center” in the taskbar.`
            : `Look for “${name} · Command Center” in the taskbar.`);
        }}><Icon name="popout" size={15} />Focus window</button>
        <button type="button" className="hq-btn" onClick={() => returnView(v)}><Icon name="returnin" size={15} />Return here</button>
      </div>
      {hint && <p className="hq-detached-hint" role="status">{hint}</p>}
    </div>
  </div>;
}
