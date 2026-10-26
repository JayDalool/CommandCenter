import { useEffect, useState, type ReactNode } from "react";
import { WIN_ID } from "../lib/shared";
import { useStore } from "../lib/store";
import { Icon } from "../components/Icon";
import { focusWindow, owners, popOut, returnHere } from "./manager";
import { viewById } from "./views";

export function useOwner(id: string) {
  const all = useStore(owners);
  return all[id] ?? null;
}

/** True when another window owns this view (so this window must not render it live). */
export function useElsewhere(id: string): boolean {
  const o = useOwner(id);
  return !!o && o.win !== WIN_ID;
}

/** Renders `children` unless the view is open in another window; then a shaded placeholder. */
export function Detachable({ id, children, className }: { id: string; children: ReactNode; className?: string }) {
  const elsewhere = useElsewhere(id);
  return elsewhere ? <DetachedPlaceholder id={id} className={className} /> : <>{children}</>;
}

export function DetachedPlaceholder({ id, className }: { id: string; className?: string }) {
  const o = useOwner(id);
  const def = viewById(id);
  const [hint, setHint] = useState(false);
  const pending = o?.win === null;
  const closing = o?.state === "closing";
  return <div className={`detached ${className ?? ""}`} role="region" aria-label={`${def?.title ?? id} is open in another window`} data-testid={`placeholder-${id}`}>
    <div className="detached-card">
      <span className="detached-ico"><Icon name="popout" size={26} /></span>
      <h3>{pending ? "Opening in a new window…" : closing ? "Its window is closing…" : "This view is open in another window"}</h3>
      <p><b>{def?.title}</b> is live in its own window. You can drag that window to any monitor. Nothing is running twice; this copy is paused so there is one owner.</p>
      <div className="detached-actions">
        <button type="button" className="btn btn-primary" onClick={() => { if (!focusWindow(id)) setHint(true); }}><Icon name="eye" size={16} /> Focus window</button>
        <button type="button" className="btn" onClick={() => returnHere(id)}><Icon name="returnin" size={16} /> Return here</button>
      </div>
      {hint && <p className="detached-hint" role="status">Your browser would not bring that window forward. Look for “CommandCenter · {def?.title}” in your taskbar, or use Return here.</p>}
    </div>
  </div>;
}

/** The ↗ control. `compact` for tab strips and panel headers. */
export function PopButton({ id, compact, label }: { id: string; compact?: boolean; label?: string }) {
  const o = useOwner(id);
  const def = viewById(id);
  if (!def) return null;
  return <button type="button" className={`popbtn ${compact ? "is-compact" : ""} ${o ? "is-out" : ""}`}
    title={o ? `${def.title} is open in another window — focus it` : `Pop out “${def.title}” into its own window (Alt+Shift+O)`}
    aria-label={o ? `Focus the window for ${def.title}` : `Pop out ${def.title}`}
    onClick={(e) => { e.stopPropagation(); e.preventDefault(); popOut(id); }} data-testid={`pop-${id}`}>
    <Icon name="popout" size={compact ? 14 : 16} />{label && <span>{label}</span>}
  </button>;
}

/** Window title for a pop-out (so Jay can find it in the taskbar). */
export function useDocTitle(t: string) { useEffect(() => { document.title = t; }, [t]); }
