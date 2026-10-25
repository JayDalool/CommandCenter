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

`docs/PAGE_MAP.md` lists every page, state and pop-out address.

## Multi-monitor and pop-outs

Use a normal browser tab (not a preview pane or an embedded viewer). Pop-outs open real windows you can drag to
another monitor. If the browser blocks the first pop-up, allow pop-ups for 127.0.0.1 and try again; the prototype
rolls the view back and tells you when a window was blocked.

The hosted preview on claude.ai runs inside a locked frame, so pop-out windows there are usually blocked. Everything
else works the same.

## Reset the demo

Settings → Demo controls → Reset demo data, or clear the site data for 127.0.0.1:5181. The wizards and approvals write
only to this browser's storage.

## Tests

```bash
npm test                                # 96 unit and component tests (jsdom)
npm run build && npm run preview &      # then, in another shell:
node e2e/run.mjs                        # 24 real-browser checks (pop-outs, menus, approvals, budgets, phone width)
```

The browser checks load Playwright from the global npm install, or from `PLAYWRIGHT_MODULE`, so the prototype does
not depend on it.

## Rebuild the screenshot gallery

```bash
npm run build && npm run preview &
node e2e/gallery.mjs http://127.0.0.1:5181/ e2e/out/gallery          # every page and state at 1920, 1366, 1280, 390 + pop-outs
node e2e/gallery.mjs http://127.0.0.1:5181/ e2e/out/gallery decisions,settings   # retake only these states
node e2e/gallery-page.mjs e2e/out/gallery e2e/out/gallery/index.html --ext png    # build the gallery page
```

The capture fails a state that does not load and warns when any page scrolls sideways.
