// Local-only, sealed Classic UI test runner. No ccd API or production credentials.
// Run from web/app: npm run test:e2e:local [-- --parity]
// First install: npm ci && npx playwright install chromium (ordinary user, developer PC).
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const app = fileURLToPath(new URL("../", import.meta.url));
const repo = path.resolve(app, "../..");
const args = process.argv.slice(2);
if (args.some(a => a !== "--parity")) {
  console.error("Usage: npm run test:e2e:local [-- --parity]");
  process.exit(2);
}
const parity = args.includes("--parity");
const steps = [];
const started = new Date().toISOString();
let tmp;
let base;
let failed = false;

function run(label, cmd, argv, cwd = app, moreEnv = {}) {
  console.log("\n=== " + label + " ===");
  const r = spawnSync(cmd, argv, {
    cwd,
    env: { ...process.env, ...moreEnv },
    stdio: "inherit",
    shell: process.platform === "win32", // npm/npx launch via .cmd on Windows
  });
  const ok = r.status === 0 && !r.error;
  steps.push({ label, ok });
  if (!ok) throw new Error(label + ": " + (r.error?.message || "exit " + r.status));
}
try {
  run("TypeScript", "npm", ["run", "typecheck"]);
  run("Unit tests", "npm", ["test"]);
  run("Build", "npm", ["run", "build"]);
  run("Sealed Chromium browser suite", "npm",
      ["run", "test:e2e", "--", "--grep-invert", "@parity"]);
  if (parity) {
    // Compare both builds on this SAME machine; do not fetch or change working branches.
    run("Verify origin/main exists locally", "git", ["rev-parse", "--verify", "origin/main"], repo);
    tmp = mkdtempSync(path.join(os.tmpdir(), "commandcenter-e2e-"));
    base = path.join(tmp, "base");
    run("Create disposable base worktree", "git",
        ["worktree", "add", "--detach", base, "origin/main"], repo);
    const baseApp = path.join(base, "web", "app");
    run("Install base dependencies", "npm", ["ci"], baseApp);
    run("Build base branch", "npm", ["run", "build"], baseApp);
    run("Capture base screenshots", "npx",
        ["playwright", "test", "--grep", "@parity", "--update-snapshots=all"],
        app, { E2E_PARITY: "1", E2E_DIST: path.join(baseApp, "dist"),
               E2E_REPORT: "playwright-report-base", E2E_OUT: "test-results-base" });
    run("Compare Classic screenshots", "npx",
        ["playwright", "test", "--grep", "@parity"],
        app, { E2E_PARITY: "1", E2E_REPORT: "playwright-report-parity",
               E2E_OUT: "test-results-parity" });
  }
} catch (err) {
  failed = true;
  console.error("\nLocal verification failed: " + err.message);
} finally {
  if (base) {
    try { run("Remove disposable base worktree", "git",
              ["worktree", "remove", "--force", base], repo); }
    catch (err) { failed = true; console.error("Cleanup: " + err.message); }
  }
  if (tmp) {
    try { rmSync(tmp, { recursive: true, force: true }); }
    catch (err) { failed = true; console.error("Temp cleanup: " + err.message); }
  }
  const dir = path.join(app, "local-e2e-results");
  mkdirSync(dir, { recursive: true });
  const report = [
    "# Local browser tests", "",
    "Started: " + started,
    "Completed: " + new Date().toISOString(),
    "Platform: " + process.platform + " / " + process.arch,
    "Node: " + process.version,
    "Mode: " + (parity ? "sealed browser + base comparison" : "sealed browser"),
    "Result: " + (failed ? "FAIL" : "PASS"), "",
    ...steps.map(s => "- " + (s.ok ? "PASS" : "FAIL") + ": " + s.label),
    "", "Runs only against fixture API data and a loopback test server.",
    "Reports: web/app/playwright-report*/ and test-results*/.", "",
  ].join("\n");
  writeFileSync(path.join(dir, "summary.md"), report);
  console.log("\n" + (failed ? "FAIL" : "PASS") + " — " + path.join(dir, "summary.md"));
  if (failed) process.exitCode = 1;
}
