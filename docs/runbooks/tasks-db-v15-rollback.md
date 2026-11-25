# Runbook: rolling back tasks.db migration v15

For Jay, or a session Jay directs on jay-server. **Every step here touches production and needs Jay's approval.**
Paths and the general procedure are the same as [tasks-db-v10-rollback.md](tasks-db-v10-rollback.md); read that
first. This page lists only what is different for v15.

## What v15 changes

Migration v15 (the weekly budget, CC-064 part a, Jay 2026-11-23) only **adds** one table, with its index and two triggers:

- `budget_changes`: an append-only record of every save of the weekly budget (and, in a later part, of a temporary
  release): who (`actor`), through what (`via`: `hq` or `cto`), the Jay message that allowed it (`jay_message_id`, for the
  CTO path), when, the kind (`settings` or `release`) and the body as JSON. The newest row of a kind wins. The triggers
  `budget_changes_append_only_u` and `_d` refuse any update or delete.

It changes no existing table, row, index or trigger (the migration drill proves this on a copy). A v15 ccd with an empty
`budget_changes` behaves like v14: no budget means no weekly lines and no alerts.

## Which case are you in?

| Situation | Do this | Data lost |
|---|---|---|
| You need the v14 ccd, and no budget was ever saved (the table is empty) | **A** of the v10 runbook with `--to 14` | None |
| The v14 ccd will not start: "schema v15, newer than this ccd" | Nothing is damaged. Switch the code forward to v15 again, or run **A** from the v15 checkout if the table is empty | None |
| You need the v14 ccd, and a budget was saved | Roll forward (preferred), or release the older code **with migration 15 added to its list**; it then leaves the table unused and there is no weekly budget until v15 returns | None; the saved budgets stay in the table, unused |
| The database is damaged | **C** of the v10 runbook, from the newest good backup | Everything since that backup |

The in-place rollback refuses, changing nothing, while `budget_changes` holds a row: those rows are Jay's budget history
and cannot be deleted (the triggers see to that, which is why the table is only ever dropped whole).

Jay can also just stop using the budget: alerts need a saved row, so without a new save nothing more is posted. Posted
alerts stay in Messages (`chat.db`, unaffected by this migration); their once-per-week memory is in ccd.db's `kv`
keys `budget:alerts:*`, which an older ccd ignores.

## How this was tested

- `python -m ccd.migration_safety drill` rehearses v14 to v15 on a copy: backup, upgrade, that only migration 15's table,
  index and triggers are added, that a v14 ccd refuses the v15 file, this rollback, restore and crash recovery.
- `server/tests/test_migration_safety.py` (`DowngradeV15`) tests the rollback and its refusal, and
  `server/tests/test_budget_week.py` (`Migration`) tests that no update or delete path exists.
