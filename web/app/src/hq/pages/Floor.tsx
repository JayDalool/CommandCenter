// The office floor: My Office's sessions as a place. Each team has its desks; a session is at its desk only while it
// is working, at Jay's door while it waits for him, in the lounge while idle and out when offline (hq/data/floor.ts).
// When a session's state changes it is seen walking to its new place. Nothing here is invented: a place is a status
// in another shape, every zone's heading says that status in words, and a feed that is not live seats nobody.
import { useLayoutEffect, useMemo, useRef, type ReactNode, type RefObject } from "react";
import "./floor.css";
import { href } from "../../lib/router";
import { ago } from "../../lib/time";
import { buildFloor, buildTeams, type Evidence, type FloorPerson, type HqSource, type Spot } from "../data";
import { Icon } from "../frame/icons";
import { Fun, Persona, useFun } from "../persona/mode";
import { ProjectLogo } from "../logos";
import { cx } from "./ui";

const AWAY: Record<Exclude<Spot, "desk">, string> = { door: "at your door", lounge: "in the lounge", out: "out", unseen: "not seen" };

/** Two letters for a session without a face: the first letters of its first two words, else its first two letters. */
export function initials(name: string): string {
  const w = name.match(/\p{L}[\p{L}\p{N}]*/gu) ?? [];
  const two = w.length > 1 ? w[0]!.charAt(0) + w[1]!.charAt(0) : (w[0] ?? name).slice(0, 2);
  return (two || "?").toUpperCase();
}

const tint = (project: string | null) => ({ ["--pj" as string]: project ? `var(--hq-pj-${project}, var(--hq-accent))` : "var(--hq-idle)" });

/** One session, wherever it stands: a face in Childish mode, two letters otherwise, its name, and what it is on.
 *  Away from its desk it also says whose team it is. Always a link, so a keyboard can stay on a session while it
 *  moves: to its task, or to Decisions for one that waits with no task, or to Teams, where every session is listed. */
function Who({ m, now }: { m: FloorPerson; now: number }) {
  const fun = useFun();
  const away = m.spot !== "desk";
  const line = [
    m.leadOf ? (away ? `${m.projectName} lead` : "Lead") : away ? m.projectName ?? "No project" : null,
    m.spot === "door" && m.waitingSince ? `waiting ${ago(m.waitingSince, now)}` : m.ticket ?? (m.leadOf ? null : m.agent),
  ].filter(Boolean).join(" · ");
  const body = <>
    <span className="hq-who-av">{fun ? <Persona lead={m.leadOf} name={m.name} size={40} />
      : <span className="hq-who-mono" aria-hidden>{initials(m.name)}</span>}</span>
    <b className="hq-ellip" title={m.name}>{m.name}</b>
    <small>{line}</small>
  </>;
  const to = m.ticket ? href("tasks", m.ticket) : href(m.spot === "door" ? "needs" : "agents");
  return <a className="hq-who" data-who={m.id} data-spot={m.spot} style={tint(m.project)} href={to}>{body}</a>;
}

/** A desk. Its owner sits at it while working; otherwise it is drawn empty, with where the owner went. The empty
 *  desk is decoration (the owner is listed once, where it is), so a screen reader does not hear it. */
function Desk({ m, now }: { m: FloorPerson; now: number }) {
  if (m.spot === "desk") return <li className={cx("hq-desk", m.leadOf && "is-lead")}><Who m={m} now={now} /></li>;
  return <li className={cx("hq-desk is-empty", m.leadOf && "is-lead")} aria-hidden>
    <span className="hq-who-av is-seat" /><b className="hq-ellip">{m.name}</b><small>{AWAY[m.spot]}</small></li>;
}

function Zone({ area, icon, title, emoji, sub, action, children }: {
  area: string; icon: string; title: string; emoji: string; sub: string; action?: ReactNode; children: ReactNode }) {
  const id = `hq-floor-${area}`;
  return <section className={`hq-zone is-${area}`} aria-labelledby={id}>
    <header><Icon name={icon} size={16} /><h4 id={id}>{title}<Fun e={emoji} /> <small>{sub}</small></h4>{action}</header>
    {children}
  </section>;
}

/** Moves each `[data-who]` from where it was last drawn to where it is now, so a session that changed state walks to
 *  its new place instead of jumping. Places are layout offsets inside the floor: scrolling, and a walk already under
 *  way, do not change them. Nobody walks when the floor itself was resized, or when the reader asked for less motion.
 *
 *  A session that changes rooms is a new element, so keyboard focus would be dropped with the old one. The session
 *  that has focus is noted while the floor renders (the old element is still there then) and given focus again here. */
function useWalk(root: RefObject<HTMLElement | null>) {
  const last = useRef<{ width: number; at: Map<string, [number, number]> }>({ width: -1, at: new Map() });
  const held = typeof document === "undefined" || !root.current?.contains(document.activeElement) ? null
    : document.activeElement?.closest<HTMLElement>("[data-who]")?.dataset.who ?? null;
  useLayoutEffect(() => {
    const floor = root.current;
    if (!floor) { last.current = { width: -1, at: new Map() }; return; }
    const width = floor.offsetWidth, at = new Map<string, [number, number]>();
    const still = width !== last.current.width || !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    for (const who of floor.querySelectorAll<HTMLElement>("[data-who]")) {
      let x = 0, y = 0;
      for (let n: HTMLElement | null = who; n && n !== floor; n = n.offsetParent as HTMLElement | null) { x += n.offsetLeft; y += n.offsetTop; }
      const id = who.dataset.who!, was = last.current.at.get(id);
      at.set(id, [x, y]);
      if (!still && was && (Math.abs(was[0] - x) >= 2 || Math.abs(was[1] - y) >= 2)) {
        const [ax, ay] = adrift(who);   // moved again before it arrived: carry on from where it is drawn
        walk(who, was[0] - x + ax, was[1] - y + ay);
      }
      if (id === held && !floor.contains(document.activeElement)) who.focus({ preventScroll: true });
    }
    last.current = { width, at };
  });
}

