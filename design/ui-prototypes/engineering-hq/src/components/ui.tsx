import type { ReactNode } from "react";
import { agent, project, task, PRESENCE_LABEL, type Presence, type Stage } from "../data/seed";
import { Icon, type IconId } from "./Icon";

export const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export function cx(...c: (string | false | null | undefined)[]) { return c.filter(Boolean).join(" "); }

/** An agent's round badge with its glyph, in the agent's colour. */
export function Avatar({ id, size = 34, ring }: { id: string; size?: number; ring?: boolean }) {
  if (id === "jay") return <span className={cx("av av-jay", ring && "is-ring")} style={{ width: size, height: size, fontSize: size * 0.42 }}>J</span>;
  const a = agent(id);
  return <span className={cx("av", ring && "is-ring")} style={{ width: size, height: size, ["--c" as string]: a.color }} title={a.name}>
    <Icon name={a.glyph} size={size * 0.56} stroke={2} /></span>;
}

export function AvatarStack({ ids, size = 20 }: { ids: string[]; size?: number }) {
  return <span className="av-stack">{ids.map((i) => <Avatar key={i} id={i} size={size} />)}</span>;
}

/** A project's square icon tile, in the project's colour. */
export function ProjIcon({ k, size = 34, icon }: { k: string; size?: number; icon?: IconId }) {
  const p = project(k);
  return <span className="pj-ico" style={{ width: size, height: size, ["--c" as string]: p.color }}>
    <Icon name={icon ?? p.icon} size={size * 0.55} stroke={2} /></span>;
}

/** A task key (SV-025) with its project's colour, the same on every page. */
export function TaskKey({ k }: { k: string }) {
  const t = task(k);
  return <b className="tkey" style={{ ["--c" as string]: t ? project(t.project).color : "var(--muted)" }}><i aria-hidden />{k}</b>;
}

const PRES_TONE: Record<Presence, string> = { working: "ok", idle: "idle", researching: "info", reviewing: "violet", waiting: "warn",
  blocked: "bad", queued: "warn", paused: "idle", offline: "off", disconnected: "bad", unknown: "idle" };
export function PresenceDot({ s, label, detail }: { s: Presence; label?: boolean; detail?: string }) {
  return <span className={`pres t-${PRES_TONE[s]}`}><i aria-hidden />{label !== false && <b>{PRESENCE_LABEL[s]}</b>}{detail && <span> · {detail}</span>}</span>;
}

const STAGE_TONE: Record<Stage, string> = { Planning: "violet", Implementing: "info", Reviewing: "violet", "UI Testing": "pink", Verifying: "warn",
  "Ready to Merge": "ok", Deploying: "warn", "Needs Jay": "bad", Blocked: "bad", Closed: "idle", Paused: "idle" };
export function StagePill({ s }: { s: Stage }) { return <span className={`pill t-${STAGE_TONE[s]}`}><i aria-hidden />{s}</span>; }

export function Pill({ tone = "idle", children, dot }: { tone?: string; children: ReactNode; dot?: boolean }) {
  return <span className={cx("pill", `t-${tone}`, !dot && "no-dot")}>{dot && <i aria-hidden />}{children}</span>;
}

export function Prio({ p }: { p: "High" | "Medium" | "Low" }) {
  return <span className={`prio p-${p.toLowerCase()}`}><i aria-hidden />{p}</span>;
}

/** A small sparkline, drawn as a polyline with a soft area under it. */
export function Spark({ data, color, w = 90, h = 26, area = true }: { data: number[]; color: string; w?: number; h?: number; area?: boolean }) {
  const max = Math.max(...data), min = Math.min(...data);
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - 2 - ((v - min) / (max - min || 1)) * (h - 4)]);
  const line = pts.map((p) => p.join(",")).join(" ");
  const id = `sg${color.replace(/[^a-z0-9]/gi, "")}${w}`;
  return <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
    <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".35" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
    {area && <polygon points={`0,${h} ${line} ${w},${h}`} fill={`url(#${id})`} />}
    <polyline points={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}

export function Panel({ title, icon, sub, action, children, className, iconTone }: {
  title?: ReactNode; icon?: IconId; sub?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; iconTone?: string }) {
  return <section className={cx("panel", className)}>
    {title && <header className="panel-h">
      {icon && <span className={cx("panel-ico", iconTone && `t-${iconTone}`)}><Icon name={icon} size={20} /></span>}
      <div className="panel-t"><h2>{title}</h2>{sub && <p>{sub}</p>}</div>
      {action && <div className="panel-a">{action}</div>}
    </header>}
    {children}
  </section>;
}

export function ViewAll({ label = "View all", onClick, href }: { label?: string; onClick?: () => void; href?: string }) {
  return href ? <a className="viewall" href={href}>{label} <Icon name="arrowr" size={14} /></a>
    : <button type="button" className="viewall" onClick={onClick}>{label} <Icon name="arrowr" size={14} /></button>;
}

/** Marks seeded sample content. Required on anything that is not live data. */
export function Demo({ label = "Demo data" }: { label?: string }) {
  return <span className="demo-tag" title="Locally seeded sample. Not a real record.">{label}</span>;
}

export function ProdBanner({ compact }: { compact?: boolean }) {
  return <div className={cx("prod-banner", compact && "is-compact")} role="note">
    <span className="pb-ico"><Icon name="shield" size={compact ? 18 : 22} /></span>
    <div><b>Production untouched · No live changes</b>{!compact && <p>All work is in development and staging. Deploys need your gate (policy: release windows, owner merge).</p>}</div>
  </div>;
}
