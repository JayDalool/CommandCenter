// The cast: 30 original characters, drawn here from a few parts (head, top, eyes, mouth, colour). They are faces for
// agents in Childish mode (Settings › Appearance › Style); Professional mode shows none. A character is decoration
// only: it never stands for a status. Colours are fixed art colours, not theme tokens, so a face looks the same on
// dark and light; each sits on its own tile.
import type { ReactNode } from "react";

type Hue = "coral" | "amber" | "moss" | "teal" | "sky" | "indigo" | "violet" | "rose" | "slate" | "sand";
type Head = "box" | "round" | "tall" | "wide" | "dome" | "hex" | "tv" | "blob";
type Top = "antenna" | "twin" | "ears" | "horns" | "sprout" | "cap" | "bolt" | "halo" | "tuft" | "none";
type Eyes = "dots" | "big" | "visor" | "glasses" | "wink" | "sleepy" | "pixel" | "cyclops" | "happy";
type Mouth = "smile" | "flat" | "o" | "grin" | "zig" | "smirk" | "tiny";

export interface Character { id: string; name: string; hue: Hue; head: Head; top: Top; eyes: Eyes; mouth: Mouth; cheeks?: boolean }

/** [tile, body, ink] */
const HUES: Record<Hue, [string, string, string]> = {
  coral: ["#e0683c", "#ffe8da", "#2a1710"], amber: ["#d9a227", "#fff3cf", "#2b2108"], moss: ["#5e9a57", "#e6f5dc", "#13240f"],
  teal: ["#2e9c97", "#dbf5f1", "#0b2422"], sky: ["#4a8fd6", "#e1eefc", "#0e2036"], indigo: ["#6b6fd9", "#e6e6fd", "#17173a"],
  violet: ["#9a67d1", "#f0e4fc", "#25123a"], rose: ["#d4638f", "#fde3ec", "#37101f"], slate: ["#5f6b7a", "#e6eaef", "#151a20"],
  sand: ["#b98e62", "#f8ebdb", "#2c1e0f"],
};

const c = (id: string, name: string, hue: Hue, head: Head, top: Top, eyes: Eyes, mouth: Mouth, cheeks = false): Character =>
  ({ id, name, hue, head, top, eyes, mouth, cheeks });

export const CAST: readonly Character[] = [
  c("pixel", "Pixel", "coral", "tv", "antenna", "pixel", "smile"),
  c("moss", "Moss", "moss", "blob", "sprout", "happy", "smile", true),
  c("bolt", "Bolt", "amber", "box", "bolt", "big", "grin"),
  c("juno", "Juno", "indigo", "round", "halo", "dots", "smile", true),
  c("kip", "Kip", "sky", "wide", "ears", "big", "tiny"),
  c("rook", "Rook", "slate", "hex", "none", "visor", "flat"),
  c("sage", "Sage", "teal", "tall", "sprout", "sleepy", "smile"),
  c("tango", "Tango", "rose", "dome", "twin", "wink", "grin"),
  c("vex", "Vex", "violet", "hex", "horns", "pixel", "zig"),
  c("wren", "Wren", "sand", "round", "tuft", "glasses", "tiny"),
  c("zed", "Zed", "slate", "box", "antenna", "sleepy", "flat"),
  c("nova", "Nova", "violet", "round", "halo", "big", "o"),
  c("orbit", "Orbit", "sky", "dome", "antenna", "cyclops", "smile"),
  c("pip", "Pip", "amber", "blob", "tuft", "dots", "o", true),
  c("quill", "Quill", "indigo", "tall", "cap", "glasses", "smirk"),
  c("rune", "Rune", "teal", "hex", "twin", "happy", "tiny"),
  c("sprocket", "Sprocket", "moss", "tv", "twin", "visor", "zig"),
  c("taffy", "Taffy", "rose", "wide", "cap", "wink", "smile", true),
  c("umber", "Umber", "sand", "box", "horns", "dots", "smirk"),
  c("volt", "Volt", "coral", "tall", "bolt", "pixel", "grin"),
  c("widget", "Widget", "teal", "tv", "none", "big", "o"),
  c("yara", "Yara", "coral", "round", "ears", "happy", "smile", true),
  c("zip", "Zip", "sky", "dome", "bolt", "dots", "grin"),
  c("ash", "Ash", "slate", "blob", "none", "sleepy", "flat"),
  c("biscuit", "Biscuit", "sand", "wide", "tuft", "dots", "smile", true),
  c("cog", "Cog", "indigo", "box", "twin", "cyclops", "flat"),
  c("dash", "Dash", "moss", "tall", "antenna", "wink", "smirk"),
  c("echo", "Echo", "violet", "dome", "halo", "glasses", "o"),
  c("fig", "Fig", "rose", "blob", "horns", "big", "zig"),
  c("dot", "Dot", "amber", "wide", "antenna", "happy", "tiny"),
];

