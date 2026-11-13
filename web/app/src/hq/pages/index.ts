// The HQ pages that replace a Classic screen at the same address while the HQ preview is on (hq/frame/Frame.tsx).
// Every other address shows the Classic screen inside the frame. Classic itself never loads these.
import type { Route } from "../../lib/router";
import { Office } from "./Office";
import { Engineering } from "./Engineering";
import { Decisions } from "./Decisions";
import { Activity } from "./Activity";
import { Teams } from "./Teams";
import { Topology } from "./Topology";
import { Approvals } from "./Approvals";
import { Budgets } from "./Budgets";
import { Messages, Revenue } from "./NotConnected";
import { Settings } from "./Settings";

export type HqPage = () => React.JSX.Element;

/** The HQ page for an address, or null for the Classic screen. #/tasks/KEY is Engineering with that task open. An
 *  address that asks for Classic's own Tasks views (?view=board, ?status=…) keeps Classic's Tasks screen. One session
 *  (#/agents/ID) and one project (#/projects/KEY) keep Classic's screens, where their actions are. */
export function hqPageFor(r: Pick<Route, "screen" | "id" | "params">): HqPage | null {
  switch (r.screen) {
    case "dashboard": case "overview": return Office;
    case "needs": return Decisions;
    case "activity": return Activity;
    case "agents": return r.id ? null : Teams;
    case "projects": return r.id ? null : Topology;
    case "tasks": return r.params.has("view") || r.params.has("status") ? null : Engineering;
    case "approvals": return Approvals;
    case "budgets": return Budgets;
    case "messages": return Messages;
    case "revenue": return Revenue;
    case "settings": return Settings;
    default: return null;
  }
}
