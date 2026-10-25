# Runbook: rolling back tasks.db migration v11

For Jay, or a session Jay directs on jay-server. **Every step here touches production and needs Jay's approval.**
Paths and the general procedure are the same as [tasks-db-v10-rollback.md](tasks-db-v10-rollback.md); read that
first. This page lists only what is different for v11.

## What v11 changes

Migration v11 (Phase 2 shadow step 1, Jay 2026-10-25) only **adds** two tables with their own indexes and triggers:

- `identity_tokens`: typed identity tokens (`cca_a_…` for agents, `cca_s_…` for services), optionally bound to one
  project. Rows appear only when Jay issues a token with Developer Unlock, but from v11 on **every** new token goes
  here whatever the flag says, so the first token Jay issues ends the "tables empty" case below. Tokens issued before v11 stay in
  `actor_tokens` and keep working.
- `identity_observations`: one row per recorded write saying who it proves to be and why Phase 2 would refuse it.
  Rows appear only when `config.json` sets `"phase2_identity_shadow": true` (default false).

It changes no existing table, row, index or trigger (the migration drill proves this on a copy). Nothing in v11
refuses a request, with or without the flag: `enforced` is always 0 and the database refuses anything else.

## Which case are you in?

| Situation | Do this | Data lost |
|---|---|---|
| The release works; you only want the shadow record off | Set `"phase2_identity_shadow": false` (or remove it) and restart ccd. No database change | None; rows stay, unused |
| You need the v10 ccd, and both tables are empty (true while no typed token was issued and the flag was never on) | **A** of the v10 runbook with `--to 10` | None |
| The v10 ccd will not start: "schema v11, newer than this ccd" | Nothing is damaged. Switch the code forward to v11 again, or run **A** from the v11 checkout if both tables are empty | None |
| You need the v10 ccd, and typed tokens or observations exist | Roll forward (preferred): keep v11, fix the faulty change, release. Or release the older code **with migration 11 added to its list**; it then leaves both tables unused, and typed tokens stop verifying (the audit records those writes as unverified; nothing is refused either way) | None |
| The database is damaged | **C** of the v10 runbook, from the newest good backup | Everything since that backup |

## A. In-place rollback to v10

From the **v11 code**, with ccd stopped:

```bash
systemctl --user stop ccd
cd /srv/server/repos/CommandCenter/server
.venv/bin/python -m ccd.migration_safety rollback --db ~/command-center/data/tasks.db --to 10 \
    --backup-dir ~/command-center/backups
# prints:  backup: ~/command-center/backups/tasks.db.pre-rollback-v11-to-v10-<stamp>
#          undone: v11; tasks.db is v10
```

It refuses, changing nothing, when either table holds a row (`identity_tokens (1 row)` and so on). Those rows are
history and are never dropped. Typed tokens issued after the upgrade stop working after a restore (**C**); re-issue
them on the restored release if needed. Observations are shadow records only; the pre-restore copy keeps them.

## How this was tested

- `python -m ccd.migration_safety drill` now rehearses v10 → v11 on a copy (an older snapshot is lifted to v10 on
  the copy first). It checks backup, upgrade, that only migration 11's tables are added, that a v10 ccd refuses the
  v11 file, this rollback, restore and crash recovery.
- `server/tests/test_migration_safety.py` (`DowngradeV11`) tests the rollback, that it keeps the pre-v11 token, and
  that it refuses when a typed token or an observation exists.
