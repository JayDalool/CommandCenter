// The office floor (My Office › Sessions › Floor): where each session is, from its presence and nothing else.
//
// A session has one desk, with its project's team, and sits at it only while herdr says it is working. Waiting on
// Jay puts it at his door, in the order the waits began. Idle is the lounge, offline is out of the office. A session
// herdr cannot vouch for right now (the feed is not live) is "not seen": no desk is drawn as occupied on old data.
import type { Presence } from "./evidence";
import type { TeamMember, TeamsView } from "./teams";

export type Spot = "desk" | "door" | "lounge" | "out" | "unseen";

export const SPOT: Record<Presence, Spot> = { working: "desk", waiting: "door", idle: "lounge", offline: "out", unknown: "unseen" };

export interface FloorPerson extends TeamMember {
  spot: Spot;
  /** The project whose team this session sits with. Null for a session herdr reports with no project. */
  project: string | null;
  projectName: string | null;
}

/** One team's desks: the lead's first, then the rest by name, so a desk stays where it is from one report to the next. */
export interface FloorTeam { key: string | null; name: string; desks: FloorPerson[] }

export interface FloorView {
  teams: FloorTeam[];
  /** Longest wait first. */
  door: FloorPerson[];
  lounge: FloorPerson[];
  out: FloorPerson[];
  unseen: FloorPerson[];
  total: number;
}

const byName = (a: TeamMember, b: TeamMember) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id);

export function buildFloor(t: TeamsView): FloorView {
  const seat = (key: string | null, name: string | null) => (m: TeamMember): FloorPerson => ({ ...m, spot: SPOT[m.presence], project: key, projectName: name });
  const teams: FloorTeam[] = t.teams
    .map((x) => ({ key: x.key, name: x.name, desks: [...(x.lead ? [x.lead] : []), ...[...x.members].sort(byName)].map(seat(x.key, x.name)) }))
    .filter((x) => x.desks.length > 0);
  if (t.unassigned.length) teams.push({ key: null, name: "No project", desks: [...t.unassigned].sort(byName).map(seat(null, null)) });
  const all = teams.flatMap((x) => x.desks);
  const at = (s: Spot) => all.filter((p) => p.spot === s);
  return { teams, lounge: at("lounge"), out: at("out"), unseen: at("unseen"), total: all.length,
    door: at("door").sort((a, b) => (a.waitingSince ?? Infinity) - (b.waitingSince ?? Infinity) || byName(a, b)) };
}
