// Messages (Jay's answers C1-C8): Jay's conversations with the CTO and each project lead. Server: ccd/leadchat.py.
// A message is stored on the server and the lead gets one fixed nudge to read it with cc-inbox; nothing Jay writes is
// typed into a terminal. Files: images, PDF and Markdown. The server sends every file as a download; an image is shown
// by fetching its bytes and making a blob of the type the server read from them. A lead that is not running waits;
// Start asks the server, which checks the budgets first and says when starting would go over.
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import "./office.css";
import "./governance.css";
import "./messages.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { href } from "../../lib/router";
import { ApiError, uploadBytes } from "../../api/client";
import type { ChatConversation, ChatDelivery, ChatFile, ChatLead, ChatMessage, ChatOverBudget, ChatOverview } from "../../api/types";
import { jayQueue } from "../../tickets/model";
import { ago } from "../../lib/time";
import { Icon } from "../frame/icons";
import { usePageNav } from "./route";
import { Pill, cx, plural } from "./ui";

const ACCEPT = "image/png,image/jpeg,image/gif,image/webp,application/pdf,.md,.markdown,.txt";
const DELIVERY: Record<ChatDelivery, string> = {
  nudged: "Sent. The lead has been told to read it.",
  queued: "Sent. The lead is busy and will be told when it is free.",
  "lead-offline": "Sent. The lead is not running, so the message waits for it.",
  "lead-paused": "Sent. This project is paused, so its lead is not told until it resumes.",
};

/** The newest Messages event, so a page that is open reloads when a lead replies or reads. */
function useChatPulse() {
  return useSelector(app.store, (d) => d.activity.find((e) => e.kind.startsWith("chat.") || e.kind === "action.chat_start")?.seq ?? 0);
}

function leadPill(l: ChatLead): [string, string] {
  if (l.paused) return ["Paused", "idle"];
  if (!l.running) return l.state === "found" || l.state === "multiple" ? ["Not identified", "warn"] : ["Not running", "idle"];
  if (l.status === "blocked") return ["Waiting on you", "jay"];
  return l.idle ? ["Ready", "ok"] : ["Working", "info"];
}

function useOverview(pulse: number) {
  const [data, setData] = useState<ChatOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    app.api.chat().then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e instanceof ApiError && e.status === 503 ? "Messages is not set up on this server yet." : (e as Error).message));
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15_000); return () => clearInterval(t); }, [load]);
  useEffect(() => { if (pulse) load(); }, [pulse, load]);
  return { data, error, reload: load };
}

export function Messages() {
  const { route, go } = usePageNav();
  const pulse = useChatPulse();
  const { data, error, reload } = useOverview(pulse);
  const convs = data?.conversations ?? [];
  const sel = route.params.get("c");
  const current = convs.find((c) => c.id === sel) ?? null;
  const pick = (id: string | null) => go("messages", null, id ? { c: id } : {});

  return <div className={cx("hq-page hq-messages", current && "has-thread")}>
    <header className="hq-hero"><div><h2>Messages</h2>
      <p>Talk to the CTO and each project's lead.</p></div></header>
    {error && !data ? <section className="hq-panel"><p className="hq-note" role="alert">{error}</p></section>
      : <div className="hq-chat">
        <nav className="hq-chat-list" aria-label="Conversations">
          {!data && <p className="hq-empty">Loading…</p>}
          {convs.map((c) => <ConvRow key={c.id} c={c} on={c.id === sel} onPick={() => pick(c.id)} />)}
        </nav>
        {current ? <Thread key={current.id} conv={current} canStart={!!data?.canStart} pulse={pulse}
          limits={data!.limits} onBack={() => pick(null)} onChange={reload} />
          : <section className="hq-chat-thread is-empty" aria-label="Conversation">
            <p className="hq-empty">Choose a conversation.</p></section>}
      </div>}
  </div>;
}

