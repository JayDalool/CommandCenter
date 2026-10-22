// Floating UI for the whole prototype: context menus, tooltips, popovers, skeletons and the sliding thumb of
// segmented controls. No dependencies: one menu and one tooltip layer per window, positioned with plain DOM maths.
// Everything here also works in pop-out windows, because each window mounts its own layers (App.tsx).
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent as RKey, type MouseEvent as RMouse, type ReactNode } from "react";
import { Store, useStore } from "../lib/store";
import { Icon } from "./Icon";
import { cx } from "./ui";

/* ---------------- context menus ---------------- */

export type MenuItem = { sep: true } | { label: string; icon?: string; hint?: string; run?: () => void; danger?: boolean; disabled?: boolean; checked?: boolean };
interface MenuState { x: number; y: number; items: MenuItem[]; label: string; opener: HTMLElement | null; id: number }
const menu = new Store<MenuState | null>(null);
let seq = 0;

/** Open the menu at a point (right-click) or under an element (keyboard, menu buttons). */
export function openMenu(at: { x: number; y: number } | HTMLElement, items: MenuItem[], label = "Actions") {
  const opener = at instanceof HTMLElement ? at : (document.activeElement as HTMLElement | null);
  let x: number, y: number;
  if (at instanceof HTMLElement) { const r = at.getBoundingClientRect(); x = r.left; y = r.bottom + 4; } else ({ x, y } = at);
  menu.set({ x, y, items, label, opener, id: ++seq });
}
export const closeMenu = () => menu.set(null);
export const menuOpen = () => !!menu.get();

/** Right-click, the context-menu key and Shift+F10 all open the same menu. */
export function useContextMenu(items: () => MenuItem[], label?: string) {
  return {
    onContextMenu: (e: RMouse<HTMLElement>) => { e.preventDefault(); e.stopPropagation(); openMenu({ x: e.clientX, y: e.clientY }, items(), label); },
    onKeyDown: (e: RKey<HTMLElement>) => { if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); e.stopPropagation(); openMenu(e.currentTarget, items(), label); } },
  };
}

export function MenuLayer() {
  const m = useStore(menu);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!m || !ref.current) { setPos(null); return; }
    const r = ref.current.getBoundingClientRect(), pad = 8;
    const left = Math.max(pad, Math.min(m.x, innerWidth - r.width - pad));
    const top = m.y + r.height + pad > innerHeight ? Math.max(pad, m.y - r.height - 4) : m.y;
    setPos({ left, top });
  }, [m?.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  // Focus the first item once the menu is placed (a hidden element can't take focus).
  useEffect(() => { if (pos) ref.current?.querySelector<HTMLElement>('[role^="menuitem"]:not([aria-disabled="true"])')?.focus({ preventScroll: true }); }, [m?.id, !!pos]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!m) return;
    const away = (e: Event) => { if (!ref.current?.contains(e.target as Node)) closeMenu(); };
    // A scroll already under way when the menu opened (scroll-into-view, momentum) must not close it.
    const opened = performance.now();
    const off = (e?: Event) => { if (e?.type === "scroll" && (performance.now() - opened < 250 || ref.current?.contains(e.target as Node))) return; closeMenu(); };
    document.addEventListener("pointerdown", away, true);
    window.addEventListener("blur", off); window.addEventListener("resize", off); document.addEventListener("scroll", off, true);
    return () => { document.removeEventListener("pointerdown", away, true); window.removeEventListener("blur", off); window.removeEventListener("resize", off); document.removeEventListener("scroll", off, true); };
  }, [m]);
  if (!m) return null;
  const done = (restore = true) => { const o = m.opener; closeMenu(); if (restore && o?.isConnected) o.focus({ preventScroll: true }); };
  const key = (e: RKey<HTMLDivElement>) => {
    const items = [...(ref.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([aria-disabled="true"])') ?? [])];
    const i = items.indexOf(document.activeElement as HTMLElement);
    const to = (n: number) => { e.preventDefault(); items[(n + items.length) % items.length]?.focus(); };
    if (e.key === "ArrowDown") to(i + 1); else if (e.key === "ArrowUp") to(i - 1);
    else if (e.key === "Home") to(0); else if (e.key === "End") to(items.length - 1);
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(); }
    else if (e.key === "Tab") { e.preventDefault(); done(); }
  };
  return <div ref={ref} className={cx("menu", pos && "is-placed")} role="menu" aria-label={m.label} onKeyDown={key}
    style={pos ? { left: pos.left, top: pos.top } : { left: m.x, top: m.y, visibility: "hidden" }} onContextMenu={(e) => e.preventDefault()}>
    {m.items.map((it, i) => "sep" in it ? <div key={`s${i}`} className="menu-sep" role="separator" />
      : <button key={it.label} type="button" role={it.checked === undefined ? "menuitem" : "menuitemcheckbox"} aria-checked={it.checked}
        aria-disabled={it.disabled || undefined} className={cx("menu-item", it.danger && "is-danger")} tabIndex={-1}
        onClick={() => { if (it.disabled) return; done(false); it.run?.(); }}>
        <span className="menu-ico">{it.checked ? <Icon name="tick" size={14} stroke={2.4} /> : it.icon ? <Icon name={it.icon} size={15} /> : null}</span>
        <span className="menu-lbl">{it.label}</span>{it.hint && <kbd className="menu-hint">{it.hint}</kbd>}</button>)}
  </div>;
}

