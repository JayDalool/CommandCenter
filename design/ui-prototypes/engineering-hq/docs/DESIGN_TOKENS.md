# Engineering HQ design tokens

The single source is the `:root` block at the top of `src/styles/hq.css`. Project and agent colours come from
`src/data/seed.ts` and are published as `--pj-<key>` CSS variables; a unit test fails if a project colour is
hard-coded anywhere else. The look is dark-first (navy and violet), macOS-inspired: rounded corners, circular
avatars, soft layered shadows, restrained translucency and short, eased motion that honours Reduce Motion.

## Colour

| Token | Value | Use |
|---|---|---|
| `--bg` | `#070b17` | Page background |
| `--bg-2` | `#050812` | Deepest background (pop-out frame) |
| `--side` | `#060a15` | Sidebar |
| `--panel` | `#0b1224` | Cards and panels |
| `--panel-2` | `#0e162c` | Raised panel, list rows |
| `--raise` | `#121b35` | Hover-raised surface |
| `--hover` | `#131d3a` | Hover fill |
| `--sel` | `#151f45` | Selected row, current step |
| `--line` | `#19233f` | Hairline borders |
| `--line-2` | `#243154` | Stronger borders, inputs |
| `--text` | `#e9edf8` | Primary text |
| `--text-2` | `#b4bdd6` | Secondary text |
| `--muted` | `#7c88a6` | Captions, metadata |
| `--faint` | `#4e5a78` | Disabled, chart "other" |
| `--accent` | `#6d5cff` | Primary actions, current item |
| `--accent-2` | `#3f7bff` | Gradient partner of the accent |
| `--accent-soft` | `rgba(109, 92, 255, .16)` | Selected backgrounds |
| `--focus` | `#8fa2ff` | Focus ring |
| `--ok` | `#2fe08c` | Healthy, passed, approved |
| `--warn` | `#ffb020` | Warning, needs input |
| `--bad` | `#ff4f6d` | Blocked, failed, high risk |
| `--info` | `#58a6ff` | Information |
| `--violet` | `#a77bff` | Review, design |
| `--pink` | `#ff4fa0` | UI testing |
| `--idle` | `#8a95b0` | Paused, unknown, not connected |

### Projects (concept-art palette, Jay 2026-10-22)

| Project | Prefix | Colour |
|---|---|---|
| SamVision | SV | `#2fe0a0` |
| GYST / LifeOps | GYST | `#9d6bff` |
| MyFamilyExpenses | MFE | `#ff9f43` |
| GauzeMate | GZ | `#ff4f7b` |
| CommandCenter | CC | `#4f8bff` |

### Agent personas

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
| ≤ 760 px (phone) | One column everywhere; tab rows, segmented controls and wide tables scroll inside themselves; long rows and panel headers wrap; the Teams hierarchy keeps at least half size and scrolls sideways inside its frame. The page itself never scrolls sideways at 390 px |
