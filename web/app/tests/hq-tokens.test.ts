// HQ's design tokens (src/hq/tokens.css, src/hq/palette.ts) must be inert in Classic: scoped to <html data-ui="hq">,
// custom properties only, nothing loaded. The browser half of this (e2e/hq-tokens.spec.ts, e2e/parity.spec.ts) checks
// the same in Chromium and proves Classic's pixels do not move.
import { HQ_AGENT_COLORS, HQ_PROJECT_COLORS } from "../src/hq/palette";

// Read with node:fs: Vitest turns every CSS import into an empty string, ?raw included. The module name is a plain
// string so the type check does not need @types/node.
const NODE_FS: string = "node:fs";
const NODE_CRYPTO: string = "node:crypto";
const { readFileSync } = (await import(NODE_FS)) as { readFileSync(path: string, encoding: "utf8"): string };
const { createHash } = (await import(NODE_CRYPTO)) as { createHash(alg: "sha256"): { update(s: string): { digest(e: "hex"): string } } };
const here = (import.meta as unknown as { dirname: string }).dirname;  // web/app/tests
const css = readFileSync(`${here}/../src/hq/tokens.css`, "utf8");
const paletteTs = readFileSync(`${here}/../src/hq/palette.ts`, "utf8");

const HQ = ':root[data-ui="hq"]';

interface Rule { media: string | null; selector: string; decls: [string, string][] }

/** A small CSS reader: top-level rules and one level of @media, which is all tokens.css may contain. */
function parse(src: string): Rule[] {
  const text = src.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];
  const close = (from: number) => {
    let depth = 0;
    for (let i = from; i < text.length; i++) {
      if (text[i] === "{") depth++;
      else if (text[i] === "}" && --depth === 0) return i;
    }
    throw new Error("unbalanced braces");
  };
  const walk = (start: number, end: number, media: string | null) => {
    let at = start;
    while (at < end) {
      const open = text.indexOf("{", at);
      if (open < 0 || open >= end) { expect(text.slice(at, end).trim(), "text outside any rule").toBe(""); return; }
      const head = text.slice(at, open).trim();
      const stop = close(open);
      if (head.startsWith("@media")) {
        expect(media, "nested @media").toBeNull();
        walk(open + 1, stop, head.slice(6).trim());
      } else {
        const decls = text.slice(open + 1, stop).split(";").map((d) => d.trim()).filter(Boolean)
          .map((d) => [d.slice(0, d.indexOf(":")).trim(), d.slice(d.indexOf(":") + 1).trim()] as [string, string]);
        rules.push({ media, selector: head, decls });
      }
      at = stop + 1;
    }
  };
  walk(0, text.length, null);
  return rules;
}

