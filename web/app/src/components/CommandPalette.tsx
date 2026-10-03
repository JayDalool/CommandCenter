// Ctrl+K. Navigation and SAFE actions only: no merge, deploy, or anything ccd refuses.
import { useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { prefs } from "../lib/prefs";
import { go } from "../lib/router";
import { scoreAll } from "../lib/fuzzy";
import { useFocusTrap } from "./Dialog";
import { NAV } from "./Shell";
import { workspace } from "../workspace/transport";
import { STATUS_META } from "../tickets/model";

export type PalKind = "ACTION" | "GO" | "PROJECT" | "AGENT" | "TASK" | "PR" | "SPACE";
export interface PalItem { id: string; kind: PalKind; label: string; hint?: string; keywords?: string; key?: string; run: () => void }

export function buildItems(onNewTask: () => void): PalItem[] {
  const d = app.data, st = d.state;
  const items: PalItem[] = [
    { id: "a:new", kind: "ACTION", label: "New task", hint: "N", keywords: "create ticket capture", run: onNewTask },
    { id: "a:console", kind: "ACTION", label: "Toggle quick console", hint: "`", run: () => prefs.patch({ consoleOpen: !prefs.get().consoleOpen }) },
    { id: "a:theme", kind: "ACTION", label: "Toggle light / dark", run: () => prefs.patch({ theme: prefs.get().theme === "dark" ? "light" : "dark" }) },
    { id: "a:density", kind: "ACTION", label: "Toggle compact rows (28 px)", run: () => prefs.patch({ density: prefs.get().density === "compact" ? "comfortable" : "compact" }) },
    { id: "a:needs", kind: "ACTION", label: "Show what needs Jay", keywords: "needs jay queue", run: () => go("tasks", null, { view: "jay" }) },
    { id: "a:import", kind: "ACTION", label: "Task migration preview (read-only)", keywords: "import migrate", run: () => go("settings", null, { tab: "import" }) },
    ...NAV.map((s, i) => ({ id: `go:${s.id}`, kind: "GO" as const, label: s.label, hint: String(i < 9 ? i + 1 : 0), run: () => go(s.id) })),
  ];
  for (const p of st?.projects ?? []) {
    items.push({ id: `p:${p.key}`, kind: "PROJECT", label: p.name, hint: p.key, keywords: `${p.key} ${p.repo}`, run: () => go("projects", p.key) });
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
  }
  for (const p of st?.projects ?? []) {
    for (const pr of p.prs) {
      items.push({ id: `pr:${p.key}:${pr.number}`, kind: "PR", label: `#${pr.number} ${pr.title}`, hint: p.name, key: `#${pr.number}`,
        keywords: `${p.key} ${pr.ref} ${pr.branch ?? ""}`, run: () => go("prs", `${p.key}#${pr.number}`) });
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
