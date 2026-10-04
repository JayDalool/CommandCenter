# Command Center Morning Brief

2026-10-04 · live `9d81198` on http://127.0.0.1:7777 · preview 7788 unchanged

## What changed overnight
- **Tasks show every project.** Imported active work from SV, GZ, MFE, GYST (149 tickets, 71 of them archived history). Default view is ALL, with project chips and counts and an "Include archived/history" toggle. Running the import again creates nothing new.
- **Workspace has one sidebar.** The activity bar switches between Explorer, Source control and Search. Diffs and Development open as tabs in the main area. Claude now appears only in the bottom dock.
- **Project pages are cockpits.** Each has an action bar: Workspace, Claude, Repo shell, Source control, Development, GitHub, New ticket (preselects the project). Command Center gets one too.
- **PTY cleanup (CC-010).**
  - A shell that exits now takes its background and `nohup` jobs with it. It only ever stops its own systemd scope.
  - A Claude attach nobody is watching releases herdr's writer slot after 60 seconds, measured on a monotonic clock.
  - Plus review fixes in the launcher, `cc-terminal` and the stale-build recovery.

## Live now
- ccd PID 1250495, 0 restarts, healthy, loopback only. The UI is served from atomic releases; the newest is `20261004T200601Z-9d81198`.
- Herdr PID 3984916, 0 restarts. samvision `wE:p2` and gauzemate `wE:p4` have the same sessions as before. No extra Claude process.
- Active tickets: SV 21 · GZ 28 · MFE 5 · GYST 24 · CC 4.

## CC tickets completed
CC-002 shells · CC-003 search · CC-004 source control · CC-005 Claude (superseded by CC-012) · CC-007 write hardening · CC-008 task import · CC-009 layout (superseded by CC-014) · CC-010 PTY follow-ups · CC-011 native terminal · CC-013 file-open fix

## CC tickets still open
All four are blocked only on you:
- CC-006: the launcher's tray and second-launch behaviour need a real Windows PC.
- CC-012: the typed canary into Claude from the browser.
- CC-014: the Workspace sidebar in a real browser.
- CC-015: the project cockpit in a real browser.

## Blocked only on Jay
- One browser pass over the new screens (lines in `docs/jay/UI_TESTS.md`). Agents here can't drive the logged-in UI.
- Two GYST tickets the import couldn't classify. Give each a status and they'll be created:
  - "Production foreign-key audit": its status is `PENDING (operator)`.
  - "Host file permissions (Issue #5)": it has no Status line.

## What Jay should test
1. Tasks: ALL plus each chip; the archived toggle shows history.
2. Workspace: Explorer, Source control and Search in the sidebar; a diff opens in the main area; open, edit and save a file; refresh, then reopen it.
3. Workspace → Claude with the native SamVision tab closed. Type `Reply exactly: BROWSER_PTY_CANARY_OK`.
4. A project page's action bar.

## Anything risky
- **Regex search** stays off: ripgrep isn't installed, and installing it needs sudo. Plain-text search works.
- **Old chunks expire.** Each UI release keeps the last 3 releases' chunks. A window left open across 4+ deploys shows "Command Center was updated" and reloads once.
- **Rollback.** Backups are in `~/command-center/backups/golive-20261004-*`. Before the import there's also `~/command-center/data/tasks.db.bak-import-20261004T194024Z`, with its report in `~/command-center/state/import-apply-20261004.json`.
