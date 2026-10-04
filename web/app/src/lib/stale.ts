// "Command Center was updated": recovering a window that outlived its build.
//
// The UI's lazy chunks (editor, terminal) are named after their content. After a
// deploy, a window still running the previous build may ask for a chunk the
// server no longer has (releases keep the last few builds' chunks, so this is
// rare). The import then fails with a browser-specific message. We recognise
// it, tell Jay, and reload ONCE: never in a loop, and never while there is
// unsaved work. Preferences live in localStorage and survive the reload.
import { Store } from "./store";

export const staleBuild = new Store<{ updated: boolean; detail: string | null }>({ updated: false, detail: null });

const PATTERNS = [
  /Failed to fetch dynamically imported module/i,   // Chromium / Edge
  /Importing a module script failed/i,              // Safari
  /error loading dynamically imported module/i,     // Firefox
  /Unable to preload CSS/i,                         // Vite CSS preload
  /ChunkLoadError|Loading chunk .* failed/i,
];

export function isChunkLoadError(e: unknown): boolean {
  const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e ?? "");
  return PATTERNS.some((p) => p.test(msg));
}

// Anything (the Workspace) can register "is there unsaved work?".
const unsaved = new Set<() => boolean>();
export function registerUnsaved(fn: () => boolean) { unsaved.add(fn); return () => { unsaved.delete(fn); }; }
export function hasUnsavedWork(): boolean {
  for (const f of unsaved) if (f()) return true;
  // Anything typed but not sent: a commit message, a Claude message, a new ticket's title…
  if (typeof document !== "undefined") {
    for (const el of Array.from(document.querySelectorAll<HTMLTextAreaElement | HTMLInputElement>("textarea, [data-unsaved-guard]"))) {
      if (el.value && el.value.trim()) return true;
    }
  }
  return false;
}

const KEY = "cc.reloadedForUpdateAt";
const WINDOW_MS = 60_000;

/** Reload once if allowed. Returns true when a reload was started.
 *  Never: over unsaved work; without sessionStorage to remember it (no way to prevent a loop);
 *  twice within a minute; or when the server does not answer (offline is not an update — the
 *  offline banner keeps the last data instead of a browser error page). */
export async function reloadOnce(now = Date.now(), storage: Storage | null = safeSession(),
  reload: () => void = () => location.reload(), probe: () => Promise<boolean> = serverAnswers): Promise<boolean> {
  if (hasUnsavedWork() || !storage) return false;
  let last: number;
  try { last = Number(storage.getItem(KEY) ?? 0) || 0; } catch { return false; }
  if (now - last < WINDOW_MS) return false;          // we already reloaded for this: don't loop
  if (!(await probe())) return false;
  try { storage.setItem(KEY, String(now)); } catch { return false; }
  reload();
  return true;
}

async function serverAnswers(): Promise<boolean> {
  try { return (await fetch("/", { cache: "no-store", credentials: "omit" })).ok; } catch { return false; }
}

/** Called wherever a lazy import fails. True if it was a stale-build failure (and handled). */
export function handleChunkError(e: unknown): boolean {
  if (!isChunkLoadError(e)) return false;
  staleBuild.set({ updated: true, detail: e instanceof Error ? e.message : String(e) });
  void reloadOnce();
  return true;
}

function safeSession(): Storage | null {
  try { return sessionStorage; } catch { return null; }
}

/** Vite fires this when a preloaded dependency of a lazy chunk fails. We only raise the banner:
 *  the event is NEVER cancelled — in Vite, preventDefault() makes the import resolve to undefined
 *  instead of rejecting, which would hide the failure from the loaders (and cache it). */
export function installStaleBuildHandler() {
  window.addEventListener("vite:preloadError", (ev) => {
    const payload = (ev as unknown as { payload?: unknown }).payload;
    if (isChunkLoadError(payload ?? "")) staleBuild.set({ updated: true, detail: String((payload as Error)?.message ?? payload) });
  });
}
