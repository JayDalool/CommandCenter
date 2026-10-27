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

## Test execution in the current draft PR

The hosted `web-e2e` workflow was removed from draft PR #72 because GitHub-hosted jobs could not start.
Use the sealed **local WSL test runner** documented below and attach `local-e2e-results/summary.md`
and any Playwright failure report to the PR. The existing GitHub `ci.yml` workflow remains unchanged.

Do not register the unverified laptop runner for browser jobs automatically. A dedicated, isolated
`browser-ci` self-hosted runner and a workflow require a separate security/isolation approval.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `E2E_PORT` | `4317` | Port for `serve.mjs` on 127.0.0.1 |
| `E2E_DIST` | `dist` | The build to serve |
| `E2E_PARITY` | unset | `1` runs `parity.spec.ts` |
| `E2E_REPORT`, `E2E_OUT` | `playwright-report`, `test-results` | Where reports and failure output go |


## Windows + WSL2 (local development; not the GitHub Actions runner)

Use an ordinary, non-root Ubuntu/WSL2 shell. Keep this checkout in WSL's Linux filesystem
(e.g. under `~/`, **not** `/mnt/c/`). No Docker, ccd API, real token, or live database is needed.

Check the dependencies first:

```bash
wsl --status   # Windows PowerShell, NOT inside WSL
```

```bash
node --version # from WSL: needs Node 22
npm --version
git --version
```

Run this inside the PR's **review checkout** (or an isolated worktree):

```bash
cd ~/CommandCenter-e2e/web/app
npm ci
npx playwright install chromium
npm run test:e2e:local
```

The command runs TypeScript, unit tests, a production build, then Chromium load/security tests
against sealed mock API fixtures. It saves `local-e2e-results/summary.md` and any failures in
`playwright-report*/` and `test-results*/`, all ignored by git. No Chromium display is required.

For pixel-level Classic parity, compare the current branch against the locally fetched
`origin/main` on the *same WSL machine*:

```bash
git fetch origin main
npm run test:e2e:local -- --parity
```

Parity temporarily checks out `origin/main` in a disposable worktree outside your repo, installs
dependencies and builds there, captures its screenshots, then compares. No branch is switched and
your working tree is not modified. Run only on trusted, reviewed PR code on your personal machine.

If Linux Chromium complains about missing shared libraries, first inspect the error and only
then, with Jay's approval on this development WSL distribution, run
`sudo npx playwright install-deps chromium` (this uses apt). Never make a self-hosted GitHub
runner automatically run `sudo` or install system packages. Ensure browser binaries are
installed once by the WSL user; do not run the tests as root.

### Future WSL self-hosted Actions job (NOT configured here)

A GitHub Actions self-hosted runner on a personal laptop can execute arbitrary checked-out
PR code with the runner user's file access. Existing D-030 runner isolation is **not** verified.
Do not automatically move this browser job onto the existing self-hosted runner. For later CI:
isolate a separate runner with a dedicated `browser-ci` label and Unix user/WSL VM,
no employer/client code, sensitive home files, SSH keys, production backups or credentials,
read-only checkout, only reviewed branches; verify the isolation first and get separate
approval before modifying a workflow. Until then, attach the local test summary and failure
screenshots to the draft PR. GitHub's normal `ci` workflow stays unchanged.
