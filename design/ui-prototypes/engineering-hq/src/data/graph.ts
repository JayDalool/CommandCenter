// The Operations Topology model. Pure: (filters, expanded groups) → positioned nodes and typed edges.
// Edge kinds are kept distinct on purpose so the picture never implies a dependency that is not there:
//   manage     Jay → project          (who directs what)
//   flow       project → stage        (that project has tasks in that pipeline stage right now)
//   task       stage → task           (an expanded stage's tasks)
//   host       stage → host           (where those sessions run: WorkerNode placement)
//   blocked    any edge carrying a blocked / paused item, drawn red / grey dashed
import { HOSTS, PROJECTS, TASKS, type ProjectKey, type Stage, type Task } from "./seed";

export type NodeKind = "jay" | "project" | "stage" | "task" | "host";
export interface GNode { id: string; kind: NodeKind; x: number; y: number; w: number; h: number; color: string; label: string; ref?: string }
export interface GEdge { id: string; from: string; to: string; kind: "manage" | "flow" | "task" | "host"; color: string; blocked?: boolean; paused?: boolean; tag?: string }

export const STAGE_GROUPS: { id: string; label: string; icon: string; stages: Stage[] }[] = [
  { id: "plan", label: "Planning", icon: "search", stages: ["Planning"] },
  { id: "build", label: "Build & Test", icon: "code", stages: ["Implementing"] },
  { id: "review", label: "Review", icon: "check", stages: ["Reviewing"] },
  { id: "qa", label: "UI Testing", icon: "mobile", stages: ["UI Testing"] },
  { id: "release", label: "Release & Verify", icon: "rocket", stages: ["Verifying", "Ready to Merge", "Deploying"] },
];
export const groupOf = (t: Task) => STAGE_GROUPS.find((g) => g.stages.includes(t.stage))?.id ?? (t.stage === "Blocked" ? "build" : null);

export interface Filters { projects: ProjectKey[]; status: "all" | "attention" | "blocked" }
export interface Layers { manage: boolean; flow: boolean; host: boolean; blocked: boolean }
export const ALL_LAYERS: Layers = { manage: true, flow: true, host: true, blocked: true };

const W = 1400;
export function buildGraph(f: Filters, expanded: string[], layers: Layers = ALL_LAYERS) {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const shown = PROJECTS.filter((p) => f.projects.length === 0 || f.projects.includes(p.key));
  const tasks = TASKS.filter((t) => shown.some((p) => p.key === t.project)).filter((t) =>
    f.status === "all" ? true : f.status === "blocked" ? t.stage === "Blocked" || t.stage === "Paused" : t.stage === "Blocked" || t.questions.length > 0);

  nodes.push({ id: "jay", kind: "jay", x: W / 2 - 125, y: 0, w: 250, h: 104, color: "#5b7cff", label: "Jay" });

  const pw = 236, pg = 34, pTotal = shown.length * pw + (shown.length - 1) * pg, px0 = W / 2 - pTotal / 2;
  shown.forEach((p, i) => {
    nodes.push({ id: `p:${p.key}`, kind: "project", x: px0 + i * (pw + pg), y: 200, w: pw, h: 126, color: p.color, label: p.name, ref: p.key });
    if (layers.manage) edges.push({ id: `e:jay:${p.key}`, from: "jay", to: `p:${p.key}`, kind: "manage", color: p.color, paused: p.health === "paused",
      tag: p.health === "paused" ? "Paused" : p.key === "samvision" ? "Release ready" : undefined });
  });

  const groups = STAGE_GROUPS.filter((g) => tasks.some((t) => groupOf(t) === g.id));
  const sw = 214, sg = 40, sTotal = groups.length * sw + Math.max(0, groups.length - 1) * sg, sx0 = W / 2 - sTotal / 2;
  const sy = 420;
  let deepest = sy + 100;
  groups.forEach((g, i) => {
    const gx = sx0 + i * (sw + sg);
    nodes.push({ id: `s:${g.id}`, kind: "stage", x: gx, y: sy, w: sw, h: 104, color: "#7c8cff", label: g.label, ref: g.id });
    const gt = tasks.filter((t) => groupOf(t) === g.id);
    const projs = [...new Set(gt.map((t) => t.project))];
    if (layers.flow) projs.forEach((pk) => {
      const blocked = gt.some((t) => t.project === pk && t.stage === "Blocked");
      if (blocked && !layers.blocked) return;
      edges.push({ id: `e:${pk}:${g.id}`, from: `p:${pk}`, to: `s:${g.id}`, kind: "flow", color: PROJECTS.find((p) => p.key === pk)!.color, blocked, tag: blocked ? "Blocked" : undefined });
    });
    if (expanded.includes(g.id)) {
      gt.forEach((t, j) => {
        const ty = sy + 136 + j * 52;
        nodes.push({ id: `t:${t.key}`, kind: "task", x: gx + 8, y: ty, w: sw - 16, h: 42, color: PROJECTS.find((p) => p.key === t.project)!.color, label: t.key, ref: t.key });
        edges.push({ id: `e:${g.id}:${t.key}`, from: `s:${g.id}`, to: `t:${t.key}`, kind: "task", color: PROJECTS.find((p) => p.key === t.project)!.color, blocked: t.stage === "Blocked" });
        deepest = Math.max(deepest, ty + 42);
      });
    }
  });

  const hy = Math.max(620, deepest + 60);
  HOSTS.forEach((h, i) => {
    nodes.push({ id: `h:${h.id}`, kind: "host", x: W / 2 - 470 + i * 500, y: hy, w: 440, h: 116, color: h.status === "online" ? "#4f8bff" : "#5d6a85", label: h.name, ref: h.id });
  });
  // Every agent session runs on the server today (policy: allowed_nodes = ["server"]); the laptop gets no placement edge.
  if (layers.host) groups.forEach((g) => edges.push({ id: `e:${g.id}:server`, from: `s:${g.id}`, to: "h:server", kind: "host", color: "#6c86c9" }));
  return { nodes, edges, bounds: { x: 0, y: 0, w: W, h: hy + 120 } };
}

/** Spread the attach points of a node's edges along its edge so curves fan out instead of stacking. */
export function ports(nodes: GNode[], edges: GEdge[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const off = new Map<string, { a: number; b: number }>();
  const spread = (list: GEdge[], node: GNode, key: "a" | "b", other: (e: GEdge) => GNode | undefined) => {
    const sorted = [...list].sort((x, y) => (other(x)?.x ?? 0) - (other(y)?.x ?? 0));
    const span = Math.min(node.w * 0.7, 26 * (sorted.length - 1));
    sorted.forEach((e, i) => {
      const o = off.get(e.id) ?? { a: 0, b: 0 };
      o[key] = sorted.length > 1 ? -span / 2 + (span * i) / (sorted.length - 1) : 0;
      off.set(e.id, o);
    });
  };
  for (const n of nodes) {
    spread(edges.filter((e) => e.from === n.id), n, "a", (e) => byId.get(e.to));
    spread(edges.filter((e) => e.to === n.id), n, "b", (e) => byId.get(e.from));
  }
  return off;
}

export function curve(a: GNode, b: GNode, ao = 0, bo = 0): string {
  const p = { x: a.x + a.w / 2 + ao, y: a.y + a.h }, q = { x: b.x + b.w / 2 + bo, y: b.y };
  const my = (p.y + q.y) / 2;
  return `M${p.x},${p.y} C${p.x},${my} ${q.x},${my} ${q.x},${q.y}`;
}
