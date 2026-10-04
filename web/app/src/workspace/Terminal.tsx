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
import { unlockDialogOpen, useDevActive } from "../components/DevMode";

type Mods = { Terminal: typeof XTerm; FitAddon: typeof FitAddon; SearchAddon: typeof SearchAddon };
let mods: Promise<Mods> | null = null;
function loadXterm(): Promise<Mods> {
  mods ??= Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit"), import("@xterm/addon-search"),
    import("@xterm/xterm/css/xterm.css")]).then(([x, f, s]) => ({ Terminal: x.Terminal, FitAddon: f.FitAddon, SearchAddon: s.SearchAddon }));
  return mods;
}

type Conn = "idle" | "connecting" | "live" | "detached" | "ended" | "refused" | "lost";
const WORD: Record<Conn, string> = { idle: "NOT CONNECTED", connecting: "CONNECTING", live: "LIVE", detached: "DETACHED",
  ended: "SESSION ENDED", refused: "REFUSED", lost: "TOO SLOW — DROPPED" };

const THEMES = {
  dark: { background: "#0d1013", foreground: "#dfe4e2", cursor: "#86c7a3", selectionBackground: "#2d4a3c" },
  light: { background: "#fbfbf8", foreground: "#1c2326", cursor: "#2f7a55", selectionBackground: "#cfe6d8" },
};

export function TerminalView({ name, label, active, theme, onMaximize }: {
  name: string; label: string; active: boolean; theme: "dark" | "light"; onMaximize?: () => void;
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
        cursorBlink: true, scrollback: 5000, allowProposedApi: false, theme: THEMES[theme], convertEol: false });
      const f = new m.FitAddon(), sa = new m.SearchAddon();
      t.loadAddon(f); t.loadAddon(sa);
      t.open(host.current);
      term.current = t; fit.current = f; finder.current = sa;
      t.onData((d) => { const s = ws.current; if (s?.readyState === WebSocket.OPEN) s.send(JSON.stringify({ t: "i", d })); });
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
    sock.onmessage = (ev) => {
      if (typeof ev.data !== "string") { t.write(new Uint8Array(ev.data as ArrayBuffer)); return; }
      try {
        const m2 = JSON.parse(ev.data);
        if (m2.t === "hello") { setCwd(m2.cwd); setConn("live"); t.reset(); sendResize(); t.focus(); }
        else if (m2.t === "exit") { ended = true; setConn("ended"); t.write(`\r\n\x1b[2m[session ended${m2.code != null ? `, exit ${m2.code}` : ""}]\x1b[0m\r\n`); }
        else if (m2.t === "lost") { ended = true; setConn("lost"); }
      } catch { /* ignore */ }
    };
    sock.onclose = (ev) => {
      if (ws.current !== sock) return;
      if (ended) return;
      if (ev.code === 4403 || ev.code === 4401) setConn("refused");
      else setConn((c) => (c === "live" || c === "connecting" ? "detached" : c));
    };
  }, [name, theme, sendResize]);

  // Connect when first shown with Developer Mode on; never on its own otherwise.
  useEffect(() => { if (active && dev && conn === "idle") void connect(); }, [active, dev, conn, connect]);
  useEffect(() => { if (!dev && ws.current) { ws.current.close(); setConn("refused"); } }, [dev]);
  useEffect(() => { if (term.current) term.current.options.theme = THEMES[theme]; }, [theme]);
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
    if (!window.confirm(`Close the ${label} session? Anything running in it is stopped.`)) return;
    if (await app.action(() => app.api.ptyClose(name), `${label} closed`)) { ws.current?.close(); ws.current = null; setConn("ended"); }
  };

  if (!dev) {
    return <div className="term-wrap is-empty"><div className="con-notyet">
      <div className="row" style={{ gap: 8 }}><span className="ro-tag is-off">DEVELOPER MODE LOCKED</span><span className="caps muted">{label}</span></div>
      <p className="text2">A real shell runs commands as jay on jay-server, so it needs Developer Unlock as well as the ccd token.</p>
      <button type="button" className="btn is-jay" onClick={unlockDialogOpen}>Unlock</button>
    </div></div>;
  }
  return <div className="term-wrap">
    <div className="term-bar">
      <span className={`ro-tag${conn === "live" ? " is-live" : conn === "refused" || conn === "lost" ? " is-off" : ""}`}>{WORD[conn]}</span>
      <span className="mono-xs">{name}</span>
      <span className="mono-xs faint trunc" title={cwd ?? ""}>{cwd ?? ""}</span>
      <span className="sl-fill" />
      <input className="input is-sm term-find" value={find} placeholder="Find in output" aria-label={`Find in ${label} output`}
        onChange={(e) => { setFind(e.target.value); if (e.target.value) finder.current?.findNext(e.target.value); }}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (e.shiftKey) finder.current?.findPrevious(find); else finder.current?.findNext(find); } }} />
      {conn === "live"
        ? <button type="button" className="btn is-quiet is-sm" onClick={detach} title="Disconnect this view; the shell keeps running">Detach</button>
        : <button type="button" className="btn is-sm" onClick={() => void connect()}>{conn === "ended" ? "New session" : "Reconnect"}</button>}
      <button type="button" className="btn is-quiet is-sm" onClick={() => void closeSession()} disabled={conn === "ended"}>Close session</button>
      {onMaximize && <button type="button" className="btn is-quiet is-sm" onClick={onMaximize} title="Maximize terminal (Ctrl+Shift+Enter)">Maximize</button>}
    </div>
    <div className="term-host" ref={host} aria-label={`${label} terminal`} />
  </div>;
}
