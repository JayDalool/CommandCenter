// Jay's menu at the right of HQ's top bar (the prototype's "me" menu): Approvals and Budgets, Settings, the theme and
// the way back to Classic. Each item is an address or a preference that Classic already has; nothing here signs out,
// approves or changes the server.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { prefs, usePrefs, type Prefs } from "../../lib/prefs";
import { href } from "../../lib/router";
import { buildDecisions } from "../data";
import "./jaymenu.css";
import { Icon } from "./icons";

const THEMES: [Prefs["theme"], string][] = [["dark", "Dark"], ["light", "Light"], ["system", "Match system"]];

export function JayMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const theme = usePrefs((p) => p.theme);
  const approvals = useSelector(app.store, (d) => buildDecisions(d).summary.approvals);

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLElement>("[role^=menuitem]")?.focus();
    const away = (e: Event) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  const close = (refocus = false) => { setOpen(false); if (refocus) btn.current?.focus(); };
  // The usual menu keys: arrows and Home/End move, Escape closes and returns to the button, Tab leaves.
  const keys = (e: KeyboardEvent) => {
    const items = [...(menu.current?.querySelectorAll<HTMLElement>("[role^=menuitem]") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const to = e.key === "ArrowDown" ? (at + 1) % items.length : e.key === "ArrowUp" ? (at - 1 + items.length) % items.length
      : e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : -1;
    if (to >= 0) { e.preventDefault(); items[to]?.focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "Tab") setOpen(false);
  };
  const toClassic = () => {
    setOpen(false);
    prefs.patch({ ui: "classic" });
    requestAnimationFrame(() => document.querySelector<HTMLElement>(".rail .rail-foot button")?.focus());
  };

  return <div className="hq-me" ref={box}>
    <button ref={btn} type="button" className="hq-me-btn" aria-haspopup="menu" aria-expanded={open} aria-label="Jay's menu"
      title="Approvals, budgets, settings and theme" onClick={() => setOpen(!open)}>
      <span className="hq-av" aria-hidden>J</span><span className="hq-me-name">Jay</span>
      <Icon name="chevdown" size={14} /></button>
    {open && <div className="hq-me-pop">
      <div className="hq-me-head"><span className="hq-av is-lg" aria-hidden>J</span><span><b>Jay</b><small>Owner</small></span></div>
      <div role="menu" aria-label="Jay's menu" ref={menu} onKeyDown={keys}>
        <a role="menuitem" href={href("approvals")} onClick={() => close()}><Icon name="check" size={16} />Approvals
          {approvals > 0 && <span className="hq-me-count">{approvals} waiting</span>}</a>
        <a role="menuitem" href={href("budgets")} onClick={() => close()}><Icon name="receipt" size={16} />Budgets</a>
        <div role="separator" />
        <a role="menuitem" href={href("settings")} onClick={() => close()}><Icon name="gear" size={16} />Settings
          <kbd className="hq-me-key">6</kbd></a>
        <a role="menuitem" href={href("settings", null, { tab: "connection" })} onClick={() => close()}><Icon name="lock" size={16} />
          Connection and sign-out</a>
        <div role="separator" />
        <div role="group" aria-labelledby="hq-me-theme">
          <span className="hq-me-label" id="hq-me-theme">Theme</span>
          {THEMES.map(([v, label]) => <button key={v} type="button" role="menuitemradio" aria-checked={theme === v}
            onClick={() => prefs.patch({ theme: v })}><span className="hq-me-radio" aria-hidden />{label}</button>)}
        </div>
        <div role="separator" />
        <button type="button" role="menuitem" onClick={toClassic}><Icon name="returnin" size={16} />Back to Classic</button>
      </div>
    </div>}
  </div>;
}
