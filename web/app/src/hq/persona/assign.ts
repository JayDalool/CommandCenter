// Who gets which character. No storage: the same names always give the same faces, in every window. The CTO and each
// project's lead get a face of their own (no two leads share one while there are faces left); every other session
// takes whichever its name lands on, so two of those can look alike.
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

/** Any other session, by its name. */
export const castFor = (name: string): Character => CAST[hash(`agent:${name.toLowerCase()}`) % CAST.length];
