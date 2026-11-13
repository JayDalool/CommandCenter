// Loads Playwright WITHOUT adding it to this package: from PLAYWRIGHT_MODULE, else the global npm root.
// (Adding @playwright/test as a dependency is a separate decision for Jay.)
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import path from "node:path";

export function loadPlaywright() {
  const req = createRequire(import.meta.url);
  const tries = [process.env.PLAYWRIGHT_MODULE, path.join(execSync("npm root -g").toString().trim(), "playwright")].filter(Boolean);
  for (const t of tries) { try { return req(t); } catch { /* next */ } }
  throw new Error("Playwright not found. Install it globally (npm i -g playwright) or set PLAYWRIGHT_MODULE.");
}
