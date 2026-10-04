// One Monaco instance, many models: each open tab keeps its own text, cursor
// and undo history. Monaco is imported lazily, so Overview and Tasks never load it.
import { useEffect, useRef, useState } from "react";
import type * as Monaco from "monaco-editor";
import { handleChunkError } from "../lib/stale";

type M = typeof Monaco;

/** A lazy loader that shares one in-flight import but NEVER caches a failure (or a module that
 *  came back without what we need): the next call imports again. */
export function lazyOnce<T>(load: () => Promise<T>, ok: (v: T) => boolean = (v) => v != null): () => Promise<T> {
  let p: Promise<T> | null = null;
  return () => {
    p ??= load().then((v) => {
      if (!ok(v)) throw new TypeError("Failed to fetch dynamically imported module (module came back empty)");
      return v;
    }).catch((e) => { p = null; throw e; });
    return p;
  };
}
const loadMonaco = lazyOnce(() => import("./monaco").then((m) => m?.monaco as unknown as M), (m) => !!m?.editor);

const LANG: Record<string, string> = {
  py: "python", ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript", mjs: "javascript",
  json: "json", md: "markdown", css: "css", scss: "scss", html: "html", yml: "yaml", yaml: "yaml", sh: "shell",
  bash: "shell", go: "go", rs: "rust", sql: "sql", toml: "ini", ini: "ini", xml: "xml", svg: "xml",
  dockerfile: "dockerfile", java: "java", kt: "kotlin", c: "c", h: "c", cpp: "cpp", cs: "csharp", rb: "ruby",
  php: "php", swift: "swift", lua: "lua", r: "r", ps1: "powershell",
};
export function languageOf(path: string): string {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  if (name === "dockerfile") return "dockerfile";
  return LANG[name.split(".").pop() ?? ""] ?? "plaintext";
}

// Open files' models outlive the component: leaving Workspace, or viewing a
// binary tab, must never drop unsaved text. A model goes only when its tab closes.
const models = new Map<string, { model: Monaco.editor.ITextModel; version: number }>();
const listeners = new Map<string, (text: string) => void>();

/** Drop a closed tab's model, whether or not the editor is mounted. */
export function disposeModel(path: string) {
  models.get(path)?.model.dispose();
  models.delete(path);
  listeners.delete(path);
}

/** A version no other tab has ever had, so a reopened file never matches a leftover model. */
let versions = 0;
export function nextVersion() { return ++versions; }

// A line to show once a path's model is on screen (search results, Go to File).
const pendingReveal = new Map<string, number>();
let revealNow: ((path: string, line: number) => boolean) | null = null;
export function revealLine(path: string, line: number) {
  if (!revealNow?.(path, line)) pendingReveal.set(path, line);
}

/** For tests. */
export function hasModel(path: string) { return models.has(path); }

export interface EditorHandle { value(path: string): string | null; dispose(path: string): void }

export function CodeEditor({ path, text, version, onChange, onSave, theme, handle, hidden = false }: {
  path: string; text: string; version: number; hidden?: boolean; onChange: (path: string, text: string) => void; onSave: () => void;
  theme: "dark" | "light"; handle: React.RefObject<EditorHandle | null>;
}) {
  const host = useRef<HTMLDivElement>(null);
  const ed = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const mon = useRef<M | null>(null);
  const save = useRef(onSave);
  save.current = onSave;
  const change = useRef(onChange);
  change.current = onChange;
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let dead = false;
    loadMonaco().then((m) => {
      if (dead || !host.current) return;
      mon.current = m;
      ed.current = m.editor.create(host.current, {
        automaticLayout: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false,
        renderWhitespace: "selection", tabSize: 4, insertSpaces: true, theme: theme === "light" ? "vs" : "vs-dark",
      });
      ed.current.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => save.current());
      handle.current = {
        value: (p) => models.get(p)?.model.getValue() ?? null,
        dispose: disposeModel,
      };
      revealNow = (p, line) => {
        const e = ed.current;
        if (!e || e.getModel() !== models.get(p)?.model) return false;
        e.revealLineInCenter(line); e.setPosition({ lineNumber: line, column: 1 }); e.focus();
        return true;
      };
      setReady(true);
    }).catch((e) => {
      setErr(handleChunkError(e) ? "Command Center was updated while this window was open — reloading to the new version."
        : String(e?.message ?? e));
    });
    return () => {
      dead = true;
      ed.current?.dispose();  // the models stay; see `models`
      revealNow = null;
      handle.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { mon.current?.editor.setTheme(theme === "light" ? "vs" : "vs-dark"); }, [theme, ready]);

  // Show `path`; (re)load its text only when the caller bumps `version` (open, reload, saved-as-new).
  useEffect(() => {
    const m = mon.current, e = ed.current;
    if (!m || !e) return;
    listeners.set(path, (t) => change.current(path, t));
    let rec = models.get(path);
    if (!rec) {
      const model = m.editor.createModel(text, languageOf(path));
      model.onDidChangeContent(() => listeners.get(path)?.(model.getValue()));
      rec = { model, version };
      models.set(path, rec);
    } else if (rec.version !== version) {
      rec.model.setValue(text);
      rec.version = version;
    }
    if (e.getModel() !== rec.model) e.setModel(rec.model);
    const line = pendingReveal.get(path);
    if (line) { pendingReveal.delete(path); e.revealLineInCenter(line); e.setPosition({ lineNumber: line, column: 1 }); e.focus(); }
  }, [path, text, version, ready]);
  useEffect(() => { if (!hidden) ed.current?.layout(); }, [hidden]);

  if (err) return <div className="ws-editor is-empty"><span className="bad-t">Editor failed to load: {err}</span></div>;
  return <div className={`ws-editor-wrap${hidden ? " is-hidden" : ""}`}>
    {!ready && <span className="muted ws-loading">Loading editor…</span>}
    <div className="ws-editor" ref={host} aria-label={`Editor: ${path}`} />
  </div>;
}
