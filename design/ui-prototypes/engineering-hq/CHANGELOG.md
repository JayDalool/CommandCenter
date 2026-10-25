# Engineering HQ prototype changelog

Each version is a commit on the draft branch `claude/project-thread-gs2u2h` (PR #64). Every gallery and package
names the commit it was captured from. Visual requests and their approval state are tracked in `DESIGN_CHANGES.md`.

## 2026-10-25 · Final design refinements

Jay's confirmed decisions are recorded in `DESIGN_CHANGES.md`: dark default, project colours, agent persona names,
Needs My Attention and the full Settings window. Everything else approved (design system, Operations Topology,
onboarding, agent hierarchy, detachable windows) is unchanged.

**Optional light theme (V7).** A macOS-inspired light variant built from the same tokens: every colour in `hq.css`
is now a token (119 new ones for surfaces, lines, inks and washes), and `src/styles/theme-light.css` redefines them
under `:root[data-hq-theme="light"]`. Project, status and graph colours keep their meaning. The terminal and the Slack
phone preview stay dark, as they are on a Mac. Choose Dark (default), Light or System in Settings › Appearance or
in Jay's menu; System follows Windows or macOS and switches when it does. The choice is shared, so every pop-out
window changes with it, and a small script in `index.html` applies it before the first paint (no dark flash).
`?theme=light|dark|system` opens the prototype in a theme for review.

**Phone navigation (V8).** At 760 px and below the sidebar gives way to a bottom tab bar: Office, Messages,
Decisions, Approvals (with their badges) and More. More opens a sheet with every other page, grouped like a phone
settings list (Company, Create, then Settings, Help and the design system). The logo sits in the top bar. Settings
opens as a list, and each section opens on its own screen with a back link. My Office's four KPIs become compact
2×2 tiles. The desktop sidebar and tab strip are unchanged.

**Vertical space at 1920×1080 (V9).** My Office: both columns now end on the same line, the topology preview is
centred in its panel, Recent Updates shows the three latest, and the Active Agents strip fits on the first screen
without scrolling. Settings is one full-height window with its sidebar on the left and the section centred, like
macOS System Settings. No cards were added.

**Review fixes (V10).** The decision room's stage labels no longer run together at 1440 px; the Messages search keeps
its height and icons; the agent directory's status wraps between parts, not inside "Waiting for Jay"; icons never
shrink in tight rows. Frosted surfaces (tab bar, menus, popovers, notices, command palette) blur what is behind
them again in the built app: the minifier had kept only the `-webkit-` form, which Chrome and Edge ignore.

**Review tooling.** The gallery adds a Light theme group, the phone tab bar, the More sheet and the phone Settings
list. New browser checks cover the theme across windows and the phone layout.

Tests: 103 unit tests, 27 browser checks. No page scrolls sideways at 1920, 1366, 1280 or 390 px, in either theme.

## 2026-10-25 · Complete prototype for review (95a6624)

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

**Full-screen Topology.** The full-screen graph showed an empty page, because the page sat in a zero-height row once the
top bar was hidden. It now fills the window, and a browser check fails if the graph is not visible.

**Agent Inspector.** Edit, Change model, Change machines, Chat and Task Room now close the inspector drawer, so it no
longer covers the page they open.

**Review tooling.** `e2e/gallery.mjs` captures every page and state at four sizes plus pop-out windows and fails
on sideways scrolling; `e2e/gallery-page.mjs` builds the visual gallery. New docs: `docs/PAGE_MAP.md`,
`docs/DESIGN_TOKENS.md`, `docs/COMPONENTS.md`, `docs/RUN_LOCALLY.md`.

Tests: 96 unit tests, 25 browser checks.

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
