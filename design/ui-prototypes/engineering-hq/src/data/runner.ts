// Runs the DEMO status feed in exactly one window (Web Lock "hq-feed"; whichever window gets it).
// If that window closes, another open window takes over, so pop-outs keep live updates after the
// main window is gone. Without Web Locks (tests), the main window runs it.
import { useEffect } from "react";
import { tickFeed } from "./live";

export function useFeedRunner(ms = 5000) {
  useEffect(() => {
    if (new URLSearchParams(location.search).has("nofeed")) return;
    let stop = false, timer: ReturnType<typeof setInterval> | undefined, release: (() => void) | undefined;
    const run = () => { timer = setInterval(() => { if (!stop) tickFeed(); }, ms); };
    const lm = (navigator as Navigator & { locks?: LockManager }).locks;
    if (lm) void lm.request("hq-feed", () => new Promise<void>((r) => { if (stop) { r(); return; } release = r; run(); })).catch(() => {});
    else if (!location.hash.startsWith("#/pop/")) run();
    return () => { stop = true; if (timer) clearInterval(timer); release?.(); };
  }, [ms]);
}
