// Who gets which character. No storage: the same names always give the same faces, in every window. The CTO and each
// project's lead get a face of their own first; then every other session herdr reports takes the face its name lands
// on, or the next free one. So no two look alike while there are faces left. A name that is not a session (a subagent
// a coordinator can call) takes whichever its name lands on, and can look like someone else.
import { CAST, type Character } from "./characters";

/** FNV-1a, 32 bit: small, stable, and spread well enough for 30 slots. */
export function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return h >>> 0;
}

/** The lead of each project key, plus "cto". Keys are taken in sorted order, so the result does not depend on the
 *  order projects are listed in; a key whose slot is taken moves to the next free one. */
export function castLeads(projectKeys: readonly string[]): Map<string, Character> {
  const out = new Map<string, Character>(), used = new Set<number>();
  for (const key of ["cto", ...[...new Set(projectKeys)].filter((k) => k !== "cto").sort()]) {
    let i = hash(`lead:${key}`) % CAST.length;
    if (used.size < CAST.length) while (used.has(i)) i = (i + 1) % CAST.length;
    used.add(i);
    out.set(key, CAST[i]);
  }
  return out;
}

/** Every project key the server names, from its three lists (the task registry, the config, the polled projects):
 *  the one list every page casts leads from, so a lead has the same face in My Office, Teams and Messages. */
export function leadKeys(src: { taskProjects: readonly { key: string }[];
  state: { projectsConfig?: readonly { key: string }[]; projects?: readonly { key: string }[] } | null }): string[] {
  return [...src.taskProjects, ...(src.state?.projectsConfig ?? []), ...(src.state?.projects ?? [])].map((p) => p.key);
}

/** Every other session, by name, after the leads. Names are taken in sorted order: a session keeps its face from
 *  one report to the next unless an earlier name that lands on the same face arrives or leaves. Keys are lower case. */
export function castSessions(leads: ReadonlyMap<string, Character>, names: readonly string[]): Map<string, Character> {
  const out = new Map<string, Character>(), used = new Set([...leads.values()].map((c) => CAST.indexOf(c)));
  for (const name of [...new Set(names.map((n) => n.toLowerCase()))].sort()) {
    let i = hash(`agent:${name}`) % CAST.length;
    if (used.size < CAST.length) while (used.has(i)) i = (i + 1) % CAST.length;
    used.add(i);
    out.set(name, CAST[i]);
  }
  return out;
}

/** A name that is not a session herdr reports. */
export const castFor = (name: string): Character => CAST[hash(`agent:${name.toLowerCase()}`) % CAST.length];
