import { useSyncExternalStore } from "react";

/** A tiny observable value. Everything in the prototype that changes lives in one of these. */
export class Store<T> {
  private subs = new Set<() => void>();
  constructor(private value: T) {}
  get = (): T => this.value;
  set(next: T | ((prev: T) => T)) {
    const v = typeof next === "function" ? (next as (p: T) => T)(this.value) : next;
    if (Object.is(v, this.value)) return;
    this.value = v;
    this.subs.forEach((f) => f());
  }
  subscribe = (f: () => void) => { this.subs.add(f); return () => { this.subs.delete(f); }; };
}

export function useStore<T>(s: Store<T>): T {
  return useSyncExternalStore(s.subscribe, s.get, s.get);
}
