# Runbook: go-live release watch and automatic rollback (CC-063)

`scripts/go-live.sh` starts `server/ccd/release_watch.py` (a copy, as the systemd user unit
`cc-release-watch-<stamp>`) after it restarts ccd. The watch lives in `~/command-center/deploys/commandcenter/`:

    .go-live.lock          flock held by go-live.sh, then by the watcher until its verdict is final
    watch/active.json      {unit, until}: the running watch (a second go-live refuses while it is active)
    watch/<stamp>/         plan.json, release_watch.py (the copy), watch.log, result.json, wheels/, db-backup/
    releases.jsonl         one line per watch: {at, from, to, checks, restarts, result, step, notified, attempts}

Policy flags `health_checks` and `auto_rollback` stay false until a rehearsal (D-004); this build is not wired to them.

## What it checks (every 15 s, 60 s grace + 5 min)
API `/api/health`; daemon (unit active, schema version = the new code's, `/api/state` after grace, herdr not ok only
if it was ok before and its socket is up); UI (`GET /` is the new index.html and every `/assets/*` answers 200).
Two bad samples in a row fail a check. A crash (systemd NRestarts above the baseline taken after go-live's restart, or
the unit failed/inactive twice) fails at once. A manual restart re-baselines. A 401/403 is a probe error, never a failure.

## Rollback steps
Preconditions first (nothing changes, ccd keeps running): previous UI dir with index.html, previous commit present,
tracked files clean, HEAD and `web/current` as recorded, new tables empty, wheels present if pins differ.
Then: stop ccd, downgrade tasks.db from the new checkout (`ccd.migration_safety rollback`), `git switch --detach` the
previous commit, `pip --no-index` from wheels downloaded by go-live.sh (only if pins differ), switch `web/current`
under `.deploy.lock`, start ccd, verify 60 s + 2 min. Never fetch, build, npm or deploy-web.sh; never a third release.

## Failure table (result `rollback_failed`, ccd always left started)
| step | what happened | state left | what you do |
|---|---|---|---|
| downgrade | new tables hold rows (Q182: no automatic restore) or the downgrade errored | new release running | decide: fix forward, or restore `tasks.db.pre-main-<stamp>` from ~/command-center/backups with ccd stopped, then `git switch --detach <from>` and `scripts/deploy-web.sh` by hand |
| checkout | git switch failed (e.g. an untracked file in the way) | new code, DB downgraded (re-migrates on start) | remove the file, rerun the steps by hand |
| pip | old pins would not install | previous code running, or, if it did not answer in 60 s, the new release again | check the venv |
| link | `web/current` switch failed (deploy-web.sh running) | previous code, new UI | `ln -sfn` by hand |
| verify | the previous release failed its own checks | back on the new release | investigate both |
| moved / precondition / lock / error | HEAD or current changed, dirty checkout, lock held, unexpected error | nothing further switched | read watch.log |
`no_previous`: nothing to go back to; nothing changed.

## go-live.sh exit codes
0 healthy, 3 rolled back, 4 rollback failed, 5 no previous release, 6 still watching (`scripts/go-live.sh --result`),
7 not watched. Anything but 0: do not record the ticket deployed with pass. Never roll back by hand while a watch is
active. Every go-live.sh run (also `--dry-run`) prints `WATCHER DIED` and `UNNOTIFIED` watches.

## Reading releases.jsonl
`tail -n 5 ~/command-center/deploys/commandcenter/releases.jsonl`. `notified: false` means Jay was not told in Messages;
the text is in `watch/<stamp>/result.json` (`message`).

## Limits
Messages only reaches Jay while ccd runs; otherwise the non-zero exit in the pane and the next go-live's notices (the
launcher tray only while the laptop runs it). Not rolled back: ~/.claude skill links and the settings hook, the
launcher exe. The first go-live that ships this runs the old script, so watching starts with the next one.
