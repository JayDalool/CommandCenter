// One Monaco instance, many models: each open tab keeps its own text, cursor
// and undo history. Monaco is imported lazily, so Overview and Tasks never load it.
import { useEffect, useRef, useState } from "react";
import type * as Monaco from "monaco-editor";

type M = typeof Monaco;
let loading: Promise<M> | null = null;
function loadMonaco(): Promise<M> {
  loading ??= import("./monaco").then((m) => m.monaco as unknown as M);
  return loading;
}

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

export interface EditorHandle { value(path: string): string | null; dispose(path: string): void }

export function CodeEditor({ path, text, version, onChange, onSave, theme, handle }: {
  path: string; text: string; version: number; onChange: (path: string, text: string) => void; onSave: () => void;
  theme: "dark" | "light"; handle: React.RefObject<EditorHandle | null>;
}) {
  const host = useRef<HTMLDivElement>(null);
  const ed = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const mon = useRef<M | null>(null);
  const models = useRef(new Map<string, { model: Monaco.editor.ITextModel; version: number }>());
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
        value: (p) => models.current.get(p)?.model.getValue() ?? null,
        dispose: (p) => { models.current.get(p)?.model.dispose(); models.current.delete(p); },
      };
      setReady(true);
    }).catch((e) => setErr(String(e?.message ?? e)));
    return () => {
      dead = true;
      ed.current?.dispose();
      models.current.forEach((m) => m.model.dispose());
      models.current.clear();
      handle.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { mon.current?.editor.setTheme(theme === "light" ? "vs" : "vs-dark"); }, [theme, ready]);

  // Show `path`; (re)load its text only when the caller bumps `version` (open, reload, saved-as-new).
  useEffect(() => {
    const m = mon.current, e = ed.current;
    if (!m || !e) return;
    let rec = models.current.get(path);
    if (!rec) {
      const model = m.editor.createModel(text, languageOf(path));
      model.onDidChangeContent(() => change.current(path, model.getValue()));
      rec = { model, version };
      models.current.set(path, rec);
    } else if (rec.version !== version) {
      rec.model.setValue(text);
      rec.version = version;
    }
    if (e.getModel() !== rec.model) e.setModel(rec.model);
  }, [path, text, version, ready]);

  if (err) return <div className="ws-editor is-empty"><span className="bad-t">Editor failed to load: {err}</span></div>;
  return <div className="ws-editor-wrap">
    {!ready && <span className="muted ws-loading">Loading editor…</span>}
    <div className="ws-editor" ref={host} aria-label={`Editor: ${path}`} />
  </div>;
}
