// WORKSPACE — the daily development surface, laid out like an IDE:
//
//   ┌ bar: project · ticket · branch · GitHub · Developer Mode ─────────────┐
//   │ EXPLORER │ MAIN: Editor | Claude | Source control | Search | Development │
//   ├──────────┴──────────────────────────────────────────────────────────────┤
//   │ TERMINAL: Claude | Repo shell (repo:<PREFIX>) | Server shell             │
//   └─────────────────────────────────────────────────────────────────────────┘
//
// Explorer width and terminal height drag (or arrow keys on the dividers),
// either side collapses, and the main area or the terminal can be maximized.
// The layout is remembered in this browser only.
//
// The project comes from the registry (/api/workspace/projects); the browser
// never names a filesystem root. Reading never needs Developer Mode; every
// write (save, upload, rename, delete, git stage/commit, terminals, messages to
// Claude) does. Nothing saves on its own.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import { Store, useSelector } from "../lib/store";
import { go, href, useRoute } from "../lib/router";
import { prefs, usePrefs, type Prefs } from "../lib/prefs";
import { ApiError, uploadBytes } from "../api/client";
import type { FileEntry, FileRead, WorkspaceProject } from "../api/types";
import { stamp } from "../lib/time";
import { EmptyState, Kbd } from "../components/ui";
import { Dialog } from "../components/Dialog";
import { DevBadge, unlockDialogOpen, useDevActive } from "../components/DevMode";
import { bytes } from "../components/Attachments";
import { DevTrail } from "../components/DevTrail";
import { CodeEditor, disposeModel, nextVersion, revealLine, type EditorHandle } from "../workspace/Editor";
import { ClaudePanel } from "../workspace/ClaudePanel";
import { TerminalView } from "../workspace/Terminal";
import { SourceControl } from "../workspace/SourceControl";
import { GoToFile, SearchPanel } from "../workspace/Search";

interface Tab { path: string; file: FileRead; text: string; version: number; dirty: boolean; conflict: string | null }
interface Upload { id: number; project: string; name: string; dir: string; f: number; state: "up" | "done" | "fail" | "ask"; msg?: string; file: File }
type Main = Prefs["wsMain"];
type Term = "claude" | "repo" | "server";

const join = (dir: string, name: string) => (dir ? `${dir}/${name}` : name);
const parentOf = (p: string) => (p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");

// Open tabs outlive the screen: going to Tasks and back keeps every file and
// every unsaved edit (the Monaco models live in workspace/Editor.tsx).
const tabStore = new Store<{ tabs: Tab[]; active: string | null }>({ tabs: [], active: null });

const ICON: Record<string, [string, string]> = {
  py: ["py", "#8db6df"], ts: ["ts", "#8db6df"], tsx: ["tsx", "#8db6df"], js: ["js", "#e5b05a"], jsx: ["jsx", "#e5b05a"],
  json: ["{}", "#c5a3cb"], md: ["md", "#aab4b3"], css: ["css", "#86c7a3"], html: ["<>", "#d6a06c"], yml: ["yml", "#c5a3cb"],
  yaml: ["yml", "#c5a3cb"], sh: ["$", "#94c88b"], go: ["go", "#6cc4bc"], rs: ["rs", "#d6a06c"], sql: ["sql", "#e2a854"],
  toml: ["tml", "#aab4b3"], txt: ["txt", "#77848a"], pdf: ["pdf", "#ec806f"], png: ["img", "#c5a3cb"], jpg: ["img", "#c5a3cb"],
  svg: ["svg", "#c5a3cb"], lock: ["lck", "#77848a"], csv: ["csv", "#94c88b"],
};
function FileIcon({ name, dir }: { name: string; dir: boolean }) {
  if (dir) return <span className="fi is-dir" aria-hidden>▤</span>;
  const [t, c] = ICON[name.split(".").pop()?.toLowerCase() ?? ""] ?? ["·", "#77848a"];
  return <span className="fi" style={{ color: c }} aria-hidden>{t}</span>;
}

function usePrefersLight() {
  const [light, setLight] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: light)").matches);
  useEffect(() => {
    const q = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!q) return;
    const on = () => setLight(q.matches);
    q.addEventListener?.("change", on);
    return () => q.removeEventListener?.("change", on);
  }, []);
  return light;
}

function useProjects() {
  const [rows, setRows] = useState<WorkspaceProject[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { app.api.workspaceProjects().then((r) => setRows(r.projects)).catch((e) => setErr((e as Error).message)); }, []);
  return { rows, err };
}

