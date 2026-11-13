// HQ's fonts (src/hq/fonts/fonts.css) are self-hosted Geist faces. A browser fetches a face only when a rendered
// element uses its family, so they stay inert in Classic as long as only HQ's tokens name them. This holds that, and
// e2e/hq-fonts.spec.ts checks the network side in Chromium.
const NODE_FS: string = "node:fs";
const { readFileSync, readdirSync, statSync } = (await import(NODE_FS)) as {
  readFileSync(path: string, encoding?: "utf8"): string;
  readdirSync(path: string): string[];
  statSync(path: string): { isDirectory(): boolean; size: number };
};
const here = (import.meta as unknown as { dirname: string }).dirname;  // web/app/tests
const dir = `${here}/../src/hq/fonts`;
const css = readFileSync(`${dir}/fonts.css`, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function files(root: string): string[] {
  return readdirSync(root).flatMap((n) => {
    const p = `${root}/${n}`;
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}

describe("HQ fonts", () => {
  it("holds only @font-face rules for Geist and Geist Mono, local woff2, swap", () => {
    const blocks = css.match(/@[a-z-]+\s*\{[^}]*\}/g) ?? [];
    expect(css.replace(/@[a-z-]+\s*\{[^}]*\}/g, "").trim()).toBe("");
    expect(blocks.length).toBe(2);
    const families = blocks.map((b) => b.match(/font-family:\s*"([^"]+)"/)?.[1]);
    expect(families).toEqual(["Geist", "Geist Mono"]);
    for (const b of blocks) {
      expect(b.startsWith("@font-face")).toBe(true);
      expect(b).toMatch(/font-display:\s*swap/);
      const urls = [...b.matchAll(/url\(\s*"([^"]+)"\s*\)/g)].map((m) => m[1]);
      expect(urls.length).toBe(1);
      expect(urls[0]).toMatch(/^\.\/[A-Za-z-]+\.woff2$/);
      const file = readFileSync(`${dir}/${urls[0].slice(2)}`) as unknown as { length: number; subarray(a: number, b: number): { toString(): string } };
      expect(file.subarray(0, 4).toString()).toBe("wOF2");
      expect(file.length).toBeLessThan(120_000);
    }
  });

  it("ships the font licence with the build (public/ is copied into dist/)", () => {
    expect(readFileSync(`${here}/../public/fonts/OFL.txt`, "utf8")).toMatch(/SIL Open Font License, Version 1\.1/);
  });

  it("is named only by HQ's own tokens, so Classic never fetches it", () => {
    // Quoted or not, in a font-family, a font shorthand or a custom property's value. Comments are not uses.
    const uses = /["']Geist( Mono)?["']|(?:font(?:-family)?|--[\w-]+)\s*:[^;{}]*\bGeist\b/i;
    const code = (t: string) => t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
    for (const t of ["font-family: Geist, sans-serif", "font: 600 12px/1 Geist Mono", "--x: Geist", "fontFamily: 'Geist'"]) {
      expect(uses.test(t), t).toBe(true);
    }
    expect(uses.test(code("/* font-family: Geist */ // font: Geist"))).toBe(false);
    const src = `${here}/../src`;
    const naming = files(src)
      .filter((p) => /\.(css|tsx?|html)$/.test(p) && !p.endsWith("/hq/fonts/fonts.css"))
      .filter((p) => uses.test(code(readFileSync(p, "utf8"))))
      .map((p) => p.slice(src.length + 1));
    expect(naming).toEqual(["hq/tokens.css"]);
  });
});
