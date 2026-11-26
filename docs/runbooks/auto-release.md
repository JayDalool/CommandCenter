# Automatic release: the dry run (CC-081, slice 1)

`server/ccd/autorelease.py` records what each weekly release window would ship for GYST and Command Center, and why
anything would be held. It never deploys, restarts, approves, rolls back or changes a gate. Releases stay Jay's Go
Live press. Design and later slices: [ADR 0010](../adr/0010-automatic-release.md).

## Switch it on (Jay)

1. Release email (CC-078) must be on and the project marked live (Settings). Without a delivered digest every window
   records "no manifest emailed".
2. In `~/command-center/board/config.json` set `"auto_release": "dry_run"`. Only that exact string turns it on;
   `"on"`, `true` or a typo reads as off, and ccd logs a warning.
3. Restart ccd (`systemctl --user restart ccd`). It reads the value at start.

To switch off: set `"off"` (or remove the key) and restart.

## Stop at once

    touch ~/command-center/state/auto-release.stop      # nothing more is written, from the next tick (60 s)
    rm ~/command-center/state/auto-release.stop         # resume

## Drill before relying on it (c7)

During a release window with the dry run on, restart ccd (`systemctl --user restart ccd`), wait two minutes, then
read the ledger (below). There must be exactly one `decision` row for that window, and each manifest ticket's
timeline shows one `release.dry_run` "would …" entry. The CC-078 tests cover moving the window and a failed send;
the CC-081 tests (`server/tests/test_auto_release.py`, class `Dedup`) cover the same for the dry run.

## Read what it recorded

- `GET /api/release` → `autoRelease.projects.<project>`: `wouldRelease` (the newest decision), `outcome` (what
  actually happened after the window) and `held`.
- Each manifest ticket's timeline: `release.dry_run` entries by `system:auto-release`, "would release in …", "would
  hold: …", then "released by <actor>: pass|fail" or "not released".
- The raw ledger: `sqlite3 ~/command-center/state/ccd.db "SELECT value FROM kv WHERE key='auto_release:commandcenter'"`.

Rows are `pin` (the main sha when the digest went out), `decision` (at the window) and `outcome` (two hours after it
opens). They hold ticket keys, short shas, fixed reasons and times only.

## What each blocker means

| blocker | meaning | what clears it |
|---|---|---|
| no manifest emailed | no delivered digest for this release (none, failed, or may not have been sent) | Release email working before the next window |
| nothing scheduled | the digest listed nothing | nothing to do |
| health checks not configured / rollback not configured | the project's policy profile `capabilities` are false | slice 2, then Jay sets them in `policy/projects/<project>.toml` |
| no rehearsal recorded / last rehearsal failed | no passing row in `~/command-center/deploys/<project>/rehearsals.jsonl` | slice 2's release drill |
| last release failed: held until Jay clears it | a failed or inconclusive line in `releases.jsonl` (CC-063), or a ticket's live deploy recorded fail, newer than the last pass | Jay, below |
| cannot tell live | `web/current` does not name a clean build (`<stamp>-<sha>`; a `-dirty` build counts) | the next clean Go Live |
| no sha pinned at digest time | ccd was down, or git could not read `origin/main`, between the digest and the window | the next release |
| cannot read range | `git log live..pinned` failed or timed out (5 s) | check the checkout |
| unlisted change `<sha>/<key>` or `<sha>/no key` | a commit on main between live and the pinned sha is not on the manifest (or names no ticket) | the release would carry unlisted code: hold it, or send a correction |

Item reasons (one ticket): pulled from the release, ticket not found, not merged and verifying, no live deploy
requested, already deployed, urgent deploy has no window, verification has not passed, waits for a later window.

Expect "not eligible" for both projects until slice 2: capabilities are false and no rehearsal exists.

## Clear a failed-release hold (Jay)

Look at the failure first (`~/command-center/deploys/<project>/releases.jsonl`, the ticket's deploy record). Then:

    cd /srv/server/repos/CommandCenter/server && python -m ccd.autorelease clear-hold commandcenter

Failures up to now no longer hold the project; a later one holds it again. Deleting or editing the log does not
clear a hold. A log line that cannot be read counts as a failure at the time it is read, so fix or remove it before
clearing. Nothing is rolled back automatically: rollback stays Jay's, per the project's own runbook.