/* ---------------- tooltips ----------------
 * One layer per window shows a styled tooltip for any element with `title` or `data-tip`. While it shows, the
 * native `title` is parked in `data-tip-title` (so the browser doesn't draw a second one) and put back after. */

const TIP_SEL = "[title],[data-tip],[data-tip-title]";
export function TipLayer() {
  const [tip, setTip] = useState<{ text: string; r: DOMRect; id: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<CSSProperties | null>(null);
  useEffect(() => {
    let cur: HTMLElement | null = null, timer = 0, shown = false, n = 0;
    const park = (el: HTMLElement) => { const t = el.getAttribute("title"); if (t !== null) { el.setAttribute("data-tip-title", t); el.removeAttribute("title"); } };
    const restore = (el: HTMLElement) => { const t = el.getAttribute("data-tip-title"); if (t !== null) { el.setAttribute("title", t); el.removeAttribute("data-tip-title"); } };
    const hide = () => { window.clearTimeout(timer); if (cur) restore(cur); cur = null; if (shown) { shown = false; setTip(null); } };
    const show = (el: HTMLElement, delay: number) => {
      if (el === cur) return;
      const warm = shown; hide();
      const text = el.getAttribute("data-tip") ?? el.getAttribute("title") ?? el.getAttribute("data-tip-title");
      if (!text || el.closest(".menu")) return;
      park(el); cur = el;
      timer = window.setTimeout(() => { if (cur === el && el.isConnected) { shown = true; setTip({ text, r: el.getBoundingClientRect(), id: ++n }); } }, warm ? 0 : delay);
    };
    const over = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const el = (e.target as Element | null)?.closest?.(TIP_SEL) as HTMLElement | null;
      if (el) show(el, 520); else hide();
    };
    const focus = (e: FocusEvent) => { const el = e.target as HTMLElement; if (el?.matches?.(":focus-visible") && el.matches(TIP_SEL)) show(el, 300); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
    document.addEventListener("pointerover", over);
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("focusin", focus);
    document.addEventListener("focusout", hide);
    document.addEventListener("keydown", key, true);
    document.addEventListener("scroll", hide, true);
    window.addEventListener("blur", hide);
    document.documentElement.addEventListener("pointerleave", hide);
    return () => {
      hide();
      document.removeEventListener("pointerover", over); document.removeEventListener("pointerdown", hide, true);
      document.removeEventListener("focusin", focus); document.removeEventListener("focusout", hide);
      document.removeEventListener("keydown", key, true); document.removeEventListener("scroll", hide, true);
      window.removeEventListener("blur", hide); document.documentElement.removeEventListener("pointerleave", hide);
    };
  }, []);
  useLayoutEffect(() => {
    if (!tip || !ref.current) { setPos(null); return; }
    const t = ref.current.getBoundingClientRect(), pad = 8, { r } = tip;
    const below = r.bottom + 8 + t.height < innerHeight - pad;
    const left = Math.max(pad, Math.min(r.left + r.width / 2 - t.width / 2, innerWidth - t.width - pad));
    setPos({ left, top: below ? r.bottom + 8 : r.top - t.height - 8, ["--tip-from" as string]: below ? "-3px" : "3px" });
  }, [tip?.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!tip) return null;
  return <div ref={ref} className={cx("tip", pos && "is-placed")} role="tooltip" style={pos ?? { left: 0, top: 0, visibility: "hidden" }}>{tip.text}</div>;
}

/* ---------------- popovers ---------------- */

/** A panel anchored to a button. Closes on Escape, outside click, or the button again. */
export function Popover({ open, onClose, anchor, children, label, align = "end", className }: {
  open: boolean; onClose: () => void; anchor: React.RefObject<HTMLElement | null>; children: ReactNode; label: string; align?: "start" | "end"; className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<CSSProperties | null>(null);
  useLayoutEffect(() => {
    if (!open || !anchor.current || !ref.current) { setPos(null); return; }
    const a = anchor.current.getBoundingClientRect(), p = ref.current.getBoundingClientRect(), pad = 8;
    const left = align === "end" ? Math.max(pad, a.right - p.width) : Math.min(a.left, innerWidth - p.width - pad);
    setPos({ left, top: a.bottom + 8 });
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (open && pos) ref.current?.querySelector<HTMLElement>("[data-autofocus], button, a, input")?.focus({ preventScroll: true }); }, [open, !!pos]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => { const t = e.target as Node; if (!ref.current?.contains(t) && !anchor.current?.contains(t)) onClose(); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { onClose(); anchor.current?.focus(); } };
    document.addEventListener("pointerdown", away, true); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", esc); };
  }, [open, onClose, anchor]);
  if (!open) return null;
  return <div ref={ref} className={cx("popover", pos && "is-placed", className)} role="dialog" aria-label={label}
    style={pos ?? { left: 0, top: 0, visibility: "hidden" }}>{children}</div>;
}

/* ---------------- skeletons ---------------- */

export function Skel({ w, h = 12, r, className, style }: { w?: number | string; h?: number; r?: number | string; className?: string; style?: CSSProperties }) {
  return <span className={cx("skel", className)} aria-hidden style={{ width: w, height: h, borderRadius: r, ...style }} />;
}
/** A neutral page placeholder shown while a view loads. Announces itself once to screen readers. */
export function PageSkeleton({ label = "Loading" }: { label?: string }) {
  return <div className="page page-skel" role="status" aria-label={label} aria-busy="true">
    <div className="skel-head"><Skel w={280} h={30} r={8} /><Skel w={420} h={14} /></div>
    <div className="skel-kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="skel-card"><Skel w={46} h={46} r={12} /><span><Skel w={90} /><Skel w={60} h={22} /></span></div>)}</div>
    <div className="skel-grid"><div className="skel-card tall">{[80, 64, 72, 56, 68].map((w, i) => <Skel key={i} w={`${w}%`} h={14} />)}</div>
      <div className="skel-card tall">{[0, 1, 2, 3].map((i) => <div key={i} className="skel-row"><Skel w={36} h={36} r="50%" /><span><Skel w="70%" /><Skel w="45%" h={10} /></span></div>)}</div></div>
  </div>;
}

/* ---------------- segmented controls ----------------
 * Every `.seg` gets a sliding thumb under its selected segment. One observer per window keeps the thumb's
 * position in CSS variables; CSS animates it (and stops animating under reduced motion). */
export function useSegThumbs() {
  useEffect(() => {
    let raf = 0;
    const place = (seg: HTMLElement) => {
      const sel = seg.querySelector<HTMLElement>(':scope > [aria-selected="true"], :scope > [aria-checked="true"], :scope > .is-on');
      if (!sel || !sel.offsetWidth) { seg.style.setProperty("--th-o", "0"); return; }
      const first = !seg.classList.contains("has-thumb");
      seg.style.setProperty("--th-x", `${sel.offsetLeft}px`); seg.style.setProperty("--th-y", `${sel.offsetTop}px`);
      seg.style.setProperty("--th-w", `${sel.offsetWidth}px`); seg.style.setProperty("--th-h", `${sel.offsetHeight}px`);
      seg.style.setProperty("--th-o", "1");
      if (first) requestAnimationFrame(() => seg.classList.add("has-thumb"));
    };
    const run = () => { raf = 0; document.querySelectorAll<HTMLElement>(".seg:not(.seg-under)").forEach(place); };
    const soon = () => { if (!raf) raf = requestAnimationFrame(run); };
    const mo = new MutationObserver(soon);
    mo.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["aria-selected", "aria-checked", "class"] });
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(soon) : null;
    ro?.observe(document.body);
    window.addEventListener("resize", soon);
    void document.fonts?.ready.then(soon);
    run();
    return () => { mo.disconnect(); ro?.disconnect(); window.removeEventListener("resize", soon); if (raf) cancelAnimationFrame(raf); };
  }, []);
}

/* ---------------- demo: simulated loading ----------------
 * Loading states only appear when something loads. The prototype loads nothing, so a reviewer can switch on
 * "Simulate slow loading" (Settings & more, or ?slow in the URL) to see the skeletons on every navigation. */
export const slowDemo = new Store<boolean>((() => { try { return new URLSearchParams(location.search).has("slow") || localStorage.getItem("hq.demo.slow") === "1"; } catch { return false; } })());
export function setSlowDemo(on: boolean) { slowDemo.set(on); try { localStorage.setItem("hq.demo.slow", on ? "1" : "0"); } catch { /* ignore */ } }
export function useSimulatedLoad(key: string, ms = 750) {
  const slow = useStore(slowDemo);
  const [ready, setReady] = useState(slow ? "" : key);
  useEffect(() => { if (!slow) { setReady(key); return; } const t = setTimeout(() => setReady(key), ms); return () => clearTimeout(t); }, [key, slow, ms]);
  return !slow || ready === key;
}
