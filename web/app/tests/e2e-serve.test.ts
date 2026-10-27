// The browser tests serve Classic with e2e/serve.mjs instead of ccd. These checks keep its headers and cache rules
// identical to ccd's own (server/ccd/api.py, UiFiles), so a CSP problem cannot pass in the tests and fail for Jay.
import { csp, securityHeaders, HASHED_ASSET, CACHE_IMMUTABLE, CACHE_REVALIDATE } from "../e2e/serve.mjs";

// Read with node:fs (Vite will not import a file outside web/app, and widening its file access is not worth it).
// The module name is a plain string so the type check does not need @types/node.
const NODE_FS: string = "node:fs";
const { readFileSync } = (await import(NODE_FS)) as { readFileSync(path: string, encoding: "utf8"): string };
const here = (import.meta as unknown as { dirname: string }).dirname;  // web/app/tests
const apiPy = readFileSync(`${here}/../../../server/ccd/api.py`, "utf8");

/** The Python string literals between `start` and `end`, joined, with ccd's {port} filled in. */
function pyString(start: string, end: string, port: number): string {
  const from = apiPy.indexOf(start);
  expect(from, `api.py still has ${start}`).toBeGreaterThan(-1);
  const block = apiPy.slice(from + start.length, apiPy.indexOf(end, from));
  return [...block.matchAll(/f?"([^"]*)"/g)].map((m) => m[1]).join("").replaceAll("{port}", String(port));
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

  it("caches the same way", () => {
    const pyRegex = /HASHED_ASSET = re\.compile\(r"([^"]+)"\)/.exec(apiPy)?.[1];
    expect(HASHED_ASSET.source.replaceAll("\\/", "/")).toBe(pyRegex);
    expect(CACHE_IMMUTABLE).toBe(/CACHE_IMMUTABLE = b"([^"]+)"/.exec(apiPy)?.[1]);
    expect(CACHE_REVALIDATE).toBe(/CACHE_REVALIDATE = b"([^"]+)"/.exec(apiPy)?.[1]);
  });
});
