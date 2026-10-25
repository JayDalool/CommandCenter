# Engineering HQ design changes

Jay approved the overall direction on 2026-10-25 (macOS-inspired style, Operations Topology, agent hierarchy,
onboarding, multi-monitor). The design is not frozen: this log tracks each requested or proposed change.

**How a request is handled**

- **Visual** (layout, colour, type, spacing, wording, motion, icons, new mock states or screens): the prototype is
  updated on draft PR #64, the affected screenshots are retaken, and the gallery, hosted prototype and ZIP are
  republished. It stays *Proposed* until Jay approves it.
- **Behaviour** (security, backend, autonomy, permissions, data sources, anything that would change what production
  does): nothing changes silently. It is written up as a proposal and marked *Needs a decision*. It moves only
  with Jay's separate approval.

Approved visual changes are carried into the matching integration PR (see the roadmap), so production matches
the last approved prototype.

## Visual changes

| # | Date | Change | Pages | Asked by | State |
|---|---|---|---|---|---|
| V1 | 2026-10-22 | Concept-art project colours | All | Jay | Approved 2026-10-22 |
| V2 | 2026-10-22 | Agent personas with role, status, task, model and project everywhere | All | Jay | Approved 2026-10-22 |
| V3 | 2026-10-22 | macOS-inspired refinement layer | All | Jay | Approved 2026-10-25 (overall direction) |
| V4 | 2026-10-25 | Needs My Attention queue at `#/decisions`; decision room at `#/decisions/sv-025`; My Office KPI renamed "Needs You" | Decisions, My Office, Topology, sidebar | Claude (audit) | **Proposed** |
| V5 | 2026-10-25 | Full Settings page in the macOS System Settings layout | Settings | Claude (Jay listed Settings) | **Proposed** |
| V6 | 2026-10-25 | Phone layout fixes: wrapping rows, scrolling tab rows, stacked queue rows; Messages as one scrolling column; Teams hierarchy at half size, scrolling sideways | All at 390 px (Messages below 1200 px) | Claude (audit) | **Proposed** |

## Open design questions

| # | Question | Since | Options |
|---|---|---|---|
| Q1 | Light theme for HQ? Today's app has dark, light and system | 2026-10-25 | Design an HQ light theme, or keep HQ dark-only with Classic for light |
| Q2 | Phone navigation | 2026-10-25 | Keep the icon rail, or a bottom tab bar (about 20% more width) |

## Behaviour requests (need a separate decision)

None open. Items such as Slack, billing, live data, agent activation and policy changes are tracked in the
integration roadmap's gates, not here.
