# Runbook: rolling back tasks.db migration v14

For Jay, or a session Jay directs on jay-server. **Every step here touches production and needs Jay's approval.**
Paths and the general procedure are the same as [tasks-db-v10-rollback.md](tasks-db-v10-rollback.md); read that
first. This page lists only what is different for v14.

## What v14 changes

Migration v14 (the delivery flow, Jay 2026-11-14) only **adds** one table:

- `ticket_flow`: one row per ticket that has been sized (intake or `criteria`) or reviewed under the nine-stage flow:
  its size, requirements, acceptance criteria, the technical reviewer's plan review, the user check, the lead's closing
  note, send-back rounds per review stage, when its plan entered technical review, and when ccd last marked it stale.

It changes no existing table, row, index or trigger (the migration drill proves this on a copy). Tickets nobody has
sized keep today's steps, so a v14 ccd with an empty `ticket_flow` behaves like v13 for every ticket.

## Which case are you in?

| Situation | Do this | Data lost |
|---|---|---|
| You need the v13 ccd, and no ticket has been sized yet (the table is empty) | **A** of the v10 runbook with `--to 13` | None |
| The v13 ccd will not start: "schema v14, newer than this ccd" | Nothing is damaged. Switch the code forward to v14 again, or run **A** from the v14 checkout if the table is empty | None |
| You need the v13 ccd, and tickets were sized | Roll forward (preferred), or release the older code **with migration 14 added to its list**; it then leaves the table unused and those tickets go back to today's steps | None; sizes and criteria stay in the table, unused |
| The database is damaged | **C** of the v10 runbook, from the newest good backup | Everything since that backup |

The in-place rollback refuses, changing nothing, while `ticket_flow` holds a row: those rows are Jay's criteria and
review records.

## How this was tested

- `python -m ccd.migration_safety drill` rehearses v13 → v14 on a copy: backup, upgrade, that only migration 14's
  table is added, that a v13 ccd refuses the v14 file, this rollback, restore and crash recovery.
- `server/tests/test_migration_safety.py` (`DowngradeV14`) tests the rollback and its refusal.
