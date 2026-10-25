# Runbook: rolling back tasks.db migration v13

For Jay, or a session Jay directs on jay-server. **Every step here touches production and needs Jay's approval.**
Paths and the general procedure are the same as [tasks-db-v10-rollback.md](tasks-db-v10-rollback.md); read that
first. This page lists only what is different for v13.

## What v13 changes

Migration v13 (Phase 2 shadow step 3, Jay 2026-10-25) only **adds** one table with its own index and triggers:

- `broker_observations`: one row per action that exercises authority (a merge, a Go Live approval, a deploy request
  or record, input typed into a Claude pane, a repository write from the Workspace, a worktree removal), with the
  Capability Broker's eight checks and whether Phase 2 would refuse it. Rows appear only while `config.json` sets
  `"phase2_broker_shadow": true` (default false).

It changes no existing table, row, index or trigger (the migration drill proves this on a copy), and nothing in v13
refuses or changes an action: `enforced` is always 0.

## Which case are you in?

| Situation | Do this | Data lost |
|---|---|---|
| The release works; you only want the shadow record off | Set `"phase2_broker_shadow": false` (or remove it) and restart ccd. No database change | None; rows stay, unused |
| You need the v12 ccd, and the table is empty (true while the flag was never on) | **A** of the v10 runbook with `--to 12` | None |
| The v12 ccd will not start: "schema v13, newer than this ccd" | Nothing is damaged. Switch the code forward to v13 again, or run **A** from the v13 checkout if the table is empty | None |
| You need the v12 ccd, and rows exist | Roll forward (preferred), or release the older code **with migration 13 added to its list**; it then leaves the table unused | None |
| The database is damaged | **C** of the v10 runbook, from the newest good backup | Everything since that backup |

The in-place rollback refuses, changing nothing, while `broker_observations` holds a row: those rows are history.

## How this was tested

- `python -m ccd.migration_safety drill` rehearses v12 → v13 on a copy: backup, upgrade, that only migration 13's
  table is added, that a v12 ccd refuses the v13 file, this rollback, restore and crash recovery.
- `server/tests/test_migration_safety.py` (`DowngradeV13`) tests the rollback and its refusal.
