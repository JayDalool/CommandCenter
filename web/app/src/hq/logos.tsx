// Project logos (ccd/hq.py). ccd lists which projects have one; the bytes come as an octet-stream that this window
// turns into a blob: URL of the type ccd stored, as it does for chat images. One list and one blob per logo for the
// whole window, however many places show it. A project without a logo shows nothing extra: no placeholder picture.
import { useEffect } from "react";
import { app } from "../store/app";
import { ApiError } from "../api/client";
import { Store, useSelector } from "../lib/store";
import type { ProjectLogo as Meta } from "../api/types";

/** What ccd accepts and what this page will show. Anything else in the list is ignored. */
export const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const LOGO_MAX = 512 * 1024;

/** "none": this ccd has no logo route (an older server). "error": the first load failed for any other reason; `error`
 *  says why, and the next place that shows a logo tries again. */
interface Logos { state: "idle" | "loading" | "ok" | "none" | "error"; meta: Record<string, Meta>; urls: Record<string, string>; error?: string }
const EMPTY: Logos = { state: "idle", meta: {}, urls: {} };
export const logos = new Store<Logos>(EMPTY);
let turn = 0, seen = 0;

/** Read ccd's list again and fetch the bytes of any logo that is new or changed (by its sha). A refresh that fails
 *  after a good load leaves whatever is already showing. */
export async function refreshLogos(): Promise<void> {
  const mine = ++turn;
  if (logos.get().state === "idle" || logos.get().state === "error") logos.patch({ state: "loading", error: undefined });
  let meta: Record<string, Meta>;
  try { meta = await app.api.logos(); }
  catch (e) {
    if (mine === turn && logos.get().state === "loading") {
      logos.patch(e instanceof ApiError && e.status === 404 ? { state: "none" }
        : { state: "error", error: e instanceof Error ? e.message : String(e) });
    }
    return;
  }
  const was = logos.get(), urls: Record<string, string> = {};
  await Promise.all(Object.entries(meta).map(async ([key, m]) => {
    if (!LOGO_TYPES.includes(m.mime)) return;
    if (was.meta[key]?.sha256 === m.sha256 && was.urls[key]) { urls[key] = was.urls[key]; return; }
    try { urls[key] = URL.createObjectURL(await app.api.logoBlob(key, m.mime)); } catch { /* this one shows no logo */ }
  }));
  const kept = new Set(Object.values(mine === turn ? urls : logos.get().urls));
  // A newer refresh won: drop what this one made. Otherwise drop what it replaced.
  for (const u of Object.values(mine === turn ? was.urls : urls)) if (!kept.has(u)) URL.revokeObjectURL(u);
  if (mine === turn) logos.set({ state: "ok", meta, urls });
}

/** Tests only: forget everything. */
export function resetLogos() { turn++; seen = 0; logos.set(EMPTY); }

/** Load the list once for the window, and again when ccd says a logo changed. Safe to call from every place that
 *  shows a logo: only the first caller and the first to see a new event do any work. */
export function useLogos() {
  const pulse = useSelector(app.store, (d) => d.activity.find((e) => e.kind.startsWith("logo."))?.seq ?? 0);
  useEffect(() => {
    const state = logos.get().state;
    if (state === "idle" || state === "error") void refreshLogos();
    else if (pulse > seen) void refreshLogos();
    seen = Math.max(seen, pulse);
  }, [pulse]);
}

/** A project's logo, when it has one. Decoration beside the project's name, so it has no text of its own. */
export function ProjectLogo({ project, size = 20 }: { project: string; size?: number }) {
  useLogos();
  const url = useSelector(logos, (l) => l.urls[project] ?? null);
  return url ? <img className="hq-logo" src={url} width={size} height={size} alt="" data-project={project} /> : null;
}
