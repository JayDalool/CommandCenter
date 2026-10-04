// Small presentational primitives. State is never colour-only: every dot has a word next to it.
import { useEffect, useState, type ReactNode } from "react";
import type { AgentStatus, CiMark, Priority, TicketStatus } from "../api/types";
import { ago, nowS } from "../lib/time";
import { STATUS_META, PRIORITY_META, FLAG_LABEL, assigneeKind, assigneeLabel, type Tone } from "../tickets/model";

export const AGENT_META: Record<AgentStatus | "offline", { label: string; tone: Tone; shape: string }> = {
  working: { label: "WORKING", tone: "working", shape: "fill" },
  blocked: { label: "BLOCKED", tone: "blocked", shape: "square" },
  idle: { label: "IDLE", tone: "idle", shape: "ring" },
  done: { label: "DONE", tone: "done", shape: "fill" },
  unknown: { label: "UNKNOWN", tone: "unknown", shape: "dash" },
  offline: { label: "OFFLINE", tone: "unknown", shape: "ring" },
};

export function StatusDot({ tone, shape = "fill", pulse = false, label }: { tone: Tone; shape?: string; pulse?: boolean;
  label?: string }) {
  return <i className={`dot tone-${tone}${pulse ? " is-pulse" : ""}`} data-shape={shape} aria-hidden={label ? undefined : true}
    aria-label={label} role={label ? "img" : undefined} />;
}

/** Agent state: dot + uppercase mono word. */
export function AgentState({ status }: { status: AgentStatus | "offline" | string }) {
  const m = AGENT_META[(status as AgentStatus) in AGENT_META ? (status as AgentStatus) : "unknown"];
  return <span className={`state tone-${m.tone}`} data-state={status}>
    <StatusDot tone={m.tone} shape={m.shape} pulse={status === "working"} /><span className="state-label">{m.label}</span>
  </span>;
}

/** Ticket status: dot + sentence-case label (soft) or 4-letter code. */
export function StateText({ status, code = false }: { status: TicketStatus; code?: boolean }) {
  const m = STATUS_META[status] ?? STATUS_META.INBOX;
  return <span className={`state tone-${m.tone}${code ? "" : " is-soft"}`} data-status={status} title={m.label}>
    <StatusDot tone={m.tone} shape={status === "DONE" ? "fill" : status === "INBOX" ? "ring" : status === "BLOCKED" ? "square"
      : ["DENIED", "CANCELLED"].includes(status) ? "dash" : "half"} />
    <span className="state-label">{code ? m.short : m.label}</span>
  </span>;
}

export function PriorityMark({ p, withLabel = false }: { p: Priority; withLabel?: boolean }) {
  const m = PRIORITY_META[p] ?? PRIORITY_META.NO_PRIORITY;
  const mark = p === "URGENT" ? <span className="prio-urgent" aria-hidden>!</span>
    : p === "NO_PRIORITY" ? <span className="prio-none" aria-hidden>—</span>
      : <span className="prio" data-bars={m.bars} aria-hidden><i /><i /><i /></span>;
  return <span className="row" style={{ gap: 6 }} title={m.label}>{mark}
    {withLabel ? <span className="text2">{m.label}</span> : <span className="sr">{m.label}</span>}</span>;
}

export function Assignee({ value, compact = false }: { value: string | null; compact?: boolean }) {
  const kind = assigneeKind(value);
  const label = assigneeLabel(value);
  const cls = kind === "human" ? "av-human" : kind === "role" ? "av-role" : kind === "agent" ? "av-agent" : "av-none";
  const glyph = kind === "human" ? "J" : kind === "role" ? label.charAt(0) : kind === "agent" ? "◆" : "";
  return <span className={`assignee is-${kind}`} title={kind === "none" ? "Unassigned" :
    `${kind === "human" ? "Human" : kind === "role" ? "Agent role" : "Specific agent"}: ${label}`}>
    <span className={`av ${cls}`} aria-hidden>{glyph}</span>
    {!compact && <span className={`assignee-name${kind === "none" ? " faint" : ""}`}>{kind === "none" ? "—" : label}</span>}
    {compact && <span className="sr">{label}</span>}
  </span>;
}

