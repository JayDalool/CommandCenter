// CLAUDE — the project's coordinator, which herdr owns. This view never starts
// a session. Output is herdr's recent pane text (read on demand, credential
// shapes redacted); herdr 0.9.3 offers no byte stream, so this is a mirror plus
// the inputs herdr safely supports:
//   blocked → ANSWER (typed into the question, then Enter)
//   idle    → SEND (herdr agent.prompt; Developer Mode)
//   working → ESC interrupts (Developer Mode)
// For general command work, use the real Repo shell.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { prefs, usePrefs } from "../lib/prefs";
import { hms } from "../lib/time";
import type { Agent, Tail } from "../api/types";
import { AgentState, EmptyState } from "../components/ui";
import { unlockDialogOpen, useDevActive } from "../components/DevMode";
import { workspace } from "./transport";
import { NativeButton } from "./Native";

const MIRROR_MS = 2000;
const LINES = 200;

function useVisible() {
  const [vis, setVis] = useState(typeof document === "undefined" || document.visibilityState === "visible");
  useEffect(() => {
    const on = () => setVis(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return vis;
}

function highlight(text: string, q: string) {
  if (!q) return text;
  const out: React.ReactNode[] = [];
  const low = text.toLowerCase(), ql = q.toLowerCase();
  let i = 0, n = 0;
  for (;;) {
    const j = low.indexOf(ql, i);
    if (j < 0 || n > 500) break;
    out.push(text.slice(i, j), <mark key={n++}>{text.slice(j, j + q.length)}</mark>);
    i = j + q.length;
  }
  out.push(text.slice(i));
  return out;
}

export function ClaudePanel({ agent, project, ticket, model, compact = false, onMaximize, active = true, prefix = null }: {
  agent: Agent | null; project: { key: string; name: string } | null; ticket: string | null; model?: string | null;
  compact?: boolean; onMaximize?: () => void; active?: boolean; prefix?: string | null;
}) {
  const visible = useVisible();
  const dev = useDevActive();
  const follow = usePrefs((p) => p.consoleFollow);
  const blocked = useSelector(app.store, (d) => d.state?.blocked ?? null);
  const herdrOk = useSelector(app.store, (d) => d.state?.sources.herdr.ok ?? false);
  const [tail, setTail] = useState<Tail | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [q, setQ] = useState("");
  const pre = useRef<HTMLPreElement>(null);
  const id = agent?.id ?? null;
  const name = agent?.agent_name || project?.key || "—";

  const read = useCallback(async () => {
    if (!id) return;
    try { setTail(await app.api.tail(id, LINES)); setAt(Date.now() / 1000); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, [id]);
  useEffect(() => {
    if (!id || !visible || !follow || !active) return;  // a hidden copy never polls
    void read();
    const t = setInterval(() => void read(), MIRROR_MS);
    return () => clearInterval(t);
  }, [id, visible, follow, read, active]);
  useEffect(() => { setTail(null); setErr(null); }, [id]);
  // Trailing blank lines from the pane are noise.
  const text = useMemo(() => (tail?.text ?? "").replace(/\s+$/, ""), [tail]);
  useEffect(() => { if (follow && !q && pre.current) pre.current.scrollTop = pre.current.scrollHeight; }, [text, follow, q]);

  if (!agent) {
    return <div className="claude is-empty"><EmptyState title={`No coordinator running for ${project?.name ?? "this project"}`}
      hint="herdr owns Claude panes. Start the coordinator in herdr; Command Center never starts one — nor does Open Claude terminal." /></div>;
  }
  const question = blocked?.find((b) => b.pane_id === agent.id);
  const status = agent.status;
  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = msg.trim();
    if (!t) return;
    if (question) {
      if (await app.action(() => app.api.answer(agent.id, t), `Answer sent to ${name}`)) { setMsg(""); void read(); }
      return;
    }
    if (!dev) { unlockDialogOpen(); return; }
    if (await app.action(() => app.api.prompt(agent.id, t), `Sent to ${name}`)) { setMsg(""); void read(); }
  };

  return <div className={`claude${compact ? " is-compact" : ""}`}>
    {!compact && <div className="claude-head" role="group" aria-label="Claude context">
      <span><span className="caps muted">Project</span> <b>{project?.name ?? "—"}</b></span>
      <span><span className="caps muted">Coordinator</span> <span className="mono">{name}</span></span>
      <span><span className="caps muted">Pane</span> <span className="mono-xs">{agent.id}</span></span>
      {model && <span><span className="caps muted">Model</span> <span className="mono-xs">{model}</span></span>}
      <span><AgentState status={status} /></span>
      {ticket && <span><span className="caps muted">Ticket</span> <span className="key">{ticket}</span></span>}
      <span className="trunc"><span className="caps muted">cwd</span> <span className="mono-xs" title={agent.cwd ?? ""}>{agent.cwd}</span></span>
      <span><span className="caps muted">herdr</span> <span className={herdrOk ? "ok-t" : "bad-t"}>{herdrOk ? "connected" : "unreachable"}</span></span>
    </div>}
    <div className="claude-bar">
      <NativeButton action="claude" prefix={prefix} small>Open Claude terminal</NativeButton>
      <span className="ro-tag" title="herdr gives ccd the pane's recent text, not a live byte stream. For real interactive work use Open Claude terminal.">MIRROR</span>
      {compact && <><span className="mono-xs">{name}</span><AgentState status={status} /></>}
      <span className="sl-fill" />
      <input className="input is-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search output" aria-label="Search Claude output" />
      <button type="button" className="btn is-quiet is-sm" aria-pressed={follow} onClick={() => prefs.patch({ consoleFollow: !follow })}>{follow ? "Following" : "Paused"}</button>
      <button type="button" className="btn is-quiet is-sm" onClick={() => void read()}>Read now</button>
      <button type="button" className="btn is-quiet is-sm" onClick={() => void navigator.clipboard?.writeText(text).then(() => app.toast("Copied"))}>Copy</button>
      <button type="button" className="btn is-quiet is-sm" onClick={() => void workspace.focusAgent(agent.id)} title="Bring this pane forward in your herdr client">Open in herdr</button>
      {onMaximize && <button type="button" className="btn is-quiet is-sm" onClick={onMaximize}>Maximize</button>}
    </div>
    <pre className="claude-out" ref={pre} tabIndex={0} aria-label={`${name} output`}>
      {err ? <span className="dim">mirror unavailable: {err}</span> : tail ? (text ? highlight(text, q) : <span className="dim">(pane is empty)</span>)
        : <span className="dim">reading the pane…</span>}
    </pre>
    <form className={`claude-input${question ? " is-jay" : ""}`} onSubmit={send}>
      {question ? <span className="ro-tag is-live" title={question.question}>ANSWER</span>
        : <span className="ro-tag">{status === "working" ? "WORKING" : "MESSAGE"}</span>}
      {question && <span className="muted trunc claude-q" title={question.question}>{question.question}</span>}
      <input className="input grow" value={msg} onChange={(e) => setMsg(e.target.value)} maxLength={question ? 2000 : 8000}
        disabled={!question && status === "working"}
        placeholder={question ? "One line, typed into the question" : status === "working" ? "Claude is working — wait, or press Esc to interrupt"
          : dev ? `Message ${name}` : "Sending a message needs Developer Mode"}
        aria-label={question ? `Answer for ${name}` : `Message for ${name}`} />
      <button type="submit" className={`btn is-sm${question ? " is-jay" : ""}`} disabled={!msg.trim() || (!question && status === "working")}>{question ? "Answer" : "Send"}</button>
      <button type="button" className="btn is-quiet is-sm" title="Press Esc in the Claude pane (interrupt)" onClick={async () => {
        if (!dev) { unlockDialogOpen(); return; }
        if (window.confirm(`Send Esc to ${name}? It interrupts what Claude is doing.`)) await app.action(() => app.api.key(agent.id, "esc"), "Esc sent");
      }}>Esc</button>
      <span className="mono-xs faint">{at ? `read ${hms(at)}` : ""}{tail?.redactions ? ` · ${tail.redactions} redacted` : ""}</span>
    </form>
  </div>;
}
