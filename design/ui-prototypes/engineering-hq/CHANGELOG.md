# Engineering HQ prototype changelog

Each version is a commit on the draft branch `claude/project-thread-gs2u2h` (PR #64). Every gallery and package
names the commit it was captured from. Visual requests and their approval state are tracked in `DESIGN_CHANGES.md`.

## 2026-10-26 · Overnight QA: accessibility and polish (V12, proposed)

A new QA sweep (`e2e/qa.mjs`) opened every gallery state and pop-out in Dark and Light at 1920, 1366, 1280 and 390 px
(600 checks), Tab-walked 14 pages in both themes, and checked Reduce Motion and the System theme. It found no crash,
console error, sideways scroll on a page, theme leak or motion problem. The first run reported 55 distinct findings;
after fixes, a second run with a stricter focus check reported 9, and the third none. An independent review then
found one more defect the sweep could not see, one regression in tonight's focus fix, and gaps in the sweep; all are
fixed. In total 19 defects are fixed (see V12):

- **Contrast.** Count badges, the tab-strip hint, code line numbers, Light status text (idle, green, amber, red,
  muted), topology edge labels in Light (SamVision green was 1.7:1 on white), the Teams heading accent in Light, the
  current lifecycle step and the step numbers in a task's Plan tab all reach 4.5:1 (3:1 for large text). In Dark,
  only the badge red, the tab-strip hint, the code line numbers and the Plan step numbers change.
- **Focus.** Text fields and selects lost their focus ring to the later field style (all fields in Light, text
  fields in Dark); the Topology canvas and the Messages search and message box had none. All show one now. Fields
  with an error keep their red border while focused.
- **Names.** In the 76 px rail the page links and the logo had no name once focused (the labels were hidden from
  screen readers, and the tooltip takes over `title` on focus). The labels are now hidden only visually. The
  conversation header's icon buttons had no name below 1500 px.
- **Pop-outs.** At 520 px the pop-out header pushed the window 20 px sideways and cut off Return to main window. The
  button shows only its icon in narrow windows, with its name kept for screen readers; a long title ends in "…".
- **Small things.** Timeline bars end with an ellipsis at 1366 and 1280; sparkline gradients get unique ids; the
  CommandCenter node's name no longer runs under its sparkline; truncated titles in Needs Your Attention and the
  conversation header show the full text on hover.
- **The sweep itself.** It measures any CSS colour, including `color-mix` results, reports a colour it cannot
  measure instead of skipping it, applies 4.5:1 exactly, reads focus rings with transitions settled, and records a
  pass that fails instead of stopping.

Tests: 103 unit tests, 27 browser checks, and a QA sweep with no findings (600 page checks, 28 keyboard walks).

## 2026-10-25 · Visual sign-off and clearer light-mode graph lines

Jay approved V7 to V10 (light theme, phone tab bar and More sheet, 1920×1080 layouts, spacing and readability
fixes) and named the prototype at `4b72f3f` the approved visual reference. `DESIGN_CHANGES.md` records it. This is
visual sign-off only, not Gate 0.

**Light-mode graph connections (V11, proposed).** At Jay's optional request, lines in the Operations Topology, the
My Office preview and the Teams hierarchy are a little deeper in Light (each project colour mixed with 22% navy
ink) and about 0.3 to 0.4 px thicker; the glow stays faint. Dark mode is pixel-for-pixel unchanged.

## 2026-10-25 · Final design refinements (4b72f3f)

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
