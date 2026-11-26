# Weekly Docker build-cache prune (CC-096)

`scripts/cc-prune-build-cache` runs exactly `docker builder prune -f` once a week and logs one line:
`<iso time> freed <size>` (or `stopped`, `busy`, `docker exit N`, `docker timeout`, `docker error`). It takes no
arguments and never prints docker's own output. It deletes only Docker's unused build cache, which rebuilds itself:
the next build of any app is slower. Images, volumes, containers and `/srv/server/backups` are outside it.

CC-089's `cc-cleanup` replaces this script and cron line when it lands (D-058); that ticket swaps the line and
deletes the script, so only one delete path remains.

## The cron line

Sunday 04:30 server time, after the 04:00 SamVision backup. Exactly this one line:

```
30 4 * * 0 /usr/bin/python3 -I /srv/server/repos/CommandCenter/scripts/cc-prune-build-cache >> /home/jay/command-center/state/build-cache-prune.log 2>&1
```

## Install (Jay, or the CTO after Jay's yes of 2026-11-25; never a PR or an agent on its own)

The job runs the live checkout, so whatever file sits at that path on Sunday runs. Install only when this prints
nothing, at a HEAD that contains the merged commit:

```
git -C /srv/server/repos/CommandCenter status --porcelain -- scripts/cc-prune-build-cache
```

Then `crontab -e`, paste the line above, and save. `crontab -l` must show it byte for byte.

## Pause, remove, check

- Pause (also pauses CC-089's cleanup): `touch ~/command-center/state/cleanup.stop`. Delete the file to resume.
- Remove: delete the line with `crontab -e`.
- Log: `~/command-center/state/build-cache-prune.log`. After the first Sunday it should read `freed <size>`, not `unknown`.
