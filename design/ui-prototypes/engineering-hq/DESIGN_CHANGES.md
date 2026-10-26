# Engineering HQ design changes

Jay approved the overall direction on 2026-10-25 (macOS-inspired style, Operations Topology, agent hierarchy,
onboarding, multi-monitor), and on 2026-10-25 signed off V7 to V10 and named the prototype at commit `4b72f3f` the
**approved visual reference**. Integration builds to that reference. Visual sign-off is not Gate 0: integration starts
only with Jay's separate approval. The design is not frozen: this log tracks each requested or proposed change.

**How a request is handled**

- **Visual** (layout, colour, type, spacing, wording, motion, icons, new mock states or screens): the prototype is
  updated on draft PR #64, the affected screenshots are retaken, and the gallery, hosted prototype and ZIP are
  republished. It stays *Proposed* until Jay approves it.
- **Behaviour** (security, backend, autonomy, permissions, data sources, anything that would change what production
  does): nothing changes silently. It is written up as a proposal and marked *Needs a decision*. It moves only
  with Jay's separate approval.

Approved visual changes are carried into the matching integration PR (see the roadmap), so production matches
the last approved prototype.

## Confirmed design decisions

Jay confirmed these on 2026-10-25. They are settled: integration builds them as shown and does not ask again.

| Decision | What it means |
|---|---|
| Dark is the default theme | Dark navy and purple is what every user sees first. Light is an optional variant (V7). |
| Project colours | SamVision green, GYST violet, MyFamilyExpenses orange, GauzeMate rose, CommandCenter blue, from the project records. |
| Agent persona names | Claude, Iris, Nova, Atlas, Pixel and Orion, with their roles, avatars and colours. |
| Needs My Attention queue | One queue for decisions, questions, reviews and approvals at `#/decisions` (V4). |
| Full macOS-style Settings | One Settings window with a sidebar and 11 sections (V5). |
| Kept as approved | Design system, Operations Topology, both onboarding wizards, agent hierarchy, detachable multi-monitor windows. |

## Visual changes

| # | Date | Change | Pages | Asked by | State |
|---|---|---|---|---|---|
| V1 | 2026-10-22 | Concept-art project colours | All | Jay | Approved 2026-10-22, confirmed 2026-10-25 |
| V2 | 2026-10-22 | Agent personas with role, status, task, model and project everywhere | All | Jay | Approved 2026-10-22, confirmed 2026-10-25 |
| V3 | 2026-10-22 | macOS-inspired refinement layer | All | Jay | Approved 2026-10-25 (overall direction) |
| V4 | 2026-10-25 | Needs My Attention queue at `#/decisions`; decision room at `#/decisions/sv-025`; My Office KPI renamed "Needs You" | Decisions, My Office, Topology, sidebar | Claude (audit) | Approved 2026-10-25 |
| V5 | 2026-10-25 | Full Settings page in the macOS System Settings layout | Settings | Claude (Jay listed Settings) | Approved 2026-10-25 |
| V6 | 2026-10-25 | Phone layout fixes: wrapping rows, scrolling tab rows, stacked queue rows; Messages as one scrolling column; Teams hierarchy at half size, scrolling sideways | All at 390 px (Messages below 1200 px) | Claude (audit) | Approved 2026-10-25 as part of the approved visual reference (under the V8 tab bar) |
| V7 | 2026-10-25 | Optional macOS-inspired light theme, plus System (follows Windows or macOS). Dark stays the default. Picker in Settings › Appearance and in Jay's menu; every open window follows | All | Jay | Approved 2026-10-25 |
| V8 | 2026-10-25 | Phone navigation: bottom tab bar (Office, Messages, Decisions, Approvals, More) with a More sheet; Settings opens as a list with a back link; My Office KPIs as 2×2 tiles. Desktop keeps the sidebar | All at 760 px and below | Jay | Approved 2026-10-25 |
| V9 | 2026-10-25 | Vertical balance at 1920×1080: My Office columns end level, topology centred, three latest updates, agent strip on screen; Settings as one full-height window | My Office, Settings | Jay | Approved 2026-10-25 |
| V10 | 2026-10-25 | Review fixes: decision stage labels no longer touch, Messages search keeps its height and icons, directory status wraps between parts | Decisions, Messages, Agents | Claude (audit) | Approved 2026-10-25 |
| V11 | 2026-10-25 | Light theme only: graph connections slightly deeper (own colour with 22% navy ink) and about 0.3 to 0.4 px thicker, glow unchanged at 14%. Dark is unchanged | Topology, My Office preview, Teams hierarchy (light) | Jay (optional) | **Proposed** |
| V12 | 2026-10-26 | Accessibility fixes from the overnight QA sweep, no layout change. Text that fell below WCAG AA now passes in both themes: count badges use a deeper red in Dark (`#ff4f6d` → `#dc2f4c`; status and project colours unchanged); in Light, muted, idle, green, amber and red text are a shade deeper, topology edge labels mix their project colour with navy, the Teams heading accent follows the theme, and the current lifecycle step number is white; in both themes the tab-strip hint and code line numbers use the muted grey and the step numbers in a task's Plan tab the secondary grey. Visible focus rings return to text fields and selects, the Topology canvas and the Messages search and message box; fields with an error stay red while focused. Rail-mode page links and the logo keep their names for screen readers. The pop-out header fits 520 px panel windows (its button shows only its icon). Timeline bars end with an ellipsis | All (mostly Light) | Claude (overnight QA) | **Proposed** |

## Open design questions

None open. Q1 (light theme) became V7: dark stays the default and light is optional. Q2 (phone navigation)
became V8: a bottom tab bar.

## Behaviour requests (need a separate decision)

None open. Items such as Slack, billing, live data, agent activation and policy changes are tracked in the
integration roadmap's gates, not here.
