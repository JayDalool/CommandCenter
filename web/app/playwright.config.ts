// Browser tests for Classic (e2e/). They run against a production build served with ccd's headers (e2e/serve.mjs)
// and fixture data, never a live ccd. See e2e/README.md.
import { defineConfig } from "@playwright/test";
import { env } from "./e2e/env";

const PORT = Number(env.E2E_PORT ?? 4317);
const DIST = env.E2E_DIST ?? "dist";
const CI = !!env.CI;

export default defineConfig({
  testDir: "e2e",
  // Parity screenshots are taken of the base build in the same job, then compared with this build. They are never
  // committed: the same runner, fonts and browser take both sides, so a difference is a change in the code.
  snapshotPathTemplate: "{testDir}/.parity/{arg}{ext}",
  outputDir: env.E2E_OUT ?? "test-results",
  fullyParallel: true,
  forbidOnly: CI,
  retries: 0,
  workers: CI ? 2 : undefined,
  reporter: [[CI ? "github" : "list"], ["html", { open: "never", outputFolder: env.E2E_REPORT ?? "playwright-report" }]],
  expect: {
    // Every pixel must match. The per-pixel threshold only absorbs Chromium's rasterising noise: a colour one step
    // off at the edge of a shadow or rounded corner, seen between two runs of the same build. Moving Classic's
    // background two steps (#0a0f18 to #0c1119) already fails on more than half the screen.
    toHaveScreenshot: { maxDiffPixels: 0, threshold: 0.006, animations: "disabled", caret: "hide", scale: "css" },
  },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    browserName: "chromium",
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1,
    locale: "en-US",
    timezoneId: "UTC",
    contextOptions: { reducedMotion: "reduce" },
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `node e2e/serve.mjs ${PORT} ${DIST}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
