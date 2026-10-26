# Engineering HQ design tokens

The single source is the `:root` block at the top of `src/styles/hq.css`. Project and agent colours come from
`src/data/seed.ts` and are published as `--pj-<key>` CSS variables; a unit test fails if a project colour is
hard-coded anywhere else. The look is dark-first (navy and violet), macOS-inspired: rounded corners, circular
avatars, soft layered shadows, restrained translucency and short, eased motion that honours Reduce Motion.

## Themes

Dark is the default (confirmed by Jay, 2026-10-25). Light is an optional variant: `src/styles/theme-light.css`
redefines the same tokens under `:root[data-hq-theme="light"]`, so no component has its own light colours. Layout,
radii, type, spacing and motion are identical in both themes.

| Choice | Result |
|---|---|
| Dark (default) | `<html data-hq-theme="dark">` |
| Light | `<html data-hq-theme="light">` |
| System | Follows `prefers-color-scheme` and switches live when Windows or macOS does |

HQ uses its own attribute, `data-hq-theme`, so a theme attribute set by a host page or by Classic can never switch it.

The choice is a shared store (`hq.theme`), so every pop-out window follows it. An inline script in `index.html`
applies it before the first paint. `?theme=light|dark|system` overrides it for a review link. The terminal and
the Slack phone preview stay dark in both themes. Project, agent and status colours keep their hue in light; the
status colours are darkened so text keeps at least 4.5:1 contrast on white panels, on the page background and on
their own tinted pills (checked by `e2e/qa.mjs`).

## Colour

| Token | Dark (default) | Light | Use |
|---|---|---|---|
| `--bg` | `#070b17` | `#f2f3f8` | Page background |
| `--bg-2` | `#050812` | `#e9ebf3` | Deepest background (pop-out frame) |
| `--side` | `#060a15` | `#e9ebf3` | Sidebar |
| `--panel` | `#0b1224` | `#ffffff` | Cards and panels |
| `--panel-2` | `#0e162c` | `#fdfdff` | Raised panel, list rows |
| `--raise` | `#121b35` | `#f0f1f7` | Hover-raised surface |
| `--hover` | `#131d3a` | `#eceef7` | Hover fill |
| `--sel` | `#151f45` | `#e6e5fd` | Selected row, current step |
| `--line` | `#19233f` | `#e1e4ee` | Hairline borders |
| `--line-2` | `#243154` | `#d0d4e2` | Stronger borders, inputs |
| `--text` | `#e9edf8` | `#151a2d` | Primary text |
| `--text-2` | `#b4bdd6` | `#434a63` | Secondary text |
| `--muted` | `#7c88a6` | `#5b637c` | Captions, metadata |
| `--faint` | `#4e5a78` | `#9aa0b4` | Disabled, chart "other" |
| `--accent` | `#6d5cff` | `#5a48f5` | Primary actions, current item |
| `--accent-2` | `#3f7bff` | `#2f6bf0` | Gradient partner of the accent |
| `--accent-soft` | `rgba(109, 92, 255, .16)` | `rgba(90, 72, 245, .1)` | Selected backgrounds |
| `--focus` | `#8fa2ff` | `#5b63f0` | Focus ring |
| `--ok` | `#2fe08c` | `#0e7243` | Healthy, passed, approved |
| `--warn` | `#ffb020` | `#985800` | Warning, needs input |
| `--bad` | `#ff4f6d` | `#d2273f` | Blocked, failed, high risk |
| `--info` | `#58a6ff` | `#1c66d0` | Information |
| `--violet` | `#a77bff` | `#7040dc` | Review, design |
| `--pink` | `#ff4fa0` | `#c5246f` | UI testing |
| `--idle` | `#8a95b0` | `#5f6780` | Paused, unknown, not connected |
| `--badge` | `#dc2f4c` | `#d2273f` | Count badges (white numbers keep 4.5:1) |

### Supporting tokens

Every other colour in `hq.css` is a token too (119 of them), grouped in the `:root` block and redefined in
`theme-light.css`:

| Group | Examples | Use |
|---|---|---|
| Surfaces | `--well`, `--field`, `--tile`, `--node`, `--btn-bg`, `--chrome`, `--float`, `--bubble`, `--topbar`, `--veil` | Inputs, tiles, graph nodes, buttons, menus, chat bubbles, top bar, modal veils |
| Lines, tracks and rings | `--panel-line`, `--row-line`, `--ring`, `--node-line`, `--track`, `--sel-line`, `--accent-line` | Borders, progress tracks, step rings, selection outlines |
| Inks | `--text-strong`, `--link`, `--violet-ink*`, `--bad-ink*`, `--warn-ink*`, `--info-ink*` | Text and icon colours on tinted backgrounds |
| Washes and shadows | `--wash` (RGB triple: white in dark, navy in light), `--shade-k` (1 in dark, .32 in light) | `rgb(var(--wash) / .04)` tints; shadow strength |

