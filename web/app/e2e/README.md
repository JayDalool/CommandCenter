# Browser tests

The web app, in Classic and in the HQ preview, in a real browser (Chromium, through `@playwright/test` 1.56.1),
sealed off from everything real:

- **The build, served like ccd serves it.** `serve.mjs` serves `dist/` with ccd's exact Content-Security-Policy,
  security headers and cache rules (`server/ccd/api.py`, `UiFiles`). `tests/e2e-serve.test.ts` fails if the two
  drift, and `serve.spec.ts` checks the server itself.
- **No ccd and no network.** Every `/api` request is answered from `tests/fixture.json`, the data the unit tests
  already use (`fixture.ts`). The live-events socket is stubbed with the server's greeting. The token is a dummy of
  the right shape. All of this is set on the browser context, so pop-outs and popups get it too. A request to
  another host is aborted and fails the test, and so does a window the page opens itself.
  One gap: Playwright cannot route a Web Worker's own WebSockets. ccd's CSP (`connect-src`) still limits them to the
  test server, and Classic's only workers are Monaco's, from its own `/assets/`; a worker from anywhere else fails.
- **The same every time.** The clock is fixed at the fixture's moment, the time zone is UTC, motion is reduced,
  animations and the text caret are off for screenshots, service workers are blocked.

## What is checked

| Spec | Checks |
| --- | --- |
| `load.spec.ts` | Every screen, every Settings tab, a task detail and both pop-outs (`routes.ts`, `SHOWS`; `SHOWS_HQ` for HQ's names), in Dark and Light, in Classic and in the HQ preview: the screen it names (the router would quietly show the Dashboard for a broken route), no console error or warning, no uncaught exception, no CSP violation, no request off the test server, no API call without a fixture answer, no write, the token only in its header (never in a URL), no window or worker it should not open, live events live. `data-ui="hq"` only in the HQ preview, and its label only there, once, in the rail (none in pop-outs). |
| `parity.spec.ts` | Every route but the two aliases (`routes.ts`, `PARITY`), in Dark and Light, looks as it does on the base branch: the whole page, then again with every scrolling panel at its end. Every Classic design token (CSS custom property) has exactly the base branch's value. In the HQ preview (`<html data-ui="hq">`), Classic's tokens must keep their values and the two pop-outs (no HQ frame) must match Classic's pixels; a framed screen has HQ's own sidebar, top bar and tabs, so it is not compared with Classic (`tests/routes-both-modes.test.tsx` checks the screen inside is Classic's, unchanged). What the branch adds on purpose (`routes.ts`, `ADDED`) is hidden first; the rest must match. |
| `ui-switch.spec.ts` | The Classic/HQ switch: Settings › General › Interface, the rail's Back to Classic (focus stays in the rail), a reload, `?ui=hq` and `?ui=classic` links (taken out of the address after), an unknown `?ui=` value from either mode, another open window following the switch, and a pop-out keeping the mode with no label. Where the label sits, at 1366 and 1100 px wide, icons-only and a short window: between the screens and the rail's foot, inside the rail, covering no control; hidden when the window is too short for it. |
| `hq-tokens.spec.ts` | HQ's tokens (`src/hq/tokens.css`) resolve only under `data-ui="hq"`, and follow Classic's Dark, Light and System theme, including Dark while the computer is in light mode. |
| `serve.spec.ts` | The test server answers like ccd: headers, caching, a plain 404 for a missing file, a 400 for a NUL byte, GET and HEAD only (Guard's 405 otherwise). |

## Running it

Once per machine: `npx playwright install chromium` (about 320 MB for the headless shell). Then:

```sh
npm run build
npm run test:e2e          # load + serve; parity is skipped without a base build
```

**Parity** compares this build with another build, normally the base branch's, on the same machine. Screenshots are
never committed: fonts differ between machines, so both sides must be taken by the same machine and browser.

`npm run test:e2e:local -- --parity` (below) does all of this. By hand:

```sh
base=$(mktemp -d)/base   # outside the repository
git worktree add --detach "$base" origin/main && (cd "$base/web/app" && npm ci && npm run build)
E2E_PARITY=1 E2E_DIST="$base/web/app/dist" npx playwright test --grep @parity --update-snapshots=all   # base
E2E_PARITY=1 npx playwright test --grep @parity                                                        # this build
```

A difference fails with expected, actual and diff images in `test-results/`; `npx playwright show-report` shows
them side by side.

**How exact it is.** Screenshots allow each pixel a tiny colour difference (`threshold` in `playwright.config.ts`)
and skip pixels Chromium anti-aliases: without that, two runs of the same build differ at the edges of shadows and
rounded corners. That tolerance hides a uniform change of about one colour step, so the design tokens are compared
as text, exactly. A change to a single colour written straight into a rule, by a step or two, can still pass.

**Both sides run this branch's harness.** The base build is screenshotted with this branch's `e2e/`,
`playwright.config.ts` and `tests/fixture.json`, so a branch that changes those changes the judge as well as the
code: review them first (`git diff origin/main -- web/app/e2e web/app/playwright.config.ts web/app/tests/fixture.json`).
The harness must also work against the base build: a wait for something only this branch renders would time the
base side out.

**What a branch adds on purpose.** A branch that adds to a Classic screen lists the new elements in `routes.ts`
(`ADDED`, CSS selectors by route). Parity hides exactly those on this build, checks each is there, and compares the
rest with the base branch as usual, so the page around the addition is still held to every pixel. An entry hides
what it matches from the comparison: review `ADDED` with the rest of the harness, and keep it to new elements.

## Where it runs

`.github/workflows/web-e2e.yml` runs the suite on GitHub's hosted `ubuntu-24.04` machines (a fresh VM per job,
read-only token, no secrets) for pull requests to `main` and pushes to `main` that touch `web/app/**`,
`server/ccd/api.py` or the workflow. On a pull request it also runs parity against the base branch. A pull request
labelled `classic-ui-change` is meant to change how Classic looks: parity still runs and uploads its differences,
but they do not fail the check.

It never runs on a self-hosted runner. The local runner below runs the same browser checks on your own machine,
plus TypeScript and the unit tests.

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

### Not on a self-hosted runner

A GitHub Actions self-hosted runner on a personal laptop can execute arbitrary checked-out
PR code with the runner user's file access. Do not move this browser job onto a self-hosted
runner. Moving it anywhere other than GitHub's hosted machines needs a separate security
review and Jay's approval.
