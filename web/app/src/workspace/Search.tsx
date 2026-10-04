// SEARCH IN PROJECT (Ctrl+Shift+F) and GO TO FILE (Ctrl+P). Both ask ccd on
// demand and are bounded there; typing again or closing cancels the request.
import { useEffect, useMemo, useRef, useState } from "react";
import { app } from "../store/app";
import type { SearchResult } from "../api/types";
import { scoreAll } from "../lib/fuzzy";
import { EmptyState } from "../components/ui";
import { useFocusTrap } from "../components/Dialog";

export function SearchPanel({ project, focusKey, onOpen }: { project: string; focusKey: number; onOpen: (path: string, line?: number) => void }) {
  const [q, setQ] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseS, setCaseS] = useState(false);
  const [glob, setGlob] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const ctl = useRef<AbortController | null>(null);
  useEffect(() => { input.current?.focus(); input.current?.select(); }, [focusKey]);
  useEffect(() => () => ctl.current?.abort(), []);

  const run = async () => {
    ctl.current?.abort();
    if (!q.trim()) { setRes(null); return; }
    const c = new AbortController();
    ctl.current = c;
    setBusy(true); setErr(null);
    try { setRes(await app.api.searchText(project, q, { regex, caseSensitive: caseS, glob: glob.trim() || undefined }, c.signal)); }
    catch (e) { if ((e as Error).name !== "AbortError") setErr((e as Error).message); }
    finally { if (ctl.current === c) setBusy(false); }
  };
  const groups = useMemo(() => {
    const m = new Map<string, SearchResult["matches"]>();
    res?.matches.forEach((x) => m.set(x.path, [...(m.get(x.path) ?? []), x]));
    return [...m.entries()];
  }, [res]);

  return <div className="search">
    <form className="search-bar" onSubmit={(e) => { e.preventDefault(); void run(); }}>
      <input ref={input} className="input grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search in project (Enter)" aria-label="Search text" />
      <button type="button" className="btn is-quiet is-sm" aria-pressed={caseS} onClick={() => setCaseS(!caseS)} title="Match case">Aa</button>
      <button type="button" className="btn is-quiet is-sm" aria-pressed={regex} onClick={() => setRegex(!regex)} title="Regular expression">.*</button>
      <input className="input is-sm" style={{ width: 130 }} value={glob} onChange={(e) => setGlob(e.target.value)} placeholder="files, e.g. *.py" aria-label="File filter" />
      {busy ? <button type="button" className="btn is-sm" onClick={() => { ctl.current?.abort(); setBusy(false); }}>Cancel</button>
        : <button type="submit" className="btn is-sm">Search</button>}
    </form>
    <div className="search-meta mono-xs muted">{err ? <span className="bad-t">{err}</span> : res
      ? `${res.matches.length} matches in ${res.files} files${res.truncated ? " — truncated, narrow the search" : ""} · .git, node_modules, build output and secret files are never searched`
      : "Searches the project's files on jay-server. Secret-looking files are excluded."}</div>
    <div className="search-res">
      {groups.map(([path, ms]) => <div key={path} className="search-file">
        <button type="button" className="search-path mono-xs" onClick={() => onOpen(path)}>{path} <span className="faint">{ms.length}</span></button>
        {ms.map((m, i) => <button type="button" key={i} className="search-hit" onClick={() => onOpen(path, m.line)}>
          <span className="mono-xs faint">{m.line}</span>
          <span className="mono-xs trunc">{m.ranges.length ? <>{m.text.slice(0, m.ranges[0][0])}<mark>{m.text.slice(m.ranges[0][0], m.ranges[0][1])}</mark>{m.text.slice(m.ranges[0][1])}</> : m.text}</span>
        </button>)}
      </div>)}
      {res && !res.matches.length && <EmptyState title="No matches" />}
    </div>
  </div>;
}

let fileCache: { project: string; at: number; files: string[] } | null = null;

export function GoToFile({ project, onOpen, onClose }: { project: string; onOpen: (path: string) => void; onClose: () => void }) {
  const ref = useFocusTrap(onClose);
  const [q, setQ] = useState("");
  const [files, setFiles] = useState<string[] | null>(fileCache?.project === project && Date.now() - fileCache.at < 30000 ? fileCache.files : null);
  const [err, setErr] = useState<string | null>(null);
  const [i, setI] = useState(0);
  useEffect(() => {
    if (files) return;
    const c = new AbortController();
    app.api.searchFiles(project, c.signal).then((r) => { fileCache = { project, at: Date.now(), files: r.files }; setFiles(r.files); })
      .catch((e) => { if ((e as Error).name !== "AbortError") setErr((e as Error).message); });
    return () => c.abort();
  }, [project, files]);
  const hits = useMemo(() => {
    if (!files) return [];
    if (!q.trim()) return files.slice(0, 50);
    return files.map((f) => ({ f, s: scoreAll(q, [f.split("/").pop() ?? f, f]) })).filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s || a.f.length - b.f.length).slice(0, 50).map((x) => x.f);
  }, [files, q]);
  useEffect(() => setI(0), [q]);
  const pick = (p: string) => { onOpen(p); onClose(); };
  return <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="palette" role="dialog" aria-modal="true" aria-label="Go to file" ref={ref}>
      <div className="palette-input"><span className="prompt">›</span><input value={q} onChange={(e) => setQ(e.target.value)} data-autofocus placeholder="Go to file…" aria-label="File name"
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(x + 1, hits.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(x - 1, 0)); }
          else if (e.key === "Enter" && hits[i]) { e.preventDefault(); pick(hits[i]); }
        }} /></div>
      <ul className="palette-list" role="listbox">
        {err ? <li className="bad-t">{err}</li> : !files ? <li className="muted">Listing files…</li> : hits.map((h, k) =>
          <li key={h} role="option" aria-selected={k === i} className={`pal-row${k === i ? " is-active" : ""}`} onMouseDown={() => pick(h)}>
            <span className="mono">{h.split("/").pop()}</span><span className="mono-xs faint trunc">{h}</span></li>)}
      </ul>
    </div>
  </div>;
}
