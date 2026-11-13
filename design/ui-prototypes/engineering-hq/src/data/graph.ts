// The Operations Topology model. Pure: (filters, expanded groups) → positioned nodes and typed edges.
// Edge kinds are kept distinct on purpose so the picture never implies a dependency that is not there:
//   manage     CommandCenter (Jay) → project   (who directs what)
//   flow       project → stage        (that project has tasks in that pipeline stage right now)
//   task       stage → task           (an expanded stage's tasks)
//   host       stage → host           (where those sessions run: WorkerNode placement)
//   blocked    any edge carrying a blocked / paused item, drawn red / grey dashed
import { HOSTS, PROJECTS, TASKS, type ProjectKey, type Stage, type Task } from "./seed";

export type NodeKind = "root" | "project" | "stage" | "task" | "host";
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

/** The control plane sits at the root (as in the approved reference); Jay directs it. */
export const ROOT: ProjectKey = "commandcenter";
export function buildGraph(f: Filters, expanded: string[], layers: Layers = ALL_LAYERS) {
  const nodes: GNode[] = [];
  const nShown = PROJECTS.filter((p) => p.key !== ROOT && (f.projects.length === 0 || f.projects.includes(p.key))).length;
  const W = Math.max(1320, nShown * 296 + 40);   // widens as projects are added; the canvas fits it
  const edges: GEdge[] = [];
  const shownAll = PROJECTS.filter((p) => f.projects.length === 0 || f.projects.includes(p.key));
  const shown = shownAll.filter((p) => p.key !== ROOT);
  const tasks = TASKS.filter((t) => shownAll.some((p) => p.key === t.project)).filter((t) =>
    f.status === "all" ? true : f.status === "blocked" ? t.stage === "Blocked" || t.stage === "Paused" : t.stage === "Blocked" || t.questions.length > 0);
  const colorOf = (k: ProjectKey) => PROJECTS.find((p) => p.key === k)?.color ?? "#5d6a85";
  const nodeOf = (k: ProjectKey) => (k === ROOT ? "root" : `p:${k}`);

  nodes.push({ id: "root", kind: "root", x: W / 2 - 160, y: 0, w: 330, h: 140, color: colorOf(ROOT), label: "CommandCenter", ref: ROOT });

  const pw = 262, pg = 34, pTotal = shown.length * pw + Math.max(0, shown.length - 1) * pg, px0 = W / 2 - pTotal / 2;
  shown.forEach((p, i) => {
    nodes.push({ id: `p:${p.key}`, kind: "project", x: px0 + i * (pw + pg), y: 190, w: pw, h: 128, color: p.color, label: p.name, ref: p.key });
    if (layers.manage) edges.push({ id: `e:root:${p.key}`, from: "root", to: `p:${p.key}`, kind: "manage", color: p.color, paused: p.health === "paused" || p.health === "onboarding",
      tag: p.health === "paused" ? "Paused" : p.health === "onboarding" ? "Onboarding" : p.key === "samvision" ? "Release ready" : undefined });
  });

  const groups = STAGE_GROUPS.filter((g) => tasks.some((t) => groupOf(t) === g.id));
  const sw = 218, sg = 34, sTotal = groups.length * sw + Math.max(0, groups.length - 1) * sg, sx0 = W / 2 - sTotal / 2;
  const sy = 388;
  let deepest = sy + 100;
  groups.forEach((g, i) => {
    const gx = sx0 + i * (sw + sg);
    nodes.push({ id: `s:${g.id}`, kind: "stage", x: gx, y: sy, w: sw, h: 100, color: "#7c8cff", label: g.label, ref: g.id });
    const gt = tasks.filter((t) => groupOf(t) === g.id);
    const projs = [...new Set(gt.map((t) => t.project))];
    if (layers.flow) projs.forEach((pk) => {
      const blocked = gt.some((t) => t.project === pk && t.stage === "Blocked");
      if (blocked && !layers.blocked) return;
      edges.push({ id: `e:${pk}:${g.id}`, from: nodeOf(pk), to: `s:${g.id}`, kind: "flow", color: colorOf(pk), blocked, tag: blocked ? "Blocked" : undefined });
    });
    if (expanded.includes(g.id)) {
      gt.forEach((t, j) => {
        const ty = sy + 128 + j * 50;
        nodes.push({ id: `t:${t.key}`, kind: "task", x: gx + 6, y: ty, w: sw - 12, h: 40, color: colorOf(t.project), label: t.key, ref: t.key });
        edges.push({ id: `e:${g.id}:${t.key}`, from: `s:${g.id}`, to: `t:${t.key}`, kind: "task", color: colorOf(t.project), blocked: t.stage === "Blocked" });
        deepest = Math.max(deepest, ty + 40);
      });
    }
  });

  const hy = Math.max(562, deepest + 56);
  HOSTS.forEach((h, i) => {
    nodes.push({ id: `h:${h.id}`, kind: "host", x: W / 2 - 470 + i * 500, y: hy, w: 440, h: 112, color: h.status === "online" ? "#6c86c9" : "#5d6a85", label: h.name, ref: h.id });
  });
  // Every agent session runs on the server today (policy: allowed_nodes = ["server"]); the laptop gets no placement edge.
  if (layers.host) groups.forEach((g) => edges.push({ id: `e:${g.id}:server`, from: `s:${g.id}`, to: "h:server", kind: "host", color: "#6c86c9" }));
  return { nodes, edges, bounds: { x: 0, y: 0, w: W, h: hy + 116 } };
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
