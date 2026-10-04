// CONSOLE — Jay's way into jay-server from the browser, in three modes.
//
//   CLAUDE        a live mirror of the project's real coordinator pane. herdr
//                 owns that pane; opening this page never starts a session and
//                 closing the browser cannot end one.
//   REPO SHELL    a shell rooted in the project's repository
//   SERVER SHELL  a general shell in $HOME
//
// The two shells need a PTY that ccd does not have yet (docs/adr/0004). Until
// Jay approves that, they show the exact command and say plainly what is
// missing. Nothing here pretends to be a terminal it is not: the Claude mirror
// is labelled READ-ONLY, and the shells are labelled NOT ENABLED.
import { useCallback, useEffect, useRef, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { prefs, usePrefs, commands } from "../lib/prefs";
import { href, go, useRoute } from "../lib/router";
import { hms } from "../lib/time";
import type { Agent, Tail } from "../api/types";
import { AgentState, Command, EmptyState, Kbd, Project, StatusDot } from "../components/ui";
import { workspace } from "../workspace/transport";

type Tab = "claude" | "repo" | "server";
const TABS: { id: Tab; label: string }[] = [
  { id: "claude", label: "Claude" }, { id: "repo", label: "Repo shell" }, { id: "server", label: "Server shell" },
];
/** How often the Claude mirror re-reads the pane while it is on screen. */
const MIRROR_MS = 2500;
const MIRROR_LINES = 200;

function useVisible() {
  const [vis, setVis] = useState(typeof document === "undefined" || document.visibilityState === "visible");
  useEffect(() => {
    const on = () => setVis(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return vis;
}

/** The project, ticket, repo, branch and coordinator the Console is pointed at. */
function useConsoleContext() {
  const route = useRoute();
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const saved = usePrefs((p) => p.consoleProject);
  const qp = route.params.get("project");
  const qt = route.params.get("ticket");
  const ticket = qt ? tickets.find((t) => t.key === qt) ?? null : null;
  const key = qp || ticket?.project || saved || st?.projects[0]?.key || null;
  const project = st?.projects.find((p) => p.key === key) ?? null;
  const cfg = st?.projectsConfig.find((p) => p.key === key) ?? null;
  const coordinator = key ? st?.coordinators?.[key] ?? null : null;
  const agent = coordinator?.paneId
    ? st?.agents.find((a) => a.id === coordinator.paneId) ?? null
    : st?.agents.find((a) => a.project === key && a.role === "coordinator") ?? null;
  // A ticket's branch is the one piece of context the repo shell would start from.
  const branch = ticket?.branch || cfg?.branch || null;
  return { key, project, cfg, coordinator, agent, ticket, branch, ticketKey: qt };
}

function Header({ rows }: { rows: { label: string; value: React.ReactNode; title?: string }[] }) {
  return <div className="con-head" role="group" aria-label="Console context">
    {rows.map((r) => <div key={r.label} className="con-cell" title={r.title}>
      <span className="caps muted">{r.label}</span>
      <span className="con-val">{r.value}</span></div>)}
  </div>;
}

export function ClaudeMirror({ agent, name }: { agent: Agent | null; name: string }) {
  const visible = useVisible();
  const follow = usePrefs((p) => p.consoleFollow);
  const blocked = useSelector(app.store, (d) => d.state?.blocked ?? null);
  const [tail, setTail] = useState<Tail | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const pre = useRef<HTMLPreElement>(null);
  const id = agent?.id ?? null;

  const read = useCallback(async () => {
    if (!id) return;
    try { setTail(await app.api.tail(id, MIRROR_LINES)); setAt(Date.now() / 1000); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, [id]);

  // Poll only while this view is on screen and the document is visible: herdr
  // has no output stream, so the mirror is a read, and an unattended tab must
  // not keep reading a pane nobody is looking at (docs/adr/0004).
  useEffect(() => {
    if (!id || !visible || !follow) return;
    void read();
    const t = setInterval(() => void read(), MIRROR_MS);
    return () => clearInterval(t);
  }, [id, visible, follow, read]);
  useEffect(() => { setTail(null); setErr(null); }, [id]);
  useEffect(() => { if (follow && pre.current) pre.current.scrollTop = pre.current.scrollHeight; }, [tail, follow]);

  if (!agent) {
    return <div className="con-term is-empty"><EmptyState title={`No coordinator running for ${name}`}
      hint="herdr owns Claude panes. Start the coordinator in herdr; Command Center never starts one." /></div>;
  }
  const q = blocked?.find((b) => b.pane_id === agent.id);
  return <>
    <pre className="con-term" ref={pre} aria-label={`${name} output, read-only`} tabIndex={0}>
      {err ? <span className="dim">mirror unavailable: {err}</span>
        : tail ? tail.text || <span className="dim">(pane is empty)</span>
          : <span className="dim">reading the pane…</span>}
    </pre>
    {q ? <form className="con-foot is-jay" onSubmit={async (e) => {
      e.preventDefault();
      if (!answer.trim()) return;
      const ok = await app.action(() => app.api.answer(agent.id, answer.trim()), `Answer sent to ${name}`);
      if (ok) { setAnswer(""); void read(); }
    }}>
      <span className="ro-tag is-live">ANSWER</span>
      <span className="muted trunc" style={{ maxWidth: "35%" }} title={q.question}>{q.question}</span>
      <input className="input grow" value={answer} onChange={(e) => setAnswer(e.target.value)} maxLength={2000}
        aria-label={`Answer for ${name}: one line, typed into the blocked agent`}
        placeholder="One line, typed into the blocked agent" />
      <button type="submit" className="btn is-jay is-sm" disabled={!answer.trim()}>Send</button>
    </form> : <div className="con-foot">
      <span className="ro-tag" title="Read from herdr on demand, credential-shaped strings redacted, never stored.">READ-ONLY MIRROR</span>
      <span className="mono-xs muted">last {MIRROR_LINES} lines · refreshed every {MIRROR_MS / 1000}s while visible
        {tail?.redactions ? ` · ${tail.redactions} redacted` : ""}</span>
      <span className="mono-xs faint" style={{ marginLeft: "auto" }}>{at ? `read ${hms(at)}` : ""}</span>
      <button type="button" className="btn is-quiet is-sm" aria-pressed={follow}
        onClick={() => prefs.patch({ consoleFollow: !follow })}>{follow ? "Following" : "Paused"}</button>
      <button type="button" className="btn is-sm" onClick={() => void read()}>Read now</button>
    </div>}
  </>;
}

/** A shell ccd cannot open yet. It says so, and gives the command that works today. */
function ShellPlaceholder({ kind, cwd, cmd }: { kind: "repo" | "server"; cwd: string; cmd: string }) {
  return <div className="con-term is-empty">
    <div className="con-notyet">
      <div className="row" style={{ gap: 8 }}><span className="ro-tag is-off">NOT ENABLED</span>
        <span className="caps muted">{kind === "repo" ? "repo shell" : "server shell"}</span></div>
      <p className="text2">An interactive shell in the browser needs a PTY service inside ccd and a WebSocket
        to carry it. That is designed and reviewed but not built: it is the one change here that would let
        anything holding the ccd token run commands, so it waits for Jay.</p>
      <p className="mono-xs muted">docs/adr/0004-console-and-real-terminals.md · phase 3</p>
      <div className="caps muted" style={{ marginTop: 10 }}>This shell, today</div>
      <Command cmd={cmd} />
      <div className="mono-xs faint">opens in {cwd}</div>
    </div>
  </div>;
}

export function Console() {
  const route = useRoute();
  const ctx = useConsoleContext();
  const st = useSelector(app.store, (d) => d.state);
  const host = usePrefs((p) => p.sshHost);
  const full = usePrefs((p) => p.consoleFull);
  const savedTab = usePrefs((p) => p.consoleTab);
  const tab = (route.params.get("tab") as Tab) || savedTab;
  const herdrOk = st?.sources.herdr.ok ?? false;

  const setTab = (t: Tab) => {
    prefs.patch({ consoleTab: t });
    go("console", null, { tab: t, project: ctx.key ?? undefined, ticket: ctx.ticketKey ?? undefined });
  };
  // Changing project is deliberate and explicit: it never happens on its own.
  const setProject = (k: string) => {
    prefs.patch({ consoleProject: k });
    go("console", null, { tab, project: k });
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && prefs.get().consoleFull) prefs.patch({ consoleFull: false });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!st) return <EmptyState title="Loading…" />;
  const name = ctx.agent?.agent_name || ctx.coordinator?.name || ctx.key || "—";
  const cwd = ctx.agent?.cwd || ctx.cfg?.path || "—";
  const repoPath = ctx.cfg?.path || "—";
  const headers = tab === "claude" ? [
    { label: "Project", value: <Project k={ctx.key} name={ctx.project?.name} /> },
    { label: "Claude session", value: <span className="mono">{name}</span>,
      title: ctx.coordinator?.canonical === false ? "not running under its canonical name" : undefined },
    { label: "Model", value: <span className="mono-xs">{ctx.cfg?.model || "—"}</span> },
    { label: "Agent state", value: ctx.agent ? <AgentState status={ctx.agent.status} /> : <AgentState status="offline" /> },
    { label: "Herdr pane", value: <span className="mono-xs">{ctx.agent?.id ?? "—"}</span> },
    { label: "cwd", value: <span className="mono-xs trunc" title={cwd}>{cwd}</span> },
  ] : tab === "repo" ? [
    { label: "Project", value: <Project k={ctx.key} name={ctx.project?.name} /> },
    { label: "Repository", value: <span className="mono-xs">{ctx.cfg?.repo || "—"}</span> },
    { label: "Branch", value: <span className="mono-xs">{ctx.branch || "—"}</span> },
    { label: "Ticket", value: ctx.ticketKey
      ? <a className="key" href={href("tasks", ctx.ticketKey)}>{ctx.ticketKey}</a> : <span className="faint">—</span> },
    { label: "cwd", value: <span className="mono-xs trunc" title={repoPath}>{repoPath}</span> },
  ] : [
    { label: "Host", value: <span className="mono">jay-server</span> },
    { label: "Scope", value: <span className="text2">whole server, not a repository</span> },
    { label: "cwd", value: <span className="mono-xs">~</span> },
  ];

  return <div className={`console-page${full ? " is-full" : ""}`}>
    <div className="con-bar">
      <div className="tabs" role="tablist" aria-label="Console mode">
        {TABS.map((t) => <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
          className="tab" onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      {tab !== "server" && <label className="row" style={{ gap: 6 }}>
        <span className="caps muted">Project</span>
        <select className="select" aria-label="Console project" value={ctx.key ?? ""}
          onChange={(e) => setProject(e.target.value)}>
          {(st?.projects ?? []).map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
        </select>
      </label>}
      {ctx.ticketKey && <a className="key" href={href("tasks", ctx.ticketKey)}>{ctx.ticketKey}</a>}
      <span className="sl-fill" />
      <button type="button" className="btn is-quiet is-sm" aria-pressed={full}
        onClick={() => prefs.patch({ consoleFull: !full })}>
        {full ? <>Exit full screen <Kbd>Esc</Kbd></> : "Full screen"}</button>
    </div>
    <Header rows={headers} />
    <div className="con-body">
      {tab === "claude" && <ClaudeMirror agent={ctx.agent} name={name} />}
      {tab === "repo" && <ShellPlaceholder kind="repo" cwd={repoPath} cmd={commands.repoShell(host, repoPath)} />}
      {tab === "server" && <ShellPlaceholder kind="server" cwd="~" cmd={commands.serverShell(host)} />}
    </div>
    <div className="con-status">
      <span className={`sl-seg is-${herdrOk ? "live" : "down"}`}><StatusDot tone={herdrOk ? "working" : "failed"} />
        <b>herdr</b><span className="sl-state">{herdrOk ? "connected" : "unreachable"}</span></span>
      <span className="sl-seg"><b>cwd</b><span className="mono-xs">{tab === "server" ? "~" : repoPath}</span></span>
      {tab !== "server" && <span className="sl-seg"><b>branch</b><span className="mono-xs">{ctx.branch || "—"}</span></span>}
      <span className="sl-fill" />
      {tab === "claude" && ctx.agent && <>
        <button type="button" className="btn is-sm" onClick={() => workspace.focusAgent(ctx.agent!.id)}>Focus in herdr</button>
        <span className="cmd-inline"><Command cmd={commands.attachAgent(host, name)} /></span>
      </>}
    </div>
  </div>;
}
