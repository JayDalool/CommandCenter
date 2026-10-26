# Run the Engineering HQ prototype locally

The prototype is a standalone Vite app. It talks to no server: no ccd, herdr, GitHub, Slack or billing. Everything
is mock data held in the browser.

## What you need

- Node.js 22 or newer and npm (the same versions `web/app` uses).
- Git access to `jaydalool/commandcenter`.

## Start it

```bash
git fetch origin claude/project-thread-gs2u2h
git checkout claude/project-thread-gs2u2h
cd design/ui-prototypes/engineering-hq
npm ci
npm run review
```

`npm run review` type-checks, builds and serves the prototype at **http://127.0.0.1:5181** and opens your browser.
It listens on 127.0.0.1 only.

For editing with live reload use `npm run dev` (http://127.0.0.1:5180).

From the ZIP package instead of git: open `prototype/dist/index.html` through any static server, for example
`npx vite preview --outDir prototype/dist --port 5181`, or run `npm ci && npm run review` inside `prototype/source`.
Opening `index.html` straight from the file system does not work, because browsers block module scripts on `file://`.

## Useful addresses

| Address | What it does |
|---|---|
| `http://127.0.0.1:5181/#/office` | My Office (the start page) |
| `#/decisions` | Needs My Attention |
| `#/topology` | Operations Topology |
| `#/settings/general` | Settings |
| `?nofeed` | Freezes the demo feed, so nothing moves while you look |
| `?slow` | Shows the loading skeletons on every navigation |
| `?theme=light` | Opens in the optional light theme (`dark` is the default; `system` follows the OS) |
| `#/settings/appearance` | Dark, Light or System |

`docs/PAGE_MAP.md` lists every page, state and pop-out address.

## Multi-monitor and pop-outs

Use a normal browser tab (not a preview pane or an embedded viewer). Pop-outs open real windows you can drag to
another monitor. If the browser blocks the first pop-up, allow pop-ups for 127.0.0.1 and try again; the prototype
rolls the view back and tells you when a window was blocked.

The hosted preview on claude.ai runs inside a locked frame, so pop-out windows there are usually blocked. Everything
else works the same.

## Phone layout

Narrow the window below 760 px (or use the browser's device toolbar at 390 × 844): the sidebar becomes a bottom tab
bar with a More sheet. Widen it again and the sidebar comes back.

## Reset the demo

Settings → Demo controls → Reset demo data, or clear the site data for 127.0.0.1:5181. The wizards and approvals write
only to this browser's storage.

## Tests

```bash
npm test                                # 103 unit and component tests (jsdom)
npm run build && npm run preview &      # then, in another shell:
node e2e/run.mjs                        # 27 real-browser checks (pop-outs, menus, approvals, budgets, theme, phone layout)
```

The browser checks load Playwright from the global npm install, or from `PLAYWRIGHT_MODULE`, so the prototype does
not depend on it.

## QA sweep

```bash
npm run build && npm run preview &
node e2e/qa.mjs                                   # every gallery state and pop-out, Dark and Light, 4 sizes (600 checks)
node e2e/qa.mjs http://127.0.0.1:5181/ e2e/out/qa.json office,decisions   # only these states
QA_THEMES=light QA_VP=1366 node e2e/qa.mjs        # narrow the run
node e2e/qa-shot.mjs topology light 1366 ".edge-tag" /tmp/shot.png   # look closer at one finding
```

For each state the sweep checks, in a real browser: page and console errors, sideways scroll, text cut off with no
ellipsis, text that runs out of its box, WCAG AA contrast (4.5:1, or 3:1 for large text, for any CSS colour including
`color-mix`; text over a gradient or image is skipped), a dark slab in Light or a
light slab in Dark, controls with no accessible name, duplicate ids and positive tabindex. It then Tab-walks 14 pages
in both themes (every stop must be on screen and show a focus ring), checks that nothing keeps animating under
Reduce Motion, and checks that System follows the OS live. It exits 1 when anything is found and writes a JSON report.
Ellipsis truncation at 1920 is listed for review, not counted as a failure. The states come from `e2e/states.mjs`,
shared with the gallery capture.

## Rebuild the screenshot gallery

```bash
npm run build && npm run preview &
node e2e/gallery.mjs http://127.0.0.1:5181/ e2e/out/gallery          # every page and state at 1920, 1366, 1280, 390 + pop-outs
node e2e/gallery.mjs http://127.0.0.1:5181/ e2e/out/gallery decisions,settings   # retake only these states
node e2e/gallery-page.mjs e2e/out/gallery e2e/out/gallery/index.html --ext png    # build the gallery page
```

The capture fails a state that does not load and warns when any page scrolls sideways.
