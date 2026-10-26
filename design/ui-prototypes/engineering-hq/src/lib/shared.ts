// State shared by every CommandCenter window of this browser profile (same origin only).
//
//   - BroadcastChannel carries changes live between open windows (same-origin by definition).
//   - localStorage gives a window that opens later the current value.
//
// Only NON-SENSITIVE UI state goes here: which window owns a view, selected tabs, filters, demo
// chat drafts. Never a token, never a Developer Unlock session (those keep using the production
// app's existing api/auth.ts + api/developer.ts handoff). Every incoming message is shape-checked
// and passed through the store's own guard before it is applied.
import { Store } from "./store";

export const WIN_ID: string = (() => {
  try { return crypto.randomUUID(); } catch { return `w${Math.random().toString(36).slice(2)}${Date.now()}`; }
})();

type Msg = { t: "shared"; name: string; value: unknown; from: string };
const channel: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("hq-shared") : null;
const registry = new Map<string, SharedStore<unknown>>();

function isMsg(d: unknown): d is Msg {
  if (!d || typeof d !== "object") return false;
  const m = d as Record<string, unknown>;
  return m.t === "shared" && typeof m.name === "string" && typeof m.from === "string" && m.from !== WIN_ID;
}

channel?.addEventListener("message", (e: MessageEvent) => {
  if (!isMsg(e.data)) return;
  registry.get(e.data.name)?.receive(e.data.value);
});

export class SharedStore<T> extends Store<T> {
  private applying = false;
  constructor(readonly name: string, initial: T, private guard: (v: unknown) => v is T) {
    super(SharedStore.load(name, initial, guard));
    registry.set(name, this as SharedStore<unknown>);
    this.subscribe(() => {
      if (this.applying) return;
      const value = this.get();
      try { localStorage.setItem(`hq.${name}`, JSON.stringify(value)); } catch { /* this window only */ }
      try { channel?.postMessage({ t: "shared", name, value, from: WIN_ID } satisfies Msg); } catch { /* closed */ }
    });
  }
  private static load<T>(name: string, initial: T, guard: (v: unknown) => v is T): T {
    try {
      const raw = localStorage.getItem(`hq.${name}`);
      if (raw) { const v: unknown = JSON.parse(raw); if (guard(v)) return v; }
    } catch { /* fall through */ }
    return initial;
  }
  /** A change from another window. Applied without re-broadcasting it. */
  receive(v: unknown) {
    if (!this.guard(v)) return;
    this.applying = true;
    try {
      this.set(v);
      try { localStorage.setItem(`hq.${this.name}`, JSON.stringify(v)); } catch { /* ignore */ }
    } finally { this.applying = false; }
  }
}

export const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Tests: wipe every shared value. */
export function resetShared() {
  try { Object.keys(localStorage).filter((k) => k.startsWith("hq.")).forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
}
