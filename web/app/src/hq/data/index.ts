// HQ's live-data layer: pure functions from Classic's store to the view models HQ pages read.
// No fetches, no writes, no new endpoints. See evidence.ts for the one rule: status only from evidence.
export * from "./evidence";
export * from "./decisions";
export * from "./engineering";
export * from "./teams";
export * from "./office";
export * from "./topology";
export * from "./activity";
export * from "./milestones";
export * from "./floor";
export * from "./seats";

import { evidence, type HqSource } from "./evidence";
import { buildOffice } from "./office";
import { buildEngineering } from "./engineering";
import { buildDecisions } from "./decisions";
import { buildTopology } from "./topology";
import { buildTeams } from "./teams";
import { buildActivity, buildAlerts } from "./activity";

/** Every page's view model from one snapshot, in roadmap order. Handy for tests and a pop-out's first paint. */
export function buildHq(src: HqSource, now: number) {
  const ev = evidence(src, now);
  return {
    evidence: ev,
    office: buildOffice(src, ev),
    engineering: buildEngineering(src, ev),
    decisions: buildDecisions(src),
    topology: buildTopology(src, ev),
    teams: buildTeams(src, ev),
    activity: buildActivity(src.activity, src.tickets),
    alerts: buildAlerts(src.state?.alerts),
  };
}
