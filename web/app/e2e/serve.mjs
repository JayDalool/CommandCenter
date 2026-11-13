// Serves a built UI (dist/) the way ccd does, for the browser tests: the same Content-Security-Policy and security
// headers (copied from server/ccd/api.py, UiFiles; tests/e2e-serve.test.ts fails if the two drift), GET and HEAD
// only (Guard's 405 otherwise), and a plain 404 for a missing file, never the app shell. There is no API here: every /api request is answered
// by the test's own fixture (e2e/fixture.ts), or gets this server's 404. No ccd, no token, no network.
//
// Usage: node e2e/serve.mjs [port] [dist-dir]      (defaults: 4317, ./dist; E2E_PORT and E2E_DIST also work)
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** ccd's UI policy for a given port (server/ccd/api.py, UiFiles.__init__). */
export function csp(port) {
  return "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
    `connect-src 'self' ws://127.0.0.1:${port} ws://localhost:${port}; font-src 'self'; ` +
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'";
}

export function securityHeaders(port) {
  return {
    "content-security-policy": csp(port),
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
  };
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".woff": "font/woff",
  ".ttf": "font/ttf", ".wasm": "application/wasm", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8" };
/** ccd's HASHED_ASSET and cache values (server/ccd/api.py). */
export const HASHED_ASSET = /^\/assets\/[A-Za-z0-9._-]+-[A-Za-z0-9_-]{8}\.(?:js|css|woff2?|ttf|svg|png|wasm)$/;
export const CACHE_IMMUTABLE = "public, max-age=31536000, immutable";
export const CACHE_REVALIDATE = "no-cache";

export function createServer(dist, port) {
  const root = path.resolve(dist);
  return http.createServer((req, res) => {
    const headers = securityHeaders(port);
    const send = (status, body, extra = {}) => { res.writeHead(status, { ...headers, ...extra }); res.end(req.method === "HEAD" ? undefined : body); };
    // ccd's Guard refuses other methods before UiFiles sees them: plain JSON, NO_STORE headers, no UI headers.
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { "content-type": "application/json", "cache-control": "no-store", "x-content-type-options": "nosniff" });
      return res.end(JSON.stringify({ ok: false, error: "the UI is read-only files" }));
    }
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (url.pathname.startsWith("/api/")) return send(404, JSON.stringify({ ok: false, error: "no fixture for this request" }), { "content-type": "application/json", "cache-control": "no-store" });
    let rel;
    try { rel = decodeURIComponent(url.pathname); } catch { rel = "\0"; }
    if (rel.includes("\0")) return send(400, "Bad Request", { "content-type": "text/plain", "cache-control": "no-store" });
    if (rel.endsWith("/")) rel += "index.html";
    const file = path.resolve(root, `.${rel}`);
    if (file !== root && !file.startsWith(root + path.sep)) return send(404, "Not Found", { "content-type": "text/plain", "cache-control": "no-store" });
    fs.stat(file, (err, st) => {
      if (err || !st.isFile()) return send(404, "Not Found", { "content-type": "text/plain", "cache-control": "no-store" });
      const cache = HASHED_ASSET.test(url.pathname) ? CACHE_IMMUTABLE : CACHE_REVALIDATE;
      res.writeHead(200, { ...headers, "content-type": TYPES[path.extname(file)] ?? "application/octet-stream", "content-length": st.size, "cache-control": cache });
      if (req.method === "HEAD") return res.end();
      fs.createReadStream(file).pipe(res);
    });
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const port = Number(process.argv[2] ?? process.env.E2E_PORT ?? 4317);
  const dist = process.argv[3] ?? process.env.E2E_DIST ?? "dist";
  if (!fs.existsSync(path.join(dist, "index.html"))) { console.error(`No ${dist}/index.html: run npm run build first.`); process.exit(1); }
  createServer(dist, port).listen(port, "127.0.0.1", () => console.log(`serving ${path.resolve(dist)} on http://127.0.0.1:${port}`));
}
