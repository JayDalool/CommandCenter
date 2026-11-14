// The cast: 30 original characters, drawn here from a few parts (head, top, eyes, mouth, colour). They are faces for
// agents in Childish mode (Settings › Appearance › Style); Professional mode shows none. A character is decoration
// only: it never stands for a status. Colours are fixed art colours, not theme tokens, so a face looks the same on
// dark and light; each sits on its own tile. Every one is a bust: a lit tile, shoulders with an outfit, a shaded head.
import { useId, type ReactNode } from "react";

type Hue = "coral" | "amber" | "moss" | "teal" | "sky" | "indigo" | "violet" | "rose" | "slate" | "sand";
type Head = "box" | "round" | "tall" | "wide" | "dome" | "hex" | "tv" | "blob";
type Top = "antenna" | "twin" | "ears" | "horns" | "sprout" | "cap" | "bolt" | "halo" | "tuft" | "none";
type Eyes = "dots" | "big" | "visor" | "glasses" | "wink" | "sleepy" | "pixel" | "cyclops" | "happy";
type Mouth = "smile" | "flat" | "o" | "grin" | "zig" | "smirk" | "tiny";

export interface Character { id: string; name: string; hue: Hue; head: Head; top: Top; eyes: Eyes; mouth: Mouth; cheeks?: boolean }

/** [tile from, tile to, head light, head shade, shoulders, part, ink, deep]. `part` is the darker body tone of necks,
 *  side parts and eye sockets; `deep` is the strong tone of outfits, stems and hair. */
