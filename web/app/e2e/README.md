# Browser tests

Classic in a real browser (Chromium, through `@playwright/test` 1.56.1), sealed off from everything real:

- **The build, served like ccd serves it.** `serve.mjs` serves `dist/` with ccd's exact Content-Security-Policy,
  security headers and cache rules (`server/ccd/api.py`, `UiFiles`). `tests/e2e-serve.test.ts` fails if the two
  drift, and `serve.spec.ts` checks the server itself.
- **No ccd and no network.** Every `/api` request is answered from `tests/fixture.json`, the data the unit tests
  already use (`fixture.ts`). The live-events socket is stubbed with the server's greeting. The token is a dummy of
  the right shape. Any request to another host is aborted, and fails the test.
- **The same every time.** The clock is fixed at the fixture's moment, the time zone is UTC, motion is reduced,
  animations and the text caret are off for screenshots, service workers are blocked.

## What is checked

| Spec | Checks |
| --- | --- |
| `load.spec.ts` | Every screen, every Settings tab, a task detail and both pop-outs (`routes.ts`, `LOAD`), in Dark and Light: no console error or warning, no uncaught exception, no CSP violation, no request off the test server, no API call without a fixture answer, no write, the token only in its header (never in a URL), and live events connected. |
| `parity.spec.ts` | 17 screens (`routes.ts`, `PARITY`) in Dark and Light look exactly as they do on the base branch. |
| `serve.spec.ts` | The test server answers like ccd: headers, caching, a plain 404 for a missing file, GET and HEAD only. |

## Running it

Once per machine: `npx playwright install chromium` (about 320 MB for the headless shell). Then:

```sh
npm run build
npm run test:e2e          # load + serve; parity is skipped without a base build
```

**Parity** compares this build with another build, normally the base branch's, on the same machine. Screenshots are
never committed: fonts differ between machines, so both sides must be taken by the same machine and browser.

```sh
git worktree add --detach ../base origin/main && (cd ../base/web/app && npm ci && npm run build)
E2E_PARITY=1 E2E_DIST=../base/web/app/dist npx playwright test --grep @parity --update-snapshots=all   # base
E2E_PARITY=1 npx playwright test --grep @parity                                                         # this build
```

A difference fails with expected, actual and diff images in `test-results/`; `npx playwright show-report` shows
them side by side.

## In CI

`.github/workflows/web-e2e.yml` runs on a GitHub-hosted `ubuntu-24.04` runner, read-only and with no secrets, for
pull requests and pushes to `main` that touch `web/app/` (or ccd's UI headers). The self-hosted runner is not used.
On a pull request it builds the base branch in the same job, screenshots it, then compares this build with it.

**A pull request that means to change how Classic looks** gets the label `classic-ui-change`. The comparison still
runs and uploads its images (artifact `playwright-report`) for review, but its differences no longer fail the check.
Without the label, any visible change to Classic fails the check.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `E2E_PORT` | `4317` | Port for `serve.mjs` on 127.0.0.1 |
| `E2E_DIST` | `dist` | The build to serve |
| `E2E_PARITY` | unset | `1` runs `parity.spec.ts` |
| `E2E_REPORT`, `E2E_OUT` | `playwright-report`, `test-results` | Where reports and failure output go |
