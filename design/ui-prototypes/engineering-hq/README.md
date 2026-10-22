# Engineering HQ — isolated design prototype

A clickable prototype of the new CommandCenter interface, built from Jay's selected reference designs.
**It is not the production app.** It never talks to ccd, herdr, GitHub or any server; every value is
local mock data and is labelled Demo / Fictional where shown. Nothing here changes autonomy, merge,
release or deploy rules.

## Run it

```bash
cd design/ui-prototypes/engineering-hq
npm ci                # same React / Vite / Vitest versions as web/app; no new libraries
npm run dev           # http://127.0.0.1:5180  (loopback only)
# or: npm run build && npm run preview   → http://127.0.0.1:5181
```

Pages: `#/office` · `#/messages/sv-lead` · `#/decisions` · `#/teams/samvision` · `#/topology` ·
`#/engineering` · `#/revenue` · `#/task/SV-025` · `#/more` (demo controls: feed outage, reset).

## Pop out any tab

- ↗ on any tab, nav item, panel header (Topology inspector, Task context, Evidence, Task detail),
  conversation header or terminal pane — or right-click a tab — or **Alt+Shift+O** (Alt+Shift+R returns).
- The original tab stays in place, shaded with ↗ and "Open in another window"; its area shows
  **Focus window** / **Return here**. Only one window owns a view at a time.
- OS close button → the view returns to the main window. Reload → keeps ownership. A crashed window
  is detected through its Web Lock and the view returns. Blocked pop-up → rolled back with an explanation.
  Main window closed → pop-outs keep working and one can become the main window.

## Tests

```bash
npm test                              # 22 unit/component tests (jsdom)
npm run build && npm run preview &    # then, in another shell:
node e2e/run.mjs                      # 12 real-browser tests with real pop-out windows
node e2e/shots.mjs                    # screenshots at 1920×1080, 1366×768 and pop-out sizes → e2e/out
```

The browser tests load Playwright from the global npm install (or `PLAYWRIGHT_MODULE`) so the
prototype does not add it as a dependency.

See `AUDIT_AND_MIGRATION_PLAN.md` for the audit, the architecture and the gated migration plan.
