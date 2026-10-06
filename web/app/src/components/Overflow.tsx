// The ⋯ menu: secondary and recovery actions live here, out of the primary row.
import { useEffect, useRef, useState } from "react";

export interface OverflowItem {
  label: string;
  /** A link (e.g. the commandcenter:// native terminal) — or an action. */
  href?: string;
  onSelect?: () => void;
  danger?: boolean;
  hidden?: boolean;
}

export function Overflow({ label, items }: { label: string; items: OverflowItem[] }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const shown = items.filter((i) => !i.hidden);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!list.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    list.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  if (!shown.length) return null;
  const close = () => { setOpen(false); btn.current?.focus(); };
  return <span className="ovf">
    <button ref={btn} type="button" className="btn is-quiet is-sm ovf-btn" aria-label={label} aria-haspopup="menu" aria-expanded={open}
      onClick={() => setOpen(!open)}>⋯</button>
    {open && <ul ref={list} className="ctx ovf-menu" role="menu" aria-label={label}
      onKeyDown={(e) => {
        const els = Array.from(list.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
        const i = els.indexOf(document.activeElement as HTMLElement);
        if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); close(); return; }
        const to = e.key === "ArrowDown" ? (i + 1) % els.length : e.key === "ArrowUp" ? (i - 1 + els.length) % els.length : -1;
        if (to >= 0) { e.preventDefault(); els[to]?.focus(); }
      }}>
      {shown.map((it) => <li key={it.label} role="none">
        {it.href
          ? <a role="menuitem" className="ctx-item" href={it.href} onClick={() => { it.onSelect?.(); setOpen(false); }}>{it.label}</a>
          : <button type="button" role="menuitem" className={`ctx-item${it.danger ? " is-danger" : ""}`}
            onClick={() => { close(); it.onSelect?.(); }}>{it.label}</button>}
      </li>)}
    </ul>}
  </span>;
}
