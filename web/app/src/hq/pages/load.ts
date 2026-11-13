// How a panel keeps one GET fresh: on mount, on a timer, and when a live event it cares about arrives. The answer is
// ccd's; nothing here makes up a value while it loads or after it fails.
import { useCallback, useEffect, useRef, useState } from "react";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { ApiError } from "../../api/client";

export interface LoadError { status: number; message: string }

/** `get` must be stable (useCallback): a new one is a new question, and an answer to the old one is dropped. */
export function useLoad<T>(get: () => Promise<T>, pulse: number, everyMs = 60_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<LoadError | null>(null);
  const turn = useRef(0);
  const load = useCallback(async () => {
    const mine = ++turn.current;
    try {
      const d = await get();
      if (mine === turn.current) { setData(d); setError(null); }
    } catch (e) {
      if (mine === turn.current) setError({ status: e instanceof ApiError ? e.status : 0, message: (e as Error).message });
    }
  }, [get]);
  useEffect(() => { void load(); const t = setInterval(() => void load(), everyMs); return () => { clearInterval(t); turn.current++; }; }, [load, everyMs]);
  useEffect(() => { if (pulse) void load(); }, [pulse, load]);
  return { data, error, reload: load };
}

/** The newest live event whose kind starts with one of `prefixes`, as a number that changes when another arrives. */
export function usePulse(prefixes: readonly string[]): number {
  return useSelector(app.store, (d) => d.activity.find((e) => prefixes.some((p) => e.kind.startsWith(p)))?.seq ?? 0);
}

/** What to say when ccd cannot answer: an older server has no such route (404), or it runs without the store (503). */
export function loadMessage(e: LoadError, what: string): string {
  if (e.status === 404) return `This server does not have ${what} yet. It arrives with the next server update.`;
  if (e.status === 503) return `${what[0].toUpperCase()}${what.slice(1)} is not set up on this server.`;
  return e.message;
}
