// Professional or Childish (Settings › Appearance › Style, this browser only). Childish gives agents a character and
// adds emoji after some labels; Professional shows neither. Both are decoration: no status, count or control depends
// on the mode, and everything a face or emoji hints at is also in words.
import "./persona.css";
import { app, type AppData } from "../../store/app";
import type { State } from "../../api/types";
import { useSelector } from "../../lib/store";
import { usePrefs } from "../../lib/prefs";
import { castFor, castLeads, castSessions, leadKeys } from "./assign";
import { Face, type Character } from "./characters";
import type { Presence } from "../data";

export const useFun = () => usePrefs((p) => p.style === "childish");

/** An emoji after a label, in Childish mode only. Hidden from screen readers: the label already says it. */
export function Fun({ e }: { e: string }) {
  return useFun() ? <span className="hq-fun" aria-hidden>{" "}{e}</span> : null;
}

export const PRESENCE_EMOJI: Record<Presence, string> = { working: "🔨", waiting: "🙋", idle: "💤", offline: "🌙", unknown: "❔" };

type Tasks = AppData["taskProjects"];
let cast: { tasks: Tasks; state: State | null; leads: Map<string, Character>; sessions: Map<string, Character> } | null = null;

/** The whole cast for one snapshot of the store, worked out once however many faces are on the page. A lead's own
 *  session is left out of the others: it has the lead's face. */
function castOf(tasks: Tasks, state: State | null) {
  if (cast && cast.tasks === tasks && cast.state === state) return cast;
  const leads = castLeads(leadKeys({ taskProjects: tasks, state }));
  const leadPanes = new Set(Object.values(state?.coordinators ?? {}).map((c) => c.paneId));
  const names = (state?.agents ?? []).filter((a) => !leadPanes.has(a.id)).map((a) => a.agent_name || a.label || a.id);
  return cast = { tasks, state, leads, sessions: castSessions(leads, names) };
}

function useCast() {
  const tasks = useSelector(app.store, (d) => d.taskProjects);
  const state = useSelector(app.store, (d) => d.state);
  return castOf(tasks, state);
}

/** An agent's face, in Childish mode only. `lead` is a project key (or "cto") for that project's lead; any other
 *  session gets a face from its `name`. `of` says whose face it is when the name is not one to read out (a seat). */
export function Persona({ lead, name, of, size = 28 }: { lead?: string | null; name?: string; of?: string; size?: number }) {
  return useFun() ? <PersonaFace lead={lead} name={name} of={of} size={size} /> : null;
}

function PersonaFace({ lead, name, of, size }: { lead?: string | null; name?: string; of?: string; size: number }) {
  const { leads, sessions } = useCast();
  const who = lead ? leads.get(lead) ?? castFor(`lead:${lead}`) : name ? sessions.get(name.toLowerCase()) ?? castFor(name) : undefined;
  return who ? <Face who={who} size={size} title={`${who.name}, the face of ${of ?? (lead ? (lead === "cto" ? "the CTO" : `the ${lead} lead`) : name)}`} /> : null;
}
