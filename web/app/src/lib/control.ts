// The control room's shared vocabulary: visible stages and their colours, project identity, which
// tickets are "active", and the deep links notifications and panels use. No React here.
import type { State, Ticket, TicketStatus, VisibleStage } from "../api/types";
import type { JayItem } from "../tickets/model";
import { href } from "./router";

/** Spec §24 stages, coloured as the approved references: Planning purple, Implementing blue,
 *  Reviewing yellow, Needs Jay red, Ready to Merge green, Closed grey. */
export const STAGE: Record<VisibleStage, { tone: string; short: string }> = {
  Planning: { tone: "plan", short: "Planning" },
  Implementing: { tone: "impl", short: "Implementing" },
  Reviewing: { tone: "review", short: "Reviewing" },
  "UI Testing": { tone: "uitest", short: "UI Testing" },
  Verifying: { tone: "verify", short: "Verifying" },
  "Ready to Merge": { tone: "merge", short: "Ready to Merge" },
  Deploying: { tone: "deploy", short: "Deploying" },
  "Needs Jay": { tone: "jay", short: "Needs Jay" },
  Blocked: { tone: "blocked", short: "Blocked" },
  Closed: { tone: "closed", short: "Closed" },
};

const CLOSED: TicketStatus[] = ["DONE", "DENIED", "CANCELLED"];
const PLAN: TicketStatus[] = ["INBOX", "PROPOSED", "RESEARCHING", "READY_TO_IMPLEMENT"];

/** ccd sends `visibleStage`; an older ccd does not, so the same rule runs here from what the row has. */
export function stageOf(t: Ticket): VisibleStage {
  if (t.visibleStage) return t.visibleStage;
  if (CLOSED.includes(t.status)) return "Closed";
  if (t.status === "BLOCKED" || t.gate === "failure") return "Blocked";
  if ((t.openQuestions ?? 0) > 0 || t.gate) return "Needs Jay";
  if (t.flags.includes("needs_jay") && (t.status === "INBOX" || t.status === "PROPOSED")) return "Needs Jay";
  if (PLAN.includes(t.status)) return "Planning";
  if (t.status === "IN_PROGRESS") return "Implementing";
  if (t.status === "IN_REVIEW") return "Reviewing";
  if (t.status === "READY_TO_MERGE") return "Ready to Merge";
  if (t.status === "VERIFYING") return t.labels.includes("ui") || t.flags.includes("needs_ui_review") || t.type === "DESIGN" ? "UI Testing" : "Verifying";
  return "Planning";
}

/** Active = in the tree and the wall: open and not archived. Closed tickets leave at once (Task History keeps them). */
export function isActive(t: Ticket) { return !t.archived && !CLOSED.includes(t.status); }

/** Project order on the dashboard and in the tree: SV · GZ · CC · GYST · MFE (the references' order). */
export const PROJECT_ORDER = ["samvision", "gauzemate", "commandcenter", "gyst", "mfe"];
export function byProjectOrder<T extends { key: string }>(rows: T[]): T[] {
  const rank = (k: string) => { const i = PROJECT_ORDER.indexOf(k); return i < 0 ? 99 : i; };
  return [...rows].sort((a, b) => rank(a.key) - rank(b.key) || a.key.localeCompare(b.key));
}

export function initials(prefix: string | undefined, name: string): string {
  return (prefix || name).replace(/[^A-Za-z]/g, "").slice(0, 2).toUpperCase();
}

export const pjVar = (key: string) => ({ ["--pj" as string]: `var(--pj-${key}, var(--muted))` }) as React.CSSProperties;

export type Focus = "questions" | "gate" | "blocker" | "deploy" | "history" | null;

/** Where a Needs Jay item or a notification takes Jay: the task, its room, the exact action. */
export function taskHref(key: string, focus: Focus = null, open = true): string {
  return href("workspace", null, { task: key, focus: focus ?? undefined, open: open ? "1" : undefined });
}

export function projectName(st: State | null, key: string | null | undefined): string {
  return st?.projects.find((p) => p.key === key)?.name ?? key ?? "";
}

export function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 5 ? "Good Night" : h < 12 ? "Good Morning" : h < 18 ? "Good Afternoon" : "Good Evening";
}

const TICKET_KEY = /^[A-Z][A-Z0-9]{0,8}(?:-[A-Z0-9]{1,8})?-\d{1,6}$/;

/** A Needs Jay queue item → the exact place to act on it. */
export function jayHref(j: JayItem): string {
  if (j.kind === "questions") return taskHref(j.ref, "questions");
  if (j.kind === "gate") return taskHref(j.ref, j.gate === "failure" ? "blocker" : j.gate === "deploy" ? "deploy" : "gate");
  if (j.kind === "ticket") return taskHref(j.ref, null);
  if (j.kind === "answer") {
    // A blocked agent: its task room when it is a task session (sv-071), else the project console.
    const key = j.ref.toUpperCase();
    return TICKET_KEY.test(key) ? taskHref(key, null) : href("workspace", null, { console: j.project, open: "1" });
  }
  if (j.url) return j.url;
  return href("workspace", null, { project: j.project });
}

/** In words, what Jay is asked to do (the dashboard's "Needs Jay" bullets). */
export function jayWords(j: JayItem): string {
  if (j.kind === "questions" && j.flags.includes("stale") && j.questions === 1) return `Still needed? ${j.ref} (task check)`;
  if (j.kind === "questions") return `Answer ${j.questions ?? ""} question${j.questions === 1 ? "" : "s"} on ${j.ref}`.replace("  ", " ");
  if (j.kind === "gate") {
    const w = j.gate === "plan" ? "Approve plan" : j.gate === "merge" ? "Accept merge" : j.gate === "ui" ? "Review UI"
      : j.gate === "deploy" ? "Allow live deploy" : "Resolve blocker";
    return `${w} · ${j.ref}`;
  }
  if (j.kind === "answer") return `Answer ${j.ref}: ${j.text}`;
  if (j.kind === "merge") return `Merge ${j.ref}`;
  return j.text;
}
