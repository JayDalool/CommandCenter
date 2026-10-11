# UI tests

Screens Jay must check. Newest first. Delete a line when it's done.

- [ ] CC-041 · Development Review matches ticket detail; Needs Jay shows keys · http://127.0.0.1:7777/#/development
- [ ] CC-034 · Deploy gate: approve; Claude prepares, waits for pane · http://127.0.0.1:7777/#/dashboard
- [ ] CC-024 · Server → Worktrees panel says finished tickets' clean worktrees are removed · http://127.0.0.1:7777/#/server
- [ ] CC-029 · Go Live: confirm lists tickets; Claude only prepares · http://127.0.0.1:7777/#/dashboard
- [ ] NIGHT SHIFT · Dashboard → ☾ Night shift → Start; each panel shows "Night shift running"; in the morning its Report shows the release candidate · http://127.0.0.1:7777/#/dashboard
- [ ] GO LIVE · Report → Go Live… → Yes, approve and prepare: Claude writes its plan to ~/command-center/deploys/<project>/ and waits; you confirm the deploy in its pane · http://127.0.0.1:7777/#/dashboard
- [ ] NIGHT SHIFT · In any repo's Claude type /night-shift (after go-live links it) · any Claude pane
- [ ] TASK CHECK · Dashboard → Check tasks → Check all projects; each Claude answers "<project> task check: …" in its pane · http://127.0.0.1:7777/#/dashboard
- [ ] TASK CHECK · A stale proposal shows Cancel it / Keep it; Cancel it closes the task · http://127.0.0.1:7777/#/tasks?view=jay
- [ ] WORKSPACE · ☰ Tasks: the Task Manager takes the tree's place, rooms stay open; open a task, change its Status, Open Task Room ▸ · http://127.0.0.1:7777/#/workspace
- [ ] CONTROL ROOM · Dashboard: five project panels, Needs Jay links open the exact question · http://127.0.0.1:7777/#/dashboard
- [ ] CONTROL ROOM · Workspace: double-click a task, Claude + Project side by side, a 5th room offers pop-out / new window · http://127.0.0.1:7777/#/workspace
- [ ] CONTROL ROOM · Pop a pane (↗) to monitor 2: same session, the slot shows + Add Pane; Reattach brings it back · http://127.0.0.1:7777/#/workspace
- [ ] CONTROL ROOM · Answer a task's questions; its Claude session continues (no new session) · http://127.0.0.1:7777/#/workspace
- [ ] CONTROL ROOM · Unlock Developer once; reload and pop-outs do not ask again · http://127.0.0.1:7777/#/workspace

- [ ] CC-026 · Development trail: Roles line and pipeline review verdict · http://127.0.0.1:7777/#/development
- [ ] CC-017 · GYST and MFE Claude tabs attach (no rename needed) · http://127.0.0.1:7777/#/workspace?console=gyst&open=1
- [ ] CC-010 · In a terminal run nohup sleep 999 &, then exit; sleep is gone · http://127.0.0.1:7777/#/files
- [ ] CC-008 · Tasks shows ALL projects; chips and archive toggle work · http://127.0.0.1:7777/#/tasks
- [ ] CC-014 · Files sidebar: Explorer / Source control / Search, diffs open in main · http://127.0.0.1:7777/#/files?project=samvision
- [ ] CC-013 · Open .py/.ts/.md files, save, refresh, reopen — no import error · http://127.0.0.1:7777/#/files
- [ ] CC-012 · Close native Claude tab, type canary in browser Claude · http://127.0.0.1:7777/#/workspace?console=samvision&open=1
- [ ] CC-011 · Project Console: Claude attaches to samvision · http://127.0.0.1:7777/#/workspace?console=samvision&open=1
- [ ] CC-011 · Open native repo terminal lands in the repo · http://127.0.0.1:7777/#/workspace?console=samvision&open=1
- [ ] CC-011 · Open native server terminal: normal jay login · http://127.0.0.1:7777/#/workspace?console=samvision&open=1
- [ ] CC-002 · Repo shell: run git status, vim, Ctrl+C, resize · http://127.0.0.1:7777/#/workspace?console=samvision&open=1
- [ ] CC-002 · Server shell: systemctl --user status ccd · http://127.0.0.1:7777/#/workspace?console=samvision&open=1
- [ ] CC-004 · Source control: diff, stage, commit, ticket branch · http://127.0.0.1:7777/#/files?view=scm
- [ ] CC-003 · Ctrl+P go to file, Ctrl+Shift+F search · http://127.0.0.1:7777/#/files
- [ ] CC-014 · Explorer right-click: new, rename, duplicate, delete · http://127.0.0.1:7777/#/files
- [ ] GOLIVE · Files: open, edit, Ctrl+S, conflict warning · http://127.0.0.1:7777/#/files
- [ ] GOLIVE · Files: drag a Windows file onto a folder · http://127.0.0.1:7777/#/files
- [ ] GOLIVE · Ticket attachments: attach, download, remove · http://127.0.0.1:7777/#/tasks
- [ ] GOLIVE · GitHub links open github.com/JayDalool/<repo> · http://127.0.0.1:7777/#/projects
- [ ] P4B-REV · Development: branch, commits, PR, CI, review, merge per ticket · http://127.0.0.1:7777/#/development
- [ ] P4B-REV · GauzeMate tickets: GM-* history kept, new ones are GZ-* · http://127.0.0.1:7777/#/tasks
