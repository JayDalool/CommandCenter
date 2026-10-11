// NOTIFICATIONS (spec §10): the top-right bell. Only what needs Jay — questions waiting, a gate to
// decide (plan, merge acceptance, UI review, live deploy), a blocked task or agent, a major failure.
// Never ordinary commits, test passes or routine stage moves.
//
// The list IS the one Needs Jay queue (ccd's state.needs + blocked agents), so it can never disagree
// with the dashboard. Something new in it plays a short tone and shows a toast; clicking takes Jay to
// the task, its room and the exact question or action. "Seen" is remembered in this browser only.
import { useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { jayQueue, type JayItem } from "../tickets/model";
import { jayHref, jayWords, projectName } from "../lib/control";
import { Ago } from "./ui";

const SEEN_KEY = "cc.seen";

function loadSeen(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]") as string[]); } catch { return new Set(); }
}
function saveSeen(s: Set<string>) {
  try { localStorage.setItem(SEEN_KEY, JSON.stringify([...s].slice(-300))); } catch { /* convenience only */ }
}

/** One soft two-note chime. No asset to load; silent when the browser has not allowed audio yet. */
export function chime() {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    [660, 880].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f;
      const t = ctx.currentTime + i * 0.14;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.08, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      o.connect(g).connect(ctx.destination);
      o.start(t); o.stop(t + 0.25);
    });
    setTimeout(() => void ctx.close(), 800);
  } catch { /* no audio */ }
}

const KIND_WORD: Record<string, string> = { questions: "Questions", gate: "Decision", answer: "Blocked agent", merge: "Merge",
  ticket: "Needs Jay", ci: "Failure", task: "Action", actions: "Action" };

export function useAttention(): JayItem[] {
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  return useMemo(() => jayQueue(st, undefined, tickets), [st, tickets]);
}

export function NotificationBell() {
  const items = useAttention();
  const st = useSelector(app.store, (d) => d.state);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState<Set<string>>(loadSeen);
  const first = useRef(true);
  const known = useRef<Set<string>>(new Set());
  const box = useRef<HTMLDivElement>(null);
  const unseen = items.filter((i) => !seen.has(i.id));

  // New attention: a tone and a toast, once per item (never for what was already there on load).
  useEffect(() => {
    const ids = new Set(items.map((i) => i.id));
    if (first.current) { first.current = false; known.current = ids; return; }
    const fresh = items.filter((i) => !known.current.has(i.id) && !seen.has(i.id));
    known.current = ids;
    if (fresh.length) {
      chime();
      app.toast(fresh.length === 1 ? `Needs you: ${jayWords(fresh[0])}` : `${fresh.length} things need you`, "ok");
    }
  }, [items, seen]);

  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);

  const markAll = () => { const s = new Set([...seen, ...items.map((i) => i.id)]); setSeen(s); saveSeen(s); };
  const go = (i: JayItem) => {
    const s = new Set([...seen, i.id]); setSeen(s); saveSeen(s); setOpen(false);
    const to = jayHref(i);
    if (to.startsWith("#")) location.hash = to; else window.open(to, "_blank", "noopener");
  };

  return <div className="bell-wrap" ref={box}>
    <button type="button" className={`bell${unseen.length ? " is-new" : ""}`} aria-haspopup="dialog" aria-expanded={open}
      aria-label={`Notifications: ${items.length} need you${unseen.length ? `, ${unseen.length} new` : ""}`}
      onClick={() => setOpen((v) => !v)}>
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
        strokeLinejoin="round" aria-hidden><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20a2 2 0 0 0 4 0" /></svg>
      {items.length > 0 && <span className="bell-n">{items.length}</span>}
    </button>
    {open && <div className="bell-pop" role="dialog" aria-label="Notifications">
      <div className="bell-head"><b>Needs you</b><span className="muted mono-xs">{items.length}</span>
        <span className="sl-fill" />{unseen.length > 0 && <button type="button" className="link mono-xs" onClick={markAll}>Mark all seen</button>}</div>
      {items.length === 0 ? <div className="bell-empty muted">Nothing needs you right now.</div>
        : <ul className="bell-list">{items.map((i) => <li key={i.id}>
          <button type="button" className={`bell-item${seen.has(i.id) ? "" : " is-new"}`} onClick={() => go(i)}>
            <span className="bell-kind" style={{ ["--pj" as string]: `var(--pj-${i.project}, var(--muted))` }}>
              <i className="pj-sq" aria-hidden />{KIND_WORD[i.kind] ?? "Action"}</span>
            <span className="bell-text">{jayWords(i)}</span>
            <span className="bell-meta mono-xs muted">{projectName(st, i.project)} · <Ago at={i.since} /></span>
          </button></li>)}</ul>}
    </div>}
  </div>;
}