/** A drag/keyboard divider. `axis` x resizes a width, y a height. */
function Splitter({ axis, value, min, max, onChange, label, invert = false }: {
  axis: "x" | "y"; value: number; min: number; max: number; onChange: (v: number) => void; label: string; invert?: boolean;
}) {
  const clamp = (v: number) => Math.round(Math.max(min, Math.min(max, v)));
  return <div role="separator" aria-orientation={axis === "x" ? "vertical" : "horizontal"} aria-label={label}
    aria-valuenow={value} aria-valuemin={min} aria-valuemax={max} tabIndex={0} className={`split is-${axis}`}
    onPointerDown={(e) => {
      e.preventDefault();
      const start = axis === "x" ? e.clientX : e.clientY, v0 = value;
      const el = e.currentTarget; el.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent) => { const d = (axis === "x" ? ev.clientX : ev.clientY) - start; onChange(clamp(v0 + (invert ? -d : d))); };
      const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
      el.addEventListener("pointermove", move); el.addEventListener("pointerup", up);
    }}
    onKeyDown={(e) => {
      const step = e.shiftKey ? 60 : 16;
      const grow = axis === "x" ? e.key === "ArrowRight" : invert ? e.key === "ArrowUp" : e.key === "ArrowDown";
      const shrink = axis === "x" ? e.key === "ArrowLeft" : invert ? e.key === "ArrowDown" : e.key === "ArrowUp";
      if (grow || shrink) { e.preventDefault(); onChange(clamp(value + (grow ? step : -step))); }
    }} />;
}

interface Menu { x: number; y: number; path: string; entry: FileEntry | null }

/** One folder level. Children load when the folder is first opened, never before. */
function Folder({ path, depth, open, toggle, onOpen, selected, target, setTarget, listings, load, onDropFiles, onMenu }: {
  path: string; depth: number; open: Set<string>; toggle: (p: string) => void; onOpen: (p: string, e: FileEntry) => void;
  selected: string | null; target: string; setTarget: (p: string) => void; listings: Record<string, FileEntry[] | string>;
  load: (p: string) => void; onDropFiles: (dir: string, files: FileList) => void; onMenu: (m: Menu) => void;
}) {
  const rows = listings[path];
  useEffect(() => { if (rows === undefined) load(path); }, [rows, path, load]);
  if (rows === undefined) return <div className="ws-row muted" style={{ paddingLeft: 10 + depth * 14 }}>loading…</div>;
  if (typeof rows === "string") return <div className="ws-row bad-t" style={{ paddingLeft: 10 + depth * 14 }}>{rows}</div>;
  if (!rows.length && depth > 0) return <div className="ws-row faint" style={{ paddingLeft: 10 + depth * 14 }}>(empty)</div>;
  return <>{rows.map((e) => {
    const p = join(path, e.name);
    const isDir = e.kind === "dir";
    const isOpen = open.has(p);
    return <div key={p}>
      <div role="treeitem" aria-expanded={isDir ? isOpen : undefined} aria-selected={selected === p}
        className={`ws-row${selected === p ? " is-sel" : ""}${target === p ? " is-target" : ""}${e.protected ? " is-protected" : ""}`}
        style={{ paddingLeft: 10 + depth * 14 }} tabIndex={0}
        title={e.protected ? "Protected: secret-looking files are never opened, downloaded or changed here" :
          e.kind === "outside" ? "Symlink that leaves the project — not followed" : `${p}${e.size != null ? ` · ${bytes(e.size)}` : ""}${e.mtime ? ` · ${stamp(e.mtime)}` : ""}`}
        onClick={() => { if (isDir) { toggle(p); setTarget(p); } else onOpen(p, e); }}
        onContextMenu={(ev) => { ev.preventDefault(); onMenu({ x: ev.clientX, y: ev.clientY, path: p, entry: e }); }}
        onKeyDown={(ev) => {
          if (ev.key === "Enter") { if (isDir) toggle(p); else onOpen(p, e); }
          else if (ev.key === "ContextMenu" || (ev.shiftKey && ev.key === "F10")) {
            ev.preventDefault(); const r = ev.currentTarget.getBoundingClientRect(); onMenu({ x: r.left + 40, y: r.bottom, path: p, entry: e });
          }
        }}
        onDragOver={(ev) => { if (isDir && ev.dataTransfer.types.includes("Files")) { ev.preventDefault(); ev.stopPropagation(); setTarget(p); } }}
        onDrop={(ev) => { if (isDir && ev.dataTransfer.files.length) { ev.preventDefault(); ev.stopPropagation(); onDropFiles(p, ev.dataTransfer.files); } }}>
        <span className="ws-caret" aria-hidden>{isDir ? (isOpen ? "▾" : "▸") : ""}</span>
        <FileIcon name={e.name} dir={isDir} />
        <span className={`ws-name${isDir ? " is-dir" : ""}`}>{e.name}</span>
        {e.git && <span className={`ws-git is-${e.git === "??" ? "new" : "mod"}`} title={`git: ${e.git}`}>{e.git === "??" ? "U" : e.git[0]}</span>}
        {e.protected && <span className="ws-lock" aria-label="protected">🔒</span>}
        {e.link && <span className="faint mono-xs">↪</span>}
        {!isDir && e.size != null && <span className="ws-size">{bytes(e.size)}</span>}
      </div>
      {isDir && isOpen && <Folder path={p} depth={depth + 1} open={open} toggle={toggle} onOpen={onOpen} selected={selected}
        target={target} setTarget={setTarget} listings={listings} load={load} onDropFiles={onDropFiles} onMenu={onMenu} />}
    </div>;
  })}</>;
}

