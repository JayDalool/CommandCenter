# Engineering HQ — isolated design prototype

A clickable prototype of the new CommandCenter interface, built from Jay's selected reference designs.
**It is not the production app.** It never talks to ccd, herdr, GitHub or any server; every value is
local mock data and is labelled Demo / Fictional where shown. Nothing here changes autonomy, merge,
release or deploy rules.

## Review it (one command)

```bash
git fetch origin claude/project-thread-gs2u2h && git checkout claude/project-thread-gs2u2h
cd design/ui-prototypes/engineering-hq
npm ci                # same React / Vite / Vitest versions as web/app; no new libraries
npm run review        # builds, serves on http://127.0.0.1:5181 and opens your browser
```

Use a normal browser tab so pop-outs can open real windows you can drag to another monitor.
`npm run dev` (port 5180) is the live-reload version for editing.

## Design decisions (Jay, 2026-10-22)

- **Project colours**: the concept-art palette. One source (`src/data/seed.ts`), published as
  `--pj-<key>` CSS variables; a test fails if a project colour is hard-coded anywhere else. Task IDs
  carry their project's colour everywhere.
- **Agent personas**: Claude, Iris, Nova, Atlas, Pixel and Orion stay as stable roles. Every place an
  agent appears shows its role, live status, current task ID, the model behind it, its project and
  last activity. Click any agent for the Agent Inspector (session ID, model ID, specialisation and
  earlier sessions); it pops out like any other view.
- **Truthful presence**: status from the demo feed has a hollow dot and a "demo" tag. A stale feed
  shows Unknown with the last-seen time; a paused project shows Paused. Never Working by default.
  In a live build the model comes from ccd's usage meter (`server/ccd/meter.py` records it per session).

Pages: `#/office` · `#/messages/sv-lead` · `#/decisions` (Needs My Attention) · `#/decisions/sv-025` (decision room) ·
`#/teams/samvision` · `#/topology` · `#/engineering` · `#/revenue` · `#/task/SV-025` · `#/agents` · `#/onboard` (New Agent) ·
`#/newproject` (New Project) · `#/design` (design system) · `#/approvals` (Slack approvals, D-032) · `#/budgets` (budgets, D-033) ·
`#/settings/<section>` (Settings, including demo controls: feed outage, slow loading, reset). `#/more` still works.

## Review package and docs

- `docs/RUN_LOCALLY.md`: how to run it, useful addresses, pop-outs, tests and the gallery.
- `docs/PAGE_MAP.md`: every page, state and pop-out window.
- `docs/DESIGN_TOKENS.md` and `docs/COMPONENTS.md`: the design system.
- `CHANGELOG.md`: what changed in each version. `DESIGN_CHANGES.md`: Jay's visual requests and their approval state,
  kept apart from anything that would change security, backend behaviour or autonomy.
- Integration roadmap (Claude Doc): https://claude.ai/artifact/3SUAvgfk4Dy63JiFebrkQi

## Approvals and budgets (Jay, 2026-10-23)

Both are mock previews in the same look, and both pop out. Nothing connects to Slack or ccd.
- **Approvals** (D-032): the request queue, a phone preview of the Slack message (an opaque link, never a credential),
  and the approval screen. Low and standard requests are approved on that signed-in screen; high-risk ones (repository
  access, policy, production, wider permissions) also need Developer Unlock and the exact ID typed. Each approval is bound
  to the request's hash, so a changed request needs a new approval. Approving inside Slack is a later step and is off.
- **Budgets** (D-033): company, project and agent budgets with alerts at 50/80/95%, four demo scenarios, which new work
  would start, and a temporary-override dialog that files a request on Approvals. One agent over its limit never stops its
  project; safety monitoring, rollback and recovery are never held. The rules match `server/ccd/budgets.py`, which only
  reports where a hold would apply (shadow mode).

## Look and feel (round 4: macOS-inspired refinement)

Same layouts, palette, project colours and graphs. Added on top, with no new dependencies:
- Tokens in `src/styles/hq.css` `:root`: radius (`--r-2xs` … `--r-xl`, `--r-pill`), type scale (`--fs-*`), spacing (`--sp-*`),
  elevation (`--e1` cards, `--e2` popovers, `--e3` modals), a restrained translucent `--material`, and motion (`--ease*`, `--dur-*`).
  The refinement layer is the last block of the stylesheet.
- `src/components/overlay.tsx`: context menus (right-click, the context-menu key or Shift+F10; arrow keys, Escape),
  tooltips for every `title` (styled, delayed, keyboard-aware), anchored popovers, skeletons, and the sliding thumb of every
  segmented control. Each window, including pop-outs, mounts its own layers.
- Right-click menus on tabs, sidebar items, agent cards, directory rows, conversations and project nodes.
- Reduced motion: follows the OS setting, or Jay's menu → Reduce motion (`<html data-motion="reduce">`).
- Loading states appear only when something loads. The prototype loads nothing, so “Simulate slow loading” (Jay's menu,
  Settings & more, or `?slow`) shows the skeletons on every navigation.

## Pop out any tab

- ↗ on any tab, nav item, panel header (Topology inspector, Task context, Evidence, Task detail, Agent inspector),
  conversation header or terminal pane — or right-click a tab — or **Alt+Shift+O** (Alt+Shift+R returns).
- The original tab stays in place, shaded with ↗ and "Open in another window"; its area shows
  **Focus window** / **Return here**. Only one window owns a view at a time.
- OS close button → the view returns to the main window. Reload → keeps ownership. A crashed window
  is detected through its Web Lock and the view returns. Blocked pop-up → rolled back with an explanation.
  Main window closed → pop-outs keep working and one can become the main window.

## Tests

```bash
npm test                              # 96 unit/component tests (jsdom)
npm run build && npm run preview &    # then, in another shell:
node e2e/run.mjs                      # 24 real-browser tests: pop-out windows, menus, tooltips, popovers, motion, loading,
                                      # approvals and budgets (including phone width)
node e2e/gallery.mjs http://127.0.0.1:5181/ e2e/out/gallery           # every page and state at 1920, 1366, 1280, 390 + pop-outs
node e2e/gallery-page.mjs e2e/out/gallery e2e/out/gallery/index.html --ext png   # the visual gallery page
node e2e/shots.mjs                    # older reference-comparison screenshots → e2e/out
python3 e2e/compare.py <references> e2e/out <out>   # reference-vs-prototype sheets (Pillow)
```

The browser tests load Playwright from the global npm install (or `PLAYWRIGHT_MODULE`) so the
prototype does not add it as a dependency.

See `AUDIT_AND_MIGRATION_PLAN.md` for the first audit and architecture, and the integration roadmap doc above for the
current phased plan (small PRs, approval gates). Production migration has not started.
