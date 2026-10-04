import { useSyncExternalStore, useRef } from "react";

/** A tiny external store: immutable snapshots, selector subscriptions, no library. */
export class Store<T> {
  private listeners = new Set<() => void>();
  constructor(private value: T) {}
  get = () => this.value;
  set = (next: T | ((prev: T) => T)) => {
    const v = typeof next === "function" ? (next as (p: T) => T)(this.value) : next;
    if (v === this.value) return;
    this.value = v;
    this.listeners.forEach((l) => l());
  };
  patch = (part: Partial<T>) => this.set((prev) => ({ ...prev, ...part }));
  subscribe = (l: () => void) => {
    this.listeners.add(l);
    return () => { this.listeners.delete(l); };
  };
}

/** Subscribe to a slice. Re-renders only when the selected value changes (Object.is, or `eq`). */
export function useSelector<T, S>(store: Store<T>, select: (s: T) => S, eq: (a: S, b: S) => boolean = Object.is): S {
  const last = useRef<{ s: S } | null>(null);
  return useSyncExternalStore(store.subscribe, () => {
    const next = select(store.get());
    if (last.current && eq(last.current.s, next)) return last.current.s;
    last.current = { s: next };
    return next;
  });
}

export function shallowEqual<A>(a: A, b: A): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => Object.is(x, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => Object.is((a as never)[k], (b as never)[k]));
  }
  return false;
}
