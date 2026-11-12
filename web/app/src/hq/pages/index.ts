// The HQ pages that replace a Classic screen at the same address while the HQ preview is on (hq/frame/Frame.tsx).
// Every other address shows the Classic screen inside the frame. Classic itself never loads these.
import type { Route } from "../../lib/router";
import { Office } from "./Office";
import { Engineering } from "./Engineering";
import { Decisions } from "./Decisions";

export type HqPage = () => React.JSX.Element;

/** The HQ page for an address, or null for the Classic screen. #/tasks/KEY is Engineering with that task open. An
 *  address that asks for Classic's own Tasks views (?view=board, ?status=…) keeps Classic's Tasks screen. */
export function hqPageFor(r: Pick<Route, "screen" | "params">): HqPage | null {
  switch (r.screen) {
    case "dashboard": case "overview": return Office;
    case "needs": return Decisions;
    case "tasks": return r.params.has("view") || r.params.has("status") ? null : Engineering;
    default: return null;
  }
}
