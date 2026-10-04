// WORKSPACE — the daily development surface: explorer, editor, and the Claude /
// repo shell / server shell panel, all pointed at one project.
//
// The project comes from the registry (ccd answers /api/workspace/projects); the
// browser never names a filesystem root. Folders load one at a time when opened.
// Saving and uploading need Developer Mode; reading never does. Nothing saves
// on its own: Ctrl+S or Save, and a file changed on disk since it was opened is
// a conflict to resolve, never an overwrite.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import { prefs, usePrefs, commands } from "../lib/prefs";
import { ApiError, uploadBytes } from "../api/client";
import type { FileEntry, FileRead, WorkspaceProject } from "../api/types";
import { stamp } from "../lib/time";
import { AgentState, Command, EmptyState } from "../components/ui";
import { Dialog } from "../components/Dialog";
import { DevBadge, unlockDialogOpen, useDevActive } from "../components/DevMode";
import { bytes } from "../components/Attachments";
import { ClaudeMirror } from "./Console";
import { CodeEditor, type EditorHandle } from "../workspace/Editor";

interface Tab { path: string; file: FileRead; text: string; version: number; dirty: boolean; conflict: string | null }
interface Upload { id: number; name: string; dir: string; f: number; state: "up" | "done" | "fail" | "ask"; msg?: string; file: File }
type Panel = "claude" | "repo" | "server";

const join = (dir: string, name: string) => (dir ? `${dir}/${name}` : name);

function useProjects() {
  const [rows, setRows] = useState<WorkspaceProject[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    app.api.workspaceProjects().then((r) => setRows(r.projects)).catch((e) => setErr((e as Error).message));
  }, []);
  return { rows, err };
}

/** One folder level. Children load when the folder is first opened, never before. */
function Folder({ project, path, depth, open, toggle, onOpen, selected, target, setTarget, listings, load, onDropFiles }: {
  project: string; path: string; depth: number; open: Set<string>; toggle: (p: string) => void;
  onOpen: (p: string, e: FileEntry) => void; selected: string | null; target: string; setTarget: (p: string) => void;
  listings: Record<string, FileEntry[] | string>; load: (p: string) => void; onDropFiles: (dir: string, files: FileList) => void;
}) {
  const rows = listings[path];
  useEffect(() => { if (rows === undefined) load(path); }, [rows, path, load]);
  if (rows === undefined) return <div className="ws-row muted" style={{ paddingLeft: 10 + depth * 14 }}>…</div>;
  if (typeof rows === "string") return <div className="ws-row bad-t" style={{ paddingLeft: 10 + depth * 14 }}>{rows}</div>;
  return <>{rows.map((e) => {
    const p = join(path, e.name);
    const isDir = e.kind === "dir";
    const isOpen = open.has(p);
    return <div key={p}>
      <div role="treeitem" aria-expanded={isDir ? isOpen : undefined} aria-selected={selected === p}
        className={`ws-row${selected === p ? " is-sel" : ""}${target === p ? " is-target" : ""}${e.protected ? " is-protected" : ""}`}
        style={{ paddingLeft: 10 + depth * 14 }} tabIndex={0}
        title={e.protected ? "Protected: secret-looking files are never opened or downloaded here" :
          e.kind === "outside" ? "Symlink that leaves the project — not followed" : `${p}${e.size != null ? ` · ${bytes(e.size)}` : ""}${e.mtime ? ` · ${stamp(e.mtime)}` : ""}`}
        onClick={() => { if (isDir) { toggle(p); setTarget(p); } else onOpen(p, e); }}
        onKeyDown={(ev) => { if (ev.key === "Enter") { if (isDir) toggle(p); else onOpen(p, e); } }}
        onDragOver={(ev) => { if (isDir && ev.dataTransfer.types.includes("Files")) { ev.preventDefault(); ev.stopPropagation(); setTarget(p); } }}
        onDrop={(ev) => { if (isDir && ev.dataTransfer.files.length) { ev.preventDefault(); ev.stopPropagation(); onDropFiles(p, ev.dataTransfer.files); } }}>
        <span className="ws-caret" aria-hidden>{isDir ? (isOpen ? "▾" : "▸") : ""}</span>
        <span className={`ws-name${isDir ? " is-dir" : ""}`}>{e.name}{isDir ? "/" : ""}</span>
        {e.git && <span className={`ws-git is-${e.git === "??" ? "new" : "mod"}`} title={`git: ${e.git}`}>{e.git === "??" ? "U" : e.git[0]}</span>}
        {e.protected && <span className="ws-lock" aria-label="protected">🔒</span>}
        {e.link && <span className="faint mono-xs">↪</span>}
        {!isDir && e.size != null && <span className="ws-size">{bytes(e.size)}</span>}
      </div>
      {isDir && isOpen && <Folder project={project} path={p} depth={depth + 1} open={open} toggle={toggle} onOpen={onOpen}
        selected={selected} target={target} setTarget={setTarget} listings={listings} load={load} onDropFiles={onDropFiles} />}
    </div>;
  })}</>;
}

