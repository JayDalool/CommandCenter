// The browser tests serve Classic with e2e/serve.mjs instead of ccd. These checks keep its headers and cache rules
// identical to ccd's own (server/ccd/api.py, UiFiles), so a CSP problem cannot pass in the tests and fail for Jay.
import { csp, securityHeaders, HASHED_ASSET, CACHE_IMMUTABLE, CACHE_REVALIDATE } from "../e2e/serve.mjs";

// Read with node:fs (Vite will not import a file outside web/app, and widening its file access is not worth it).
// The module name is a plain string so the type check does not need @types/node.
const NODE_FS: string = "node:fs";
const { readFileSync } = (await import(NODE_FS)) as { readFileSync(path: string, encoding: "utf8"): string };
const here = (import.meta as unknown as { dirname: string }).dirname;  // web/app/tests
const apiPy = readFileSync(`${here}/../../../server/ccd/api.py`, "utf8");

/** The Python string literals between `start` and `end`, joined, with ccd's {port} filled in. Anything else between
 *  them (a variable, a function call, a format other than {port}) fails: this reader would not understand it. */
function pyString(start: string, end: string, port: number): string {
  const from = apiPy.indexOf(start);
  expect(from, `api.py still has ${start}`).toBeGreaterThan(-1);
  const block = apiPy.slice(from + start.length, apiPy.indexOf(end, from));
  const literal = /f?(?:"([^"\\]*)"|'([^'\\]*)')/g;
  expect(block.replace(literal, "").trim(), "only adjacent string literals").toBe("");
  const text = [...block.matchAll(literal)].map((m) => m[1] ?? m[2]).join("");
  expect(text.replace(/\{port\}/g, ""), "no {placeholder} but {port}").not.toMatch(/[{}]/);
  return text.replaceAll("{port}", String(port));
}

describe("e2e/serve.mjs matches ccd's UiFiles", () => {
  it("sends the same Content-Security-Policy", () => {
    for (const port of [4317, 8765]) {
      expect(csp(port)).toBe(pyString('(b"content-security-policy", (', ").encode())", port));
    }
  });

  it("sends the same security headers and no others", () => {
    const block = apiPy.slice(apiPy.indexOf("self.headers = ["), apiPy.indexOf("]\n", apiPy.indexOf("self.headers = [")));
    const names = [...block.matchAll(/\(b"([a-z-]+)"/g)].map((m) => m[1]);
    expect(Object.keys(securityHeaders(4317)).sort()).toEqual(names.sort());
    for (const [name, value] of [...block.matchAll(/\(b"([a-z-]+)", b"([^"]+)"\)/g)].map((m) => [m[1], m[2]])) {
      expect(securityHeaders(4317)[name], name).toBe(value);
    }
  });

  it("caches the same way: a year for a hashed asset, revalidate the rest, never store an error", () => {
    expect(apiPy).toContain("ok = 200 <= status < 300 or status == 304");
    expect(apiPy).toContain('cache = CACHE_IMMUTABLE if (immutable and ok) else CACHE_REVALIDATE if ok else b"no-store"');
    const pyRegex = /HASHED_ASSET = re\.compile\(r"([^"]+)"\)/.exec(apiPy)?.[1];
    expect(HASHED_ASSET.source.replaceAll("\\/", "/")).toBe(pyRegex);
    expect(CACHE_IMMUTABLE).toBe(/CACHE_IMMUTABLE = b"([^"]+)"/.exec(apiPy)?.[1]);
    expect(CACHE_REVALIDATE).toBe(/CACHE_REVALIDATE = b"([^"]+)"/.exec(apiPy)?.[1]);
  });

  it("refuses other methods the way Guard does (serve.spec.ts checks the response)", () => {
    expect(apiPy).toContain('NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}');
    expect(apiPy).toContain('elif scope["type"] == "http" and scope.get("method") not in ("GET", "HEAD"):\n            problem = (405, "the UI is read-only files")');
  });
});