Graph connections keep their project colour in both themes. In light, each line is drawn in its colour mixed
with 22% navy ink (`color-mix(in oklab, var(--c) 78%, #10142c)`), about 0.3 to 0.4 px thicker, with the glow
at 14% (V11). Each edge passes its colour to CSS as `--c`. Edge labels are text, so in light they mix the colour
with 44% navy (`color-mix(in oklab, var(--c) 56%, #10142c)`), which keeps every project colour at 4.5:1 on white (V12).

### Projects (concept-art palette, approved 2026-10-22, confirmed 2026-10-25)

| Project | Prefix | Colour |
|---|---|---|
| SamVision | SV | `#2fe0a0` |
| GYST / LifeOps | GYST | `#9d6bff` |
| MyFamilyExpenses | MFE | `#ff9f43` |
| GauzeMate | GZ | `#ff4f7b` |
| CommandCenter | CC | `#4f8bff` |

### Agent personas (approved 2026-10-22, confirmed 2026-10-25)

| Agent | Role | Colour |
|---|---|---|
| Claude | Project Lead | `#ff7a45` |
| Iris | Research / Planning Lead | `#4f7bff` |
| Nova | Implementation Agent | `#a463ff` |
| Atlas | Independent Code Reviewer | `#22c98e` |
| Pixel | UI Testing Lead | `#ff4fa0` |
| Orion | Release / DevOps Lead | `#ffb020` |

## Type

| Token | Value |
|---|---|
| `--font` | Inter, Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif |
| `--font-display` | Inter Display, Inter, Segoe UI Variable Display, Segoe UI, system-ui, sans-serif |
| `--mono` | JetBrains Mono, Cascadia Mono, Consolas, monospace |
| `--fs-xs` … `--fs-3xl` | 11.5, 12.5, 13.5, 14, 16, 18, 22, 30 px |

Fonts are local system fonts only; nothing is downloaded, so the production content security policy (`font-src 'self'`) holds.

## Shape and space

| Token | Value |
|---|---|
| `--r-2xs`, `--r-xs`, `--r-sm`, `--r-md`, `--r`, `--r-lg`, `--r-xl`, `--r-pill` | 5, 7, 9, 10, 12, 14, 18, 999 px |
| `--sp-1` … `--sp-8` | 4, 8, 12, 16, 20, 24, 32 px (4 px grid) |
| `--side-w` | 252 px sidebar (76 px icon rail at 1440 px and below) |
| `--top-h` | 64 px top bar |

## Elevation and material

| Token | Use |
|---|---|
| `--hl` | Hairline top highlight on cards |
| `--e1` | Cards and panels |
| `--e2` | Menus and popovers (also `--shadow`) |
| `--e3` | Modals and drawers |
| `--material`, `--material-line` | Translucent floating surfaces (menus, popovers, tooltips) |

## Motion

| Token | Value |
|---|---|
| `--ease` | `cubic-bezier(.2, .8, .2, 1)` |
| `--ease-out` | `cubic-bezier(.16, 1, .3, 1)` |
| `--ease-spring` | `cubic-bezier(.34, 1.36, .64, 1)` |
| `--dur-1`, `--dur-2`, `--dur-3` | 120, 180, 260 ms |

Reduce Motion (OS setting, Settings → Appearance, or Jay's menu) sets `<html data-motion="reduce">` and turns
animations off.

## Breakpoints

| Width | Change |
|---|---|
| ≤ 1500 px | Wizards move the preview under the form; Teams stacks its glance card |
| ≤ 1440 px | Sidebar becomes a 76 px icon rail (so 1366 and 1280 laptops use the rail); task cards in messages stack |
| ≤ 1400 px | Budgets in two columns; Approvals puts the Slack preview under the approval screen |
| ≤ 1200 px | Office, Engineering, Decisions and Topology stack; Messages becomes one scrolling column (list, conversation, task context); Design System in one column |
| ≤ 1100 px | Wizards in one column; Needs My Attention stacks its side panel |
| ≤ 1000 px | Settings, Budgets and Approvals stack |
| ≤ 760 px (phone) | Bottom tab bar (Office, Messages, Decisions, Approvals, More) replaces the sidebar and tab strip; More opens a sheet; Settings opens as a list; My Office KPIs are 2×2 tiles. One column everywhere; tab rows, segmented controls and wide tables scroll inside themselves; long rows and panel headers wrap; the Teams hierarchy keeps at least half size and scrolls sideways inside its frame. The page itself never scrolls sideways at 390 px |
