// The test server answers like ccd's UiFiles (server/ccd/api.py): its headers on every response, a hashed asset
// cached for a year, everything else revalidated, a plain 404 (never the app shell) for a missing file, and nothing
// but GET and HEAD. tests/e2e-serve.test.ts checks the header values themselves against api.py.
import { test, expect } from "@playwright/test";
import { csp } from "./serve.mjs";
import { env } from "./env";

const PORT = Number(env.E2E_PORT ?? 4317);

function headersOf(res: { headers(): Record<string, string> }) {
  const h = res.headers();
  return { csp: h["content-security-policy"], frame: h["x-frame-options"], referrer: h["referrer-policy"],
    sniff: h["x-content-type-options"] };
}
const STRICT = { csp: csp(PORT), frame: "DENY", referrer: "no-referrer", sniff: "nosniff" };

test("the app shell has ccd's headers and is revalidated", async ({ request }) => {
  const res = await request.get("/");
  expect(res.status()).toBe(200);
  expect(headersOf(res)).toEqual(STRICT);
  expect(res.headers()["cache-control"]).toBe("no-cache");
  expect(res.headers()["content-type"]).toMatch(/^text\/html/);
});

test("a hashed asset is immutable", async ({ request }) => {
  const html = await (await request.get("/")).text();
  const asset = /\/assets\/[A-Za-z0-9._-]+-[A-Za-z0-9_-]{8}\.js/.exec(html)?.[0];
  expect(asset, "index.html names a hashed script").toBeTruthy();
  const res = await request.get(asset!);
  expect(res.status()).toBe(200);
  expect(headersOf(res)).toEqual(STRICT);
  expect(res.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
});

test("a missing file is a plain 404, not the app shell", async ({ request }) => {
  for (const path of ["/assets/gone-AbCdEf12.js", "/nope", "/..%2f..%2fpackage.json"]) {
    const res = await request.get(path);
    expect(res.status(), path).toBe(404);
    expect(headersOf(res), path).toEqual(STRICT);
    expect(res.headers()["cache-control"], path).toBe("no-store");
    expect(await res.text(), path).not.toContain("<html");
  }
});

test("there is no API without a fixture, and nothing but GET and HEAD", async ({ request }) => {
  const api = await request.get("/api/state");
  expect(api.status()).toBe(404);
  expect(await api.json()).toEqual({ ok: false, error: "no fixture for this request" });
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const res = await request.fetch("/", { method });
    expect(res.status(), method).toBe(405);
    expect(headersOf(res), method).toEqual(STRICT);
  }
  expect((await request.head("/")).status()).toBe(200);
});
