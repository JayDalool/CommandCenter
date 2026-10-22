// Every detachable thing has a stable view id. The id names WHAT is shown, never a credential:
//   page:<page>      a top-level page (My Office, Messages, …)
//   dm:<conversation> one conversation
//   task:<KEY>       a Task Room
//   term:<KEY>       a Task Room's terminal pane
//   panel:<name>     an inspector / side panel
import { conversation, project, task } from "../data/seed";
import { PAGES, type Page } from "../lib/router";

export type ViewKind = "page" | "dm" | "task" | "term" | "panel";
export interface ViewDef { id: string; kind: ViewKind; title: string; sub?: string; color?: string; hash: string }

export const PAGE_TITLE: Record<Page, string> = { office: "My Office", messages: "Messages", decisions: "Decisions", teams: "Teams",
  topology: "Operations Topology", engineering: "Engineering", revenue: "Revenue", more: "More" };

const PANELS: Record<string, { title: string; hash: string }> = {
  "topology-inspector": { title: "Topology Inspector", hash: "#/topology" },
  "task-context": { title: "Current Task Context", hash: "#/messages" },
  evidence: { title: "Evidence & Context", hash: "#/decisions" },
  "task-detail": { title: "Task Detail", hash: "#/engineering" },
};

export const ID_SHAPE = /^(page|dm|task|term|panel):[A-Za-z0-9_-]{1,64}$/;

export function viewById(id: string): ViewDef | null {
  if (!ID_SHAPE.test(id)) return null;
  const [kind, rest] = id.split(":") as [ViewKind, string];
  if (kind === "page") return (PAGES as readonly string[]).includes(rest)
    ? { id, kind, title: PAGE_TITLE[rest as Page], hash: `#/${rest}` } : null;
  if (kind === "dm") {
    const c = conversation(rest); if (!c) return null;
    return { id, kind, title: c.kind === "dm" ? `${c.project ? project(c.project).name : ""} · ${c.title} DM` : c.title, sub: c.sub,
      color: c.project ? project(c.project).color : undefined, hash: `#/messages/${rest}` };
  }
  if (kind === "task" || kind === "term") {
    const t = task(rest); if (!t) return null;
    return { id, kind, title: kind === "task" ? `${t.key} Task Room` : `${t.key} · Terminal`, sub: t.title,
      color: project(t.project).color, hash: `#/task/${rest}` };
  }
  const p = PANELS[rest];
  return p ? { id, kind, title: p.title, hash: p.hash } : null;
}

/** The view a main-window route shows (its tab). */
export function viewForRoute(screen: string, id: string | null): ViewDef | null {
  if (screen === "task" && id) return viewById(`task:${id}`);
  return viewById(`page:${screen}`);
}