function ConvRow({ c, on, onPick }: { c: ChatConversation; on: boolean; onPick: () => void }) {
  const [label, tone] = leadPill(c.lead);
  const now = Date.now() / 1000;
  return <button type="button" className={cx("hq-chat-row", on && "is-on")} aria-current={on ? "true" : undefined} onClick={onPick}>
    <span className={cx("hq-chat-av", c.kind === "cto" && "is-cto")} aria-hidden
      style={c.kind === "project" ? { background: `var(--hq-pj-${c.id}, var(--hq-node-neutral))` } : undefined}>
      {c.kind === "cto" ? "CTO" : c.name.slice(0, 2)}</span>
    <span className="hq-chat-row-main">
      <span className="hq-chat-row-top"><b>{c.kind === "cto" ? "CTO" : `${c.name} lead`}</b>
        {c.last && <time>{ago(c.last.at, now)}</time>}</span>
      <span className="hq-chat-row-sub hq-ellip">{c.last ? `${c.last.side === "jay" ? "You: " : ""}${c.last.text || plural(c.last.files, "file")}`
        : "No messages yet"}</span>
    </span>
    <span className="hq-chat-row-end">
      {c.unread > 0 ? <span className="hq-badge is-jay" aria-label={`${c.unread} unread`}>{c.unread}</span>
        : <Pill tone={tone}>{label}</Pill>}
    </span>
  </button>;
}

