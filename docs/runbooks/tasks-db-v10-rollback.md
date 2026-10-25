# Runbook: rolling back tasks.db migration v10

For Jay, or a session Jay directs on jay-server. **Every step here touches production and needs Jay's approval.**
Paths are the defaults (`ccd.service`, `scripts/go-live.sh`): checkout `/srv/server/repos/CommandCenter`,
database `~/command-center/data/tasks.db` (or `$CCD_DATA_DIR/tasks.db`), backups `~/command-center/backups/`.

## What v10 changes, and why a rollback is rarely needed

Migration v10 only **adds** four tables (`agent_registrations`, `agent_config_versions`, `onboarding_drafts`,
`onboarding_events`) with their own indexes and triggers. It changes no existing table, row, index or trigger
(the migration drill proves this on a copy). With `onboarding_groundwork` off, which is the default, ccd never writes
to those tables, so they stay empty and the v10 code behaves exactly like v9.

Two facts decide every case below:

- **A v9 ccd refuses a v10 file and changes nothing.** It logs `tasks.db is schema v10, newer than this ccd (v9);
  refusing to run` and stops. The data is safe; ccd is down until one of the fixes below.
- **The in-place rollback keeps everything.** `python -m ccd.migration_safety rollback` backs the file up, then drops
  the four tables only when they are empty, in one transaction, and commits only if the result is exactly the v9
  schema. Every ticket, comment, event, audit row and usage row written after the upgrade stays. It refuses, changing
  nothing, when any onboarding table holds a row: those rows are history and are never dropped.

## Which case are you in?

| Situation | Do this | Data lost |
|---|---|---|
| The release works; you only want onboarding off | Set `"onboarding_groundwork": false` (or remove it) in `config.json` and restart ccd. No database change | None; records stay, unused |
| You need the older ccd, and the onboarding tables are empty (always true while the flag has never been on) | **A.** In-place rollback, then switch the code back | None |
| The older ccd will not start: "schema v10, newer than this ccd" | Nothing is damaged. Fastest: switch the code forward to the v10 release again and restart. If you must stay on the older code and the tables are empty: **A** (run it from a v10 checkout) | None |
| You need the older ccd, and onboarding records exist | **B.** Roll forward instead (preferred), or **C** as the last resort | None with B; everything since the upgrade with C, unless exported |
| The upgrade itself failed or was killed part-way | Nothing to undo: the migration is one transaction, so the file is still exactly v9 (the drill's recovery checks). Restart the v10 code to retry, or switch back to the older code, which opens the v9 file | None |
| The database is damaged (integrity check fails) | **C**, from the newest good backup | Everything since that backup |

## A. In-place rollback to v9 (keeps all data)

Run the tool from the **v10 code** (the older code does not have it), before switching the checkout back.

```bash
systemctl --user stop ccd
systemctl --user is-active ccd || true            # expect "inactive"
cd /srv/server/repos/CommandCenter/server
.venv/bin/python -m ccd.migration_safety rollback --db ~/command-center/data/tasks.db --to 9 \
    --backup-dir ~/command-center/backups
# prints:  backup: ~/command-center/backups/tasks.db.pre-rollback-v10-to-v9-<stamp>
#          undone: v10; tasks.db is v9
```

Then switch the code back as `go-live.sh` printed it (`git switch --detach <previous sha>`, `pip install -r
server/requirements.txt`, `scripts/deploy-web.sh`) and start ccd:

```bash
systemctl --user start ccd
curl -fsS -H "Host: 127.0.0.1:7777" http://127.0.0.1:7777/api/health    # ccd answers
journalctl --user -u ccd -n 20 | grep -i "refusing" || echo "no refusal"
```

If the rollback is **refused**, nothing was changed (the message says why: rows in an onboarding table, a schema it
does not recognise, or a step without a downgrade). Start ccd again on the v10 code and go to **B**.

## B. Onboarding records exist: roll forward

The records exist only because the flag was turned on, which itself needed Jay's approval. Keep the v10 code (turn
the flag off if onboarding is the problem) and fix forward: revert or patch only the change that caused the trouble
and release that. Nothing is lost and no history is dropped. If an older release is truly needed, release it **with
migration v10 added to its migration list** (one entry from `server/ccd/tasks.py`); it then opens the v10 file and
simply leaves the four tables unused. Both are ordinary releases through `go-live.sh`.

## C. Restore a backup (last resort; loses work)

Restoring a backup returns tasks.db to the moment of that backup. Every ticket, comment, approval, audit row and
usage row written since then is gone from the database. Jay decides this explicitly.

1. Stop ccd and confirm it stopped (`systemctl --user stop ccd`, then `is-active` says inactive).
2. Keep what you are about to replace, so the restore itself can be undone:
   ```bash
   cd /srv/server/repos/CommandCenter/server
   .venv/bin/python -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" \
       ~/command-center/data/tasks.db ~/command-center/backups/tasks.db.before-restore-$(date -u +%Y%m%dT%H%M%SZ)
   ```
3. If onboarding records exist, export them first (read-only; keeps them outside the database with a SHA-256):
   ```bash
   .venv/bin/python -m ccd.migration_safety export-onboarding --db ~/command-center/data/tasks.db \
       --out ~/command-center/backups/onboarding-records-$(date -u +%Y%m%dT%H%M%SZ).json
   ```
4. **Never leave another file's write-ahead log next to a restored database.** After a clean stop there is no
   `tasks.db-wal`; if one is there (ccd was killed), move both side files away first, or SQLite may replay pages from
   the old file into the restored one:
   ```bash
   cd ~/command-center/data
   for f in tasks.db-wal tasks.db-shm; do [ -e "$f" ] && mv "$f" ../backups/"$f".moved-$(date -u +%Y%m%dT%H%M%SZ); done
   ```
5. Restore with SQLite's backup API (safe whatever the journal mode), then check it:
   ```bash
   cd /srv/server/repos/CommandCenter/server
   .venv/bin/python -c "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro', uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); print(d.execute('PRAGMA integrity_check').fetchone()[0], 'schema v%d' % d.execute('PRAGMA user_version').fetchone()[0]); d.close(); s.close()" \
       ~/command-center/backups/<the backup> ~/command-center/data/tasks.db
   # expect: ok schema v9   (or v10, if the backup was taken after the upgrade)
   ```
6. Make sure the code matches the restored schema (a v9 file opens in either release; a v10 file needs the v10
   code), then `systemctl --user start ccd` and check `/api/health` as in A.

`go-live.sh` prints a shorter rollback that copies the pre-deploy backup with `cp`. That is safe only after a clean
stop with no `tasks.db-wal` present; steps 4 and 5 above cover the case where ccd did not stop cleanly.

## Before the upgrade, and how this was tested

- `go-live.sh` backs tasks.db up with SQLite's backup API before it switches the code
  (`~/command-center/backups/tasks.db.pre-<branch>-<stamp>`).
- Rehearse on a copy, never on the live file: `python -m ccd.migration_safety drill --snapshot COPY.db --out DIR
  --old-ccd <older checkout>/server --redact --label "…" --clean` checks backup, upgrade, schema integrity,
  backward compatibility, this rollback, restore and crash recovery. Make COPY.db with a read-only backup:
  `python -c "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro', uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d)" tasks.db COPY.db`.
- `server/tests/test_migration_safety.py` runs the drill in CI and tests each refusal of the rollback and the
  export.
- From tasks.db v11 on, the drill rehearses the newest migration (v10 → v11); see
  [tasks-db-v11-rollback.md](tasks-db-v11-rollback.md). The v10 rollback tests still run under a patched v10 ccd.
