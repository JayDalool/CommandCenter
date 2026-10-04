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
export function hasUnsavedWork(): boolean { for (const f of unsaved) if (f()) return true; return false; }

const KEY = "cc.reloadedForUpdateAt";
const WINDOW_MS = 60_000;

/** Reload once if allowed. Returns true when a reload was started. */
export function reloadOnce(now = Date.now(), storage: Storage | null = safeSession(),
  reload: () => void = () => location.reload()): boolean {
  if (hasUnsavedWork()) return false;
  let last = 0;
  try { last = Number(storage?.getItem(KEY) ?? 0) || 0; } catch { /* storage unavailable */ }
  if (now - last < WINDOW_MS) return false;          // we already reloaded for this: don't loop
  try { storage?.setItem(KEY, String(now)); } catch { /* ignore */ }
  reload();
  return true;
}

/** Called wherever a lazy import fails. True if it was a stale-build failure (and handled). */
export function handleChunkError(e: unknown): boolean {
  if (!isChunkLoadError(e)) return false;
  staleBuild.set({ updated: true, detail: e instanceof Error ? e.message : String(e) });
  reloadOnce();
  return true;
}

function safeSession(): Storage | null {
  try { return sessionStorage; } catch { return null; }
}

/** Vite fires this when a preloaded dependency of a lazy chunk fails. */
export function installStaleBuildHandler() {
  window.addEventListener("vite:preloadError", (ev) => {
    if (handleChunkError((ev as unknown as { payload?: unknown }).payload ?? "Failed to fetch dynamically imported module")) {
      ev.preventDefault();
    }
  });
}