const rules = parse(css);
const find = (selector: string, media: string | null) => rules.find((r) => r.selector === selector && r.media === media)!;
const dark = new Map(find(HQ, null).decls);
const light = new Map(find(`${HQ}[data-theme="light"]`, null).decls);
const system = new Map(find(`${HQ}[data-theme="system"]`, "(prefers-color-scheme: light)").decls);

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe("HQ tokens are inert in Classic", () => {
  it("scopes every rule to :root[data-ui=\"hq\"]", () => {
    expect(rules.length).toBeGreaterThan(0);
    for (const r of rules) {
      for (const s of r.selector.split(",")) expect(s.trim().startsWith(HQ), s).toBe(true);
      expect([HQ, `${HQ}[data-theme="light"]`, `${HQ}[data-theme="system"]`]).toContain(r.selector);
    }
  });

  it("uses @media only for light mode, window width and reduced motion", () => {
    for (const r of rules) {
      if (r.media === null) continue;
      expect(r.media).toMatch(/^\((prefers-color-scheme: light|max-width: \d+px|prefers-reduced-motion: reduce)\)$/);
    }
    expect(find(`${HQ}[data-theme="system"]`, "(prefers-color-scheme: light)")).toBeTruthy();
  });

  it("follows the computer's light mode only when Classic's theme is System", () => {
    // Otherwise Classic Dark on a computer in light mode would get HQ's light tokens.
    for (const r of rules) {
      const system = r.selector === `${HQ}[data-theme="system"]`;
      expect(r.media === "(prefers-color-scheme: light)", `${r.media} ${r.selector}`).toBe(system);
    }
  });

  it("declares only --hq-* custom properties", () => {
    for (const r of rules) for (const [name] of r.decls) expect(name, `${r.selector} ${name}`).toMatch(/^--hq-[a-z0-9-]+$/);
  });

  it("loads nothing and overrides nothing", () => {
    expect(css).not.toMatch(/@import|@font-face|url\(|!important|expression\(/i);
    expect(css.replace(/\/\*[\s\S]*?\*\//g, "").match(/@[a-z-]+/g)?.every((a) => a === "@media")).toBe(true);
  });

  it("refers only to its own tokens", () => {
    const defined = new Set(rules.flatMap((r) => r.decls.map(([n]) => n)));
    for (const ref of css.matchAll(/var\((--[a-z0-9-]+)/g)) expect(defined.has(ref[1]), ref[1]).toBe(true);
  });
});

describe("HQ tokens match the approved design (d55aab0, Workbench)", () => {
  it("is exactly what the generator wrote (its seal), so a hand edit fails even without the approved commit", () => {
    // `node design/hq-tokens/generate.mjs --check` (in npm run test:e2e:local) compares with the commit itself.
    for (const [name, text] of [["tokens.css", css], ["palette.ts", paletteTs]]) {
      const stated = /values sha256 ([0-9a-f]{64})/.exec(text)?.[1];
      const actual = createHash("sha256").update(text.replace(/values sha256 [0-9a-f]{64}/, "values sha256 ")).digest("hex");
      expect(actual, `${name} was edited by hand: run node design/hq-tokens/generate.mjs`).toBe(stated);
    }
  });

  it("has every token: 188 dark, 153 light, 5 project colours", () => {
    expect([...dark.keys()].filter((k) => !k.startsWith("--hq-pj-")).length).toBe(188);
    expect([...dark.keys()].filter((k) => k.startsWith("--hq-pj-")).length).toBe(5);
    expect(light.size).toBe(153);
    for (const k of light.keys()) expect(dark.has(k), `${k} has a dark value`).toBe(true);
  });

  it("System uses exactly the Light values", () => {
    expect([...system]).toEqual([...light]);
  });

  it("keeps body text at 4.5:1 or better on every surface, in both themes", () => {
    // Status colours used as text (--hq-ok, --hq-warn, --hq-idle …) are below 4.5:1 on some light surfaces at the
    // approved commit; the proposed V12 values fix that and arrive by regenerating from the commit Jay approves.
    for (const theme of [dark, new Map([...dark, ...light])]) {
      for (const ink of ["--hq-text", "--hq-text-2", "--hq-muted", "--hq-link"]) {
        for (const surface of ["--hq-bg", "--hq-panel", "--hq-panel-2", "--hq-raise"]) {
          expect(contrast(theme.get(ink)!, theme.get(surface)!), `${ink} on ${surface}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it("keeps white on the count badge at 4.5:1 or better, in both themes", () => {
    for (const theme of [dark, new Map([...dark, ...light])]) {
      expect(contrast("#ffffff", theme.get("--hq-badge")!)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("palette.ts has the 11 approved colours, and tokens.css agrees", () => {
    expect(HQ_PROJECT_COLORS).toEqual({ samvision: "#4fbf8f", gyst: "#9a86d8", mfe: "#d1a94a", gauzemate: "#d9748a",
      commandcenter: "#6a9ad8" });
    expect(HQ_AGENT_COLORS).toEqual({ claude: "#ff7a45", iris: "#4f7bff", nova: "#a463ff", atlas: "#22c98e",
      pixel: "#ff4fa0", orion: "#ffb020" });
    for (const [key, color] of Object.entries(HQ_PROJECT_COLORS)) expect(dark.get(`--hq-pj-${key}`)).toBe(color);
  });
});

describe("only the Interface preference turns HQ on", () => {
  it("no source file but lib/prefs.ts sets data-ui", () => {
    // A heuristic over the source; e2e/load.spec.ts checks the attribute itself on every route.
    const sources = { ...import.meta.glob("../src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }),
      "../index.html": readFileSync(`${here}/../index.html`, "utf8") } as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    // Comments out (a // after a colon or quote is a URL, not a comment), then any way of reaching the attribute.
    const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
    const sets = /data-ui|dataset\s*(\.\s*ui\b|\[\s*["'`]ui["'`]\s*\])|Object\.assign\(\s*[\w.]*dataset\b/;
    const setters = Object.entries(sources).filter(([, src]) => sets.test(code(src))).map(([f]) => f);
    expect(setters).toEqual(["../src/lib/prefs.ts"]);
  });
});