export function Project({ k, name }: { k: string | null; name?: string }) {
  if (!k) return <span className="faint">—</span>;
  return <span className="pj" style={{ ["--pj" as string]: `var(--pj-${k}, var(--faint))` }}>
    <i className="pj-mark" aria-hidden /><span className="pj-name">{name ?? k}</span></span>;
}

export function Flags({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return <span className="row" style={{ gap: 4 }}>{flags.map((f) => <span key={f} className="flag">{FLAG_LABEL[f] ?? f}</span>)}</span>;
}

export function Ci({ mark }: { mark: CiMark | string }) {
  const cls = mark === "✓" ? "ci-ok" : mark === "✗" ? "ci-bad" : mark === "…" ? "ci-run" : "ci-none";
  const word = mark === "✓" ? "passing" : mark === "✗" ? "failing" : mark === "…" ? "running" : "no checks";
  return <span className={`ci ${cls}`} title={`checks ${word}`}>{mark}<span className="sr"> checks {word}</span></span>;
}

/** A relative age that re-renders itself every 10 s without touching the store. */
export function Ago({ at, title }: { at: number | null | undefined; title?: string }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 10_000); return () => clearInterval(t); }, []);
  return <time className="mono-xs muted" dateTime={at ? new Date(at * 1000).toISOString() : undefined}
    title={title ?? (at ? new Date(at * 1000).toLocaleString() : undefined)}>{ago(at, nowS())}</time>;
}

export function Panel({ title, count, meta, tools, children, className = "", pad = false, jay = false, id }: {
  title: string; count?: number | string; meta?: ReactNode; tools?: ReactNode; children: ReactNode; className?: string;
  pad?: boolean; jay?: boolean; id?: string }) {
  const hid = id ? `${id}-h` : undefined;
  // The id is on the section, so a layout can place panels by name and a link
  // can jump to one. The heading carries `${id}-h`.
  return <section id={id} className={`panel ${jay ? "is-jay " : ""}${className}`} aria-labelledby={hid}>
    <header className="panel-head">
      <h2 className="panel-title" id={hid}>{title}</h2>
      {count != null && <span className="panel-count">{count}</span>}
      {meta && <div className="panel-meta">{meta}</div>}
      {tools && <div className="panel-tools">{tools}</div>}
    </header>
    <div className={`panel-body${pad ? " is-pad" : ""}`}>{children}</div>
  </section>;
}

export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="detail-row"><dt>{label}</dt><dd>{children}</dd></div>;
}

export function EmptyState({ title, children, hint }: { title: string; children?: ReactNode; hint?: string }) {
  return <div className="empty" role="status"><div className="empty-title">{title}</div>{children && <div>{children}</div>}
    {hint && <div className="mono">{hint}</div>}</div>;
}

export function Kbd({ children }: { children: ReactNode }) { return <kbd className="kbd">{children}</kbd>; }

export function StaleIndicator({ at, limitS, label = "stale" }: { at: number | null | undefined; limitS: number; label?: string }) {
  if (!at || nowS() - at <= limitS) return null;
  return <span className="stale-tag" title={`last update ${new Date(at * 1000).toLocaleTimeString()}`}>{label} {ago(at)}</span>;
}

export function Copy({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return <button type="button" className="btn is-sm" onClick={async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* no clipboard */ }
  }} aria-label={`${label}: ${text}`}>{done ? "Copied" : label}</button>;
}

export function Command({ cmd }: { cmd: string }) {
  return <div className="cmd"><code title={cmd}>{cmd}</code><Copy text={cmd} /></div>;
}

export function Seg<T extends string>({ value, options, onChange, label }: { value: T; label: string;
  options: { v: T; label: ReactNode; n?: number }[]; onChange: (v: T) => void }) {
  return <div className="seg" role="group" aria-label={label}>{options.map((o) =>
    <button key={o.v} type="button" aria-pressed={value === o.v} onClick={() => onChange(o.v)}>
      {o.label}{o.n != null && <span className="n">{o.n}</span>}</button>)}</div>;
}
