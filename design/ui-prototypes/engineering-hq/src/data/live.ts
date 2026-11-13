// Shared, synchronised DEMO state: per-view UI state (selected tabs, filters, drafts), mock chat and
// a simulated agent-status feed. Every window of the prototype sees the same values, so a view that
// moves to another window keeps its tab, filters and unsent draft, and a status change shows in both.
import { useCallback } from "react";
import { SharedStore, WIN_ID, isRecord } from "../lib/shared";
import { useStore } from "../lib/store";
import { INITIAL_AGENT_STATE, SEED_CHAT, type AgentState, type ChatMessage } from "./seed";

// ---- per-view UI state ----
type VS = Record<string, Record<string, unknown>>;
export const viewState = new SharedStore<VS>("viewstate", {}, (v): v is VS => isRecord(v) && Object.values(v).every(isRecord));

export function useViewState<T>(view: string, key: string, init: T): [T, (v: T) => void] {
  const all = useStore(viewState);
  const v = (all[view]?.[key] as T | undefined) ?? init;
  const set = useCallback((next: T) => viewState.set((s) => ({ ...s, [view]: { ...(s[view] ?? {}), [key]: next } })), [view, key]);
  return [v, set];
}

// ---- mock chat (idempotent by client message id) ----
type Chat = Record<string, ChatMessage[]>;
const isChat = (v: unknown): v is Chat => isRecord(v) && Object.values(v).every((l) => Array.isArray(l) && l.every((m) => isRecord(m) && typeof m.cid === "string" && typeof m.text === "string"));
export const chat = new SharedStore<Chat>("chat", SEED_CHAT, isChat);

/** Append once. A replayed or re-sent message with the same cid is ignored, so no duplicates. */
export function appendMessage(conv: string, m: ChatMessage) {
  chat.set((c) => ((c[conv] ?? []).some((x) => x.cid === m.cid) ? c : { ...c, [conv]: [...(c[conv] ?? []), m] }));
}

export function newCid() { try { return crypto.randomUUID(); } catch { return `${WIN_ID}-${Date.now()}-${Math.random()}`; } }

const timeNow = () => new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

const REPLIES: Record<string, string> = {
  default: "Got it. I've noted this on the task. Nothing changes in production without your approval.",
  status: "SV-025: planning done, implementation ~70%, review queued behind it. Production untouched.",
  task: "I'll draft it as a task with Problem / Why, requirements and acceptance criteria, then bring it to you before anyone starts.",
};

/** DEMO: send as Jay, then the agent answers. A real build would post through an approved API. */
export function sendDemo(conv: string, text: string, agentId: string | undefined, cid = newCid()) {
  appendMessage(conv, { cid, from: "jay", at: timeNow(), text });
  if (!agentId) return;
  const key = /status|update/i.test(text) ? "status" : /task|create|build/i.test(text) ? "task" : "default";
  setTimeout(() => appendMessage(conv, { cid: `${cid}:r`, from: agentId, at: timeNow(), text: REPLIES[key] }), 900);
}

// ---- simulated live feed ----
/**
 * source says where agent presence comes from. The prototype only ever has "demo". A live build would
 * set "live" from ccd session events; the UI marks every "demo" status so it never reads as real activity.
 */
export interface Feed { agents: Record<string, AgentState>; beat: number; outage: boolean; source: "demo" | "live" }
const isFeed = (v: unknown): v is Feed => isRecord(v) && isRecord(v.agents) && typeof v.beat === "number" && typeof v.outage === "boolean"
  && (v.source === "demo" || v.source === "live") && Object.values(v.agents).every((s) => isRecord(s) && typeof s.status === "string" && typeof s.at === "number");
export const feed = new SharedStore<Feed>("feed2", { agents: INITIAL_AGENT_STATE, beat: Date.now(), outage: false, source: "demo" }, isFeed);
export const FEED_STALE_MS: number = (() => {
  try { const v = Number(new URLSearchParams(location.search).get("stalems")); return v > 0 ? v : 15000; } catch { return 15000; }
})();

type Step = { id: string } & Partial<AgentState> & Pick<AgentState, "status" | "detail">;
const CYCLE: Step[] = [
  { id: "nova", status: "working", detail: "implementing · tests 44/48", task: "SV-025", project: "samvision" },
  { id: "atlas", status: "reviewing", detail: "PR #839 · 2 comments left", task: "SV-029", project: "samvision" },
  { id: "nova", status: "working", detail: "implementing · tests 48/48", task: "SV-025", project: "samvision" },
  { id: "iris", status: "researching", detail: "comparable-sales weights", task: "SV-031", project: "samvision" },
  { id: "atlas", status: "idle", detail: "review posted on PR #839", task: "SV-029", project: "samvision" },
  { id: "iris", status: "offline", detail: "session ended · plan saved", task: "SV-031", project: "samvision", session: undefined },
  { id: "iris", status: "idle", detail: "planning complete", task: "SV-031", project: "samvision", session: "plan-sv-92f4", model: "claude-opus-5-5" },
  { id: "atlas", status: "reviewing", detail: "PR #839 at head 7f3a9c1", task: "SV-029", project: "samvision" },
];
let step = 0;
/** One tick of the DEMO feed (one window runs it; see App). */
export function tickFeed(now = Date.now()) {
  const f = feed.get();
  if (f.outage) return;
  const { id, ...c } = CYCLE[step++ % CYCLE.length];
  feed.set({ ...f, beat: now, agents: { ...f.agents, [id]: { ...f.agents[id], ...c, at: now } } });
}
export function setOutage(on: boolean) { feed.set((f) => ({ ...f, outage: on, beat: on ? f.beat : Date.now() })); }
