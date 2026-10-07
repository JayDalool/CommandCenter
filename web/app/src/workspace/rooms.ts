// The Workspace wall's layout: which rooms each Workspace window shows, which terminals each room
// shows, and what has been popped out to another window. Shared by every Command Center window of
// this browser (localStorage + the `storage` event), so a room popped out on monitor 2 frees its slot
// on monitor 1 at once.
//
// This is LAYOUT only. The work itself — Claude, Codex, shells — lives in named ccd PTY sessions and
// herdr panes, keyed by the room's task or project (sessionName). Moving, popping out, closing or
// reattaching a room or a pane never starts another process: every window attaches to the SAME
// session by name. Ending a session is a separate, explicit action (End Session).
import { Store } from "../lib/store";

export type Tool = "claude" | "codex" | "project" | "server";
export const TOOLS: Tool[] = ["claude", "codex", "project", "server"];
export const TOOL_LABEL: Record<Tool, string> = { claude: "Claude", codex: "Codex", project: "Project", server: "Server" };
export const MAX_ROOMS = 4;
export const MAX_PANES = 4;

export interface Room {
  id: string;                    // t:<KEY> or p:<project> — one room per task / project, ever
  kind: "task" | "project";
  project: string;
  key: string | null;            // the ticket key of a Task Room; null for a Project Console
  slots: (Tool | null)[];        // pane positions (1–4); null = a freed slot showing "+ Add Pane"
  out: Partial<Record<Tool, "popped" | "detached">>;   // panes living in their own window, or closed there
  where: "wall" | "popped" | "detached";
}

export interface Layout {
  v: 1;
  rooms: Record<string, Room>;
  walls: Record<string, string[]>;            // Workspace window id → room ids, in slot order
  split: Record<string, { x: number; y: number }>;
}

const KEY = "cc.rooms";
const EMPTY: Layout = { v: 1, rooms: {}, walls: { "1": [] }, split: {} };

export function parseLayout(raw: string | null): Layout {
  try {
    const o = JSON.parse(raw ?? "") as Layout;
    if (o?.v !== 1 || typeof o.rooms !== "object" || typeof o.walls !== "object") return structuredClone(EMPTY);
    // Drop dangling ids; a room is on at most one wall.
    const seen = new Set<string>();
    for (const w of Object.keys(o.walls)) {
      o.walls[w] = (o.walls[w] ?? []).filter((id) => o.rooms[id] && !seen.has(id) && seen.add(id)).slice(0, MAX_ROOMS);
    }
    for (const r of Object.values(o.rooms)) if (r.where === "wall" && !seen.has(r.id)) r.where = "detached";
    o.split ??= {};
    return o;
  } catch { return structuredClone(EMPTY); }
}

function load(): Layout {
  try { return parseLayout(localStorage.getItem(KEY)); } catch { return structuredClone(EMPTY); }
}

export const layout = new Store<Layout>(load());
let writing = false;
layout.subscribe(() => {
  if (writing) return;
  try { localStorage.setItem(KEY, JSON.stringify(layout.get())); } catch { /* this window only */ }
});
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY) return;
    writing = true;
    try { layout.set(parseLayout(e.newValue)); } finally { writing = false; }
  });
}

/** Tests and "reset layout". */
export function resetLayout(l: Layout = structuredClone(EMPTY)) { layout.set(l); }

export const roomId = (kind: Room["kind"], project: string, key: string | null) => (kind === "task" ? `t:${key}` : `p:${project}`);

/** The ccd session a pane attaches to. Same name in every window → the same shell, Claude or Codex. */
export function sessionName(room: Pick<Room, "kind" | "key">, tool: Tool, prefix: string): string {
  if (tool === "server") return "server";
  const id = room.kind === "task" ? room.key! : prefix;
  return `${tool === "project" ? "repo" : tool}:${id}`;
}

export const visibleTools = (r: Room) => r.slots.filter((s): s is Tool => !!s);

function patchRoom(id: string, fn: (r: Room) => Room) {
  layout.set((l) => (l.rooms[id] ? { ...l, rooms: { ...l.rooms, [id]: fn(l.rooms[id]) } } : l));
}

export function wallOf(l: Layout, id: string): string | null {
  return Object.keys(l.walls).find((w) => l.walls[w].includes(id)) ?? null;
}

export type OpenResult = { ok: true; room: Room; existed: boolean; wall: string | null } | { ok: false; full: true };

/** Open a task room or project console on `wall`. An already-open room is reused, never duplicated. */
export function openRoom(wall: string, spec: { kind: Room["kind"]; project: string; key: string | null; tools?: Tool[] }): OpenResult {
  const id = roomId(spec.kind, spec.project, spec.key);
  const l = layout.get();
  const have = l.rooms[id];
  if (have && have.where === "wall") return { ok: true, room: have, existed: true, wall: wallOf(l, id) };
  if (have && have.where === "popped") return { ok: true, room: have, existed: true, wall: null };
  const ids = l.walls[wall] ?? [];
  if (ids.length >= MAX_ROOMS) return { ok: false, full: true };
  const room: Room = have ? { ...have, where: "wall" }
    : { id, kind: spec.kind, project: spec.project, key: spec.key, slots: [...(spec.tools ?? ["claude"])], out: {}, where: "wall" };
  layout.set({ ...l, rooms: { ...l.rooms, [id]: room }, walls: { ...l.walls, [wall]: [...ids, id] } });
  return { ok: true, room, existed: !!have, wall };
}

/** Close the room in this window. Its sessions keep running; reopening attaches to them again. */
export function closeRoom(id: string) {
  layout.set((l) => {
    const walls = Object.fromEntries(Object.entries(l.walls).map(([w, ids]) => [w, ids.filter((x) => x !== id)]));
    const rooms = { ...l.rooms };
    delete rooms[id];
    return { ...l, walls, rooms };
  });
}

