import type { State } from "../api/types";
import type { LiveStatus } from "../api/live";

export type Fresh = "live" | "stale" | "down" | "off";
export interface FreshRow { id: "herdr" | "github" | "host" | "tasks" | "ccd"; label: string; state: Fresh;
  ageS: number | null; detail: string }

// How old each source may be before it is called stale. ccd polls GitHub every
// 120 s and the host every 120 s; twice that plus slack is still "live".
export const LIMITS = { github: 300, host: 300, herdrSnapshot: 90 };

/** One line per source: live / stale / down. Never hides staleness. */
export function freshness(st: State | null, conn: { status: LiveStatus; lastMessageAt: number | null },
                          nowS: number): FreshRow[] {
  const rows: FreshRow[] = [];
  const ccdAge = conn.lastMessageAt ? nowS - conn.lastMessageAt / 1000 : null;
  rows.push({ id: "ccd", label: "CCD", state: conn.status === "live" ? "live" : conn.status === "connecting" ? "stale" : "down",
    ageS: ccdAge, detail: conn.status === "live" ? "event stream connected" : conn.status === "connecting"
      ? "reconnecting" : "offline — showing last known data" });
  if (!st) return rows;
  const h = st.sources.herdr;
  const herdrAt = Math.max(h.lastEventAt ?? 0, h.lastSnapshotAt ?? 0) || null;
  const herdrAge = herdrAt ? nowS - herdrAt : null;
  rows.unshift({ id: "herdr", label: "HERDR",
    state: !h.ok ? "down" : herdrAge != null && herdrAge > LIMITS.herdrSnapshot ? "stale" : "live",
    ageS: herdrAge, detail: h.ok ? (h.warning ?? "connected") : (h.error ?? "unreachable") });
  const gh = Object.entries(st.sources.github);
  const oldest = gh.reduce<number | null>((m, [, v]) => v.asOf == null ? m : m == null ? v.asOf : Math.min(m, v.asOf), null);
  const ghErr = gh.filter(([, v]) => v.error).map(([k, v]) => `${k}: ${v.error}`);
  const ghAge = oldest ? nowS - oldest : null;
  rows.splice(1, 0, { id: "github", label: "GITHUB",
    state: oldest == null ? "down" : ghAge! > LIMITS.github ? "stale" : ghErr.length ? "stale" : "live",
    ageS: ghAge, detail: ghErr.length ? ghErr.join("; ") : `${gh.length} repos` });
  const ho = st.sources.host;
  const hoAge = ho.asOf ? nowS - ho.asOf : null;
  rows.splice(2, 0, { id: "host", label: "HOST", state: ho.error ? "down" : hoAge == null ? "down" :
    hoAge > LIMITS.host ? "stale" : "live", ageS: hoAge, detail: ho.error ?? "vitals" });
  const t = st.sources.tasks;
  rows.splice(3, 0, { id: "tasks", label: "TASKS", state: !t ? "off" : t.ok ? "live" : "down", ageS: null,
    detail: !t ? "task system not enabled on this ccd" : "tasks.db" });
  // When the stream is down nothing above can be trusted as current.
  if (conn.status !== "live") rows.forEach((r) => { if (r.id !== "ccd" && r.state === "live") r.state = "stale"; });
  return rows;
}
