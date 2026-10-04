// ATTACHMENTS — files attached to a ticket or a project. They are stored by ccd
// outside every repository, are never rendered or run in the page, and always
// download as files. Adding and removing need Developer Mode.
import { useCallback, useEffect, useState } from "react";
import { app } from "../store/app";
import { uploadBytes, ApiError } from "../api/client";
import type { Attachment } from "../api/types";
import { stamp } from "../lib/time";
import { Panel } from "./ui";
import { unlockDialogOpen, useDevActive } from "./DevMode";

export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function typeOf(name: string) { const ext = name.includes(".") ? name.split(".").pop()!.toUpperCase() : ""; return ext || "FILE"; }

export function AttachmentsPanel({ owner, ownerKey }: { owner: "ticket" | "project"; ownerKey: string }) {
  const dev = useDevActive();
  const [rows, setRows] = useState<Attachment[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ name: string; f: number }[]>([]);
  const [over, setOver] = useState(false);

  const load = useCallback(async () => {
    try { setRows((await app.api.attachments(owner, ownerKey)).attachments); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, [owner, ownerKey]);
  useEffect(() => { void load(); }, [load]);

  const add = async (files: FileList | File[]) => {
    if (!dev) { unlockDialogOpen(); return; }
    for (const file of Array.from(files)) {
      setProgress((p) => [...p, { name: file.name, f: 0 }]);
      try {
        await uploadBytes(`/api/attachments?${new URLSearchParams({ owner, key: ownerKey, name: file.name })}`, file,
          (f) => setProgress((p) => p.map((x) => x.name === file.name ? { ...x, f } : x)));
        app.toast(`Attached ${file.name}`);
      } catch (e) {
        app.toast(`${file.name}: ${(e as ApiError).message}`, "bad");
      } finally {
        setProgress((p) => p.filter((x) => x.name !== file.name));
      }
    }
    void load();
  };

  return <Panel title="Attachments" count={rows?.length ?? 0} tools={<label className="btn is-sm">
      Attach file<input type="file" multiple hidden onChange={(e) => { if (e.target.files) void add(e.target.files); e.target.value = ""; }}
        onClick={(e) => { if (!dev) { e.preventDefault(); unlockDialogOpen(); } }} aria-label="Attach file" /></label>}>
    <div className={`att-drop${over ? " is-over" : ""}`}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) void add(e.dataTransfer.files); }}>
      {err && <div className="bad-t mono-xs">{err}</div>}
      {progress.map((p) => <div key={p.name} className="row mono-xs"><span className="trunc">{p.name}</span>
        <progress max={1} value={p.f} aria-label={`Uploading ${p.name}`} /></div>)}
      {rows && rows.length > 0 ? <table className="tbl"><thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Uploaded</th><th>By</th><th /></tr></thead>
        <tbody>{rows.map((a) => <tr key={a.id}>
          <td className="is-title"><span className="t trunc" title={a.name}>{a.name}</span></td>
          <td className="mono-xs muted">{typeOf(a.name)}</td>
          <td className="mono-xs">{bytes(a.size)}</td>
          <td className="mono-xs muted">{stamp(a.uploadedAt)}</td>
          <td className="mono-xs muted">{a.uploadedBy}</td>
          <td className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
            <button type="button" className="btn is-quiet is-sm" onClick={() =>
              void app.api.download(`/api/attachments/${a.id}/download`, a.name).catch((e) => app.toast((e as Error).message, "bad"))}>Download</button>
            <button type="button" className="btn is-quiet is-sm" onClick={async () => {
              if (!dev) { unlockDialogOpen(); return; }
              if (await app.action(() => app.api.removeAttachment(a.id), `Removed ${a.name}`)) void load();
            }}>Remove</button></td></tr>)}</tbody></table>
        : <div className="muted mono-xs">{rows ? "No attachments. Drop files here or use Attach file." : "Loading…"}</div>}
      <div className="mono-xs faint">Stored by Command Center outside the repository · never committed · downloads only</div>
    </div>
  </Panel>;
}