export function Workspace() {
  const route = useRoute();
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const theme = usePrefs((p) => p.theme);
  const host = usePrefs((p) => p.sshHost);
  const savedProject = usePrefs((p) => p.consoleProject);
  const savedPanel = usePrefs((p) => p.consoleTab);
  const dev = useDevActive();
  const { rows: projects, err: projErr } = useProjects();

  const qt = route.params.get("ticket");
  const ticket = qt ? tickets.find((t) => t.key === qt) ?? null : null;
  const key = route.params.get("project") || ticket?.project || savedProject || "samvision";
  const proj = projects?.find((p) => p.key === key) ?? null;
  const panel = ((route.params.get("tab") as Panel) || savedPanel || "claude") as Panel;

  const [listings, setListings] = useState<Record<string, FileEntry[] | string>>({});
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState("");
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [over, setOver] = useState(false);
  const [git, setGit] = useState(true);
  const editor = useRef<EditorHandle | null>(null);
  const upId = useRef(0);

  // A different project is a different tree. Unsaved tabs are kept until closed.
  useEffect(() => { setListings({}); setOpen(new Set()); setTarget(""); }, [key]);

  const load = useCallback((path: string) => {
    setListings((l) => ({ ...l, [path]: l[path] ?? [] }));
    app.api.listDir(key, path, git).then((r) => setListings((l) => ({ ...l, [path]: r.entries })))
      .catch((e) => setListings((l) => ({ ...l, [path]: (e as Error).message })));
  }, [key, git]);
  const refresh = () => { setListings({}); };
  const toggle = (p: string) => setOpen((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n; });

  const setProject = (k: string) => { prefs.patch({ consoleProject: k }); go("workspace", null, { project: k, tab: panel }); };
  const setPanel = (t: Panel) => { prefs.patch({ consoleTab: t }); go("workspace", null, { project: key, ticket: qt ?? undefined, tab: t }); };

  const openFile = async (path: string, e?: FileEntry) => {
    if (e?.protected) { app.toast("Protected file: Command Center never opens secret-looking files", "bad"); return; }
    if (e && e.kind !== "file") { app.toast("Not a regular file inside the project", "bad"); return; }
    const id = `${key}:${path}`;
    if (tabs.some((t) => t.path === id)) { setActive(id); return; }
    try {
      const file = await app.api.readFile(key, path);
      setTabs((ts) => [...ts, { path: id, file, text: file.text ?? "", version: 1, dirty: false, conflict: null }]);
      setActive(id);
    } catch (err) { app.toast((err as Error).message, "bad"); }
  };

  const cur = tabs.find((t) => t.path === active) ?? null;

  const save = useCallback(async () => {
    const t = tabs.find((x) => x.path === active);
    if (!t || t.file.kind !== "text") return;
    if (!dev) { unlockDialogOpen(); return; }
    const text = editor.current?.value(t.path) ?? t.text;
    try {
      const r = await app.api.saveFile(t.file.project, t.file.path, text, t.file.sha);
      setTabs((ts) => ts.map((x) => x.path === t.path ? { ...x, text, dirty: false, conflict: null,
        file: { ...x.file, sha: r.sha, size: r.size, mtime: r.mtime } } : x));
      app.toast(`Saved ${t.file.path}`);
    } catch (e) {
      const msg = (e as Error).message;
      if ((e as ApiError).status === 409) setTabs((ts) => ts.map((x) => x.path === t.path ? { ...x, conflict: msg } : x));
      else app.toast(msg, "bad");
    }
  }, [tabs, active, dev]);

  const reload = async (t: Tab) => {
    if (t.dirty && !window.confirm(`Discard your unsaved changes to ${t.file.path} and load the version on disk?`)) return;
    try {
      const file = await app.api.readFile(t.file.project, t.file.path);
      setTabs((ts) => ts.map((x) => x.path === t.path ? { ...x, file, text: file.text ?? "", version: x.version + 1, dirty: false, conflict: null } : x));
    } catch (e) { app.toast((e as Error).message, "bad"); }
  };

  const close = (t: Tab) => {
    if (t.dirty && !window.confirm(`${t.file.path} has unsaved changes. Close it anyway?`)) return;
    editor.current?.dispose(t.path);
    setTabs((ts) => { const rest = ts.filter((x) => x.path !== t.path); if (active === t.path) setActive(rest[rest.length - 1]?.path ?? null); return rest; });
  };

  // Ctrl+S anywhere on the page (Monaco handles it inside the editor too).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); void save(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);
  // Leaving with unsaved work asks first.
  useEffect(() => {
    const any = tabs.some((t) => t.dirty);
    const onUnload = (e: BeforeUnloadEvent) => { if (any) { e.preventDefault(); } };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [tabs]);

  const sendUpload = async (u: Upload, conflict: "fail" | "replace" | "rename") => {
    setUploads((us) => us.map((x) => x.id === u.id ? { ...x, state: "up", f: 0, msg: undefined } : x));
    try {
      const r = await uploadBytes(`/api/files/upload?${new URLSearchParams({ project: key, dir: u.dir, name: u.name, conflict })}`,
        u.file, (f) => setUploads((us) => us.map((x) => x.id === u.id ? { ...x, f } : x)));
      setUploads((us) => us.map((x) => x.id === u.id ? { ...x, state: "done", f: 1, msg: r.renamed ? `saved as ${r.name}` : "uploaded" } : x));
      setListings((l) => { const n = { ...l }; delete n[u.dir]; return n; });
    } catch (e) {
      const err = e as ApiError & { data?: { exists?: boolean } };
      setUploads((us) => us.map((x) => x.id === u.id ? { ...x, state: err.status === 409 && err.data?.exists ? "ask" : "fail", msg: err.message } : x));
    }
  };
  const dropFiles = (dir: string, files: FileList) => {
    setOver(false);
    if (!dev) { unlockDialogOpen(); return; }
    const list = Array.from(files).map((file) => ({ id: ++upId.current, name: file.name, dir, f: 0, state: "up" as const, file }));
    setUploads((us) => [...us.filter((x) => x.state !== "done"), ...list]);
    list.forEach((u) => void sendUpload(u, "fail"));
  };

  const coordinatorAgent = useMemo(() => {
    const id = proj?.coordinator?.id;
    return id ? st?.agents.find((a) => a.id === id) ?? null : st?.agents.find((a) => a.project === key && a.role === "coordinator") ?? null;
  }, [proj, st, key]);
  const ask = uploads.find((u) => u.state === "ask");

  if (projErr) return <EmptyState title="Workspace unavailable" hint={projErr} />;
  if (!projects) return <EmptyState title="Loading projects…" />;
  const crumbs = target ? target.split("/") : [];

  return <div className="ws-page">
    <div className="ws-bar">
      <label className="row" style={{ gap: 6 }}><span className="caps muted">Project</span>
        <select className="select" aria-label="Workspace project" value={key} onChange={(e) => setProject(e.target.value)}>
          {projects.map((p) => <option key={p.key} value={p.key}>{p.name} · {p.prefix}</option>)}
        </select></label>
      {qt && <span className="row" style={{ gap: 6 }}><span className="caps muted">Ticket</span><a className="key" href={href("tasks", qt)}>{qt}</a></span>}
      <span className="row" style={{ gap: 6 }}><span className="caps muted">Branch</span><span className="mono-xs">{ticket?.branch || proj?.branch || "—"}</span></span>
      {proj?.github && <a className="mono-xs link" href={proj.github.url} target="_blank" rel="noopener noreferrer" title="Open the repository on GitHub">{proj.github.slug} ↗</a>}
      <span className="mono-xs faint trunc" title={proj?.root ?? ""}>{proj?.root}</span>
      <span className="sl-fill" />
      <DevBadge />
    </div>
    <div className="ws-main">
      <aside className={`ws-explorer${over ? " is-over" : ""}`} aria-label="Explorer"
        onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }}
        onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) dropFiles(target, e.dataTransfer.files); }}>
        <div className="ws-ex-head">
          <span className="caps muted">Explorer</span>
          <span className="sl-fill" />
          <button type="button" className="btn is-quiet is-sm" aria-pressed={git} onClick={() => { setGit(!git); refresh(); }} title="Show git status (one cached git status per refresh)">git</button>
          <button type="button" className="btn is-quiet is-sm" onClick={refresh} aria-label="Refresh explorer">↻</button>
        </div>
        <nav className="ws-crumbs mono-xs" aria-label="Upload folder">
          <button type="button" className="link" onClick={() => setTarget("")}>{proj?.name ?? key}</button>
          {crumbs.map((c, i) => <span key={i}> / <button type="button" className="link" onClick={() => setTarget(crumbs.slice(0, i + 1).join("/"))}>{c}</button></span>)}
        </nav>
        <div className="ws-tree" role="tree" aria-label={`${proj?.name ?? key} files`}>
          {proj && !proj.exists ? <div className="muted ws-row">checkout not found on the server</div>
            : <Folder project={key} path="" depth={0} open={open} toggle={toggle} onOpen={(p, e) => void openFile(p, e)}
              selected={cur?.file.project === key ? cur.file.path : null} target={target} setTarget={setTarget}
              listings={listings} load={load} onDropFiles={dropFiles} />}
        </div>
        <div className="ws-drop mono-xs">{dev ? <>Drop files from Windows to upload into <b>{target || "/"}</b></> : <>Uploading needs <button type="button" className="link" onClick={unlockDialogOpen}>Developer Unlock</button></>}</div>
        {uploads.length > 0 && <div className="ws-uploads" aria-live="polite">
          {uploads.map((u) => <div key={u.id} className="row mono-xs">
            <span className="trunc" title={join(u.dir, u.name)}>{u.name}</span>
            {u.state === "up" ? <progress max={1} value={u.f} aria-label={`Uploading ${u.name}`} />
              : <span className={u.state === "done" ? "ok-t" : u.state === "ask" ? "warn-t" : "bad-t"}>{u.state === "ask" ? "exists" : u.msg}</span>}
            {u.state !== "up" && <button type="button" className="btn is-quiet is-sm" aria-label="Dismiss" onClick={() => setUploads((us) => us.filter((x) => x.id !== u.id))}>×</button>}
          </div>)}
        </div>}
      </aside>
      <section className="ws-center" aria-label="Editor">
        <div className="ws-tabs" role="tablist" aria-label="Open files">
          {tabs.map((t) => <span key={t.path} role="tab" aria-selected={t.path === active} className={`ws-tab${t.path === active ? " is-active" : ""}`}>
            <button type="button" className="ws-tab-name" onClick={() => setActive(t.path)} title={`${t.file.project}: ${t.file.path}`}>
              {t.file.path.split("/").pop()}{t.dirty && <span className="ws-dirty" aria-label="unsaved"> ●</span>}</button>
            <button type="button" className="ws-tab-x" aria-label={`Close ${t.file.path}`} onClick={() => close(t)}>×</button>
          </span>)}
        </div>
        {cur ? <>
          <div className="ws-filebar">
            <span className="mono-xs" title={cur.file.path}><span className="faint">{cur.file.project}/</span>{cur.file.path}</span>
            <span className="mono-xs faint">{bytes(cur.file.size)} · {cur.file.mode} · {stamp(cur.file.mtime)}</span>
            <span className="sl-fill" />
            <button type="button" className="btn is-sm" onClick={() => void app.api.download(`/api/files/download?${new URLSearchParams({ project: cur.file.project, path: cur.file.path })}`, cur.file.path.split("/").pop() ?? "file").catch((e) => app.toast((e as Error).message, "bad"))}>Download</button>
            <button type="button" className="btn is-sm" onClick={() => void reload(cur)}>Reload</button>
            {cur.file.kind === "text" && <button type="button" className="btn is-sm is-jay" disabled={!cur.dirty} onClick={() => void save()}
              title={dev ? "Save (Ctrl+S)" : "Saving needs Developer Unlock"}>Save</button>}
          </div>
          {cur.conflict && <div className="ws-conflict" role="alert">
            <b>Not saved.</b> {cur.conflict}. Your text is still here.
            <button type="button" className="btn is-sm" onClick={() => void reload(cur)}>Load disk version (discard mine)</button>
            <button type="button" className="btn is-sm" onClick={() => setTabs((ts) => ts.map((x) => x.path === cur.path ? { ...x, conflict: null } : x))}>Keep editing</button>
          </div>}
          {cur.file.kind === "text"
            ? <CodeEditor path={cur.path} text={cur.text} version={cur.version} theme={theme === "light" ? "light" : "dark"} handle={editor}
              onSave={() => void save()} onChange={(p, text) => setTabs((ts) => ts.map((x) => x.path === p ? { ...x, dirty: text !== x.text } : x))} />
            : <div className="ws-editor-wrap is-empty"><EmptyState title={cur.file.kind === "large" ? "Too large for the editor" : "Binary file"}
              hint={`${bytes(cur.file.size)} — download it instead. The editor opens UTF-8 text up to 2 MB.`} /></div>}
        </> : <div className="ws-editor-wrap is-empty"><EmptyState title="Open a file from the explorer"
          hint="Ctrl+S saves (Developer Mode). Drag files from Windows onto a folder to upload." /></div>}
      </section>
    </div>
    <section className="ws-panel" aria-label="Terminal panel">
      <div className="tabs" role="tablist" aria-label="Terminal mode">
        {(["claude", "repo", "server"] as Panel[]).map((t) => <button key={t} type="button" role="tab" aria-selected={panel === t}
          className="tab" onClick={() => setPanel(t)}>{t === "claude" ? "Claude" : t === "repo" ? `Repo shell · repo:${proj?.prefix ?? "?"}` : "Server shell"}</button>)}
        <span className="sl-fill" />
        {panel === "claude" && <span className="row mono-xs" style={{ gap: 8 }}>
          <span>{coordinatorAgent?.agent_name || proj?.coordinator?.name || key}</span>
          {coordinatorAgent ? <AgentState status={coordinatorAgent.status} /> : <AgentState status="offline" />}
          <span className="faint trunc">{coordinatorAgent?.cwd ?? ""}</span></span>}
      </div>
      <div className="ws-panel-body">
        {panel === "claude" && <ClaudeMirror agent={coordinatorAgent} name={coordinatorAgent?.agent_name || key} />}
        {panel !== "claude" && <div className="con-term is-empty"><div className="con-notyet">
          <div className="row" style={{ gap: 8 }}><span className="ro-tag is-off">NOT ENABLED</span>
            <span className="caps muted">{panel === "repo" ? `repo shell · repo:${proj?.prefix ?? ""}` : "server shell"}</span></div>
          <p className="text2">The browser PTY (ADR 0004 phase 3) is not shipped: it is the one feature that lets a browser
            run commands, and it has not passed its security review yet. Use the command below meanwhile.</p>
          <Command cmd={panel === "repo" ? commands.repoShell(host, proj?.root ?? "~") : commands.serverShell(host)} />
        </div></div>}
      </div>
    </section>
    {ask && <Dialog title={`${ask.name} already exists`} onClose={() => setUploads((us) => us.map((x) => x.id === ask.id ? { ...x, state: "fail", msg: "skipped" } : x))}>
      <p className="text2">A file named <span className="mono">{ask.name}</span> is already in <span className="mono">{ask.dir || "/"}</span>. Nothing was overwritten.</p>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn is-jay" onClick={() => void sendUpload(ask, "replace")}>Replace</button>
        <button type="button" className="btn" data-autofocus onClick={() => void sendUpload(ask, "rename")}>Keep both (rename)</button>
        <button type="button" className="btn is-quiet" onClick={() => setUploads((us) => us.map((x) => x.id === ask.id ? { ...x, state: "fail", msg: "skipped" } : x))}>Skip</button>
      </div>
    </Dialog>}
  </div>;
}
