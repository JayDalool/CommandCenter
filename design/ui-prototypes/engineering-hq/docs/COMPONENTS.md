# Engineering HQ components

React 19 + TypeScript, no UI library. Every component reads colours, radii, shadows and motion from the tokens in
`docs/DESIGN_TOKENS.md`. The live specimens are on the Design System page (`#/design`).

## Building blocks — `src/components/ui.tsx`

| Component | Props | Notes |
|---|---|---|
| `Avatar` | `id`, `size`, `ring` | Circular, agent or Jay; colour and glyph from the persona |
| `AvatarStack` | `ids`, `size` | Overlapping circles for teams |
| `ProjIcon` | `k`, `size`, `icon` | Rounded square tile in the project colour |
| `TaskKey` | `k` | Mono task ID with its project's colour dot |
| `PresenceDot` | `s`, `label`, `detail` | Working, Reviewing, Waiting, Idle, Paused, Unknown. Hollow when from the demo feed |
| `Pill` | `tone`, `dot` | Tones: ok, warn, bad, info, violet, idle |
| `StagePill` | `s` | Pipeline stage with its tone |
| `Prio` | `p` | High, Medium, Low |
| `Spark` | `data`, `color`, `w`, `h`, `area` | Tiny line chart for KPI tiles |
| `Panel` | `title`, `icon`, `iconTone`, `sub`, `action` | Card with header, icon tile and actions |
| `ViewAll` | `label`, `onClick`, `href` | Quiet link with arrow |
| `Demo` | `label` | Dashed amber "Demo data" tag on anything mock |
| `ProdBanner` | `compact` | "Production untouched · No live changes" |

## Forms — `src/components/form.tsx`

| Component | Notes |
|---|---|
| `Field` | Label, hint, error and optional marker around any input |
| `Seg` | Segmented control (radio group) with a sliding thumb |
| `Chips` | Multi-select chips; locked chips show why |
| `GrantPick`, `GrantBadge` | Allow / Ask / Deny permission picker, capped by a ceiling |
| `Modal` | Centred dialog with focus trap, Escape and a footer |
| `Money` | Currency input |

## Overlays — `src/components/overlay.tsx`

| Component | Notes |
|---|---|
| `openMenu`, `useContextMenu`, `MenuLayer` | Context menus by right-click, the menu key or Shift+F10; arrow keys and Escape |
| `TipLayer` | Styled, delayed tooltips for every `title`, keyboard-aware |
| `Popover` | Anchored popover (bell, Jay's menu) |
| `Skel`, `PageSkeleton`, `useSimulatedLoad` | Loading skeletons, shown only while something loads |
| `useSegThumbs` | Sliding thumb for every segmented control |

## Agents — `src/components/agent.tsx`, `src/components/manage.tsx`

| Component | Notes |
|---|---|
| `useAgentView`, `statusOf` | Honest status: Unknown on a stale feed, Paused on a paused project, never Working by default |
| `AgentStatus`, `AgentMeta`, `AgentDot`, `AgentRow` | Status, current task, model, project and last activity |
| `AgentDrawer`, `AgentInspector` | Full details; pops out as `panel:agent` |
| `ManageSection` | Edit, change model, pause or resume, reassign, offboard |
| `PermissionsReview` | Effective permission = grant ∩ project rules ∩ machine ∩ task mode |
| `WorkHistory` | Earlier sessions and tasks, kept after offboarding |

## Graphs — `src/components/GraphFrame.tsx`

`GraphFrame` draws the Office topology preview and the Teams hierarchy: positioned HTML nodes over an SVG of
curved, animated edges, scaled to fit its box. With `fitWidth` (Teams) it scales to the width only, takes the scaled
height and, below `minScale`, scrolls sideways inside its frame, opening on the centre. The full Operations Topology (`src/pages/Topology.tsx` with `src/data/graph.ts`)
has its own pan, zoom, fit and full-screen canvas, with typed edges so the picture never implies a dependency that
is not there. No graph library.

## Windows — `src/windows/`

| Piece | Notes |
|---|---|
| `views.ts` | Stable view ids (`page:`, `dm:`, `task:`, `term:`, `panel:`) and their titles |
| `manager.ts` | One owner per view, Web Lock liveness, pop out, focus, return, notices |
| `Detachable`, `PopButton`, `DetachedPlaceholder` | Wraps any view so it can move to another window; the original shows Focus window and Return here |

## Shell — `src/components/Shell.tsx`

Sidebar with badges and pop-out buttons, top bar (search, production status, bell, Jay's menu), tab strip with
right-click menu, search palette, toasts.

## Pages — `src/pages/`

`Office`, `Messages`, `Decisions` (queue and decision room), `Teams`, `Agents`, `Topology`, `Engineering`, `TaskRoom`,
`Revenue`, `Approvals`, `Budgets`, `Settings`, `DesignSystem`, `More`, and the wizards in `onboarding/`
(`NewAgent`, `NewProject`, shared `Wizard`).

## Data — `src/data/` (mock only)

| Module | Holds |
|---|---|
| `seed.ts` | Projects, agents, tasks, conversations, the SV-025 decision |
| `org.ts` | The organisation store the wizards write to (browser only) |
| `live.ts` | Demo feed, chat and per-view shared state |
| `governance.ts` | D-032 approvals and D-033 budgets, mirroring `server/ccd/budgets.py` |
| `needs.ts` | The one list behind Needs My Attention and every "needs you" count |
| `graph.ts` | The Operations Topology model: filters and expanded groups in, positioned nodes and typed edges out |
| `catalog.ts`, `validate.ts` | Templates, permissions and the wizards' validation rules |
| `runner.ts` | Runs the demo feed in exactly one window, so pop-outs keep updating when the main window closes |