function Thread({ conv, canStart, pulse, limits, onBack, onChange }: {
  conv: ChatConversation; canStart: boolean; pulse: number; limits: ChatOverview["limits"]; onBack: () => void; onChange: () => void;
}) {
  const [msgs, setMsgs] = useState<ChatMessage[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const load = useCallback(() => {
    app.api.chatHistory(conv.id).then((d) => { setMsgs(d.messages); setErr(null); }).catch((e) => setErr((e as Error).message));
  }, [conv.id]);
  useEffect(load, [load]);
  useEffect(() => { if (pulse) load(); }, [pulse, load]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [msgs?.length]);
  // Reading the conversation marks the lead's messages read.
  const lastLead = msgs?.filter((m) => m.side === "lead" && !m.seenAt).at(-1)?.id;
  useEffect(() => {
    if (!lastLead) return;
    app.api.chatSeen(conv.id, lastLead).then(onChange).catch(() => {});
  }, [lastLead, conv.id, onChange]);

  const questions = useSelector(app.store, (d) => conv.kind === "project"
    ? jayQueue(d.state, undefined, d.tickets).filter((j) => j.project === conv.id && (j.kind === "questions" || j.kind === "answer")).length : 0);
  const who = conv.kind === "cto" ? "the CTO" : `the ${conv.name} lead`;

  return <section className="hq-chat-thread" aria-label={`Conversation with ${who}`}>
    <header className="hq-chat-head">
      <button type="button" className="hq-chat-back hq-btn" onClick={onBack} aria-label="All conversations"><Icon name="chevl" size={16} /></button>
      <div><h3>{conv.kind === "cto" ? "CTO" : `${conv.name} lead`}</h3>
        <small>{conv.kind === "cto" ? "Across every active repository" : conv.lead.name}</small></div>
      <Pill tone={leadPill(conv.lead)[1]}>{leadPill(conv.lead)[0]}</Pill>
    </header>
    <LeadBanner conv={conv} canStart={canStart} onDone={(t) => { setNotice(t); onChange(); }} />
    {questions > 0 && <a className="hq-chat-card" href={href("needs")}>
      <Icon name="shield" size={16} /><span><b>{plural(questions, "question")}</b> from {conv.name} wait for you in Decisions.</span>
      <Icon name="chevron" size={14} /></a>}
    <div className="hq-chat-log" role="log" aria-live="polite" aria-label="Messages">
      {err && <p className="hq-note" role="alert">Could not load the conversation: {err}</p>}
      {msgs && msgs.length === 0 && <p className="hq-empty">No messages yet. What you write here is kept, and {who} reads it when told.</p>}
      {msgs?.map((m) => <Bubble key={m.id} m={m} who={conv.kind === "cto" ? "CTO" : `${conv.name} lead`} />)}
      <div ref={end} />
    </div>
    {notice && <p className="hq-chat-notice" role="status">{notice}</p>}
    <Composer conv={conv} limits={limits} onSent={(m, d) => { setMsgs((x) => [...(x ?? []), m]); setNotice(DELIVERY[d]); onChange(); }} />
  </section>;
}

function LeadBanner({ conv, canStart, onDone }: { conv: ChatConversation; canStart: boolean; onDone: (text: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState<ChatOverBudget[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const l = conv.lead;
  if (l.running || l.state === "unknown") return null;
  const name = conv.kind === "cto" ? "The CTO" : `The ${conv.name} lead`;
  if (l.paused) return <p className="hq-chat-banner">{conv.name} is paused. Messages wait until you resume it.</p>;
  if (l.state === "found" || l.state === "multiple") {
    return <p className="hq-chat-banner">A Claude is running in {conv.name}'s folder but is not set as its lead. Adopt it in
      {" "}<a className="hq-link" href={href("workspace")}>Workspace</a>, and messages reach it.</p>;
  }
  const start = (ok = false) => {
    setBusy(true); setErr(null);
    app.api.chatStart(conv.id, ok).then((r) => {
      if (r.needsApproval) { setOver(r.overBudget ?? []); return; }
      setOver(null);
      onDone(r.started ? `${name} is starting. Your messages reach it once it is ready.` : `${name} is already running.`);
    }).catch((e) => setErr((e as Error).message)).finally(() => setBusy(false));
  };
  return <div className="hq-chat-banner" role="note">
    <span>{name} is not running. {conv.waiting > 0 ? `${plural(conv.waiting, "message")} wait${conv.waiting === 1 ? "s" : ""} for it.` : "Messages wait for it."}</span>
    {canStart ? <button type="button" className="hq-btn is-primary" disabled={busy} onClick={() => start(false)}>{busy ? "Starting…" : "Start it"}</button>
      : <span className="hq-note">Starting leads from here is switched off.</span>}
    {over && <div className="hq-chat-over" role="alertdialog" aria-label="Over budget">
      <p><b>Starting it would go over budget.</b> {over.map((o) => `${o.scope === "company" ? "Company" : o.key} ${o.period}: ${o.pct ?? "?"}% of $${o.limitUsd ?? "?"}`).join("; ")}.</p>
      <div><button type="button" className="hq-btn is-primary" disabled={busy} onClick={() => start(true)}>Start anyway</button>
        <button type="button" className="hq-btn" onClick={() => setOver(null)}>Not now</button></div>
    </div>}
    {err && <p className="hq-note" role="alert">{err}</p>}
  </div>;
}

function fmtSize(n: number) { return n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`; }

function Bubble({ m, who }: { m: ChatMessage; who: string }) {
  const mine = m.side === "jay";
  const at = new Date(m.at * 1000);
  return <article className={cx("hq-msg", mine ? "is-me" : "is-lead")} aria-label={`${mine ? "You" : who}, ${at.toLocaleString()}`}>
    <div className="hq-msg-bubble">
      {m.text && <p>{m.text}</p>}
      {m.files.length > 0 && <div className="hq-msg-files">{m.files.map((f) => <FileChip key={f.id} f={f} />)}</div>}
    </div>
    <footer><time dateTime={at.toISOString()}>{at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
      {m.via === "slack" && <span> · from Slack</span>}
      {mine && <span> · {m.seenAt ? "Read" : "Not read yet"}</span>}</footer>
  </article>;
}

function FileChip({ f }: { f: ChatFile }) {
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (f.kind !== "image") return;
    let gone = false, made: string | null = null;
    app.api.chatFileBlob(f).then((b) => { if (!gone) { made = URL.createObjectURL(b); setUrl(made); } }).catch(() => {});
    return () => { gone = true; if (made) URL.revokeObjectURL(made); };
  }, [f]);
  const save = () => void app.api.download(`/api/chat/files/${encodeURIComponent(f.id)}`, f.name).catch((e) => app.toast((e as Error).message, "bad"));
  const preview = () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (text === null) app.api.chatFileBlob(f).then((b) => b.text()).then(setText).catch(() => setText("Could not read the file."));
  };
  if (f.kind === "image") {
    return <figure className="hq-msg-img">
      {url ? <button type="button" onClick={save} title={`Download ${f.name}`}><img src={url} alt={f.name} /></button>
        : <span className="hq-msg-img-wait">{f.name}</span>}
      <figcaption>{f.name} · {fmtSize(f.size)}</figcaption></figure>;
  }
  return <div className="hq-msg-file">
    <span className="hq-msg-file-ico" aria-hidden>{f.kind === "pdf" ? "PDF" : "MD"}</span>
    <span className="hq-msg-file-name"><b className="hq-ellip">{f.name}</b><small>{fmtSize(f.size)}</small></span>
    {f.kind === "markdown" && <button type="button" className="hq-btn" aria-expanded={open} onClick={preview}>{open ? "Hide" : "Read"}</button>}
    <button type="button" className="hq-btn" onClick={save}>Download</button>
    {open && <pre className="hq-msg-md">{text ?? "Loading…"}</pre>}
  </div>;
}

interface Pending { key: string; name: string; size: number; progress: number; id?: string; error?: string }

function Composer({ conv, limits, onSent }: { conv: ChatConversation; limits: ChatOverview["limits"]; onSent: (m: ChatMessage, d: ChatDelivery) => void }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Pending[]>([]);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const uploading = files.some((f) => !f.id && !f.error);
  const ready = files.filter((f) => f.id);
  const canSend = !sending && !uploading && (text.trim().length > 0 || ready.length > 0) && text.length <= limits.text;

  const add = (e: ChangeEvent<HTMLInputElement>) => {
    const list = [...(e.target.files ?? [])];
    e.target.value = "";
    for (const file of list.slice(0, Math.max(0, limits.filesPerMessage - files.length))) {
      const key = `${file.name}:${file.size}:${Math.random()}`;
      if (file.size > limits.fileBytes) {
        setFiles((x) => [...x, { key, name: file.name, size: file.size, progress: 0, error: `larger than ${fmtSize(limits.fileBytes)}` }]);
        continue;
      }
      setFiles((x) => [...x, { key, name: file.name, size: file.size, progress: 0 }]);
      const q = new URLSearchParams({ conversation: conv.id, name: file.name });
      (uploadBytes(`/api/chat/files?${q}`, file, (p) => setFiles((x) => x.map((f) => f.key === key ? { ...f, progress: p } : f))) as
        unknown as Promise<{ file: ChatFile }>)
        .then((r) => setFiles((x) => x.map((f) => f.key === key ? { ...f, id: r.file.id, progress: 1 } : f)))
        .catch((e) => setFiles((x) => x.map((f) => f.key === key ? { ...f, error: (e as Error).message } : f)));
    }
  };
  const send = () => {
    if (!canSend) return;
    setSending(true); setErr(null);
    app.api.chatSend(conv.id, text, ready.map((f) => f.id!)).then((r) => {
      setText(""); setFiles([]); onSent(r.message, r.delivery);
    }).catch((e) => setErr((e as Error).message)).finally(() => setSending(false));
  };
  const keys = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
  };
  const who = conv.kind === "cto" ? "the CTO" : `the ${conv.name} lead`;
  const tooLong = text.length > limits.text;
  return <div className="hq-chat-compose">
    {files.length > 0 && <ul className="hq-chat-pending" aria-label="Files to send">{files.map((f) => <li key={f.key} className={cx(f.error && "is-bad")}>
      <span className="hq-ellip">{f.name}</span>
      <small>{f.error ? f.error : f.id ? fmtSize(f.size) : `${Math.round(f.progress * 100)}%`}</small>
      <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((x) => x.filter((y) => y.key !== f.key))}><Icon name="x" size={14} /></button>
    </li>)}</ul>}
    <div className="hq-chat-box">
      <button type="button" className="hq-btn hq-chat-attach" aria-label="Attach an image, PDF or Markdown file" title="Attach an image, PDF or Markdown file"
        onClick={() => input.current?.click()} disabled={files.length >= limits.filesPerMessage}><Icon name="plus" size={16} /></button>
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={add} />
      <textarea aria-label={`Message ${who}`} placeholder={`Message ${who}`} rows={2} value={text}
        onChange={(e) => setText(e.target.value)} onKeyDown={keys} />
      <button type="button" className="hq-btn is-primary" onClick={send} disabled={!canSend}>{sending ? "Sending…" : "Send"}</button>
    </div>
    {(err || tooLong) && <p className="hq-note" role="alert">{tooLong ? `A message is at most ${limits.text} characters.` : err}</p>}
  </div>;
}

/** The unread count for the sidebar and the bell (state.chat, refreshed with every event). */
export function useChatUnread(): number {
  return useSelector(app.store, (d) => d.state?.chat?.unread ?? 0);
}

export const _test = { DELIVERY, leadPill };
