// The bottom bar is a LAUNCHER and a status line, not a terminal. Real terminal
// work happens on the Console page; this says what the selected project's
// coordinator is doing and gets Jay there in one key.
import { useEffect } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { prefs, usePrefs, commands } from "../lib/prefs";
import { go, href } from "../lib/router";
import { AgentState, Copy, Project } from "./ui";

export function QuickConsole({ hidden }: { hidden: boolean }) {
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const sel = usePrefs((p) => p.consoleAgent);
  const host = usePrefs((p) => p.sshHost);
  const agents = st?.agents ?? null;
  const agent = agents?.find((a) => a.id === sel) ?? agents?.find((a) => a.status === "blocked")
    ?? agents?.find((a) => a.status === "working") ?? agents?.[0] ?? null;
  const ticket = agent ? tickets.find((t) => t.agentPaneId === agent.id) ?? null : null;
  const name = agent?.agent_name || agent?.id || "";

  useEffect(() => {
    const open = (e: Event) => { prefs.patch({ consoleOpen: true, consoleAgent: (e as CustomEvent).detail }); };
    window.addEventListener("cc:console", open);
    return () => window.removeEventListener("cc:console", open);
  }, []);

  if (hidden) return <section className="console" hidden aria-label="Quick console" />;
  const blocked = agent && st?.blocked.find((b) => b.pane_id === agent.id);
  return <section className="quickbar" aria-label="Quick console">
    <select className="select" aria-label="Agent" value={agent?.id ?? ""}
      onChange={(e) => prefs.patch({ consoleAgent: e.target.value })}>
      {agents?.map((a) => <option key={a.id} value={a.id}>{a.agent_name || a.id} · {a.project ?? "?"} · {a.status}</option>)}
      {!agents?.length && <option value="">no live agents</option>}
    </select>
    {agent ? <>
      {ticket ? <a className="key" href={href("tasks", ticket.key)}>{ticket.key}</a> : null}
      <Project k={agent.project} />
      <AgentState status={agent.status} />
      {blocked && <span className="trunc muted" style={{ maxWidth: "28%" }} title={blocked.question}>{blocked.question}</span>}
      <span className="mono-xs faint trunc" title={agent.cwd ?? ""}>{agent.cwd ?? ""}</span>
      <span className="sl-fill" />
      <button type="button" className="btn is-sm is-jay" onClick={() => go("console", null,
        { tab: "claude", project: agent.project ?? undefined, ticket: ticket?.key })}>Open console</button>
      <button type="button" className="btn is-sm" onClick={() => void app.action(() => app.api.focusAgent(agent.id),
        `Focused ${name} in herdr`)}>Focus Claude</button>
      <button type="button" className="btn is-sm" onClick={() => go("console", null,
        { tab: "repo", project: agent.project ?? undefined, ticket: ticket?.key })}>Repo shell</button>
      <Copy text={commands.attachAgent(host, name)} label="Copy attach" />
    </> : <>
      <span className="muted">No live agent. herdr owns every Claude pane; start one there.</span>
      <span className="sl-fill" />
      <button type="button" className="btn is-sm" onClick={() => go("console")}>Open console</button>
    </>}
    <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ consoleOpen: false })}
      aria-label="Close quick console">Close `</button>
  </section>;
}