type Pal = readonly [string, string, string, string, string, string, string, string];
const HUES: Record<Hue, Pal> = {
  coral: ["#f49468", "#cc4c25", "#fff7f0", "#f4d3bf", "#f0cbb5", "#dfb199", "#2a1710", "#c2451f"],
  amber: ["#f7cc58", "#c07f0a", "#fffbee", "#f2dc98", "#ecd48c", "#d6ba6e", "#2b2108", "#a96f06"],
  moss: ["#8fc882", "#41793c", "#f8fdf2", "#cfe8c0", "#cfe8c0", "#b5e0a6", "#13240f", "#2f6a2b"],
  teal: ["#5fc4bd", "#1c7672", "#f1fdfb", "#c5ebe5", "#bfe6e0", "#9fd0c9", "#0b2422", "#17635f"],
  sky: ["#7db4ee", "#2c6cb3", "#f3f9ff", "#cfe1f7", "#c8dcf4", "#a9c5e8", "#0e2036", "#235a99"],
  indigo: ["#9698ee", "#4a4db8", "#f6f6ff", "#d6d7f8", "#d0d1f5", "#b3b5ea", "#17173a", "#3d409f"],
  violet: ["#bb8fe8", "#7545ad", "#fbf5ff", "#e3d0f6", "#dcc8f2", "#c4a9e3", "#25123a", "#633a96"],
  rose: ["#ec8fb2", "#b0426d", "#fff5f9", "#f7cfde", "#f3c8d8", "#e3a8bf", "#37101f", "#96365c"],
  slate: ["#8693a3", "#434d5a", "#f6f8fa", "#d5dbe2", "#cfd6de", "#b3bcc7", "#151a20", "#39424d"],
  sand: ["#d6ae84", "#946b43", "#fffaf3", "#efdcc4", "#ebd6bc", "#d6bb9b", "#2c1e0f", "#7d5935"],
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

/** Where a head puts things, on the 96 grid: top edge, eye line, half the eye spacing, mouth line, left edge, bottom
 *  edge, and how far the top edge has dropped 15 across from the middle (where horns stand). A hard head is a
 *  machine, shaded top to bottom; a soft one is shaded round and has a bright patch. */
const GEO: Record<Head, { top: number; ey: number; ex: number; my: number; side: number; foot: number; drop: number; hard: boolean }> = {
  box: { top: 24, ey: 44, ex: 12, my: 56, side: 19, foot: 69, drop: 0, hard: true },
  round: { top: 22, ey: 45, ex: 10.5, my: 57, side: 23, foot: 72, drop: 5, hard: false },
  tall: { top: 20, ey: 41, ex: 9, my: 56, side: 29, foot: 72, drop: 6, hard: true },
  wide: { top: 31, ey: 48, ex: 15, my: 59, side: 12, foot: 71, drop: 0, hard: false },
  dome: { top: 21, ey: 46, ex: 12, my: 58, side: 21, foot: 70, drop: 4.5, hard: true },
  hex: { top: 17.5, ey: 42, ex: 10.5, my: 56, side: 23.5, foot: 73, drop: 8.5, hard: true },
  tv: { top: 22, ey: 43, ex: 11, my: 55, side: 17, foot: 69, drop: 0, hard: true },
  blob: { top: 24, ey: 47.5, ex: 11, my: 58, side: 19, foot: 74, drop: 4, hard: false },
};

/** How far each top rises above the head. A top is drawn from its foot, so a head that starts high can shrink it
 *  to keep it inside the tile. */
const RISE: Record<Top, number> = { antenna: 20, twin: 17.5, ears: 0, horns: 13, sprout: 20, cap: 18, bolt: 22.5, halo: 14, tuft: 15, none: 0 };

function head(h: Head, fill: string, ink: string): ReactNode {
  switch (h) {
    case "box": return <rect x="19" y="24" width="58" height="45" rx="13" fill={fill} />;
    case "round": return <circle cx="48" cy="47" r="25" fill={fill} />;
    case "tall": return <rect x="29" y="20" width="38" height="52" rx="17" fill={fill} />;
    case "wide": return <rect x="12" y="31" width="72" height="40" rx="19" fill={fill} />;
    case "dome": return <path d="M21 64V48a27 27 0 0 1 54 0v16a6 6 0 0 1-6 6H27a6 6 0 0 1-6-6z" fill={fill} />;
    case "hex": return <path fill={fill} d={"M42.4 20.7Q48 17.5 53.6 20.7L66.9 28.3Q72.5 31.5 72.5 38V52.5Q72.5 59 66.9 62.2L53.6 69.8"
      + "Q48 73 42.4 69.8L29.1 62.2Q23.5 59 23.5 52.5V38Q23.5 31.5 29.1 28.3z"} />;
    case "blob": return <path d="M49 24c17 0 28 11 28 25 0 15-12 25-29 25S19 64 19 50c0-15 12-26 30-26z" fill={fill} />;
    case "tv": return <><rect x="17" y="22" width="62" height="47" rx="14" fill={fill} /><rect x="23" y="28" width="50" height="35" rx="9" fill={ink} />
      <path d="M26.5 37a6 6 0 0 1 6-6h17L34 60h-1.5a6 6 0 0 1-6-6z" fill="#fff" opacity=".07" /></>;
  }
}

/** The bright patch on a soft head. */
const SHINE: Partial<Record<Head, [number, number]>> = { blob: [35, 34.5], round: [37, 33], wide: [30, 40.5] };

/** A machine's side parts: handles on a TV, bolts on a box, ear pieces on a dome. */
function sides(h: Head, side: number, ey: number, part: string, ink: string): ReactNode {
  const both = (f: (x: number) => ReactNode) => <>{f(side)}{f(96 - side)}</>;
  switch (h) {
    case "tv": return both((x) => <rect x={x - (x < 48 ? 6.5 : 2.5)} y={ey - 4} width="9" height="14" rx="4.5" fill={part} />);
    case "box": return both((x) => <><circle cx={x < 48 ? x - 2.5 : x + 2.5} cy={ey + 2} r="6.5" fill={part} />
      <circle cx={x < 48 ? x - 2.5 : x + 2.5} cy={ey + 2} r="2.3" fill={ink} /></>);
    case "dome": return both((x) => <rect x={x - (x < 48 ? 5 : 3)} y={ey - 2} width="8" height="15" rx="4" fill={part} />);
    default: return null;
  }
}

/** A top, drawn around its foot at 0,0 with up as minus. */
function top(t: Top, p: Pal): ReactNode {
  const [, , h0, , , part, ink, deep] = p, stem = { stroke: ink, strokeWidth: 3, strokeLinecap: "round" as const, fill: "none" };
  switch (t) {
    case "antenna": return <><path d="M0 6V-9.5" {...stem} /><circle cy="-12" r="7.5" fill="#fff" opacity=".28" /><circle cy="-12" r="4.4" fill={h0} /></>;
    case "twin": return <><path d="M-8 9l-5-18M8 9l5-18" {...stem} />
      <circle cx="-13.5" cy="-11" r="6.2" fill="#fff" opacity=".25" /><circle cx="13.5" cy="-11" r="6.2" fill="#fff" opacity=".25" />
      <circle cx="-13.5" cy="-11" r="3.7" fill={h0} /><circle cx="13.5" cy="-11" r="3.7" fill={h0} /></>;
    case "horns": return <><path d="M-19.5 8C-23.5 0-24.5-7-21.5-14c5.5 3 9.5 8.5 11 19zM19.5 8C23.5 0 24.5-7 21.5-14c-5.5 3-9.5 8.5-11 19z" fill={h0} />
      <path d="M-23.3-6c0-2.8.6-5.5 1.8-8 2.7 1.5 5 3.6 6.8 6.3zM23.3-6c0-2.8-.6-5.5-1.8-8-2.7 1.5-5 3.6-6.8 6.3z" fill={deep} /></>;
    case "sprout": return <><path d="M0 2c0-4.5.5-8 .5-11.5" {...stem} stroke={deep} />
      <path d="M.5-9c-3-8.5-11.5-10.5-17-7.5 1 8.5 9.5 11.5 17 7.5z" fill={part} /><path d="M.5-9c3-8.5 11.5-10.5 17-7.5-1 8.5-9.5 11.5-17 7.5z" fill={h0} />
      <path d="M.5-9c-5-2.5-9.5-4.5-13.5-6M.5-9c5-2.5 9.5-4.5 13.5-6" stroke={deep} strokeWidth="1.2" strokeLinecap="round" fill="none" opacity=".5" /></>;
    case "cap": return <><path d="M-19 3c0-11 8-17 19-17s19 6 19 17z" fill={deep} />
      <path d="M-19 3c0-11 8-17 19-17 1.5 0 3 .1 4.4.3C-6-10.5-12-5-13 3z" fill="#fff" opacity=".16" />
      <rect x="-21" y="-1" width="42" height="6.5" rx="3.25" fill={ink} /><circle cy="-14.5" r="3.2" fill={h0} /></>;
    case "bolt": return <path d="M4-21.5L-7.5-8h7l-2.5 9L8.5-12.5h-7z" fill={h0} stroke={ink} strokeWidth="2.2" strokeLinejoin="round" />;
    case "halo": return <><ellipse cy="-8.5" rx="14.5" ry="4.4" fill="none" stroke="#fff" strokeWidth="7.5" opacity=".28" />
      <ellipse cy="-8.5" rx="14.5" ry="4.4" fill="none" stroke={h0} strokeWidth="3.2" /></>;
    case "tuft": return <path fill={deep}
      d="M-8 4c-1.5-6 0-10.5 3-14 .8 3 1.7 5 3 6.5.2-4.5 1.2-8 3.6-11 1.6 3.2 2.4 6.6 2.2 10.6 1.2-1.6 2.6-2.8 4.4-3.6.6 4.4-.2 8.2-2.2 11.5z" />;
    default: return null;
  }
}

/** The outfit on the shoulders. It follows the top, so a character's clothes go with its head gear. */
function outfit(t: Top, p: Pal): ReactNode {
  const [t0, , , , , , ink, deep] = p;
  const line = { stroke: deep, strokeWidth: 3.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  switch (t) {
    case "antenna": return <><path d="M37 77l11 9 11-9" {...line} /><circle cx="48" cy="92" r="2.6" fill={deep} /></>;
    case "sprout": return <path d="M29 75c5 5 12 8 19 8s14-3 19-8c1.5 5-.5 9-4 11.5-4.5 2.5-9.5 3.5-15 3.5s-10.5-1-15-3.5C29.5 84 27.5 80 29 75z" fill={deep} />;
    case "bolt": return <><rect x="38.5" y="82" width="19" height="16" rx="4" fill={ink} /><path d="M49.8 84.5l-5.3 6.3h3.3l-1.3 4.2 5.3-6.3h-3.3z" fill={t0} /></>;
    case "twin": return <><path d="M38 77q10 7.5 20 0M48 81.5V97" {...line} strokeWidth="2.8" /><rect x="45.4" y="84.5" width="5.2" height="7.5" rx="2.6" fill={deep} /></>;
    case "ears": return <><path d="M29 75.5c5 4.5 12 7 19 7s14-2.5 19-7l2 7c-5.5 4.5-13 7-21 7s-15.5-2.5-21-7z" fill={deep} />
      <path d="M53 88.5l8-2 3.5 11-9 1z" fill={deep} /><path d="M54.5 89.5l1.8 8" stroke={ink} strokeWidth="1.4" strokeLinecap="round" opacity=".35" /></>;
    case "horns": return <path d="M34.5 76l13.5 8.5-10.5 7zM61.5 76L48 84.5l10.5 7z" fill={deep} />;
    case "cap": return <><path d="M33 77c4 5.5 9 8.5 15 8.5s11-3 15-8.5" {...line} /><path d="M43.5 86v6.5M52.5 86v6.5" {...line} strokeWidth="2.2" />
      <circle cx="43.5" cy="93.5" r="1.9" fill={deep} /><circle cx="52.5" cy="93.5" r="1.9" fill={deep} /></>;
    case "halo": return <><path d="M48 84l-10-5.5v11zM48 84l10-5.5v11z" fill={deep} stroke={deep} strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="48" cy="84" r="2.8" fill={ink} /></>;
    case "tuft": return <><path d="M38.5 77q9.5 7 19 0" {...line} /><circle cx="48" cy="88" r="2.1" fill={deep} /><circle cx="48" cy="94.5" r="2.1" fill={deep} /></>;
    default: return <path d="M18 87.5c9-3.5 19-5.5 30-5.5s21 2 30 5.5M14.5 94.5c10-4 21.5-6 33.5-6s23.5 2 33.5 6" {...line} strokeWidth="2.8" />;
  }
}

/** Eyes. On a TV head they glow on the dark screen: `fg` is then the light tone and `ink` the screen. */
function eyes(e: Eyes, y: number, ex: number, p: Pal, tv: boolean): ReactNode {
  const [t0, t1, , h1, , part, ink] = p, fg = tv ? h1 : ink, white = tv ? h1 : "#fff";
  const line = { stroke: fg, strokeWidth: 3.2, strokeLinecap: "round" as const, fill: "none" };
  const both = (f: (x: number) => ReactNode, x = ex) => <>{f(48 - x)}{f(48 + x)}</>;
  const dot = (x: number) => <>{tv && <circle cx={x} cy={y} r="6.6" fill={t0} opacity=".28" />}
    <circle cx={x} cy={y} r="4" fill={fg} /><circle cx={x + 1.3} cy={y - 1.4} r="1.2" fill={tv ? ink : "#fff"} /></>;
  switch (e) {
    case "dots": return both(dot);
    case "big": { const x = Math.max(ex, 11.5); return <>
      <path d={`M${48 - x - 7.5} ${y - 11}q7-4.5 13.5-1.5M${48 + x - 6} ${y - 12.5}q6.5-3 13.5 1.5`} {...line} strokeWidth="2.4" />
      {both((c) => <><circle cx={c} cy={y + 0.5} r={tv ? 10 : 8.6} fill={tv ? t0 : part} opacity={tv ? 0.28 : 1} /><circle cx={c} cy={y} r="8" fill={white} />
        <circle cx={c + 1.3} cy={y + 0.8} r="5.3" fill={ink} /><circle cx={c + 3.3} cy={y - 1.4} r="1.9" fill={white} /></>, x)}</>; }
    case "visor": return <><rect x={48 - ex - 8.5} y={y - 7} width={2 * ex + 17} height="14" rx="7" fill={tv ? t0 : ink} opacity={tv ? 0.3 : 1} />
      {!tv && <rect x={48 - ex - 5} y={y - 5} width={2 * ex + 10} height="3.6" rx="1.8" fill="#fff" opacity=".12" />}
      {both((c) => <><circle cx={c} cy={y} r="4.6" fill={t0} opacity=".4" /><circle cx={c} cy={y} r="2.5" fill={tv ? h1 : "#fff"} /></>)}</>;
    case "glasses": { const x = Math.max(ex, 9.6); return <>
      {both((c) => <><circle cx={c} cy={y} r="7.4" fill="#fff" fillOpacity=".5" stroke={fg} strokeWidth="2.6" /><circle cx={c + 0.6} cy={y + 0.4} r="2.5" fill={fg} /></>, x)}
      <path d={`M${48 - x + 7.4} ${y - 1}q${x - 7.4}-2.5 ${2 * (x - 7.4)} 0M${48 - x - 7.4} ${y - 1}l-3.2-1.2M${48 + x + 7.4} ${y - 1}l3.2-1.2`}
        {...line} strokeWidth="2.4" /></>; }
    case "wink": return <>{dot(48 - ex)}<path d={`M${48 + ex - 5} ${y + 1.5}q5-6 10 0`} {...line} /></>;
    case "sleepy": return both((c) => <path d={`M${c - 5} ${y - 1}q5 5.5 10 0`} {...line} />);
    case "pixel": return both((c) => tv
      ? <><rect x={c - 6} y={y - 6} width="12" height="12" rx="2.5" fill={t0} opacity=".28" /><rect x={c - 3.5} y={y - 3.5} width="7" height="7" rx="1" fill={fg} /></>
      : <><rect x={c - 4.2} y={y - 4.2} width="8.4" height="8.4" rx="1.6" fill={fg} />
        <rect x={c - 2.4} y={y - 2.4} width="2.6" height="2.6" rx=".6" fill="#fff" opacity=".85" /></>);
    case "cyclops": return <><circle cx="48" cy={y + 0.6} r="11.8" fill={part} /><circle cx="48" cy={y} r="11" fill="#fff" />
      <circle cx="49" cy={y + 0.8} r="6.4" fill={t1} /><circle cx="49" cy={y + 0.8} r="3.3" fill={ink} /><circle cx="51.6" cy={y - 2.4} r="2.2" fill="#fff" /></>;
    case "happy": return both((c) => <path d={`M${c - 5.5} ${y + 2}q5.5-8 11 0`} {...line} strokeWidth="3.3" />);
  }
}

function mouth(m: Mouth, y: number, p: Pal, tv: boolean): ReactNode {
  const ink = p[6], fg = tv ? p[3] : ink;
  const line = { stroke: fg, strokeWidth: 3, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  switch (m) {
    // A smile on a screen is made of pixels.
    case "smile": return tv ? <path d={`M40 ${y - 3}h3v3h10v-3h3v3h-3v3H43v-3h-3z`} fill={fg} /> : <path d={`M42.5 ${y}q5.5 5.5 11 0`} {...line} />;
    case "flat": return <path d={`M43 ${y + 1.5}h10`} {...line} />;
    case "o": return <ellipse cx="48" cy={y + 2} rx="3.6" ry="4.2" fill={fg} />;
    case "grin": return <><path d={`M37.5 ${y}h21a10.5 8.5 0 0 1-21 0z`} fill={fg} />
      <path d={`M40.5 ${y}h15v2a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2z`} fill={tv ? ink : "#fff"} /><path d={`M44 ${y + 7}a5 2.8 0 0 1 8 0 8 5 0 0 1-8 0z`} fill="#e8734a" /></>;
    case "zig": return <path d={`M40 ${y + 0.5}l4 3 4-3 4 3 4-3`} {...line} />;
    case "smirk": return <path d={`M43 ${y + 1.5}q7 2.5 10.5-3.5`} {...line} />;
    case "tiny": return <path d={`M45 ${y}q3 3.2 6 0`} {...line} />;
  }
}

/** One character on its tile. Decoration: hidden from screen readers, because the caller names the agent in text
 *  beside it and a face inside a link or button would otherwise be read out as part of its name. `title` is the
 *  tooltip a mouse shows. */
export function Face({ who, size = 32, title }: { who: Character; size?: number; title?: string }) {
  const p = HUES[who.hue], g = GEO[who.head], [t0, t1, h0, h1, shoulders, part, ink] = p, tv = who.head === "tv";
  // One eye is as tall as two eyes and a brow, so it sits higher and the mouth moves down to clear it.
  const one = who.eyes === "cyclops";
  // Each face carries its own gradients, named apart from every other face on the page: one shared name would be
  // looked up in whichever face comes first, and stops painting when that one is hidden.
  const id = `hqf${useId().replace(/[^A-Za-z0-9]/g, "")}`, fill = `url(#${id}h)`, shine = SHINE[who.head];
  const stops = <><stop offset="0" stopColor={h0} /><stop offset="1" stopColor={h1} /></>;
  // Stems, horns and rings stand behind the head; leaves, hats and hair sit on it.
  const behind = who.top === "antenna" || who.top === "twin" || who.top === "horns" || who.top === "halo";
  const rise = RISE[who.top], foot = g.top + (who.top === "horns" ? g.drop : 0);
  const crown = rise > 0 && <g transform={`translate(48 ${foot}) scale(${Math.min(1, (g.top - 2.5) / rise)})`}>{top(who.top, p)}</g>;
  return <svg className="hq-face" viewBox="0 0 96 96" width={size} height={size} aria-hidden data-character={who.id}>
    {title && <title>{title}</title>}
    <defs>
      <linearGradient id={`${id}t`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={t0} /><stop offset="1" stopColor={t1} /></linearGradient>
      {g.hard ? <linearGradient id={`${id}h`} x1="0" y1="0" x2="0" y2="1">{stops}</linearGradient>
        : <radialGradient id={`${id}h`} cx=".38" cy=".28" r=".85">{stops}</radialGradient>}
      <clipPath id={`${id}c`}><rect width="96" height="96" rx="22" /></clipPath>
    </defs>
    <rect width="96" height="96" rx="22" fill={`url(#${id}t)`} />
    <circle cx="48" cy="45" r="39" fill="#fff" opacity=".1" />
    {/* Only the shoulders reach the tile's corners, so only they are clipped to it. */}
    <g clipPath={`url(#${id}c)`}>
      <path d="M13 100c0-15 15-25 35-25s35 10 35 25z" fill={shoulders} />
      <path d="M13 100c0-15 15-25 35-25 3 0 6 .2 9 .7C43 79 33 87 32 100z" fill={h0} />
      {outfit(who.top, p)}
    </g>
    <rect x="41" y={g.foot - 4} width="14" height="12" rx="3" fill={part} />
    {who.top === "ears"
      ? <><circle cx={g.side + 1.5} cy={g.ey - 2} r="8.5" fill={fill} /><circle cx={94.5 - g.side} cy={g.ey - 2} r="8.5" fill={fill} />
        <circle cx={g.side + 1.5} cy={g.ey - 2} r="4.6" fill={part} /><circle cx={94.5 - g.side} cy={g.ey - 2} r="4.6" fill={part} /></>
      : sides(who.head, g.side, g.ey, part, ink)}
    {behind && crown}
    {head(who.head, fill, ink)}
    {shine && <ellipse cx={shine[0]} cy={shine[1]} rx="7" ry="3.8" fill="#fff" opacity=".6" transform={`rotate(-30 ${shine[0]} ${shine[1]})`} />}
    {!behind && crown}
    {who.cheeks && <><ellipse cx={41.5 - g.ex} cy={g.ey + 9.5} rx="5.2" ry="3.6" fill="#f29c8f" opacity=".7" />
      <ellipse cx={54.5 + g.ex} cy={g.ey + 9.5} rx="5.2" ry="3.6" fill="#f29c8f" opacity=".7" /></>}
    {eyes(who.eyes, g.ey - (one ? 3 : 0), g.ex, p, tv)}
    {mouth(who.mouth, g.my + (one ? 3.5 : 0), p, tv)}
  </svg>;
}
