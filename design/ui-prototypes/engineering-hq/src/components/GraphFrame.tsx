// A fixed-layout neon graph scaled to fit its box. Used for the Office topology preview and the Teams
// hierarchy. (The full Operations Topology has its own pan/zoom canvas.)
import { useEffect, useRef, useState, type ReactNode } from "react";
import { curve, type GNode } from "../data/graph";
import { cx } from "./ui";

export interface FNode { id: string; x: number; y: number; w: number; h: number; color: string; body: ReactNode; className?: string; onClick?: () => void; label: string }
export interface FEdge { from: string; to: string; color: string; ao?: number; bo?: number; dashed?: boolean; bus?: number }

/** An org-chart connector: down from a, across at y = bus, down into b, with rounded corners. */
function busPath(a: GNode, b: GNode, ao: number, bo: number, bus: number) {
  const px = a.x + a.w / 2 + ao, py = a.y + a.h, qx = b.x + b.w / 2 + bo, qy = b.y;
  if (Math.abs(px - qx) < 1) return `M${px},${py} V${qy}`;
  const r = Math.min(14, Math.abs(qx - px) / 2), dir = qx > px ? 1 : -1;
  return `M${px},${py} V${bus - r} Q${px},${bus} ${px + dir * r},${bus} H${qx - dir * r} Q${qx},${bus} ${qx},${bus + r} V${qy}`;
}

export function GraphFrame({ w, h, nodes, edges, className }: { w: number; h: number; nodes: FNode[]; edges: FEdge[]; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [k, setK] = useState(1);
  useEffect(() => {
    const el = box.current; if (!el) return;
    const fit = () => { const r = el.getBoundingClientRect(); if (r.width) setK(Math.min(r.width / w, r.height ? r.height / h : 9)); };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(fit); ro.observe(el); return () => ro.disconnect();
  }, [w, h]);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return <div className={cx("gframe", className)} ref={box}>
    <div className="gframe-world" style={{ width: w, height: h, transform: `scale(${k})` }}>
      <svg className="edges" width={w} height={h} aria-hidden>
        <defs><filter id="glow2" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3" /></filter></defs>
        {edges.map((e, i) => {
          const a = byId.get(e.from) as unknown as GNode, b = byId.get(e.to) as unknown as GNode; if (!a || !b) return null;
          const d = e.bus != null ? busPath(a, b, e.ao ?? 0, e.bo ?? 0, e.bus) : curve(a, b, e.ao ?? 0, e.bo ?? 0);
          return <g key={i} className={cx("edge", e.dashed && "is-paused")}>
            {!e.dashed && <path d={d} stroke={e.color} className="edge-glow" filter="url(#glow2)" />}
            <path d={d} stroke={e.color} className="edge-line" />
            <circle cx={a.x + a.w / 2 + (e.ao ?? 0)} cy={a.y + a.h} r="3.6" fill={e.color} /><circle cx={b.x + b.w / 2 + (e.bo ?? 0)} cy={b.y} r="3.6" fill={e.color} />
          </g>;
        })}
      </svg>
      {nodes.map((n) => {
        const st = { left: n.x, top: n.y, width: n.w, height: n.h, ["--c" as string]: n.color };
        return n.onClick ? <button key={n.id} type="button" className={cx("gnode", n.className)} style={st} onClick={n.onClick} aria-label={n.label}>{n.body}</button>
          : <div key={n.id} className={cx("gnode", n.className)} style={st} aria-label={n.label}>{n.body}</div>;
      })}
    </div>
  </div>;
}
