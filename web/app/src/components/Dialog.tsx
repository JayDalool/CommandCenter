// Modal dialog with a focus trap, Esc to close and focus restored on close.
import { useEffect, useRef, type ReactNode } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  // Callers pass inline closures; keep the latest in a ref so the trap is set up
  // once per open and never steals focus back on a parent re-render.
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>("[data-autofocus]") ?? el?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close.current(); return; }
      if (e.key !== "Tab" || !el) return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    };
    el?.addEventListener("keydown", onKey);
    return () => { el?.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, []);
  return ref;
}

export function Dialog({ title, onClose, children, footer, className = "dialog" }: { title: ReactNode; onClose: () => void;
  children: ReactNode; footer?: ReactNode; className?: string }) {
  const ref = useFocusTrap(onClose);
  return <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className={className} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} ref={ref}>
      <div className="dialog-head"><h2 className="panel-title">{title}</h2>
        <button type="button" className="btn is-quiet is-sm" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close">Esc</button></div>
      <div className="dialog-body">{children}</div>
      {footer && <div className="dialog-foot">{footer}</div>}
    </div>
  </div>;
}

/** In-app replacement for window.confirm: Cancel (focused first) and Esc leave things alone. */
export function ConfirmDialog({ title, children, confirmLabel = "OK", danger, onConfirm, onClose }: { title: ReactNode; children: ReactNode;
  confirmLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void }) {
  return <Dialog title={title} onClose={onClose}>
    <p className="text2">{children}</p>
    <div className="row" style={{ marginTop: 10 }}>
      <button type="button" className={`btn${danger ? " is-danger" : " is-jay"}`} onClick={() => { onClose(); onConfirm(); }}>{confirmLabel}</button>
      <button type="button" className="btn is-quiet" data-autofocus onClick={onClose}>Cancel</button>
    </div>
  </Dialog>;
}