export function moveRoom(wall: string, from: number, to: number) {
  layout.set((l) => {
    const ids = [...(l.walls[wall] ?? [])];
    if (from < 0 || from >= ids.length || to < 0 || to >= ids.length) return l;
    const [x] = ids.splice(from, 1);
    ids.splice(to, 0, x);
    return { ...l, walls: { ...l.walls, [wall]: ids } };
  });
}

/** A fresh Workspace window id (the next number). */
export function newWall(): string {
  const l = layout.get();
  const n = Math.max(1, ...Object.keys(l.walls).map((w) => Number(w) || 1)) + 1;
  layout.set({ ...l, walls: { ...l.walls, [String(n)]: [] } });
  return String(n);
}

export function setSplit(wall: string, s: { x: number; y: number }) {
  layout.set((l) => ({ ...l, split: { ...l.split, [wall]: s } }));
}

// ---------- room pop-out ----------

export function popRoomState(id: string) {
  layout.set((l) => {
    if (!l.rooms[id]) return l;
    const walls = Object.fromEntries(Object.entries(l.walls).map(([w, ids]) => [w, ids.filter((x) => x !== id)]));
    return { ...l, walls, rooms: { ...l.rooms, [id]: { ...l.rooms[id], where: "popped" } } };
  });
}

/** Back onto `wall` (if it has room). */
export function returnRoom(id: string, wall: string): boolean {
  const l = layout.get();
  if (!l.rooms[id]) return false;
  const ids = l.walls[wall] ?? [];
  if (!ids.includes(id) && ids.length >= MAX_ROOMS) return false;
  layout.set({ ...l, rooms: { ...l.rooms, [id]: { ...l.rooms[id], where: "wall" } },
    walls: { ...l.walls, [wall]: ids.includes(id) ? ids : [...ids, id] } });
  return true;
}

/** Its pop-out window closed: the room is detached (listed to reopen); nothing stops. */
export function detachRoom(id: string) {
  patchRoom(id, (r) => (r.where === "popped" ? { ...r, where: "detached" } : r));
}

// ---------- panes ----------

/** Show or hide one tool. A popped-out tool comes back into the room (its window closes). */
export function toggleTool(id: string, tool: Tool) {
  patchRoom(id, (r) => {
    if (r.out[tool]) return reattach(r, tool);
    if (r.slots.includes(tool)) return { ...r, slots: r.slots.filter((s) => s !== tool) };
    return place(r, tool);
  });
}

function place(r: Room, tool: Tool): Room {
  const i = r.slots.indexOf(null);
  if (i >= 0) { const slots = [...r.slots]; slots[i] = tool; return { ...r, slots }; }
  if (r.slots.length >= MAX_PANES) return r;
  return { ...r, slots: [...r.slots, tool] };
}

function reattach(r: Room, tool: Tool): Room {
  const out = { ...r.out };
  delete out[tool];
  return place({ ...r, out }, tool);
}

export function addPane(id: string, slot: number, tool: Tool) {
  patchRoom(id, (r) => {
    if (r.slots.includes(tool)) return r;
    const out = { ...r.out };
    delete out[tool];
    const slots = [...r.slots];
    slots[slot] = tool;
    return { ...r, slots, out };
  });
}

/** The pane leaves for its own window: its slot is freed ("+ Add Pane"), the session keeps running. */
export function popPaneState(id: string, tool: Tool) {
  patchRoom(id, (r) => ({ ...r, slots: r.slots.map((s) => (s === tool ? null : s)), out: { ...r.out, [tool]: "popped" } }));
}

export function reattachPane(id: string, tool: Tool) { patchRoom(id, (r) => reattach(r, tool)); }

export function detachPane(id: string, tool: Tool) {
  patchRoom(id, (r) => (r.out[tool] === "popped" ? { ...r, out: { ...r.out, [tool]: "detached" } } : r));
}

/** Drop a freed slot (the room re-flows to fewer panes). */
export function dropSlot(id: string, slot: number) {
  patchRoom(id, (r) => ({ ...r, slots: r.slots.filter((_, i) => i !== slot) }));
}

// ---------- windows ----------

const FEATURES = "popup=yes,width=1100,height=720";

export function openWindow(hash: string, name: string, features = FEATURES): Window | null {
  return window.open(`${location.pathname}${location.search}${hash}`, name, features);
}

export function popOutRoom(id: string) {
  popRoomState(id);
  openWindow(`#/room/${encodeURIComponent(id)}`, `cc-room-${id}`);
}

export function popOutPane(id: string, tool: Tool) {
  popPaneState(id, tool);
  openWindow(`#/pane/${encodeURIComponent(id)}/${tool}`, `cc-pane-${id}-${tool}`, "popup=yes,width=900,height=600");
}

export function openWorkspaceWindow(wall: string) {
  openWindow(`#/workspace?w=${encodeURIComponent(wall)}`, `cc-workspace-${wall}`, "popup=no");
}

/** Grid shape for n rooms (spec §12): 1 full · 2 side by side · 3 and 4 a 2×2. */
export function wallShape(n: number): { cols: number; rows: number; cells: number } {
  if (n <= 1) return { cols: 1, rows: 1, cells: 1 };
  if (n === 2) return { cols: 2, rows: 1, cells: 2 };
  return { cols: 2, rows: 2, cells: 4 };
}

/** Pane areas for n panes (spec §14): 1 full · 2 side by side · 3 one on top, two below · 4 a 2×2. */
export function paneAreas(n: number): string[] {
  if (n <= 1) return ["a"];
  if (n === 2) return ["a", "b"];
  if (n === 3) return ["a", "b", "c"];
  return ["a", "b", "c", "d"];
}
