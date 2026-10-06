// A real terminal: xterm.js (bundled locally, lazy-loaded) attached to a named
// ccd PTY session over the authenticated WebSocket /api/pty/{name}.
//
// The ccd token and the Developer Mode session travel as WebSocket
// subprotocols, never in the URL. Leaving the page or pressing DETACH only
// disconnects this view: the shell keeps running on jay-server and RECONNECT
// replays its recent output. CLOSE SESSION ends that shell (after a confirm).
import { useCallback, useEffect, useRef, useState } from "react";
import type { Terminal as XTerm } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import type { SearchAddon } from "@xterm/addon-search";
import { getToken } from "../api/auth";
import { devSession } from "../api/developer";
import { app } from "../store/app";
import { handleChunkError } from "../lib/stale";
import { installClipboard, makeInputSender } from "./termClipboard";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";
import { Overflow, type OverflowItem } from "../components/Overflow";

type Mods = { Terminal: typeof XTerm; FitAddon: typeof FitAddon; SearchAddon: typeof SearchAddon };
let mods: Promise<Mods> | null = null;
function loadXterm(): Promise<Mods> {
  mods ??= Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit"), import("@xterm/addon-search"),
    import("@xterm/xterm/css/xterm.css")]).then(([x, f, s]) => {
    if (!x?.Terminal || !f?.FitAddon || !s?.SearchAddon) throw new TypeError("Failed to fetch dynamically imported module (terminal)");
    return { Terminal: x.Terminal, FitAddon: f.FitAddon, SearchAddon: s.SearchAddon };
  }).catch((e) => { mods = null; handleChunkError(e); throw e; });
  return mods;
}

type Conn = "idle" | "connecting" | "live" | "detached" | "ended" | "refused" | "lost" | "elsewhere";
const WORD: Record<Conn, string> = { idle: "NOT CONNECTED", connecting: "CONNECTING", live: "LIVE", detached: "DETACHED",
  ended: "SESSION ENDED", refused: "REFUSED", lost: "TOO SLOW — DROPPED", elsewhere: "ATTACHED ELSEWHERE" };
// herdr allows one writable attach per terminal; its refusal text, as the attach client prints it.
const HERDR_BUSY = "already has an attached client";
const PREAMBLE_BYTES = 8 * 1024;

/** Feed it each output chunk; true once the herdr refusal text appeared inside the attach
 *  preamble (the first PREAMBLE_BYTES). Text Claude prints later never counts. */
export function busyDetector(limit = PREAMBLE_BYTES): (bytes: Uint8Array) => boolean {
  const dec = new TextDecoder();
  let seen = 0, text = "", hit = false;
  return (bytes) => {
    if (hit) return true;
    if (seen >= limit) return false;
    const take = bytes.subarray(0, limit - seen);
    seen += take.length;
    text += dec.decode(take, { stream: true });
    if (text.includes(HERDR_BUSY)) hit = true;
    return hit;
  };
}

// The terminal well is dark in both themes (as the Claude mirror is); its colours come from the tokens.
function termTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => css.getPropertyValue(n).trim() || d;
  return { background: v("--term-bg", "#0b0e10"), foreground: v("--term-text", "#c9d4cf"), cursor: v("--accent", "#86c7a3"),
    selectionBackground: "#2d4a3c" };
}

