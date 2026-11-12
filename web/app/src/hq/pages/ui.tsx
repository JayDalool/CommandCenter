// Small pieces HQ pages share. Styles are in office.css (.hq-pill and the t-* tones).
import type { ReactNode } from "react";
import type { Presence } from "../data";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export const PRESENCE_TONE: Record<Presence, string> = { working: "ok", waiting: "warn", idle: "info", offline: "idle", unknown: "idle" };

export function Pill({ tone, children, title }: { tone: string; children: ReactNode; title?: string }) {
  return <span className={`hq-pill t-${tone}`} title={title}><i aria-hidden />{children}</span>;
}

/** A summary figure. With `to`, the whole tile is a link to where the figure comes from. */
export function Kpi({ label, value, sub, tone, to }: { label: string; value: string | number; sub: string; tone?: string; to?: string }) {
  const body = <><small>{label}</small><b className={tone ? `t-${tone}` : undefined}>{value}</b><em>{sub}</em></>;
  return to ? <a className="hq-kpi" href={to}>{body}</a> : <div className="hq-kpi">{body}</div>;
}
