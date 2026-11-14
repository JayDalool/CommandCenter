// Live or not live, and the weekly release window (ccd's release store, flow contract §5). A live project has real
// users, so its changes go out together in one weekly window; a project that is not live has no window. ccd says
// which is which and when the window is. One read for the whole browser window, and again when ccd says either
// changed. An older ccd has no such route: then nothing about it is shown anywhere.
import { useEffect } from "react";
import "./release.css";
import { app } from "../store/app";
import { ApiError } from "../api/client";
import { Store, useSelector } from "../lib/store";
import { href } from "../lib/router";
import type { ReleaseState, ReleaseWindow } from "../api/types";

/** "none": this ccd has no release route. "error": the first read failed for another reason; the next place that
 *  shows a label tries again. */
export interface Release { state: "idle" | "loading" | "ok" | "none" | "error"; data: ReleaseState | null; error?: string }
const EMPTY: Release = { state: "idle", data: null };
export const release = new Store<Release>(EMPTY);
let turn = 0, seen = 0;

/** Read ccd's release state again. A refresh that fails after a good read keeps what is showing. */
export async function refreshRelease(): Promise<void> {
  const mine = ++turn;
  if (release.get().state === "idle" || release.get().state === "error") release.patch({ state: "loading", error: undefined });
  try {
    const data = await app.api.release();
    if (mine === turn) release.set({ state: "ok", data });
  } catch (e) {
    if (mine === turn && release.get().state === "loading") {
      release.patch(e instanceof ApiError && e.status === 404 ? { state: "none" }
        : { state: "error", error: e instanceof Error ? e.message : String(e) });
    }
  }
}

/** ccd's answer to a change: a PUT returns the same body as GET, so no second read is needed. */
export function setRelease(data: ReleaseState) { turn++; release.set({ state: "ok", data }); }

/** Tests only: forget everything. */
export function resetRelease() { turn++; seen = 0; release.set(EMPTY); }

/** Load once for the window, and again when ccd says the window or a project's live switch changed. Safe to call
 *  from every place that shows it. */
export function useRelease(): Release {
  const pulse = useSelector(app.store, (d) => d.activity.find((e) => e.kind.startsWith("release."))?.seq ?? 0);
  useEffect(() => {
    const state = release.get().state;
    if (state === "idle" || state === "error") void refreshRelease();
    else if (pulse > seen && state !== "none") void refreshRelease();
    seen = Math.max(seen, pulse);
  }, [pulse]);
  return useSelector(release, (r) => r);
}

export const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
/** The zones Jay names in words. Any other zone shows as ccd sends it. */
const ZONES: Record<string, string> = { "America/Winnipeg": "Central" };

/** "22:00" → "10 p.m.", "09:30" → "9:30 a.m.". Anything else comes back as it is. */
export function clock(time: string): string {
  const m = /^(\d{1,2}):(\d{2})$/.exec(time);
  if (!m || +m[1] > 23 || +m[2] > 59) return time;
  const h = +m[1];
  return `${h % 12 || 12}${m[2] === "00" ? "" : `:${m[2]}`} ${h < 12 ? "a.m." : "p.m."}`;
}
/** "Wednesday 10 p.m. Central" */
export const windowText = (w: ReleaseWindow) => `${WEEKDAYS[w.weekday] ?? "Day " + w.weekday} ${clock(w.time)} ${ZONES[w.tz] ?? w.tz}`;
/** The day of a moment, in the window's own time zone: "Wed, Nov 18". */
export function dayText(at: number, tz: string): string {
  const d = new Date(at * 1000);
  try { return new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", month: "short", day: "numeric" }).format(d); }
  catch { return d.toDateString(); }   // a zone this browser does not know
}

/** "Live" or "Not live" beside a project's name. Nothing while ccd has not answered, on an older ccd, and for a
 *  project ccd does not list. */
export function LiveTag({ project }: { project: string }) {
  const r = useRelease();
  const p = r.data?.projects[project];
  if (!r.data || !p) return null;
  const w = r.data.window;
  return p.live
    ? <span className="hq-live is-live" data-live="true"
      title={`Live. Changes go out together in the weekly release: ${windowText(w)}. Next: ${dayText(w.next, w.tz)}.`}><i aria-hidden />Live</span>
    : <span className="hq-live" data-live="false" title="Not live. No release window: a change can go out as soon as it is merged.">Not live</span>;
}

/** The same in a sentence, with where to change it: for a project's own panel. */
export function ReleaseNote({ project }: { project: string }) {
  const r = useRelease();
  const p = r.data?.projects[project];
  if (!r.data || !p) return null;
  const w = r.data.window;
  return <p className="hq-note hq-live-note"><LiveTag project={project} />
    <span>{p.live ? `Changes go out together in the weekly release, ${windowText(w)}. Next: ${dayText(w.next, w.tz)}.`
      : "No release window. A change can go out as soon as it is merged."}{" "}
      <a className="hq-link" href={href("settings", null, { tab: "profiles" })}>Change</a></span></p>;
}