export function TerminalView({ name, label, active, theme, closeText, info, menu = [] }: {
  name: string; label: string; active: boolean; theme: "dark" | "light";
  /** The CLOSE SESSION confirmation; Claude's says Claude itself keeps running. */
  closeText?: string;
  /** The compact context line (e.g. "samvision · opus · idle"); the cwd from ccd when absent. */
  info?: React.ReactNode;
  /** Extra ⋯ items (e.g. Open in Windows Terminal), after Find / Detach / Close session. */
  menu?: OverflowItem[];
}) {
  const dev = useDevActive();
  const host = useRef<HTMLDivElement>(null);
  const term = useRef<XTerm | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const finder = useRef<SearchAddon | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const [conn, setConn] = useState<Conn>("idle");
  const [cwd, setCwd] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const [finding, setFinding] = useState(false);
  const enc = useRef(new TextEncoder());

  const sendResize = useCallback(() => {
    const t = term.current, s = ws.current;
    if (!t || !fit.current) return;
    try { fit.current.fit(); } catch { /* hidden */ }
    if (s?.readyState === WebSocket.OPEN) s.send(JSON.stringify({ t: "r", c: t.cols, r: t.rows }));
  }, []);

  const connect = useCallback(async () => {
    const sid = devSession();
    const token = getToken();
    if (!sid || !token) { setConn("refused"); return; }
    const m = await loadXterm();
    if (!term.current && host.current) {
      const t = new m.Terminal({ fontFamily: '"Cascadia Mono", "JetBrains Mono", Consolas, monospace', fontSize: 13,
        cursorBlink: true, scrollback: 5000, allowProposedApi: false, theme: termTheme(), convertEol: false });
      const f = new m.FitAddon(), sa = new m.SearchAddon();
      t.loadAddon(f); t.loadAddon(sa);
      t.open(host.current);
      term.current = t; fit.current = f; finder.current = sa;
      // Paste (Ctrl+V, Ctrl+Shift+V, Shift+Insert) and copy-on-selection; see termClipboard.ts.
      installClipboard(t);
      // Everything typed or pasted goes out in order, large pastes in paced chunks.
      const sendInput = makeInputSender((d) => {
        const s = ws.current;
        if (s?.readyState !== WebSocket.OPEN) return false;
        s.send(JSON.stringify({ t: "i", d }));
        return true;
      }, (msg) => t.write(msg));
      t.onData(sendInput);
      t.onBinary((d) => { const s = ws.current; if (s?.readyState === WebSocket.OPEN) s.send(enc.current.encode(d)); });
    }
    ws.current?.close();
    const t = term.current!;
    try { fit.current?.fit(); } catch { /* not laid out yet */ }
    setConn("connecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${location.host}/api/pty/${encodeURIComponent(name)}?cols=${t.cols}&rows=${t.rows}`,
      ["ccd.v1", `ccd-token.${token}`, `ccd-dev.${sid}`]);
    sock.binaryType = "arraybuffer";
    ws.current = sock;
    let ended = false;
    let busy = false;
    const sawBusy = busyDetector();
    sock.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        const bytes = new Uint8Array(ev.data as ArrayBuffer);
        if (!busy && name.startsWith("claude:") && sawBusy(bytes)) busy = true;
        t.write(bytes); return;
      }
      try {
        const m2 = JSON.parse(ev.data);
        if (m2.t === "hello") { setCwd(m2.cwd); setConn("live"); t.reset(); sendResize(); t.focus(); }
        else if (m2.t === "exit" && busy) {
          ended = true; setConn("elsewhere");
          t.write("\r\n\x1b[33mClaude is attached somewhere else (the native terminal?). Close that one, then Retry.\x1b[0m\r\n");
        }
        else if (m2.t === "exit") { ended = true; setConn("ended"); t.write(`\r\n\x1b[2m[session ended${m2.code != null ? `, exit ${m2.code}` : ""}]\x1b[0m\r\n`); }
        else if (m2.t === "lost") { ended = true; setConn("lost"); }
      } catch { /* ignore */ }
    };
    sock.onclose = (ev) => {
      if (ws.current !== sock) return;
      if (ended) return;
      if (ev.code === 4403 || ev.code === 4401 || ev.code === 4404 || ev.code === 4400) setConn("refused");
      else setConn((c) => (c === "live" || c === "connecting" ? "detached" : c));
    };
  }, [name, theme, sendResize]);

  // Connect when first shown with Developer Mode on; never on its own otherwise.
  useEffect(() => { if (active && dev && conn === "idle") void connect(); }, [active, dev, conn, connect]);
  // Locking Developer Mode ends this view; unlocking again reconnects when the tab is showing.
  // Only a view that was connected comes back by itself; a detached or closed one stays as Jay left it.
  useEffect(() => {
    if (!dev) { const s = ws.current; ws.current = null; s?.close(); setConn((c) => (c === "live" || c === "connecting" ? "idle" : c)); }
  }, [dev]);
  useEffect(() => { if (term.current) term.current.options.theme = termTheme(); }, [theme]);
  useEffect(() => {
    if (!host.current) return;
    const ro = new ResizeObserver(() => sendResize());
    ro.observe(host.current);
    return () => ro.disconnect();
  }, [sendResize]);
  useEffect(() => { if (active) { sendResize(); term.current?.focus(); } }, [active, sendResize]);
  // Leaving the screen detaches; the shell keeps running on the server.
  useEffect(() => () => { ws.current?.close(); term.current?.dispose(); }, []);

  const detach = () => { const s = ws.current; ws.current = null; s?.close(); setConn("detached"); };
  const closeSession = async () => {
    if (!window.confirm(closeText ?? `Close the ${label} session? Anything running in it is stopped.`)) return;
    if (await app.action(() => app.api.ptyClose(name), `${label} closed`)) { ws.current?.close(); ws.current = null; setConn("ended"); }
  };

  // The xterm host is ALWAYS mounted (the terminal lives in it); the lock notice is an overlay.
  // Primary row: state, context, and only the action that state needs. The rest is under ⋯.
  const bad = conn === "refused" || conn === "lost" || conn === "elsewhere";
  const recover = conn === "live" || conn === "connecting" ? null
    : conn === "ended" ? "New session" : conn === "elsewhere" || conn === "refused" ? "Retry" : conn === "idle" ? null : "Reconnect";
  return <div className="term-wrap">
    {!dev && <div className="term-lock"><div className="term-lock-card">
      <span className="ro-tag is-off">DEVELOPER LOCKED</span>
      <button type="button" className="btn is-jay is-sm" onClick={unlockDialogOpen}>Unlock</button>
    </div></div>}
    <div className="term-bar" inert={!dev}>
      {conn === "live"
        ? <span className="term-dot is-live" role="status" aria-label="live" title="live" />
        : <span role="status" className={`ro-tag${bad ? " is-off" : ""}`}>{WORD[conn]}</span>}
      <span className="mono-xs trunc term-info" title={typeof info === "string" ? info : cwd ?? ""}>{info ?? cwd ?? ""}</span>
      <span className="sl-fill" />
      {finding && <input className="input is-sm term-find" value={find} placeholder="Find" aria-label={`Find in ${label} output`} autoFocus
        onChange={(e) => { setFind(e.target.value); if (e.target.value) finder.current?.findNext(e.target.value); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { setFinding(false); term.current?.focus(); }
          else if (e.key === "Enter") { e.preventDefault(); if (e.shiftKey) finder.current?.findPrevious(find); else finder.current?.findNext(find); }
        }} />}
      {recover && <button type="button" className="btn is-sm" onClick={() => void connect()}>{recover}</button>}
      <Overflow label={`${label} actions`} items={[
        { label: finding ? "Hide find" : "Find in output", onSelect: () => setFinding(!finding) },
        { label: "Detach this view", onSelect: detach, hidden: conn !== "live" },
        ...menu,
        { label: "Close session…", onSelect: () => void closeSession(), danger: true, hidden: conn === "ended" || conn === "idle" },
      ]} />
    </div>
    <div className="term-host" ref={host} aria-label={`${label} terminal`} inert={!dev} />
  </div>;
}
