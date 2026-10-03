import type { CcdEvent } from "../api/types";
import { hms } from "../lib/time";
import { href } from "../lib/router";

export type FeedCat = "AGENT" | "TASK" | "PR" | "CI" | "JAY" | "HOST" | "ALERT" | "CCD" | "ACTION";
export function categorize(kind: string): FeedCat {
  if (kind === "jay.action_required") return "JAY";
  if (kind.startsWith("agent.")) return "AGENT";
  if (kind.startsWith("task.")) return "TASK";
  if (kind.startsWith("pr.")) return "PR";
  if (kind.startsWith("ci.")) return "CI";
  if (kind.startsWith("host.")) return "HOST";
  if (kind.startsWith("alert.")) return "ALERT";
  if (kind.startsWith("action.")) return "ACTION";
  return "CCD";
}
const CAT_CLASS: Record<FeedCat, string> = { AGENT: "cat-agent", TASK: "cat-task", PR: "cat-ci", CI: "cat-ci", JAY: "cat-jay",
  HOST: "cat-host", ALERT: "cat-warn", CCD: "", ACTION: "" };

/** Noise that is not "meaningful": our own focus clicks, routine reconnect chatter. */
export function meaningful(e: CcdEvent): boolean {
  return !["action.focus", "daemon.herdr_connected"].includes(e.kind);
}

export function ActivityRow({ e }: { e: CcdEvent }) {
  const cat = categorize(e.kind);
  const isTicket = cat === "TASK" && e.ref;
  const sev = e.severity === "warn" ? " warn-t" : e.severity === "action" ? " jay-t" : "";
  return <li className="feed-row">
    <time className="mono-xs muted" dateTime={new Date(e.at * 1000).toISOString()}>{hms(e.at).slice(0, 5)}</time>
    <span className={`cat ${CAT_CLASS[cat]}`}>{cat}</span>
    <span className={`feed-text${sev}`} title={e.text}>
      {e.project && <span className="mono-xs muted">{e.project} · </span>}
      {isTicket ? <a className="link" href={href("tasks", e.ref!)}>{e.text}</a> : e.text}
    </span>
  </li>;
}
