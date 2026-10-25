# Runbook: rolling back tasks.db migration v12

For Jay, or a session Jay directs on jay-server. **Every step here touches production and needs Jay's approval.**
Paths and the general procedure are the same as [tasks-db-v10-rollback.md](tasks-db-v10-rollback.md); read that
first. This page lists only what is different for v12.

## What v12 changes

Migration v12 (Phase 2 shadow step 2, Jay 2026-10-25) only **adds** three tables with their own indexes and triggers:

- `node_keys`: a worker node's Ed25519 public key, sent at enrolment. Rows appear only while `config.json` sets
  `"phase2_node_shadow": true` (default false). Revoking a node also revokes its key; approving a node does
  **not** approve its key (no screen shows the fingerprint yet).
- `node_observations`: one row per enrolment and heartbeat with the reasons Phase 2 would refuse it. Only with the
  flag on.
- `node_nonces`: nonces of verified signatures, kept 10 minutes to see a replay. Only with the flag on.

It changes no existing table, row, index or trigger (the migration drill proves this on a copy), and nothing in v12
refuses a request: `enforced` is always 0. The release also adds one pinned runtime dependency, `cryptography`;
`go-live.sh` installs it with `pip install -r server/requirements.txt`.

## Which case are you in?

| Situation | Do this | Data lost |
|---|---|---|
| The release works; you only want the shadow check off | Set `"phase2_node_shadow": false` (or remove it) and restart ccd. No database change | None; rows stay, unused |
| You need the v11 ccd, and all three tables are empty (true while the flag was never on) | **A** of the v10 runbook with `--to 11` | None |
| The v11 ccd will not start: "schema v12, newer than this ccd" | Nothing is damaged. Switch the code forward to v12 again, or run **A** from the v12 checkout if the tables are empty | None |
| You need the v11 ccd, and rows exist | Roll forward (preferred), or release the older code **with migration 12 added to its list**; it then leaves the tables unused | None |
| The database is damaged | **C** of the v10 runbook, from the newest good backup | Everything since that backup |

The in-place rollback refuses, changing nothing, while any of the three tables holds a row. `node_nonces` holds
only replay-check nonces, no history: if it is the only table with rows, clearing it with ccd stopped
(`sqlite3 tasks.db "DELETE FROM node_nonces"`, after the backup) is safe and lets **A** run.

## How this was tested

- `python -m ccd.migration_safety drill` rehearses v11 → v12 on a copy: backup, upgrade, that only migration 12's
  tables are added, that a v11 ccd refuses the v12 file, this rollback, restore and crash recovery.
- `server/tests/test_migration_safety.py` (`DowngradeV12`) tests the rollback and its refusal for each table.