/** What ends each walk under way, so a second walk of the same element replaces the first instead of being cut
 *  short by the first one's timer. */
const ending = new WeakMap<HTMLElement, () => void>();

/** How far from its place an element is drawn right now: not zero only while it is walking. */
function adrift(el: HTMLElement): [number, number] {
  const t = typeof DOMMatrixReadOnly === "function" ? getComputedStyle(el).transform : "";
  if (!t || t === "none") return [0, 0];
  const m = new DOMMatrixReadOnly(t);
  return [m.m41, m.m42];
}

/** First-last-invert-play with one CSS transition: put the element back where it was drawn, then let go. */
function walk(el: HTMLElement, dx: number, dy: number) {
  ending.get(el)?.();
  const ms = Math.round(Math.min(1800, 450 + Math.hypot(dx, dy) * 1.6));
  el.style.transition = "none";
  el.style.transform = `translate(${dx}px, ${dy}px)`;
  el.classList.add("is-walking");
  void el.offsetWidth;   // the browser has to see the starting place before the transition is switched on
  el.style.transition = `transform ${ms}ms cubic-bezier(.45, .05, .25, 1)`;
  el.style.transform = "";
  const stop = () => { window.clearTimeout(timer); el.removeEventListener("transitionend", arrived); ending.delete(el); };
  const done = () => { stop(); el.classList.remove("is-walking"); el.style.transition = ""; };
  // only its own walk ends it, not a transition of something inside it
  const arrived = (e: TransitionEvent) => { if (e.target === el && (!e.propertyName || e.propertyName === "transform")) done(); };
  const timer = window.setTimeout(done, ms + 150);   // a transition that never runs (a hidden tab) still ends
  el.addEventListener("transitionend", arrived);
  ending.set(el, stop);
}

export function Floor({ src, ev }: { src: HqSource; ev: Evidence }) {
  const v = useMemo(() => buildFloor(buildTeams(src, ev)), [src, ev]);
  const root = useRef<HTMLDivElement>(null);
  useWalk(root);
  const live = ev.sessions === "live";
  if (!v.total) return <p className="hq-empty">herdr reports no sessions.</p>;
  // An empty room is only a fact while herdr is reporting. Otherwise it is not known who would be in it.
  const people = (list: FloorPerson[], empty: string) => list.length
    ? <ul className="hq-floor-people">{list.map((m) => <li key={m.id}><Who m={m} now={ev.now} /></li>)}</ul>
    : <p className="hq-empty">{live ? empty : "Not known while the feed is not live."}</p>;
  const count = (n: number, what: string) => (live ? `${n} ${what}` : "not known");
  const working = v.teams.reduce((n, t) => n + t.desks.filter((m) => m.spot === "desk").length, 0);
  return <div className="hq-floor" ref={root}>
    {!live && <p className="hq-note" role="status">The session feed is not live, so nobody can be placed. These are the sessions herdr last reported.</p>}
    {/* The door comes first for a keyboard, a screen reader and a phone: it is who needs Jay. On a wide screen the
        desks are drawn to its left (floor.css). */}
    <div className="hq-floor-plan">
      <Zone area="door" icon="door" title="At your door" emoji="🙋" sub={count(v.door.length, "waiting for you")}
        action={v.door.length > 0 && <a className="hq-link" href={href("needs")}>Open Decisions</a>}>
        {people(v.door, "Nobody is waiting for you.")}
      </Zone>
      <Zone area="desks" icon="desk" title="At their desks" emoji="🔨" sub={count(working, "working")}>
        <div className="hq-floor-teams">{v.teams.map((t) => <div className="hq-floor-team" key={t.key ?? ""} style={tint(t.key)}>
          <span className="hq-floor-team-name hq-with-logo" aria-hidden>{t.key && <ProjectLogo project={t.key} size={16} />}{t.name}</span>
          {/* With nobody at a desk the whole list is decoration, so it is not read out as an empty list. */}
          <ul aria-label={`${t.name} desks`} aria-hidden={t.desks.every((m) => m.spot !== "desk") || undefined}>
            {t.desks.map((m) => <Desk key={m.id} m={m} now={ev.now} />)}</ul>
        </div>)}</div>
      </Zone>
      <Zone area="lounge" icon="sofa" title="In the lounge" emoji="☕" sub={count(v.lounge.length, "idle")}>
        {people(v.lounge, "Nobody is idle.")}
      </Zone>
      {v.out.length > 0 && <Zone area="out" icon="moon" title="Out of the office" emoji="🌙" sub={`${v.out.length} offline`}>
        {people(v.out, "")}
      </Zone>}
      {v.unseen.length > 0 && <Zone area="unseen" icon="eyeoff" title="Not seen" emoji="❔" sub={`${v.unseen.length}, status unknown`}>
        {people(v.unseen, "")}
      </Zone>}
    </div>
  </div>;
}
