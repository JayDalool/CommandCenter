import raw from "./fixture.json";
import type { State, TaskList, CcdEvent } from "../src/api/types";

export const fixture = raw as unknown as { state: State; tasks: TaskList };
export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
export const state = () => clone(fixture.state);
export const tasks = () => clone(fixture.tasks);

export function ev(seq: number, kind: string, extra: Partial<CcdEvent> = {}): CcdEvent {
  return { seq, at: 1_791_000_000 + seq, source: "test", kind, severity: "info", project: "samvision", agentId: null,
    ref: null, text: `${kind} ${seq}`, data: {}, ...extra };
}

/** A scripted WebSocket: tests push server messages and inspect what the client did. */
export class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string, public protocols: string[]) { FakeSocket.all.push(this); }
  open() { this.onopen?.(); }
  send() { /* client never sends */ }
  msg(m: unknown) { this.onmessage?.({ data: JSON.stringify(m) }); }
  close() { if (this.closed) return; this.closed = true; this.onclose?.({ code: 1000 }); }
  drop(code = 1006) { this.closed = true; this.onclose?.({ code }); }
  static last() { return FakeSocket.all[FakeSocket.all.length - 1]; }
  static reset() { FakeSocket.all = []; }
}

export function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
