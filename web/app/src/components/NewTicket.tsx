// Capture in under five seconds: N, type a title, Enter. Project remembers the last one.
import { useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { prefs } from "../lib/prefs";
import { go, useRoute } from "../lib/router";
import { Dialog } from "./Dialog";
import { PRIORITIES, ROLES, type Priority } from "../api/types";
import { PRIORITY_META } from "../tickets/model";

export function NewTicket({ onClose, defaults }: { onClose: () => void; defaults?: { parent?: string; project?: string } }) {
  const projects = useSelector(app.store, (d) => d.taskProjects);
  const route = useRoute();
  const routeProject = route.screen === "projects" ? route.id : route.params.get("project");
  const [project, setProject] = useState(defaults?.project ?? routeProject ?? prefs.get().lastProject ?? projects[0]?.key ?? "");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState<Priority>("NO_PRIORITY");
  const [assignee, setAssignee] = useState("");
  const [needsJay, setNeedsJay] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim() || !project || busy) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = { project, title: title.trim() };
      if (priority !== "NO_PRIORITY") body.priority = priority;
      if (assignee) body.assignee = assignee;
      if (needsJay) body.needs_jay = true;
      if (defaults?.parent) body.parent = defaults.parent;
      const t = await app.api.createTask(body as { project: string; title: string });
      app.putTicket(t);
      prefs.patch({ lastProject: project });
      app.toast(`${t.key} created`, "ok");
      onClose();
      if (open) go("tasks", t.key);
    } catch (e) {
      setErr((e as Error).message);
    } finally { setBusy(false); }
  };

  return <Dialog title={defaults?.parent ? `New subtask of ${defaults.parent}` : "New task"} onClose={onClose}
    footer={<>
      <label className="row muted" style={{ fontSize: "var(--fs-xs)" }}><input type="checkbox" checked={open} onChange={(e) => setOpen(e.target.checked)} /> Open after create</label>
      <span className="muted mono-xs" style={{ marginLeft: "auto" }}>Enter create · Esc cancel</span>
      <button type="button" className="btn is-primary" onClick={submit} disabled={!title.trim() || !project || busy}>Create</button>
    </>}>
    <form onSubmit={(e) => { e.preventDefault(); void submit(); }} style={{ display: "grid", gap: 10 }}>
      <div className="np-row">
        <select className="select" value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project" required>
          {projects.map((p) => <option key={p.key} value={p.key}>{p.prefix} · {p.name}</option>)}
        </select>
        <input data-autofocus data-unsaved-guard className="input np-title" value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Title — what needs to happen" aria-label="Title" maxLength={300} required />
      </div>
      <div className="np-opts">
        <select className="fsel" value={priority} onChange={(e) => setPriority(e.target.value as Priority)} aria-label="Priority">
          {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
        </select>
        <select className="fsel" value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assignee">
          <option value="">Unassigned</option><option value="jay">Jay (human)</option>
          {ROLES.map((r) => <option key={r} value={`role:${r}`}>{r.toLowerCase()} (agent role)</option>)}
        </select>
        <button type="button" className="fchip is-jay" aria-pressed={needsJay} onClick={() => setNeedsJay((v) => !v)}>needs:jay</button>
        <span className="muted mono-xs" style={{ alignSelf: "center" }}>Lands in INBOX. Everything else can wait.</span>
      </div>
      {err && <div className="bad-t" role="alert">{err}</div>}
      <button type="submit" hidden />
    </form>
  </Dialog>;
}