/** Where a head puts its features: top edge, eye line, half the eye spacing, mouth line, left edge. */
const GEO: Record<Head, { top: number; ey: number; ex: number; my: number; side: number }> = {
  box: { top: 21, ey: 33, ex: 8, my: 43, side: 14 }, round: { top: 20, ey: 35, ex: 7, my: 44, side: 15 },
  tall: { top: 16, ey: 31, ex: 6, my: 43, side: 19 }, wide: { top: 25, ey: 36, ex: 10, my: 44, side: 9 },
  dome: { top: 19, ey: 35, ex: 8, my: 45, side: 14 }, hex: { top: 18, ey: 33, ex: 7, my: 44, side: 15 },
  tv: { top: 20, ey: 32, ex: 7, my: 40, side: 12 }, blob: { top: 19, ey: 34, ex: 7.5, my: 44, side: 13 },
};

function head(h: Head, body: string, ink: string): ReactNode {
  switch (h) {
    case "box": return <rect x="14" y="21" width="36" height="30" rx="8" fill={body} />;
    case "round": return <circle cx="32" cy="37" r="17" fill={body} />;
    case "tall": return <rect x="19" y="16" width="26" height="37" rx="12" fill={body} />;
    case "wide": return <rect x="9" y="25" width="46" height="27" rx="13" fill={body} />;
    case "dome": return <path d="M14 48V37a18 18 0 0 1 36 0v11a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4z" fill={body} />;
    case "hex": return <path d="M32 18l17 9v19l-17 9-17-9V27z" fill={body} stroke={body} strokeWidth="3" strokeLinejoin="round" />;
    case "blob": return <path d="M33 19c11 0 18 8 18 17 0 11-8 17-19 17S13 47 13 37c0-10 8-18 20-18z" fill={body} />;
    case "tv": return <>
      <rect x="18" y="49" width="6" height="5" rx="2" fill={body} /><rect x="40" y="49" width="6" height="5" rx="2" fill={body} />
      <rect x="12" y="20" width="40" height="31" rx="7" fill={body} /><rect x="16" y="24" width="32" height="22" rx="4" fill={ink} /></>;
  }
}

function top(t: Top, y: number, side: number, ey: number, body: string, ink: string): ReactNode {
  const line = { stroke: ink, strokeWidth: 2.4, strokeLinecap: "round" as const, fill: "none" };
  switch (t) {
    case "antenna": return <><path d={`M32 ${y + 1}V${y - 7}`} {...line} /><circle cx="32" cy={y - 9} r="3.2" fill={body} /></>;
    case "twin": return <><path d={`M25 ${y + 2}l-3-8M39 ${y + 2}l3-8`} {...line} />
      <circle cx="21.5" cy={y - 8} r="2.6" fill={body} /><circle cx="42.5" cy={y - 8} r="2.6" fill={body} /></>;
    case "ears": return <><circle cx={side + 1} cy={ey - 2} r="5.5" fill={body} /><circle cx={63 - side} cy={ey - 2} r="5.5" fill={body} /></>;
    case "horns": return <path d={`M21 ${y + 5}l-3-11 9 6zM43 ${y + 5}l3-11-9 6z`} fill={body} stroke={body} strokeWidth="1.5" strokeLinejoin="round" />;
    case "sprout": return <><path d={`M32 ${y + 1}V${y - 5}`} {...line} />
      <path d={`M32 ${y - 5}c-1-5-6-6-9-5 0 5 4 7 9 5zM32 ${y - 5}c1-5 6-6 9-5 0 5-4 7-9 5z`} fill={body} /></>;
    case "cap": return <><rect x="17" y={y - 3} width="30" height="9" rx="4.5" fill={ink} /><circle cx="32" cy={y - 5} r="3" fill={body} /></>;
    case "bolt": return <path d={`M34 ${y - 12}l-8 9h5l-2 7 8-9h-5z`} fill={body} stroke={ink} strokeWidth="1.2" strokeLinejoin="round" />;
    case "halo": return <ellipse cx="32" cy={y - 5} rx="10" ry="3" fill="none" stroke={body} strokeWidth="2.6" />;
    case "tuft": return <path d={`M26 ${y + 2}l2-7 3 5 2-8 3 8 2-5 2 7`} {...line} strokeLinejoin="round" />;
    case "none": return null;
  }
}

