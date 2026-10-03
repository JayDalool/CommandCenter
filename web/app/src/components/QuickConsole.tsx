// The bottom console. Browser mode is honest: a READ-ONLY tail fetched on
// demand, the few safe actions ccd allows, and the exact command that opens
// the real interactive terminal in herdr. It never pretends to be a shell.
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { prefs, usePrefs, commands } from "../lib/prefs";
import type { Tail } from "../api/types";
import { AgentState, Command, Project } from "./ui";
import { workspace } from "../workspace/transport";
import { hms } from "../lib/time";

export function QuickConsole({ hidden }: { hidden: boolean }) {
  const agents = useSelector(app.store, (d) => d.state?.agents ?? null);
  const blocked = useSelector(app.store, (d) => d.state?.blocked ?? null);
  const sel = usePrefs((p) => p.consoleAgent);
  const host = usePrefs((p) => p.sshHost);
  const agent = agents?.find((a) => a.id === sel) ?? agents?.[0] ?? null;
  const [tail, setTail] = useState<Tail | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  const read = async () => {
    if (!agent) return;
    setBusy(true);
    try { setTail(await app.api.tail(agent.id, 60)); setAt(Date.now() / 1000); setErr(null); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  useEffect(() => { setTail(null); setErr(null); if (!hidden && agent) void read(); }, [agent?.id, hidden]);
  useEffect(() => {
    const open = (e: Event) => { prefs.patch({ consoleOpen: true, consoleAgent: (e as CustomEvent).detail }); };
    window.addEventListener("cc:console", open);
    return () => window.removeEventListener("cc:console", open);
  }, []);

  if (hidden) return <section className="console" hidden aria-label="Quick console" />;
  const q = agent && blocked?.find((b) => b.pane_id === agent.id);
  const name = agent?.agent_name || agent?.id || "";
  return <section className="console" aria-label="Quick console">
    <div className="console-side">
      <div className="caps muted">Agent</div>
      <select className="select" aria-label="Agent" value={agent?.id ?? ""} onChange={(e) => prefs.patch({ consoleAgent: e.target.value })}>
        {agents?.map((a) => <option key={a.id} value={a.id}>{a.agent_name || a.id} · {a.project ?? "?"} · {a.status}</option>)}
      </select>
      {agent && <>
        <div className="row"><AgentState status={agent.status} /><Project k={agent.project} /></div>
        <div className="mono-xs muted trunc" title={agent.cwd}>{agent.cwd}</div>
        <div className="mono-xs faint">pane {agent.id} · {agent.workspace || "—"}</div>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button type="button" className="btn is-sm" onClick={() => workspace.focusAgent(agent.id)}>Focus in herdr</button>
          <button type="button" className="btn is-sm" onClick={read} disabled={busy}>{busy ? "Reading…" : "Read tail"}</button>
        </div>
        <div className="caps muted" style={{ marginTop: 4 }}>Interactive (opens a real terminal)</div>
        <Command cmd={commands.attachAgent(host, name)} />
      </>}
    </div>
    <div className="console-main">
      <div className="console-head">
        <span className="ro-tag" title="Fetched on demand from ccd. Credential-shaped strings are redacted. Never stored.">READ-ONLY TAIL</span>
        <span className="mono-xs muted">{agent ? `${name} · last 60 lines · redacted${tail?.redactions ? ` (${tail.redactions})` : ""}` : "no agent"}</span>
        <span className="mono-xs faint" style={{ marginLeft: "auto" }}>{at ? `read ${hms(at)}` : ""}</span>
        <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ consoleOpen: false })} aria-label="Close console">Close `</button>
      </div>
      <pre className="term" aria-label="Agent output, read-only" tabIndex={0}>{err ? <span className="dim">tail unavailable: {err}</span>
        : tail ? tail.text || <span className="dim">(empty)</span> : <span className="dim">Select an agent and read its tail.</span>}</pre>
      {q ? <form className="console-foot" onSubmit={async (e) => {
        e.preventDefault();
        if (!agent || !answer.trim()) return;
        const ok = await app.action(() => app.api.answer(agent.id, answer.trim()), `Answer sent to ${name}`);
        if (ok) { setAnswer(""); void read(); }
      }}>
        <span className="ro-tag is-live">ANSWER</span>
        <span className="muted trunc" style={{ maxWidth: "40%" }} title={q.question}>{q.question}</span>
        <input className="input grow" value={answer} onChange={(e) => setAnswer(e.target.value)} maxLength={2000}
          aria-label={`Answer for ${name} (one line, typed into the blocked agent)`} placeholder="One line, sent to the blocked agent" />
        <button type="submit" className="btn is-jay is-sm" disabled={!answer.trim()}>Send</button>
      </form> : <div className="console-foot mono-xs muted">
        Read-only view. To type into this agent, run the command on the left in Windows Terminal.</div>}
    </div>
  </section>;
}
