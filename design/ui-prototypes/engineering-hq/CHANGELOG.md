# Engineering HQ prototype changelog

Each version is a commit on the draft branch `claude/project-thread-gs2u2h` (PR #64). Every gallery and package
names the commit it was captured from. Visual requests and their approval state are tracked in `DESIGN_CHANGES.md`.

## 2026-10-25 · Complete prototype for review

**Every control does something.** An automated click-through clicked all 1,303 visible controls on 29 routes,
each in a fresh browser. What it found, and the fixes:
- Task detail tabs (Details, Plan, Checks, Activity) and the Evidence tabs (Logs, Screenshots, UI Findings, Files)
  now each show their own content. Before, only the highlight moved.
- Engineering's Environment and Assignee filters now filter, with Reset filters when nothing matches.
- Workbench checkboxes select rows and open a selection bar (Copy keys, Clear; bulk changes stay disabled).
- Review Plan, Attach, New Message and the design-system sample buttons now work.
- The Topology inspector hides its close button when there is nothing to go back to.
- The Slack preview's Open in CommandCenter highlights the approval screen.

**New design, for Jay's review:**
- **Needs My Attention** at `#/decisions`: decisions, questions, reviews and approvals in one queue, with kind
  filters and a "how your answers travel" panel. The decision room moved to `#/decisions/sv-025`, so Back works.
  The sidebar badge, the bell, My Office's KPI (now "Needs You") and the Topology summary all count this one list.
- **Settings** at `#/settings/<section>`: a macOS System Settings layout with 11 sections (General, Appearance,
  Notifications, Windows & monitors, Security, Connections, Operating profiles, Workers, Demo controls, Other
  destinations, Help & shortcuts). `#/more` still works.

**Phone width.** Ten pages scrolled sideways or cut content at 390 px. All 31 routes now fit at 1920, 1366, 1280
and 390 px; tab rows and segmented controls scroll inside themselves, and queue rows stack. A second pass from the
phone screenshots fixed cramped layouts the scroll check could not see: Messages had squeezed its conversation list
and thread to a few pixels (it is now one scrolling column), Engineering's Release Gate and Model Usage sat side by
side, the task detail's Answer Questions button covered its text, the wizards' footer stacked four buttons, permission
pickers were cut off, and the Teams hierarchy shrank to a quarter size over an empty band (it now keeps half size and
scrolls sideways inside its frame, opening on the Project Lead).

**Agent Inspector.** Edit, Change model, Change machines, Chat and Task Room now close the inspector drawer, so it no
longer covers the page they open.

**Review tooling.** `e2e/gallery.mjs` captures every page and state at four sizes plus pop-out windows and fails
on sideways scrolling; `e2e/gallery-page.mjs` builds the visual gallery. New docs: `docs/PAGE_MAP.md`,
`docs/DESIGN_TOKENS.md`, `docs/COMPONENTS.md`, `docs/RUN_LOCALLY.md`.

Tests: 96 unit tests, 24 browser checks.

## 2026-10-24 · D-024 defaults (5862c09)

Budgets show Jay's approved defaults: alert levels, the checkpoint-only overrun, the per-step cap, who approves
large steps and the burn-rate breaker. Teams shows the Claude Project Lead per project; paused GauzeMate has none.

## 2026-10-23 · Approvals and budgets (fe215b8)

Approvals (D-032): request queue, approval screen with three risk tiers, Developer Unlock and typed ID for high
risk, hash binding, Slack phone preview. Budgets (D-033): company, project and agent budgets with alerts, four
scenarios and an override request. All mock.

## 2026-10-22 · macOS-inspired refinement (80eb6e4)

Tokens for radius, type, spacing, elevation, material and motion. Context menus, tooltips, popovers, skeletons,
sliding segmented thumbs, Reduce Motion.

## 2026-10-22 · Onboarding (74c4988)

Guided New Agent (10 steps) and New Project (9 steps) wizards, writing only to the browser's mock store.

## 2026-10-22 · Agent identity and project colours (e16b2ce)

Concept-art project palette from one source; stable agent personas with role, live status, task, model,
project and last activity; Agent Inspector; honest presence (Unknown when stale, never Working by default).

## 2026-10-22 · First prototype (77da8f4)

Isolated interactive prototype: My Office, Messages, Decisions, Teams, Operations Topology, Engineering,
Revenue, Task Room, and pop-out of any tab to another window.
