// Professional or Childish (Settings › Appearance › Style, this browser only). Childish gives agents a character and
// adds emoji after some labels; Professional shows neither. Both are decoration: no status, count or control depends
// on the mode, and everything a face or emoji hints at is also in words.
import { useMemo } from "react";
import "./persona.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { usePrefs } from "../../lib/prefs";
import { castFor, castLeads, leadKeys } from "./assign";
import { Face } from "./characters";
import type { Presence } from "../data";

export const useFun = () => usePrefs((p) => p.style === "childish");

/** An emoji after a label, in Childish mode only. Hidden from screen readers: the label already says it. */
export function Fun({ e }: { e: string }) {
  return useFun() ? <span className="hq-fun" aria-hidden>{" "}{e}</span> : null;
}

export const PRESENCE_EMOJI: Record<Presence, string> = { working: "🔨", waiting: "🙋", idle: "💤", offline: "🌙", unknown: "❔" };

function useLeadCast() {
  const tasks = useSelector(app.store, (d) => d.taskProjects);
  const state = useSelector(app.store, (d) => d.state);
  return useMemo(() => castLeads(leadKeys({ taskProjects: tasks, state })), [tasks, state]);
}

/** An agent's face, in Childish mode only. `lead` is a project key (or "cto") for that project's lead; any other
 *  session gets a face from its `name`. */
export function Persona({ lead, name, size = 28 }: { lead?: string | null; name?: string; size?: number }) {
  return useFun() ? <PersonaFace lead={lead} name={name} size={size} /> : null;
}

function PersonaFace({ lead, name, size }: { lead?: string | null; name?: string; size: number }) {
  const leads = useLeadCast();
  const who = lead ? leads.get(lead) ?? castFor(`lead:${lead}`) : name ? castFor(name) : undefined;
  return who ? <Face who={who} size={size} title={`${who.name}, the face of ${lead ? (lead === "cto" ? "the CTO" : `the ${lead} lead`) : name}`} /> : null;
}
