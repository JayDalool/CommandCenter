// The Claude tab of the terminal dock: the project's EXISTING coordinator, attached live.
//
// Which Claude that is comes from ccd's one resolver (ccd/coordid.py), the same one the
// native terminal uses. When it is not sure, this says so plainly and offers the one
// action that fixes it — Adopt the Claude it found, or pick one of several. Nothing here
// starts, resumes or renames Claude.
import { useState } from "react";
import { app } from "../store/app";
import type { Agent, Coordinator, WorkspaceProject } from "../api/types";
import { devOr } from "../components/DevMode";
import { TerminalView } from "./Terminal";
import { nativeUri } from "./Native";
import { workspace } from "./transport";

export function ClaudeDock({ proj, coord, agent, model, active, theme }: {
  proj: WorkspaceProject; coord: Coordinator | null; agent: Agent | null; model: string | null;
  active: boolean; theme: "dark" | "light";
}) {
  const [busy, setBusy] = useState(false);
  // An older ccd without `state` behaves as before: a pane id means ready.
  const state = coord?.state ?? (coord?.paneId ? "ready" : "none");
  const candidates = coord?.candidates ?? [];

  const adopt = async (sessionId: string) => {
    if (!devOr(() => void adopt(sessionId))) return;
    setBusy(true);
    // On success the button stays disabled: the next snapshot turns this tab into the terminal.
    const ok = await app.action(() => app.api.adoptCoordinator(proj.key, sessionId), `${proj.name}: coordinator adopted`);
    if (!ok) setBusy(false);
  };

  if (state !== "ready") {
    const title = state === "found" ? "COORDINATOR FOUND" : state === "multiple" ? "MULTIPLE CLAUDE SESSIONS" : "NO COORDINATOR";
    return <div className="claude-state" role="status" aria-label={`Claude: ${title.toLowerCase()}`}>
      <span className={`ro-tag${state === "none" ? " is-off" : ""}`}>{title}</span>
      {state === "none" && <span className="mono-xs muted">no Claude running in {proj.root ?? proj.name}</span>}
      {state === "found" && candidates[0] && <>
        <span className="mono-xs muted">{candidates[0].paneId} · {candidates[0].status}</span>
        <button type="button" className="btn is-jay is-sm" disabled={busy} onClick={() => void adopt(candidates[0].sessionId)}>Adopt</button>
      </>}
      {state === "multiple" && <ul className="claude-pick" aria-label="Choose the coordinator">
        {candidates.map((c) => <li key={c.sessionId} className="row">
          <span className="mono-xs">{c.paneId}</span><span className="mono-xs muted">{c.status} · {c.sessionId.slice(0, 8)}</span>
          <button type="button" className="btn is-sm" disabled={busy} onClick={() => void adopt(c.sessionId)}>Use this one</button>
        </li>)}
      </ul>}
    </div>;
  }

  const status = coord?.status ?? agent?.status ?? "unknown";
  const info = <span className="row" style={{ gap: 6 }}>
    <span>{coord?.name ?? proj.key}{model ? ` · ${model}` : ""} · {status}</span>
    {status === "blocked" && <span className="ro-tag is-off">BLOCKED</span>}
  </span>;
  const native = nativeUri("claude", proj.prefix);
  // herdr allows one writer per Claude: hand it to Windows Terminal by releasing this attach first.
  const release = () => void app.api.ptyClose(`claude:${proj.prefix}`).catch(() => undefined);
  return <TerminalView key={`claude:${proj.prefix}`} name={`claude:${proj.prefix}`} label={`Claude · ${proj.name}`}
    active={active} theme={theme} info={info}
    closeText={`Close the Claude terminal for ${proj.name}? Only this view closes — Claude keeps running.`}
    menu={[
      { label: "Open in Windows Terminal", href: native ?? undefined, onSelect: release, hidden: !native },
      { label: "Show in herdr", onSelect: () => { if (coord?.paneId) void workspace.focusAgent(coord.paneId); }, hidden: !coord?.paneId },
    ]} />;
}
