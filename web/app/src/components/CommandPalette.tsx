// Ctrl+K. Navigation and SAFE actions only: no merge, deploy, or anything ccd refuses.
import { useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { prefs } from "../lib/prefs";
import { go, parse } from "../lib/router";
import { scoreAll } from "../lib/fuzzy";
import { useFocusTrap } from "./Dialog";
import { NAV } from "./Shell";
import { workspace } from "../workspace/transport";
import { STATUS_META } from "../tickets/model";
import { nativeUri } from "../workspace/Native";

export type PalKind = "ACTION" | "GO" | "PROJECT" | "AGENT" | "TASK" | "PR" | "SPACE";
export interface PalItem { id: string; kind: PalKind; label: string; hint?: string; keywords?: string; key?: string; run: () => void }

/** The ticket and project the Workspace is showing, read from the address when the command runs. */
function currentWorkspace(): { project: string | null; ticket: string | null } {
  const r = parse(location.hash);
  const onWs = r.screen === "workspace" || r.screen === "console" || r.screen === "files";
  const ticket = onWs ? r.params.get("ticket") ?? r.params.get("task") : null;
  const t = ticket ? app.data.tickets.find((x) => x.key === ticket) : null;
  return { ticket, project: (onWs && r.params.get("project")) || t?.project || prefs.get().consoleProject || app.data.state?.projects[0]?.key || null };
}

export function buildItems(onNewTask: () => void): PalItem[] {
  const d = app.data, st = d.state;
  const items: PalItem[] = [
    { id: "a:new", kind: "ACTION", label: "New ticket", hint: "N", keywords: "create task capture", run: onNewTask },
    { id: "a:theme", kind: "ACTION", label: "Toggle light / dark", run: () => prefs.patch({ theme: prefs.get().theme === "dark" ? "light" : "dark" }) },
    { id: "a:density", kind: "ACTION", label: "Toggle compact rows (28 px)", run: () => prefs.patch({ density: prefs.get().density === "compact" ? "comfortable" : "compact" }) },
    { id: "a:needs", kind: "ACTION", label: "Show what needs Jay", keywords: "needs jay queue", run: () => go("tasks", null, { view: "jay" }) },
    { id: "a:import", kind: "ACTION", label: "Task migration preview (read-only)", keywords: "import migrate", run: () => go("settings", null, { tab: "import" }) },
    // Workspace: keyboard-first development
    ...([["Open Files", {}, "files ide editor explorer upload"], ["Explorer", { side: "explorer" }, "files tree sidebar"],
      ["Source Control", { side: "scm" }, "git diff stage commit branch sidebar"], ["Search", { side: "search", search: true }, "ctrl+shift+f grep find text sidebar"],
      ["Go to file", { goto: true }, "ctrl+p file open"], ["Open Claude", { term: "claude" }, "coordinator dock terminal"],
      ["Open Project terminal", { term: "repo" }, "repo shell bash dock"], ["Open Server terminal", { term: "server" }, "shell bash home dock"],
      ["Development", { dev: true }, "ticket trail commits pr ci"],
    ] as [string, Record<string, unknown>, string][]).map(([label, detail, kw], i) => ({ id: `w:${i}`, kind: "ACTION" as const, label,
      hint: label === "Go to file" ? "Ctrl P" : label === "Search" ? "Ctrl ⇧ F" : i > 0 ? "Files" : undefined, keywords: `files ${kw}`,
      run: () => { if (!location.hash.startsWith("#/files")) go("files"); setTimeout(() => window.dispatchEvent(new CustomEvent("cc:workspace", { detail })), 50); } })),
    // The Workspace's current ticket or project (from the address, then the last project used).
    { id: "w:gh", kind: "ACTION", label: "Open GitHub", hint: "current project", keywords: "workspace github repo", run: () => {
      const cur = currentWorkspace(), url = st?.projects.find((x) => x.key === cur.project)?.repoUrl;
      if (url) window.open(url, "_blank", "noopener,noreferrer"); else app.toast("No GitHub repository for this project", "bad");
    } },
    { id: "w:pr", kind: "ACTION", label: "Open PR", hint: "current ticket", keywords: "workspace pull request github", run: () => {
      const cur = currentWorkspace();
      const url = (cur.ticket ? d.development?.rows.find((r) => r.key === cur.ticket)?.pr?.url : null)
        ?? (cur.ticket ? st?.projects.flatMap((x) => x.prs).find((pr) => pr.branch && pr.branch === d.tickets.find((t) => t.key === cur.ticket)?.branch)?.url : null);
      if (url) window.open(url, "_blank", "noopener,noreferrer"); else app.toast(cur.ticket ? `${cur.ticket} has no PR yet` : "Open Workspace from a ticket to open its PR", "bad");
    } },
    // Native Windows Terminal (CommandCenter.exe 0.3.0): allowlisted actions only.
    ...(() => {
      const key = prefs.get().consoleProject ?? st?.projects[0]?.key ?? null;
      const prefix = st?.projectsConfig.find((p) => p.key === key)?.prefix ?? null;
      const name = st?.projects.find((p) => p.key === key)?.name ?? key ?? "";
      return ([["Claude in Windows Terminal", nativeUri("claude", prefix), name], ["Project in Windows Terminal", nativeUri("repo", prefix), name],
        ["Server in Windows Terminal", nativeUri("server"), "jay-server"]] as [string, string | null, string][])
        .filter(([, uri]) => uri).map(([label, uri, hint], i) => ({ id: `nt:${i}`, kind: "ACTION" as const, label, hint,
          keywords: "native windows terminal ssh wt", run: () => { location.href = uri!; } }));
    })(),
    ...NAV.map((s) => ({ id: `go:${s.id}`, kind: "GO" as const, label: s.label, hint: s.key, run: () => go(s.id) })),
    // Diagnostics: no longer primary navigation, still one command away (and under Settings → Diagnostics).
    ...([["projects", "Projects"], ["development", "Development"], ["agents", "Agents"], ["server", "Server"], ["alerts", "Alerts"],
      ["prs", "Pull requests"], ["workspaces", "herdr layout"]] as [string, string][]).map(([id, label]) => ({ id: `go:${id}`,
      kind: "GO" as const, label, hint: "diagnostics", keywords: "ops diagnostics", run: () => go(id) })),
  ];
  for (const p of st?.projects ?? []) {
    items.push({ id: `p:${p.key}`, kind: "PROJECT", label: p.name, hint: p.key, keywords: `${p.key} ${p.repo}`, run: () => go("projects", p.key) });
    items.push({ id: `pw:${p.key}`, kind: "ACTION", label: `Open ${p.name}`, hint: "Workspace", keywords: `${p.key} workspace open project`,
      run: () => { prefs.patch({ consoleProject: p.key }); go("workspace", null, { project: p.key }); } });
    if (p.repoUrl) items.push({ id: `gh:${p.key}`, kind: "ACTION", label: `Open ${p.name} on GitHub`, hint: p.repo, keywords: `${p.key} github repo`,
      run: () => window.open(p.repoUrl!, "_blank", "noopener,noreferrer") });
    const c = st?.coordinators[p.key];
    if (c?.paneId) {
      items.push({ id: `fc:${p.key}`, kind: "ACTION", label: `Focus ${p.name} coordinator`, hint: c.name,
        keywords: `${p.key} coordinator focus herdr`, run: () => void workspace.focusAgent(c.paneId!) });
    }
  }
  for (const a of st?.agents ?? []) {
    const proj = st?.projects.find((p) => p.key === a.project)?.name ?? a.project ?? "";
    items.push({ id: `ag:${a.id}`, kind: "AGENT", label: `${proj} / ${a.agent_name || a.role}`, hint: `${a.id} · ${a.status}`,
      keywords: `${a.agent_name} ${a.project} ${a.role} ${a.status}`, run: () => go("agents", a.id) });
  }
  for (const w of st?.workspaces ?? []) {
    items.push({ id: `ws:${w.id}`, kind: "SPACE", label: `Open ${w.label || w.id} workspace`, hint: w.id,
      keywords: `workspace ${w.project ?? ""} ${w.label}`, run: () => go("workspaces", w.id) });
  }
  for (const t of d.tickets) {
    if (t.archived) continue;
    items.push({ id: `t:${t.key}`, kind: "TASK", label: `${t.key} ${t.title}`, hint: STATUS_META[t.status]?.label, key: t.key,
      keywords: `${t.project} ${t.labels.join(" ")}`, run: () => go("tasks", t.key) });
    if (!["DONE", "DENIED", "CANCELLED"].includes(t.status))
      items.push({ id: `tw:${t.key}`, kind: "ACTION", label: `Open ${t.key} Task Room`, hint: t.title,
        keywords: `${t.project} workspace room`, run: () => go("workspace", null, { task: t.key, open: "1" }) });
  }
  for (const p of st?.projects ?? []) {
    for (const pr of p.prs) {
      items.push({ id: `pr:${p.key}:${pr.number}`, kind: "PR", label: `#${pr.number} ${pr.title}`, hint: p.name, key: `#${pr.number}`,
        keywords: `${p.key} ${pr.ref} ${pr.branch ?? ""}`, run: () => go("prs", `${p.key}#${pr.number}`) });
      if (pr.url) items.push({ id: `prg:${p.key}:${pr.number}`, kind: "ACTION", label: `Open PR #${pr.number} on GitHub`, hint: p.name,
        keywords: `${p.key} pr github ${pr.title}`, run: () => window.open(pr.url!, "_blank", "noopener,noreferrer") });
    }
  }
  return items;
}

const ORDER: Record<PalKind, number> = { ACTION: 0, PROJECT: 1, AGENT: 2, SPACE: 3, TASK: 4, PR: 5, GO: 6 };

export function rank(items: PalItem[], q: string, limit = 40): PalItem[] {
  if (!q.trim()) return items.filter((i) => i.kind === "ACTION" || i.kind === "GO").slice(0, limit);
  const exact = q.trim().toLowerCase();
  return items.map((i) => ({ i, s: i.key && i.key.toLowerCase() === exact ? 10_000 : scoreAll(q, [i.label, i.hint ?? "", i.keywords ?? ""]) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || ORDER[a.i.kind] - ORDER[b.i.kind])
    .slice(0, limit).map((x) => x.i);
}

export function CommandPalette({ onClose, onNewTask }: { onClose: () => void; onNewTask: () => void }) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const items = useMemo(() => buildItems(onNewTask), [onNewTask]);
  const shown = useMemo(() => rank(items, q), [items, q]);
  const ref = useFocusTrap(onClose);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => setI(0), [q]);
  useEffect(() => { list.current?.querySelector(`[data-i="${i}"]`)?.scrollIntoView({ block: "nearest" }); }, [i]);
  const run = (it?: PalItem) => { if (!it) return; onClose(); it.run(); };
  return <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette" ref={ref}>
      <div className="palette-input"><span className="prompt" aria-hidden>&gt;</span>
        <input data-autofocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Jump to a project, agent, task, PR — or run an action"
          role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={shown[i] ? `pal-${shown[i].id}` : undefined}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setI((v) => Math.min(shown.length - 1, v + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setI((v) => Math.max(0, v - 1)); }
            else if (e.key === "Enter") { e.preventDefault(); run(shown[i]); }
          }} /></div>
      <div className="palette-list" id="pal-list" role="listbox" ref={list} aria-label="Results">
        {shown.length === 0 && <div className="empty">No match. Try a project, a key like SV-056, or #94.</div>}
        {shown.map((it, n) => <div key={it.id} id={`pal-${it.id}`} data-i={n} role="option" aria-selected={n === i}
          className="pal-item" onMouseMove={() => setI(n)} onMouseDown={(e) => { e.preventDefault(); run(it); }}>
          <span className={`pal-kind${it.kind === "ACTION" || it.kind === "SPACE" ? " is-action" : ""}`}>{it.kind}</span>
          <span className="trunc">{it.label}</span><span className="pal-hint">{it.hint}</span></div>)}
      </div>
      <div className="palette-foot"><span>↑↓ move</span><span>Enter run</span><span>Esc close</span>
        <span style={{ marginLeft: "auto" }}>Merge and deploy are not here, by design.</span></div>
    </div>
  </div>;
}