function NameDialog({ title, initial, onDone, onClose }: { title: string; initial: string; onDone: (v: string) => void; onClose: () => void }) {
  const [v, setV] = useState(initial);
  return <Dialog title={title} onClose={onClose}>
    <form onSubmit={(e) => { e.preventDefault(); if (v.trim()) { onDone(v.trim()); onClose(); } }} className="row">
      <input className="input mono grow" value={v} onChange={(e) => setV(e.target.value)} data-autofocus aria-label="Name"
        onFocus={(e) => { const dot = e.target.value.lastIndexOf("."); e.target.setSelectionRange(0, dot > 0 ? dot : e.target.value.length); }} />
      <button type="submit" className="btn is-jay" disabled={!v.trim()}>OK</button>
    </form>
  </Dialog>;
}

export function Workspace() {
  const route = useRoute();
  const st = useSelector(app.store, (d) => d.state);
  const tickets = useSelector(app.store, (d) => d.tickets);
  const development = useSelector(app.store, (d) => d.development);
  const p = usePrefs((x) => x);
  const dev = useDevActive();
  const prefersLight = usePrefersLight();
  const { rows: projects, err: projErr } = useProjects();

  const qt = route.params.get("ticket");
  const ticket = qt ? tickets.find((t) => t.key === qt) ?? null : null;
  const key = route.params.get("project") || ticket?.project || p.consoleProject || "samvision";
  const proj = projects?.find((x) => x.key === key) ?? null;
  const term = ((route.params.get("tab") as Term) || p.consoleTab || "claude") as Term;
  const main: Main = (route.params.get("view") as Main) || p.wsMain;
  const theme: "dark" | "light" = p.theme === "light" || (p.theme === "system" && prefersLight) ? "light" : "dark";

  const [listings, setListings] = useState<Record<string, FileEntry[] | string>>({});
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState("");
  const { tabs, active } = useSelector(tabStore, (d) => d);
  const setTabs = (f: (ts: Tab[]) => Tab[]) => tabStore.set((d) => ({ ...d, tabs: f(d.tabs) }));
  const setActive = (a: string | null) => tabStore.patch({ active: a });
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [over, setOver] = useState(false);
  const [git, setGit] = useState(true);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [naming, setNaming] = useState<{ title: string; initial: string; done: (v: string) => void } | null>(null);
  const [goto, setGoto] = useState(false);
  const [searchFocus, setSearchFocus] = useState(0);
  const [seenTerms, setSeenTerms] = useState<Set<Term>>(new Set([term]));
  const editor = useRef<EditorHandle | null>(null);
  const upId = useRef(0);
  const keyRef = useRef(key);
  keyRef.current = key;
  const inflight = useRef(new Set<string>());
  const pickFile = useRef<HTMLInputElement>(null);

  useEffect(() => { setSeenTerms((s) => (s.has(term) ? s : new Set([...s, term]))); }, [term]);
  useEffect(() => { setListings({}); setOpen(new Set()); setTarget(""); inflight.current.clear(); }, [key]);
  useEffect(() => { void app.refreshDevelopment(); }, []);

  const load = useCallback((path: string) => {
    const want = key, tag = `${want}:${path}`;
    if (inflight.current.has(tag)) return;
    inflight.current.add(tag);
    // A response for a project Jay has since left is dropped, never shown in the new tree.
    const put = (v: FileEntry[] | string) => { inflight.current.delete(tag); if (keyRef.current === want) setListings((l) => ({ ...l, [path]: v })); };
    app.api.listDir(want, path, git).then((r) => put(r.entries)).catch((e) => put((e as Error).message));
  }, [key, git]);
  const refresh = () => { inflight.current.clear(); setListings({}); };
  const invalidate = (dir: string) => setListings((l) => { const n = { ...l }; delete n[dir]; return n; });
  const toggle = (x: string) => setOpen((s) => { const n = new Set(s); if (n.has(x)) n.delete(x); else n.add(x); return n; });

  const nav = (patch: Partial<{ project: string; tab: Term; view: Main; ticket: string | null }>) => {
    go("workspace", null, { project: patch.project ?? key, ticket: (patch.ticket === undefined ? qt : patch.ticket) ?? undefined,
      tab: patch.tab ?? term, view: patch.view ?? main });
  };
  const setProject = (k: string) => { prefs.patch({ consoleProject: k }); nav({ project: k, ticket: null }); };
  const setTerm = (t: Term) => { prefs.patch({ consoleTab: t, wsTermOpen: true, wsMax: prefs.get().wsMax === "main" ? "none" : prefs.get().wsMax }); nav({ tab: t }); };
  const setMain = (m: Main) => { prefs.patch({ wsMain: m, wsMax: prefs.get().wsMax === "term" ? "none" : prefs.get().wsMax }); nav({ view: m }); };

  const openFile = async (path: string, e?: FileEntry, line?: number) => {
    if (e?.protected) { app.toast("Protected file: Command Center never opens secret-looking files", "bad"); return; }
    if (e && e.kind !== "file") { app.toast("Not a regular file inside the project", "bad"); return; }
    const id = `${key}:${path}`;
    if (main !== "editor") setMain("editor");
    if (line) revealLine(id, line);
    if (tabStore.get().tabs.some((t) => t.path === id)) { setActive(id); return; }
    try {
      const file = await app.api.readFile(key, path);
      setTabs((ts) => ts.some((t) => t.path === id) ? ts : [...ts, { path: id, file, text: file.text ?? "", version: nextVersion(), dirty: false, conflict: null }]);
      setActive(id);
    } catch (err) { app.toast((err as Error).message, "bad"); }
  };

  const cur = tabs.find((t) => t.path === active) ?? null;
  const [lastText, setLastText] = useState<string | null>(null);
  useEffect(() => { if (cur?.file.kind === "text") setLastText(cur.path); }, [cur]);
  const textTab = cur?.file.kind === "text" ? cur : tabs.find((t) => t.path === lastText && t.file.kind === "text") ?? null;

  const save = useCallback(async () => {
    const t = tabStore.get().tabs.find((x) => x.path === tabStore.get().active);
    if (!t || t.file.kind !== "text") return;
    if (!dev) { unlockDialogOpen(); return; }
    const text = editor.current?.value(t.path) ?? t.text;
    try {
      const r = await app.api.saveFile(t.file.project, t.file.path, text, t.file.sha);
      const now = editor.current?.value(t.path) ?? text;  // keys typed while saving stay dirty
      tabStore.set((d) => ({ ...d, tabs: d.tabs.map((x) => x.path === t.path ? { ...x, text, dirty: now !== text, conflict: null,
        file: { ...x.file, sha: r.sha, size: r.size, mtime: r.mtime } } : x) }));
      app.toast(`Saved ${t.file.path}`);
    } catch (e) {
      const msg = (e as Error).message;
      if ((e as ApiError).status === 409) tabStore.set((d) => ({ ...d, tabs: d.tabs.map((x) => x.path === t.path ? { ...x, conflict: msg } : x) }));
      else app.toast(msg, "bad");
    }
  }, [dev]);

  const reload = async (t: Tab) => {
    if (t.dirty && !window.confirm(`Discard your unsaved changes to ${t.file.path} and load the version on disk?`)) return;
    try {
      const file = await app.api.readFile(t.file.project, t.file.path);
      setTabs((ts) => ts.map((x) => x.path === t.path ? { ...x, file, text: file.text ?? "", version: nextVersion(), dirty: false, conflict: null } : x));
    } catch (e) { app.toast((e as Error).message, "bad"); }
  };
  const close = (t: Tab) => {
    if (t.dirty && !window.confirm(`${t.file.path} has unsaved changes. Close it anyway?`)) return;
    disposeModel(t.path);
    tabStore.set((d) => { const rest = d.tabs.filter((x) => x.path !== t.path);
      return { tabs: rest, active: d.active === t.path ? rest[rest.length - 1]?.path ?? null : d.active }; });
  };

  const maximize = (m: "main" | "term") => prefs.patch({ wsMax: prefs.get().wsMax === m ? "none" : m, wsTermOpen: true });

  // Keyboard: Ctrl+S save · Ctrl+P go to file · Ctrl+Shift+F search · Ctrl+` terminal · Ctrl+Shift+` repo shell
  // · Ctrl+B explorer · Ctrl+Shift+Enter maximize terminal · Esc closes menus. Inside a real terminal, Ctrl+P,
  // Ctrl+S, Ctrl+B and Ctrl+Shift+F stay the shell's (Ctrl+P is shell history there).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inTerm = (e.target as HTMLElement | null)?.closest?.(".xterm");
      const mod = e.ctrlKey || e.metaKey;
      if (e.key === "Escape" && menu) { setMenu(null); return; }
      if (!mod) return;
      const k = e.key.toLowerCase();
      if (k === "s" && !e.shiftKey && !inTerm) { e.preventDefault(); void save(); }
      else if (k === "p" && !e.shiftKey && !inTerm) { e.preventDefault(); setGoto(true); }
      else if (k === "f" && e.shiftKey && !inTerm) { e.preventDefault(); setMain("search"); setSearchFocus((n) => n + 1); }
      else if (e.code === "Backquote" && !e.shiftKey) { e.preventDefault(); prefs.patch({ wsTermOpen: !prefs.get().wsTermOpen, wsMax: "none" }); }
      else if (e.code === "Backquote" && e.shiftKey) { e.preventDefault(); setTerm("repo"); }
      else if (k === "b" && !e.shiftKey && !inTerm) { e.preventDefault(); prefs.patch({ wsExplorerOpen: !prefs.get().wsExplorerOpen }); }
      else if (e.key === "Enter" && e.shiftKey) { e.preventDefault(); maximize("term"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {
    const any = tabs.some((t) => t.dirty);
    const onUnload = (e: BeforeUnloadEvent) => { if (any) e.preventDefault(); };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [tabs]);
  // The command palette steers the Workspace with events.
  useEffect(() => {
    const onCmd = (e: Event) => {
      const d = (e as CustomEvent).detail as { main?: Main; term?: Term; goto?: boolean; search?: boolean };
      if (d.main) setMain(d.main);
      if (d.term) setTerm(d.term);
      if (d.goto) setGoto(true);
      if (d.search) { setMain("search"); setSearchFocus((n) => n + 1); }
    };
    window.addEventListener("cc:workspace", onCmd);
    return () => window.removeEventListener("cc:workspace", onCmd);
  });

  const sendUpload = async (u: Upload, conflict: "fail" | "replace" | "rename") => {
    setUploads((us) => us.map((x) => x.id === u.id ? { ...x, state: "up", f: 0, msg: undefined } : x));
    try {
      const r = await uploadBytes(`/api/files/upload?${new URLSearchParams({ project: u.project, dir: u.dir, name: u.name, conflict })}`,
        u.file, (f) => setUploads((us) => us.map((x) => x.id === u.id ? { ...x, f } : x)));
      setUploads((us) => us.map((x) => x.id === u.id ? { ...x, state: "done", f: 1, msg: r.renamed ? `saved as ${r.name}` : "uploaded" } : x));
      if (keyRef.current === u.project) invalidate(u.dir);
    } catch (e) {
      const err = e as ApiError & { data?: { exists?: boolean } };
      setUploads((us) => us.map((x) => x.id === u.id ? { ...x, state: err.status === 409 && err.data?.exists ? "ask" : "fail", msg: err.message } : x));
    }
  };
  const dropFiles = (dir: string, files: FileList) => {
    setOver(false);
    if (!dev) { unlockDialogOpen(); return; }
    const list = Array.from(files).map((file) => ({ id: ++upId.current, project: key, name: file.name, dir, f: 0, state: "up" as const, file }));
    setUploads((us) => [...us.filter((x) => x.state !== "done"), ...list]);
    list.forEach((u) => void sendUpload(u, "fail"));
  };

  // Explorer operations: every one needs Developer Mode; ccd enforces it too.
  const op = async (fn: () => Promise<unknown>, ok: string, dirs: string[]) => {
    if (!dev) { unlockDialogOpen(); return; }
    if (await app.action(fn, ok)) dirs.forEach(invalidate);
  };
  const menuItems = (m: Menu) => {
    const isDir = m.entry?.kind === "dir";
    const dir = m.entry ? (isDir ? m.path : parentOf(m.path)) : m.path;
    const items: { label: string; run: () => void; danger?: boolean }[] = [
      { label: "New file…", run: () => setNaming({ title: `New file in ${dir || "/"}`, initial: "", done: (n) => void op(async () => {
        await app.api.saveFile(key, join(dir, n), "", null); setOpen((s) => new Set([...s, dir])); void openFile(join(dir, n)); }, `Created ${n}`, [dir]) }) },
      { label: "New folder…", run: () => setNaming({ title: `New folder in ${dir || "/"}`, initial: "", done: (n) => void op(() => app.api.mkdir(key, dir, n), `Created ${n}/`, [dir]) }) },
      { label: "Upload files here…", run: () => { setTarget(dir); pickFile.current?.click(); } },
    ];
    if (m.entry) {
      const name = m.entry.name;
      if (!m.entry.protected) {
        items.push({ label: "Rename…", run: () => setNaming({ title: `Rename ${name}`, initial: name, done: (n) => void op(() => app.api.renamePath(key, m.path, n), `Renamed to ${n}`, [parentOf(m.path)]) }) });
        if (!isDir) {
          items.push({ label: "Duplicate", run: () => void op(() => app.api.duplicate(key, m.path), `Duplicated ${name}`, [parentOf(m.path)]) });
          items.push({ label: "Download", run: () => void app.api.download(`/api/files/download?${new URLSearchParams({ project: key, path: m.path })}`, name).catch((e) => app.toast((e as Error).message, "bad")) });
        }
      }
      items.push({ label: "Copy path", run: () => void navigator.clipboard?.writeText(m.path).then(() => app.toast("Path copied")) });
      if (!m.entry.protected) items.push({ label: isDir ? "Delete folder…" : "Delete…", danger: true, run: () => {
        if (window.confirm(isDir ? `Delete the folder ${m.path} and everything in it? This cannot be undone.` : `Delete ${m.path}? This cannot be undone.`))
          void op(() => app.api.removePath(key, m.path), `Deleted ${name}`, [parentOf(m.path)]);
      } });
    }
    return items;
  };

  const coordinatorAgent = useMemo(() => {
    const id = proj?.coordinator?.id;
    return id ? st?.agents.find((a) => a.id === id) ?? null : st?.agents.find((a) => a.project === key && a.role === "coordinator") ?? null;
  }, [proj, st, key]);
  const cfg = st?.projectsConfig.find((x) => x.key === key) ?? null;
  const devRow = qt ? development?.rows.find((r) => r.key === qt) ?? null : null;
  const projectRows = development?.rows.filter((r) => r.project === key) ?? [];
  const prUrl = devRow?.pr?.url ?? null;
  const ask = uploads.find((u) => u.state === "ask");

  if (projErr) return <EmptyState title="Workspace unavailable" hint={projErr} />;
  if (!projects) return <EmptyState title="Loading projects…" />;
  const crumbs = target ? target.split("/") : [];
  const exOpen = p.wsExplorerOpen;
  const termOpen = (p.wsTermOpen || p.wsMax === "term") && p.wsMax !== "main";
  const mainOpen = p.wsMax !== "term";
  const termLabel = (t: Term) => (t === "claude" ? "Claude" : t === "repo" ? `Repo shell · repo:${proj?.prefix ?? "?"}` : "Server shell");
  const MAIN_TABS: { id: Main; label: string }[] = [{ id: "editor", label: "Editor" }, { id: "claude", label: "Claude" },
    { id: "scm", label: "Source control" }, { id: "search", label: "Search" }, { id: "dev", label: "Development" }];
  const rows = !mainOpen ? "auto 0 0 minmax(0,1fr)" : termOpen ? `auto minmax(0,1fr) 6px ${p.wsTermH}px` : "auto minmax(0,1fr) 0 0";

  return <div className="ws2" style={{ gridTemplateRows: rows }}>
    <div className="ws-bar">
      <label className="row" style={{ gap: 6 }}><span className="caps muted">Project</span>
        <select className="select" aria-label="Workspace project" value={key} onChange={(e) => setProject(e.target.value)}>
          {projects.map((x) => <option key={x.key} value={x.key}>{x.name} · {x.prefix}</option>)}
        </select></label>
      <span className="row" style={{ gap: 6 }}><span className="caps muted">Ticket</span>
        {qt ? <a className="key" href={href("tasks", qt)}>{qt}</a> : <span className="faint">—</span>}</span>
      <span className="row" style={{ gap: 6 }}><span className="caps muted">Branch</span><span className="mono-xs">{ticket?.branch || proj?.branch || "—"}</span></span>
      {devRow?.pr?.number != null && prUrl && <a className="mono-xs link" href={prUrl} target="_blank" rel="noopener noreferrer">PR #{devRow.pr.number} ↗</a>}
      {proj?.github && <a className="mono-xs link" href={proj.github.url} target="_blank" rel="noopener noreferrer" title="Open the repository on GitHub">{proj.github.slug} ↗</a>}
      <span className="sl-fill" />
      <button type="button" className="btn is-quiet is-sm" onClick={() => setGoto(true)} title="Go to file">Go to file <Kbd>Ctrl P</Kbd></button>
      <DevBadge />
    </div>

    <div className="ws2-main" style={{ gridTemplateColumns: exOpen ? `${p.wsExplorerW}px 6px minmax(0,1fr)` : "28px 0 minmax(0,1fr)" }} hidden={!mainOpen}>
      {exOpen ? <aside className={`ws-explorer${over ? " is-over" : ""}`} aria-label="Explorer"
        onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }}
        onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) dropFiles(target, e.dataTransfer.files); }}>
        <div className="ws-ex-head">
          <span className="caps muted">Explorer</span><span className="sl-fill" />
          <button type="button" className="btn is-quiet is-sm" onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMenu({ x: r.left, y: r.bottom, path: target, entry: null }); }}
            title="New file, folder or upload" aria-label="New file, folder or upload">+</button>
          <button type="button" className="btn is-quiet is-sm" aria-pressed={git} onClick={() => { setGit(!git); refresh(); }} title="Show git status">git</button>
          <button type="button" className="btn is-quiet is-sm" onClick={refresh} aria-label="Refresh explorer">↻</button>
          <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ wsExplorerOpen: false })} aria-label="Collapse explorer (Ctrl+B)">«</button>
        </div>
        <nav className="ws-crumbs mono-xs" aria-label="Current folder">
          <button type="button" className="link" onClick={() => setTarget("")}>{proj?.name ?? key}</button>
          {crumbs.map((c, i) => <span key={i}> / <button type="button" className="link" onClick={() => setTarget(crumbs.slice(0, i + 1).join("/"))}>{c}</button></span>)}
        </nav>
        <div className="ws-tree" role="tree" aria-label={`${proj?.name ?? key} files`}
          onContextMenu={(e) => { if (e.target === e.currentTarget) { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, path: target, entry: null }); } }}>
          {proj && !proj.exists ? <div className="muted ws-row">checkout not found on the server</div>
            : <Folder path="" depth={0} open={open} toggle={toggle} onOpen={(x, e) => void openFile(x, e)}
              selected={cur?.file.project === key ? cur.file.path : null} target={target} setTarget={setTarget}
              listings={listings} load={load} onDropFiles={dropFiles} onMenu={setMenu} />}
        </div>
        <div className="ws-drop mono-xs">{dev ? <>Drop files to upload into <b>{target || "/"}</b></> : <>Changing files needs <button type="button" className="link" onClick={unlockDialogOpen}>Developer Unlock</button></>}</div>
        {uploads.length > 0 && <div className="ws-uploads" aria-live="polite">
          {uploads.map((u) => <div key={u.id} className="row mono-xs">
            <span className="trunc" title={join(u.dir, u.name)}>{u.name}</span>
            {u.state === "up" ? <progress max={1} value={u.f} aria-label={`Uploading ${u.name}`} />
              : <span className={u.state === "done" ? "ok-t" : u.state === "ask" ? "warn-t" : "bad-t"}>{u.state === "ask" ? "exists" : u.msg}</span>}
            {u.state !== "up" && <button type="button" className="btn is-quiet is-sm" aria-label="Dismiss" onClick={() => setUploads((us) => us.filter((x) => x.id !== u.id))}>×</button>}
          </div>)}
        </div>}
        <input ref={pickFile} type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) dropFiles(target, e.target.files); e.target.value = ""; }} />
      </aside> : <button type="button" className="ws-ex-rail" onClick={() => prefs.patch({ wsExplorerOpen: true })} aria-label="Show explorer (Ctrl+B)" title="Explorer (Ctrl+B)">»</button>}
      {exOpen ? <Splitter axis="x" value={p.wsExplorerW} min={180} max={640} onChange={(v) => prefs.patch({ wsExplorerW: v })} label="Explorer width" /> : <span />}

      <section className="ws-center" aria-label="Main area">
        <div className="ws-maintabs" role="tablist" aria-label="Main view">
          {MAIN_TABS.map((t) => <button key={t.id} type="button" role="tab" aria-selected={main === t.id} className="tab" onClick={() => setMain(t.id)}>{t.label}</button>)}
          <span className="sl-fill" />
          <button type="button" className="btn is-quiet is-sm" aria-pressed={p.wsMax === "main"} onClick={() => maximize("main")}>{p.wsMax === "main" ? "Restore" : "Maximize"}</button>
          {!termOpen && <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ wsTermOpen: true, wsMax: "none" })}>Terminal <Kbd>Ctrl `</Kbd></button>}
        </div>
        <div className="ws-view" hidden={main !== "editor"}>
          <div className="ws-tabs" role="tablist" aria-label="Open files">
            {tabs.map((t) => <span key={t.path} role="tab" aria-selected={t.path === active} className={`ws-tab${t.path === active ? " is-active" : ""}`}>
              <button type="button" className="ws-tab-name" onClick={() => setActive(t.path)} title={`${t.file.project}: ${t.file.path}`}>
                <FileIcon name={t.file.path} dir={false} />{t.file.path.split("/").pop()}{t.dirty && <span className="ws-dirty" aria-label="unsaved"> ●</span>}</button>
              <button type="button" className="ws-tab-x" aria-label={`Close ${t.file.path}`} onClick={() => close(t)}>×</button>
            </span>)}
          </div>
          {cur ? <>
            <div className="ws-filebar">
              <span className="mono-xs trunc" title={cur.file.path}><span className="faint">{cur.file.project} / </span>{cur.file.path.split("/").join(" / ")}</span>
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
            {cur.file.kind !== "text" && <div className="ws-editor-wrap is-empty"><EmptyState title={cur.file.kind === "large" ? "Too large for the editor" : "Binary file"}
              hint={`${bytes(cur.file.size)} — download it instead. The editor opens UTF-8 text up to 2 MB.`} /></div>}
          </> : <div className="ws-editor-wrap is-empty"><EmptyState title="Open a file from the explorer"
            hint="Ctrl+P go to file · Ctrl+Shift+F search · Ctrl+S save (Developer Mode) · drop files from Windows onto a folder" /></div>}
          {/* Mounted while any text tab is open, so switching to a binary tab never drops another tab's edits. */}
          {textTab && <CodeEditor path={textTab.path} text={textTab.text} version={textTab.version} theme={theme} handle={editor}
            hidden={cur?.file.kind !== "text"} onSave={() => void save()}
            onChange={(x, text) => setTabs((ts) => ts.map((t) => t.path === x ? { ...t, dirty: text !== t.text } : t))} />}
        </div>
        {main === "claude" && <div className="ws-view"><ClaudePanel agent={coordinatorAgent} project={proj ? { key: proj.key, name: proj.name } : null}
          ticket={qt} model={cfg?.model ?? null} onMaximize={() => maximize("main")} /></div>}
        {main === "scm" && <div className="ws-view"><SourceControl project={key}
          ticket={ticket ? { key: ticket.key, title: ticket.title, branch: ticket.branch || null } : null}
          githubUrl={proj?.github?.url ?? null} prUrl={prUrl} onOpenFile={(x) => void openFile(x)} /></div>}
        {main === "search" && <div className="ws-view"><SearchPanel project={key} focusKey={searchFocus} onOpen={(x, line) => void openFile(x, undefined, line)} /></div>}
        {main === "dev" && <div className="ws-view ws-devview">
          {qt ? <><div className="td-sec-title">{qt} · development</div><DevTrail row={devRow} repo={proj?.github?.slug ?? null} /></>
            : <div className="muted mono-xs">Open Workspace from a ticket (or pick one below) to see its trail here.</div>}
          <div className="td-sec-title" style={{ marginTop: 14 }}>{proj?.name} · tickets with development work</div>
          {projectRows.length ? <table className="tbl"><tbody>{projectRows.map((r) => <tr key={r.key} className="is-click" onClick={() => nav({ ticket: r.key })}>
            <td><span className="key">{r.key}</span></td><td className="is-title"><span className="t trunc">{r.title}</span></td>
            <td className="mono-xs">{r.branch?.name ?? "—"}</td><td className="mono-xs">{r.pr?.number != null ? `#${r.pr.number} ${r.pr.state}` : "—"}</td>
            <td className="mono-xs">{r.ci ?? "—"}</td><td className="mono-xs">{r.merge ?? "—"}</td></tr>)}</tbody></table>
            : <div className="muted mono-xs">No branches or PRs linked to {proj?.prefix} tickets yet.</div>}
        </div>}
      </section>
    </div>

    {termOpen && mainOpen ? <Splitter axis="y" value={p.wsTermH} min={120} max={Math.max(200, (typeof window !== "undefined" ? window.innerHeight : 900) - 220)}
      onChange={(v) => prefs.patch({ wsTermH: v })} label="Terminal height" invert /> : <span />}
    <section className="ws-panel" aria-label="Terminal panel" hidden={!termOpen}>
      <div className="tabs ws-termtabs" role="tablist" aria-label="Terminal">
        {(["claude", "repo", "server"] as Term[]).map((t) => <button key={t} type="button" role="tab" aria-selected={term === t} className="tab" onClick={() => setTerm(t)}>{termLabel(t)}</button>)}
        <span className="sl-fill" />
        <button type="button" className="btn is-quiet is-sm" aria-pressed={p.wsMax === "term"} onClick={() => maximize("term")} title="Ctrl+Shift+Enter">{p.wsMax === "term" ? "Restore" : "Maximize"}</button>
        <button type="button" className="btn is-quiet is-sm" onClick={() => prefs.patch({ wsTermOpen: false, wsMax: "none" })} aria-label="Hide terminal (Ctrl+`)">Hide</button>
      </div>
      <div className="ws-panel-body">
        <div className="ws-term-pane" hidden={term !== "claude"}>
          {seenTerms.has("claude") && <ClaudePanel compact agent={coordinatorAgent} project={proj ? { key: proj.key, name: proj.name } : null}
            ticket={qt} model={cfg?.model ?? null} onMaximize={() => setMain("claude")} />}
        </div>
        {/* Terminals stay mounted once opened, so switching tabs never reconnects. */}
        {proj && seenTerms.has("repo") && <div className="ws-term-pane" hidden={term !== "repo"}>
          <TerminalView key={`repo:${proj.prefix}`} name={`repo:${proj.prefix}`} label={termLabel("repo")} active={term === "repo" && termOpen} theme={theme} onMaximize={() => maximize("term")} />
        </div>}
        {seenTerms.has("server") && <div className="ws-term-pane" hidden={term !== "server"}>
          <TerminalView name="server" label="Server shell" active={term === "server" && termOpen} theme={theme} onMaximize={() => maximize("term")} />
        </div>}
      </div>
    </section>

    {menu && <div className="ctx-scrim" onMouseDown={() => setMenu(null)} onContextMenu={(e) => { e.preventDefault(); setMenu(null); }}>
      <ul className="ctx" role="menu" style={{ left: Math.min(menu.x, window.innerWidth - 220), top: Math.min(menu.y, window.innerHeight - 280) }}
        onMouseDown={(e) => e.stopPropagation()}>
        <li className="ctx-head mono-xs faint">{menu.path || "/"}</li>
        {menuItems(menu).map((it, i) => <li key={it.label} role="none"><button type="button" role="menuitem" autoFocus={i === 0}
          className={`ctx-item${it.danger ? " is-danger" : ""}`} onClick={() => { setMenu(null); it.run(); }}>{it.label}</button></li>)}
      </ul>
    </div>}
    {naming && <NameDialog title={naming.title} initial={naming.initial} onDone={naming.done} onClose={() => setNaming(null)} />}
    {goto && <GoToFile project={key} onOpen={(x) => void openFile(x)} onClose={() => setGoto(false)} />}
    {ask && <Dialog title={`${ask.name} already exists`} onClose={() => setUploads((us) => us.map((x) => x.id === ask.id ? { ...x, state: "fail", msg: "skipped" } : x))}>
      <p className="text2">A file named <span className="mono">{ask.name}</span> is already in <span className="mono">{ask.project}/{ask.dir || ""}</span>. Nothing was overwritten.</p>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn is-jay" onClick={() => void sendUpload(ask, "replace")}>Replace</button>
        <button type="button" className="btn" data-autofocus onClick={() => void sendUpload(ask, "rename")}>Keep both (rename)</button>
        <button type="button" className="btn is-quiet" onClick={() => setUploads((us) => us.map((x) => x.id === ask.id ? { ...x, state: "fail", msg: "skipped" } : x))}>Skip</button>
      </div>
    </Dialog>}
  </div>;
}
