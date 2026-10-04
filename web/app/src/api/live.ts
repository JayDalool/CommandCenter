import type { CcdEvent, WsMessage } from "./types";

export type LiveStatus = "connecting" | "live" | "offline";

export interface LiveHandlers {
  onEvent(ev: CcdEvent): void;
  /** The server could not replay what we missed: refetch /api/state, then restart(seq). */
  onLost(reason: string): void;
  onStatus(status: LiveStatus, info: { lastMessageAt: number | null; attempt: number }): void;
  onAuthFailed?(): void;
}

export interface LiveOptions {
  url?: string;
  token: () => string | null;
  WebSocketImpl?: typeof WebSocket;
  now?: () => number;
  /** silence longer than this (ms) means the socket is dead even if it never closed */
  staleAfterMs?: number;
}

export const WS_PROTOCOL = "ccd.v1";

/**
 * ccd's event stream: replay from `since`, then live; reconnect with backoff,
 * resuming from the last seq seen. The token travels as a WebSocket
 * subprotocol, never in the URL.
 */
export class Live {
  private ws: WebSocket | null = null;
  private seq = 0;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setInterval> | null = null;
  private stopped = true;
  lastMessageAt: number | null = null;
  status: LiveStatus = "offline";

  constructor(private handlers: LiveHandlers, private opts: LiveOptions) {}

  private now() { return (this.opts.now ?? Date.now)(); }

  private url() {
    if (this.opts.url) return this.opts.url;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/api/events`;
  }

  get lastSeq() { return this.seq; }

  start(since: number) {
    // Never two sockets: a second start (overlapping boots, StrictMode) replaces the first.
    this.closeSocket();
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    this.stopped = false;
    this.seq = since;
    this.attempt = 0;
    this.connect();
    if (!this.watchdog) {
      this.watchdog = setInterval(() => {
        const stale = this.opts.staleAfterMs ?? 45_000;
        if (this.status === "live" && this.lastMessageAt && this.now() - this.lastMessageAt > stale) {
          this.ws?.close();  // ccd pings every 20 s; silence means a dead path
        }
      }, 5_000);
    }
  }

  restart(since: number) {
    this.start(since);
  }

  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.watchdog) clearInterval(this.watchdog);
    this.timer = null;
    this.watchdog = null;
    this.closeSocket();
    this.setStatus("offline");
  }

  private closeSocket() {
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      try { ws.close(); } catch { /* already closed */ }
    }
  }

  private setStatus(s: LiveStatus) {
    this.status = s;
    this.handlers.onStatus(s, { lastMessageAt: this.lastMessageAt, attempt: this.attempt });
  }

  private connect() {
    if (this.stopped) return;
    const token = this.opts.token();
    const WS = this.opts.WebSocketImpl ?? WebSocket;
    this.setStatus("connecting");
    const protocols = token ? [WS_PROTOCOL, `ccd-token.${token}`] : [WS_PROTOCOL];
    let ws: WebSocket;
    try {
      ws = new WS(`${this.url()}?since=${this.seq}`, protocols);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    let opened = false;
    ws.onopen = () => { opened = true; };
    ws.onmessage = (m) => {
      this.lastMessageAt = this.now();
      let msg: WsMessage;
      try { msg = JSON.parse(String(m.data)); } catch { return; }
      switch (msg.type) {
        case "hello":
        case "replay_done":
          this.attempt = 0;
          this.setStatus("live");
          break;
        case "ping":
          if (this.status !== "live") this.setStatus("live");
          break;
        case "events_lost":
          this.seq = msg.seq;
          this.handlers.onLost(msg.reason ?? "events lost");
          break;
        case "event":
          if (msg.event.seq <= this.seq) return;  // replay overlap
          this.seq = msg.event.seq;
          this.handlers.onEvent(msg.event);
          break;
      }
    };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (!opened && (e.code === 4401 || e.code === 1006) && this.attempt >= 2 && this.handlers.onAuthFailed) {
        // A browser reports a refused upgrade as 1006; after a few tries, ask the app to recheck the token.
        this.handlers.onAuthFailed();
      }
      this.setStatus("offline");
      this.scheduleReconnect();
    };
    ws.onerror = () => { /* onclose follows */ };
  }

  private scheduleReconnect() {
    if (this.stopped) return;
    const delay = Math.min(30_000, 1000 * 2 ** this.attempt) * (0.85 + Math.random() * 0.3);
    this.attempt += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.connect(), delay);
  }
}
