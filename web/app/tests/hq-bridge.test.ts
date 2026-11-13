// HQ's stylesheets may change one of Classic's variables in one place only: frame/classic-bridge.css, under
// :root[data-ui="hq"] .hq-shell, pointing it at an HQ token that exists. Everywhere else they declare --hq-* (tokens.css)
// or nothing. e2e/parity.spec.ts checks the resulting values in a browser; this holds the scope.
const NODE_FS: string = "node:fs";
const { readFileSync, readdirSync, statSync } = (await import(NODE_FS)) as {
  readFileSync(path: string, encoding: "utf8"): string;
  readdirSync(path: string): string[];
  statSync(path: string): { isDirectory(): boolean };
};
const here = (import.meta as unknown as { dirname: string }).dirname;  // web/app/tests
const root = `${here}/../src/hq`;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = `${dir}/${n}`;
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}
/** [selector, declarations] for every rule; @media blocks are opened, their own selectors kept. */
function rules(css: string): [string, string][] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const out: [string, string][] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m; (m = re.exec(text));) out.push([m[1].replace(/@media[^{]*\{/g, "").trim(), m[2]]);
  return out;
}
const decls = (body: string) => body.split(";").map((d) => d.trim()).filter(Boolean)
  .map((d) => [d.slice(0, d.indexOf(":")).trim(), d.slice(d.indexOf(":") + 1).trim()] as const);

const sheets = files(root).filter((p) => p.endsWith(".css") && !p.endsWith("/hq/tokens.css"));
const BRIDGE = `${root}/frame/classic-bridge.css`;
const tokens = new Set(readFileSync(`${root}/tokens.css`, "utf8").match(/--hq-[a-z0-9-]+(?=\s*:)/g) ?? []);

describe("Classic's variables inside HQ", () => {
  it("are declared only in frame/classic-bridge.css", () => {
    expect(sheets).toContain(BRIDGE);
    const where = sheets.flatMap((p) => rules(readFileSync(p, "utf8"))
      .flatMap(([sel, body]) => decls(body).filter(([n]) => n.startsWith("--")).map(([n]) => `${p.slice(root.length + 1)} ${sel} ${n}`)));
    expect(where.length).toBeGreaterThan(30);
    expect(where.filter((w) => !w.startsWith("frame/classic-bridge.css "))).toEqual([]);
  });

  it("only under :root[data-ui=\"hq\"] .hq-shell, each pointing at an HQ token that exists", () => {
    const r = rules(readFileSync(BRIDGE, "utf8"));
    expect(r.map(([sel]) => sel)).toEqual([':root[data-ui="hq"] .hq-shell']);
    for (const [n, v] of decls(r[0][1]).filter(([n]) => n.startsWith("--"))) {
      expect(n.startsWith("--hq-"), n).toBe(false);
      const target = /^var\((--hq-[a-z0-9-]+)\)$/.exec(v)?.[1];
      expect(target && tokens.has(target), `${n}: ${v}`).toBe(true);
    }
  });
});
