// Everything waiting for Jay, from one place: the Needs My Attention queue, the sidebar badge,
// the bell, My Office and the Topology summary all count the same list.
import { DECISION, agent } from "./seed";
import { TIER_LABEL, TIER_TONE, gov, tierOf, type Req } from "./governance";
import { useViewState } from "./live";
import { useStore } from "../lib/store";
import { go } from "../lib/router";

export type Kind = "Decision" | "Question" | "Review" | "Approval";
export interface Need { id: string; kind: Kind; icon: string; tone: string; k?: string; project?: string; title: string; sub: string; pill: [string, string]; age: string; open: () => void; done?: string }
export const inPopout = () => location.hash.startsWith("#/pop/");
const ageOf = (at: number) => { const m = Math.max(0, Math.round((Date.now() - at) / 60_000)); return m < 60 ? `${Math.max(1, m)} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const reqWho = (id: string) => (id === "jay" ? "Jay" : agent(id)?.name ?? id);

/** Everything waiting for Jay, in one list. Each item opens where it is answered; nothing is answered from the list. */
export function needs(requests: Req[], answered: Record<string, unknown>, decided: { option: string } | null, openDecision: (id: string) => void): Need[] {
  const work: Need[] = [
    { id: "d-sv-025", kind: "Decision", icon: "edit", tone: "info", k: "SV-025", project: "samvision", title: DECISION.title, sub: "Proposed by Claude · Option A recommended", pill: decided ? [`Decided: ${decided.option}`, "ok"] : ["High", "bad"], age: "2 h ago", open: () => openDecision("sv-025"), done: decided ? "Decided" : undefined },
    { id: "q-mfe-014", kind: "Question", icon: "lock", tone: "warn", k: "MFE-014", project: "mfe", title: "Pick a release window for MyFamilyExpenses", sub: "Blocks mobile settings · asked by Pixel", pill: ["Blocker", "bad"], age: "3 h ago", open: () => go("task", "MFE-014") },
    { id: "r-gyst-019", kind: "Review", icon: "code", tone: "violet", k: "GYST-019", project: "gyst", title: "Personal-data trigger: memory retention", sub: "Personal-data changes always come to you", pill: ["Needs input", "warn"], age: "6 h ago", open: () => go("task", "GYST-019") },
    { id: "q-cc-061", kind: "Question", icon: "help", tone: "info", k: "CC-061", project: "commandcenter", title: "Keep the repo's project colours or the concept's?", sub: "Engineering HQ prototype · asked by Nova", pill: ["Design", "violet"], age: "1 d ago", open: () => go("task", "CC-061") },
    { id: "r-cc-058", kind: "Review", icon: "shield", tone: "ok", k: "CC-058", project: "commandcenter", title: "Autonomy v3 shadow report", sub: "Read-only comparison ready", pill: ["Review", "violet"], age: "1 d ago", open: () => go("task", "CC-058") },
  ];
  const appr: Need[] = requests.map((r) => { const tier = tierOf(r); const d = answered[r.id] as { decision?: string } | undefined; const expired = r.expires <= Date.now();
    return { id: r.id, kind: "Approval", icon: "shield", tone: TIER_TONE[tier] === "bad" ? "warn" : TIER_TONE[tier] === "ok" ? "ok" : "info", project: r.project, title: r.title,
      sub: `${TIER_LABEL[tier]} · asked by ${reqWho(r.requestedBy)}`, pill: d?.decision ? [d.decision === "approved" ? "Approved" : "Declined", "ok"] : expired ? ["Expired", "idle"] : [TIER_LABEL[tier], TIER_TONE[tier]],
      age: ageOf(r.at), open: () => go("approvals", r.id), done: d?.decision ?? (expired ? "expired" : undefined) }; });
  return [...work, ...appr];
}


/** Counts for badges and summaries, from the same list as the queue. */
export function useNeedsSummary() {
  const g = useStore(gov);
  const [recorded] = useViewState<null | { option: string; at: string }>("page:decisions", "recorded", null);
  const waiting = needs(g.requests, g.decisions, recorded, () => {}).filter((n) => !n.done);
  return { total: waiting.length, urgent: waiting.filter((n) => n.pill[1] === "bad").length,
    approvals: waiting.filter((n) => n.kind === "Approval").length, blockers: waiting.filter((n) => n.pill[0] === "Blocker").length, top: waiting.slice(0, 3) };
}
