// Small form and dialog building blocks shared by the onboarding wizards and the agent inspector.
import { useEffect, useId, useRef, type ReactNode } from "react";
import { GRANT_LABEL, type Grant } from "../data/catalog";
import { Icon } from "./Icon";
import { cx } from "./ui";

export function Field({ label, hint, error, children, wide, optional }: { label: ReactNode; hint?: ReactNode; error?: string; children: (id: string) => ReactNode; wide?: boolean; optional?: boolean }) {
  const id = useId();
  return <div className={cx("fld", wide && "is-wide", error && "has-err")}>
    <label htmlFor={id}>{label}{optional && <small className="muted"> optional</small>}</label>
    {children(id)}
    {error ? <p className="fld-err" role="alert"><Icon name="info" size={13} /> {error}</p> : hint ? <p className="fld-hint">{hint}</p> : null}
  </div>;
}

export function Seg<T extends string>({ value, options, onChange, label, size }: { value: T; options: { id: T; label: ReactNode; disabled?: boolean; title?: string }[]; onChange: (v: T) => void; label: string; size?: "sm" }) {
  return <div className={cx("seg", "seg-ctl", size === "sm" && "is-sm")} role="radiogroup" aria-label={label}>
    {options.map((o) => <button key={o.id} type="button" role="radio" aria-checked={value === o.id} disabled={o.disabled} title={o.title} onClick={() => onChange(o.id)}>{o.label}</button>)}
  </div>;
}

export function Chips({ value, options, onChange, label }: { value: string[]; options: { id: string; label: ReactNode; locked?: string; hint?: string }[]; onChange: (v: string[]) => void; label: string }) {
  return <div className="chips" role="group" aria-label={label}>
    {options.map((o) => { const on = value.includes(o.id);
      return <button key={o.id} type="button" className={cx("chip", on && "is-on", o.locked && "is-locked")} aria-pressed={on} disabled={!!o.locked} title={o.locked ?? o.hint}
        onClick={() => onChange(on ? value.filter((x) => x !== o.id) : [...value, o.id])}>{o.locked ? <Icon name="lock" size={12} /> : on ? <Icon name="tick" size={12} /> : null}{o.label}</button>; })}
  </div>;
}

/** Allowed / Requires approval / Denied. Options above `ceiling` are locked and say why. */
export function GrantPick({ value, onChange, ceiling, label, limit }: { value: Grant; onChange: (g: Grant) => void; ceiling: Grant; label: string; limit?: string }) {
  const R: Record<Grant, number> = { deny: 0, approval: 1, allow: 2 };
  return <div className="grant-pick" role="radiogroup" aria-label={label}>
    {(["allow", "approval", "deny"] as Grant[]).map((g) => { const locked = R[g] > R[ceiling];
      return <button key={g} type="button" role="radio" aria-checked={value === g} className={cx(`g-${g}`, value === g && "is-on")} disabled={locked}
        title={locked ? limit ?? "Above CommandCenter's limit" : GRANT_LABEL[g]} onClick={() => onChange(g)}>
        {locked && <Icon name="lock" size={11} />}{g === "allow" ? "Allow" : g === "approval" ? "Approval" : "Deny"}</button>; })}
  </div>;
}

export function GrantBadge({ g, children }: { g: Grant; children?: ReactNode }) {
  return <span className={`grant g-${g}`}><Icon name={g === "allow" ? "tick" : g === "approval" ? "shield" : "x"} size={11} />{children ?? GRANT_LABEL[g]}</span>;
}

/** A modal dialog. Focus moves in; Escape closes; the backdrop shades the window behind it. */
export function Modal({ title, children, onClose, footer, tone, wide }: { title: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; tone?: "bad" | "warn"; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("[data-autofocus], button, input, select, textarea")?.focus();
    return () => { prev?.focus?.(); };
  }, []);
  return <div className="modal-veil" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div ref={ref} className={cx("modal", tone && `is-${tone}`, wide && "is-wide")} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}>
      <header className="modal-h"><h2>{title}</h2><button type="button" className="icon-btn" aria-label="Close dialog" onClick={onClose}><Icon name="x" size={16} /></button></header>
      <div className="modal-b">{children}</div>
      {footer && <footer className="modal-f">{footer}</footer>}
    </div>
  </div>;
}

export function Money({ v, onChange, label, id }: { v: number; onChange: (n: number) => void; label: string; id: string }) {
  return <span className="money"><span aria-hidden>$</span><input id={id} type="number" min={0} step={1} inputMode="decimal" value={Number.isFinite(v) ? v : ""} aria-label={label}
    onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} /></span>;
}