function eyes(e: Eyes, y: number, ex: number, fg: string, other: string): ReactNode {
  const l = 32 - ex, r = 32 + ex, line = { stroke: fg, strokeWidth: 2.2, strokeLinecap: "round" as const, fill: "none" };
  switch (e) {
    case "dots": return <><circle cx={l} cy={y} r="2.6" fill={fg} /><circle cx={r} cy={y} r="2.6" fill={fg} /></>;
    case "big": return <><circle cx={l} cy={y} r="4.6" fill="#fff" /><circle cx={r} cy={y} r="4.6" fill="#fff" />
      <circle cx={l + 0.9} cy={y + 0.6} r="2.2" fill="#14161a" /><circle cx={r + 0.9} cy={y + 0.6} r="2.2" fill="#14161a" /></>;
    case "visor": return <><rect x={l - 5} y={y - 4.5} width={2 * ex + 10} height="9" rx="4.5" fill={fg} />
      <circle cx={l} cy={y} r="1.7" fill={other} /><circle cx={r} cy={y} r="1.7" fill={other} /></>;
    case "glasses": return <><circle cx={l} cy={y} r="4.8" {...line} /><circle cx={r} cy={y} r="4.8" {...line} />
      <path d={`M${l + 4.8} ${y}H${r - 4.8}`} {...line} /><circle cx={l} cy={y} r="1.6" fill={fg} /><circle cx={r} cy={y} r="1.6" fill={fg} /></>;
    case "wink": return <><circle cx={l} cy={y} r="2.6" fill={fg} /><path d={`M${r - 3.2} ${y + 0.5}q3.2-3.6 6.4 0`} {...line} /></>;
    case "sleepy": return <><path d={`M${l - 3.2} ${y - 0.5}q3.2 3.4 6.4 0`} {...line} /><path d={`M${r - 3.2} ${y - 0.5}q3.2 3.4 6.4 0`} {...line} /></>;
    case "pixel": return <><rect x={l - 2.6} y={y - 2.6} width="5.2" height="5.2" fill={fg} /><rect x={r - 2.6} y={y - 2.6} width="5.2" height="5.2" fill={fg} /></>;
    case "cyclops": return <><circle cx="32" cy={y} r="6.2" fill="#fff" /><circle cx="32.8" cy={y + 0.5} r="2.9" fill="#14161a" /></>;
    case "happy": return <><path d={`M${l - 3.2} ${y + 1}q3.2-4.2 6.4 0`} {...line} /><path d={`M${r - 3.2} ${y + 1}q3.2-4.2 6.4 0`} {...line} /></>;
  }
}

function mouth(m: Mouth, y: number, fg: string): ReactNode {
  const line = { stroke: fg, strokeWidth: 2.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  switch (m) {
    case "smile": return <path d={`M27 ${y}q5 4.6 10 0`} {...line} />;
    case "flat": return <path d={`M28 ${y + 1}h8`} {...line} />;
    case "o": return <circle cx="32" cy={y + 1} r="2.3" fill={fg} />;
    case "grin": return <><path d={`M26 ${y - 1}h12a6 6 0 0 1-12 0z`} fill={fg} /><rect x="28" y={y - 1} width="8" height="2" rx="1" fill="#fff" /></>;
    case "zig": return <path d={`M26 ${y}l3 2 3-2 3 2 3-2`} {...line} />;
    case "smirk": return <path d={`M28 ${y + 1}q5 2 8-2.4`} {...line} />;
    case "tiny": return <path d={`M30 ${y}q2 2.2 4 0`} {...line} />;
  }
}

/** One character on its tile. Decorative: the caller names the agent in text beside it. */
export function Face({ who, size = 32, title }: { who: Character; size?: number; title?: string }) {
  const [tile, body, ink] = HUES[who.hue], g = GEO[who.head];
  // On the TV head the features sit on the dark screen, so they are drawn in the body colour.
  const fg = who.head === "tv" ? body : ink, other = who.head === "tv" ? ink : body;
  return <svg className="hq-face" viewBox="0 0 64 64" width={size} height={size} role="img" aria-hidden={title ? undefined : true}
    aria-label={title} data-character={who.id}>
    {title && <title>{title}</title>}
    <rect width="64" height="64" rx="14" fill={tile} />
    <path d="M15 64c2-6 9-9 17-9s15 3 17 9z" fill={ink} opacity=".3" />
    {who.top === "ears" && top("ears", g.top, g.side, g.ey, body, ink)}
    {head(who.head, body, ink)}
    {who.top !== "ears" && top(who.top, g.top, g.side, g.ey, body, ink)}
    {who.cheeks && <><circle cx={32 - g.ex - 5} cy={g.ey + 6} r="2.6" fill={tile} opacity=".5" /><circle cx={32 + g.ex + 5} cy={g.ey + 6} r="2.6" fill={tile} opacity=".5" /></>}
    {eyes(who.eyes, g.ey, g.ex, fg, other)}
    {mouth(who.mouth, g.my, fg)}
  </svg>;
}
