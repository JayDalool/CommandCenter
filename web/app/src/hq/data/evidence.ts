// What HQ may say about a session, a project or a host, and only from evidence.
//
// Every HQ view model starts here. A status is shown only when the feed behind it is live: a stale or
// missing feed makes it Unknown, never Working. Nothing here fetches; it reads what Classic's store
// already holds (/api/state, tickets, activity, the event-stream connection).
import type { Agent, CcdEvent, State, TaskProject, Ticket } from "../../api/types";
import type { LiveStatus } from "../../api/live";
import { freshness, LIMITS, type Fresh, type FreshRow } from "../../lib/freshness";

/** The slice of Classic's AppData that HQ reads. AppData satisfies it as is. */
export interface HqSource {
  state: State | null;
  tickets: Ticket[];
  activity: CcdEvent[];
  taskProjects?: TaskProject[];
  conn: { status: LiveStatus; lastMessageAt: number | null };
}

/** A session's presence. `waiting` = blocked on Jay's answer. `unknown` = the feed cannot vouch for it. */
export type Presence = "working" | "idle" | "waiting" | "offline" | "unknown";
export const PRESENCE_LABEL: Record<Presence, string> = {
  working: "Working", idle: "Idle", waiting: "Waiting for Jay", offline: "Offline", unknown: "Unknown",
};

export interface Evidence {
  rows: FreshRow[];
  /** herdr: the only source of session status. */
  sessions: Fresh;
  github: Fresh;
  host: Fresh;
  tasks: Fresh;
  stream: Fresh;
  now: number;
}

const rowState = (rows: FreshRow[], id: FreshRow["id"]): Fresh => rows.find((r) => r.id === id)?.state ?? "down";

/** One read of lib/freshness.ts, shared by every view built from the same snapshot. */
export function evidence(src: HqSource, now: number): Evidence {
  const rows = freshness(src.state, src.conn, now);
  return { rows, sessions: rowState(rows, "herdr"), github: rowState(rows, "github"), host: rowState(rows, "host"),
    tasks: rowState(rows, "tasks"), stream: rowState(rows, "ccd"), now };
}

/** A session's presence from herdr's own report. Anything herdr cannot vouch for right now is Unknown. */
export function presenceOf(a: Agent | undefined, ev: Evidence): Presence {
  if (ev.sessions !== "live") return "unknown";
  if (!a) return "offline";
  if (!a.live) return "offline";
  switch (a.status) {
    case "working": return "working";
    case "blocked": return "waiting";
    case "idle": case "done": return "idle";
    default: return "unknown";
  }
}

/** One project's GitHub feed: its own asOf and error, then the stream rule from lib/freshness.ts. */
export function projectGithub(st: State | null, key: string, ev: Evidence): Fresh {
  const s = st?.sources.github[key];
  if (!s || s.asOf == null) return "down";
  const fresh: Fresh = s.error || ev.now - s.asOf > LIMITS.github ? "stale" : "live";
  return fresh === "live" && ev.stream !== "live" ? "stale" : fresh;
}

/** Sessions by pane id, for tickets and coordinators that name a pane. */
export const agentsById = (st: State | null) => new Map((st?.agents ?? []).map((a) => [a.id, a]));
