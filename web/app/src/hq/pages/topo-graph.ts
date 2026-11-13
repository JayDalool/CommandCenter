// Company's graph layout: buildTopology's view → positioned nodes and typed edges, following the prototype's
// data/graph.ts. Pure, so it is tested without a browser. Edge kinds stay distinct so the picture never implies a
// dependency the data does not have:
//   manage  Jay → project          (who directs what; dashed when the project has no open work)
//   flow    project → stage        (that project has open tasks in that stage now; red dashed when one is blocked)
//   task    stage → task           (an expanded stage's tasks)
//   host    stage → the ccd host   (every agent session runs there; worker nodes run none yet, so they get no edge)
import type { TopologyView } from "../data";

export type NodeKind = "root" | "project" | "stage" | "task" | "more" | "host";
export interface GNode { id: string; kind: NodeKind; x: number; y: number; w: number; h: number; ref: string; pj?: string }
export interface GEdge { id: string; from: string; to: string; kind: "manage" | "flow" | "task" | "host"; pj?: string;
  blocked?: boolean; idle?: boolean }
export interface Layers { manage: boolean; flow: boolean; host: boolean }
export interface Graph { nodes: GNode[]; edges: GEdge[]; bounds: { w: number; h: number } }

export const ALL_LAYERS: Layers = { manage: true, flow: true, host: true };
/** An expanded stage draws at most this many task nodes, then one "N more" node; the inspector lists them all. */
export const TASK_NODES = 8;

export const hostId = (h: { kind: string; id: string }) => `h:${h.kind}:${h.id}`;

/** Lay a row of `n` boxes of width `w` and gap `g`, centred on `cx`. */
const row = (n: number, w: number, g: number, cx: number) => {
  const total = n * w + Math.max(0, n - 1) * g;
  return (i: number) => cx - total / 2 + i * (w + g);
};

export function layoutTopology(v: TopologyView, expanded: readonly string[], layers: Layers = ALL_LAYERS): Graph {
  const PW = 224, PG = 22, SW = 200, SG = 24, HW = 300, HG = 24, M = 24;
  const W = Math.max(960, v.projects.length * (PW + PG) + 2 * M, v.stages.length * (SW + SG) + 2 * M, v.hosts.length * (HW + HG) + 2 * M);
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];

  nodes.push({ id: "root", kind: "root", x: W / 2 - 140, y: 0, w: 280, h: 92, ref: "jay" });

  const px = row(v.projects.length, PW, PG, W / 2);
  v.projects.forEach((p, i) => {
    nodes.push({ id: `p:${p.key}`, kind: "project", x: px(i), y: 146, w: PW, h: 122, ref: p.key, pj: p.key });
    if (layers.manage) edges.push({ id: `e:root:${p.key}`, from: "root", to: `p:${p.key}`, kind: "manage", pj: p.key, idle: p.edge === "idle" });
  });

  const SY = 340, SH = 96;
  let deepest = SY + SH;
  const sx = row(v.stages.length, SW, SG, W / 2);
  v.stages.forEach((s, i) => {
    const x = sx(i);
    nodes.push({ id: `s:${s.id}`, kind: "stage", x, y: SY, w: SW, h: SH, ref: s.id });
    if (layers.flow) for (const f of s.flows) {
      edges.push({ id: `e:${f.project}:${s.id}`, from: `p:${f.project}`, to: `s:${s.id}`, kind: "flow", pj: f.project, blocked: f.blocked });
    }
    if (!expanded.includes(s.id)) return;
    const shown = s.tasks.slice(0, TASK_NODES);
    shown.forEach((t, j) => {
      const y = SY + SH + 30 + j * 50;
      nodes.push({ id: `t:${t.key}`, kind: "task", x: x + 6, y, w: SW - 12, h: 40, ref: t.key, pj: t.project });
      edges.push({ id: `e:${s.id}:${t.key}`, from: `s:${s.id}`, to: `t:${t.key}`, kind: "task", pj: t.project, blocked: t.blocked });
      deepest = Math.max(deepest, y + 40);
    });
    if (s.tasks.length > shown.length) {
      const y = SY + SH + 30 + shown.length * 50;
      nodes.push({ id: `m:${s.id}`, kind: "more", x: x + 6, y, w: SW - 12, h: 34, ref: s.id });
      deepest = Math.max(deepest, y + 34);
    }
  });

  const HY = Math.max(SY + SH + 70, deepest + 56), HH = 112;
  const hx = row(v.hosts.length, HW, HG, W / 2);
  v.hosts.forEach((h, i) => nodes.push({ id: hostId(h), kind: "host", x: hx(i), y: HY, w: HW, h: HH, ref: hostId(h) }));
  const ccd = v.hosts.find((h) => h.kind === "ccd");
  if (layers.host && ccd) for (const s of v.stages) edges.push({ id: `e:${s.id}:host`, from: `s:${s.id}`, to: hostId(ccd), kind: "host" });

  return { nodes, edges, bounds: { w: W, h: HY + HH + 8 } };
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

/** The nodes and edges touching `id`, for hover emphasis. */
export function neighbours(id: string, edges: GEdge[]): Set<string> {
  const s = new Set([id]);
  for (const e of edges) { if (e.from === id) s.add(e.to); if (e.to === id) s.add(e.from); }
  return s;
}
