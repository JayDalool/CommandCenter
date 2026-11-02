# Manitoba permanent UTC−05 — timezone audit (2026-11-01)

Audit run 2026-11-01 evening to 2026-11-02 ~01:00 Winnipeg time, on jay-server, by Claude Code.
Source of the rule: IANA tzdata 2026e (Manitoba keeps −05 after 2026-10-31); latest release at audit time is
2026f (2026-10-27, https://www.iana.org/time-zones). Manitoba notice: https://www.gov.mb.ca/timechange/.

## A. Executive summary

| | |
|---|---|
| Repository | CommandCenter (`JayDalool/CommandCenter`) |
| Base | `main` at `fcf2210` |
| Branch | `claude/manitoba-tz-2026` (worktree `/srv/server/repos/CommandCenter-tz`) |
| Commits | `bb94a60` tests + check script + architecture note; the next commit adds this report |
| Result | **PASS — no code change needed in CommandCenter.** Regression tests and a check script added, awaiting review. |

**Production elsewhere on jay-server is affected now.** The running containers of **gyst-lifeops**,
**samvision-web** and **myfamilyexpenses-app** have tzdata **2026c** (and MFE's Node has ICU tz 2026c). Verified
inside each image: they read Winnipeg as **−06** since 2026-11-01 07:00 UTC, so local times are an hour early and
local dates flip at 01:00 instead of 00:00. Those repos were only read, not changed (section H).

## B. Timezone impact (CommandCenter)

| Component | Uses local time? | Status |
|---|---|---|
| ccd storage, API, events, SQLite | No — epoch seconds | Unaffected |
| Budgets / metering (`budgets.period_bounds`, `meter.py`) | No — UTC days and months by design | Unaffected |
| Night-shift cutoff `nightshift.cutoff_after` (07:00 local) | Yes, host C library | Correct on jay-server (verified) |
| Brief "written today" (`model.py:336`) | Yes, host | Correct |
| Task-record stamps (`records._ts`) | Yes, host | Correct |
| Release windows `Thu 01:00 America/Winnipeg` (`policy/`) | Label only; nothing schedules from it (`autonomy.py:438`) | Unaffected |
| Browser UI (`web/app`, `toLocale*`, `getHours`) | Viewer's browser zone | Display only; depends on Jay's PC (H) |
| Windows launcher (Go) | UTC log stamps only (`launcher/logfile.go:40`) | Unaffected |
| `ccd.service` | No TZ set → `/etc/localtime` = America/Winnipeg | Correct |
| CI (`.github/workflows/ci.yml`) | Self-hosted runner on the laptop (WSL) | Not reachable; check (H) |

## C. Findings

| # | Severity | Finding | Evidence |
|---|---|---|---|
| 1 | No change | ccd's three local-time paths give the right instants | host tzdata `2026e-0ubuntu0.26.04.1` (installed 2026-10-21 06:47); `ccd.service` active since 2026-10-26 20:15 CDT, so it loaded 2026e; new tests pass |
| 2 | Medium (environment) | Host Node `22.22.2-1nodesource1` bundles ICU tz **2025c**: Winnipeg reads −06 after 2026-11-01 | `node -p process.versions.tz` → 2025c; `Intl` gives `GMT-06:00` for 2027-01-15. CommandCenter web code does no Winnipeg math, so its tests and build are unaffected (223/223 pass under default and UTC). NodeSource candidate `22.23.4` has tz 2026e (Node v22.23.4 notes: "deps: update timezone to 2026e") |
| 3 | Low | Historical "CDT" stamps in docs (`docs/ARCHITECTURE.md:33`, `plans/*.md`, `scripts/herdr.service:5`) | Correct for their dates; left as is |
| 4 | Low | Abbreviation after the change is `EST` from glibc (`timedatectl`: `America/Winnipeg (EST, -0500)`), Node/browsers may say other names | Nothing in ccd parses abbreviations; offsets verified instead |
| 5 | Observation, unverified | This Claude Code session reported "today 2026-11-01" while the host clock read 2026-11-02 00:05 −05 | Could be a stale runtime in the Claude binary or just the session start time; not proven |

## D. Changes completed

Branch `claude/manitoba-tz-2026`, commit `bb94a60`:

- `server/tests/test_timezone_manitoba.py` (new): sets `TZ=America/Winnipeg` and checks the six offsets
  (Jan 2026 −06; Jul 2026, Nov 1 2026 after 07:00 UTC, Jan 2027, Mar 14 2027, Nov 7 2027 −05) through the C library
  and `zoneinfo`; the 07:00 night cutoff on four nights (8 h shifts, no gained or lost hour); local midnight at
  05:00 UTC (`records._ts`, date rollover); UTC budget periods. Fails with "tz database predates IANA 2026e" on
  stale machines.
- `scripts/check-tz.sh` (new, read-only): checks C library, Python and Node on any Linux box; exit 1 on stale data.
- `docs/ARCHITECTURE.md`: new "Time and time zones" section.
- `docs/jay/MY_ACTIONS.md`: three lines for Jay (second commit, with this report).

No product code, schedule, storage format or data changed.

## E. Test results

| Command (from `server/`, venv `server/.venv`, Python 3.14.4) | Result |
|---|---|
| `python -m unittest discover -s tests -t .` on `main` before the change | OK (skipped=1) |
| `python -m unittest discover -s tests -t .` on the branch | OK — 996 tests, skipped=1, exit 0 |
| `TZ=<z> python -m unittest tests.test_timezone_manitoba tests.test_nightshift` for z = unset, UTC, America/Chicago, America/Winnipeg, Asia/Kolkata | OK ×5 |
| Same new test with `TZDIR`/`PYTHONTZPATH` = the 2026c zoneinfo copied from the gyst-lifeops image | FAILED (failures=6) — as intended: proves the test catches stale data. The Mar 14 2027 cutoff case passes under both, as expected |
| `scripts/check-tz.sh` on jay-server | C library PASS, Python PASS, Node 22.22.2 / ICU 2025c **FAIL** (exit 1) |
| `web/app`: `npm ci`, `npm run typecheck`, `npx vitest run`, `TZ=UTC npx vitest run`, `npm run build` | pass; 31 files, 223 tests both runs; build exit 0 |

Full backend suite on the branch: `Ran 996 tests in 327.375s — OK (skipped=1)`, exit 0 (includes the 4 new tests).

Not run: CI on the laptop runner (not reachable from here; the PR's CI run is the check). No shellcheck on the host.

## F. Dependencies (jay-server)

| Runtime | Version | tz data | Winnipeg 2027-01-15 | Provenance |
|---|---|---|---|---|
| System tzdata | 2026e-0ubuntu0.26.04.1 | 2026e | −05 ✓ | Ubuntu, dpkg log 2026-10-21 (2026c → 2026e) |
| Python | 3.14.4 (`/usr/bin/python3`, `server/.venv`) | system zoneinfo, no pip `tzdata` | −05 ✓ | `zoneinfo.TZPATH` = `/usr/share/zoneinfo`… |
| Node | 22.22.2 (NodeSource) | ICU 78.2, tz 2025c | −06 ✗ | `process.versions`; candidate 22.23.4 has 2026e |
| Go (launcher) | go 1.24 in `go.mod`; no Go on host | Windows uses its own zone data | not applicable (UTC only) | |

No Python, JS or Go timezone libraries in CommandCenter's manifests (no pytz, tzdata, moment, date-fns-tz, luxon).

Before/after: unchanged. Nothing was installed or upgraded.

## G. Production impact

**CommandCenter (ccd): none found.** It loaded 2026e at its 2026-10-26 start. Safe read-only check:
`scripts/check-tz.sh` and `systemctl --user show ccd -p ActiveEnterTimestamp` (must be after 2026-10-21 06:47).

**Other production on jay-server: yes, now.** Checked with throwaway `--network none` containers from the
running images (no exec into live containers, no env read):

| Container | Image built | tzdata | Winnipeg 2026-11-02 05:30 UTC | Code that uses it |
|---|---|---|---|---|
| gyst-lifeops | 2026-10-08 | 2026c (deb12u1) | 23:30 −06 ✗ (should be 00:30 −05) | `internal/clock/clock.go:25` DefaultTimezone America/Winnipeg: every stored calendar day; prayer times `internal/services/prayer.go:262` |
| samvision-web | 2026-10-15 | 2026c (deb13u1), Python zoneinfo −06 ✗ | ✗ | `samvision/api/clock.py:21`, `vehicle/constants.py:131`, `api/trips.py:53`; stale fallback `LOCAL_FALLBACK_OFFSET_HOURS = -6` (`clock.py:23`) |
| myfamilyexpenses-app-1 | 2026-10-07 | 2026c; Node 22.23.3, ICU tz 2026c ✗ | ✗ | `lib/reporting.ts:128` and `app/dashboard/page.tsx:17` (if `APP_TIME_ZONE=America/Winnipeg` — `.env` not read) |
| fms-api / fms-web | 2026-05-14 | 2025b; Node ICU 2025c | ✗ | no Winnipeg code found; runs in UTC → no effect |

Likely effect until rebuilt: from 00:00 to 00:59 Winnipeg time each day these apps think it is still the previous
day (GYST task/tracker/prayer day, SamVision local dates, MFE "today"/month/year ranges), and displayed local times
are an hour early. Records written in that hour may carry the previous calendar day. Stored UTC instants are fine.

Fix (for each project's own session, not done here): rebuild with a fresh base. Verified today: current
`debian:bookworm-slim` and `debian:trixie-slim` already have tzdata 2026e, 2026f in updates.

Tests in those repos that encode the old rule (read, not run): gyst-lifeops `internal/clock/clock_test.go:77,80,85`
and `internal/handlers/localday_test.go:38`; samvisionai `tests/test_valuation_form_winnipeg_date.py:31`,
`tests/test_advisor_winnipeg_date.py:38`, `tests/test_rental_planner_web.py:1746`, `tests/test_vehicle_summary.py:31`.
They pass inside the stale images and fail on a 2026e host — so a rebuild needs those tests fixed in the same PR.

Host cron (`crontab -l`) runs backups at 03:30–04:00 and the legacy board at 07:45 local: cron uses system tzdata
(2026e), so these now run at −05 local as intended. No systemd timers belong to this repo.

## H. Manual actions required

### Urgent

1. **Rebuild gyst-lifeops, samvision-web and myfamilyexpenses-app with current tz data** (production deploys need you;
   each repo has its own rules — SamVision and GauzeMate: Jay merges). Dispatch to each coordinator: "Manitoba
   UTC−05: rebuild on a fresh base (`docker build --pull`), check `TZ=America/Winnipeg date -d 2027-01-15T18:00Z +%z`
   = `-0500` inside the image, fix the old-DST tests listed in this report, and replace SamVision's −6 fallback."
   Read-only check now: `docker run --rm --network none --entrypoint sh <image> -c 'head -1 /usr/share/zoneinfo/tzdata.zi'`.
2. **Check your Windows PC clock.** The browser UI shows times in the PC's zone. If Windows is still on a zone that
   follows US Central DST, it shows −06 since Nov 1. Check the clock matches jay-server (`date` there). In the
   browser DevTools console:
   `new Intl.DateTimeFormat("en-CA",{timeZone:"America/Winnipeg",timeZoneName:"longOffset"}).format(new Date("2027-01-15T18:00Z"))`
   must end `GMT-05:00`; if not, update the browser.

### Approval required

3. **Upgrade host Node to 22.23.4** (NodeSource candidate, tz 2026e): `sudo apt-get install --only-upgrade nodejs`,
   then `scripts/check-tz.sh`. Not done: system package on the production host. Low risk for CommandCenter (build and
   tests only); running Node processes keep the old binary until restarted.
4. **Check the laptop CI runner (WSL):** run `scripts/check-tz.sh` there. If the C library or Python line fails,
   `sudo apt-get install --only-upgrade tzdata` in WSL — otherwise the new test turns this repo's CI red.
5. **Review and merge** the PR for `claude/manitoba-tz-2026` (tests, script, docs only).

### Optional

6. Pin the web UI to `America/Winnipeg` (`timeZone` in `web/app/src/lib/time.ts` and the `toLocale*` calls) if you
   want server time regardless of the PC's zone. Not done: it changes what the UI shows, so it is your call.

## I. Deployment and rollback (not executed)

CommandCenter change is tests, a script and docs: nothing to deploy to ccd. After merge, `scripts/go-live.sh` would
only rebuild the same UI. Rollback: `git revert <merge commit>` on main.

Other apps (when you approve each): build on a fresh base, check tz offset in the image, deploy by that project's
runbook, then check one local date at a known instant. Rollback: redeploy the previous image ID
(gyst-lifeops `2c906264e480`, samvision-web `d7218b72c090`, myfamilyexpenses-app `b8634d237729`) — rollback brings
back −06.

## J. Final status

| Repository | Access | Status |
|---|---|---|
| CommandCenter | full | **PASS — changes implemented and verified, awaiting review** (tests/docs only; code already correct) |
| gyst-lifeops | read only | **FAIL — unresolved production issue** (image tzdata 2026c; 4 tests encode old DST) |
| samvisionai (`/srv/server/apps/samvisionai`) | read only | **FAIL — unresolved production issue** (image tzdata 2026c; tests and −6 fallback) |
| MyFamilyExpenses | read only | **FAIL — unresolved production issue** if `APP_TIME_ZONE=America/Winnipeg` (image tz 2026c) |
| FMS | read only | PASS — no Winnipeg code; stale tz data has no effect today |
| GauzeMate | read only | PASS — phone app, uses the device zone |
