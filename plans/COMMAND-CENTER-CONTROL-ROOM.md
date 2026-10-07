# COMMAND CENTER — FINAL IMPLEMENTATION SPEC

> Frozen 2026-10-07 (Phase A). The text below is Jay's approved specification, unchanged except
> for the reference-image paths. How each part maps onto Command Center is in the appendix at the end.
## Manager Control Room + Task Rooms + tmux-style Workspace

**Status:** Approved product direction  
**Priority:** P0 — implement now  
**Goal:** Finish the Command Center redesign quickly by reusing the working backend and replacing the noisy UI with the approved control-room workflow.

---

# 1. PRODUCT DEFINITION

Command Center is **not VS Code** and it is **not an analytics dashboard**.

It is Jay's **software-development control room**.

Its job is to let Jay:

1. see what happened across all active projects,
2. see what needs his attention,
3. open a project/task quickly,
4. answer Claude or Codex questions,
5. keep active task sessions alive until the task is complete,
6. supervise several projects at once,
7. inspect/upload project files when needed,
8. use Claude, Codex, project CLI and server CLI,
9. understand blockers in manager-friendly language,
10. allow reviewed work to merge automatically,
11. get warned before anything is deployed to a live environment,
12. keep a complete, evidence-backed history for every task.

The core mental model is:

**Dashboard → Workspace → Task Room**

- **Dashboard:** manager morning/night overview.
- **Workspace:** live multi-task control wall.
- **Task Room:** one active ticket, its context, questions and terminal tools.

---

# 2. APPROVED VISUAL REFERENCES

Use these design files as the primary reference:

- `docs/design/control-room-poster.webp` (the infographic poster: all three concepts)
- `docs/design/dashboard-reference.webp`
- `docs/design/workspace-reference.webp`
- `docs/design/terminal-reference.png`

These are APPROVED references.

Do not redesign the product into a different visual direction.

The approved visual personality is:

- dark control room,
- low eye strain,
- compact but not cluttered,
- useful before beautiful,
- small amounts of meaningful color,
- square / technical terminal geometry,
- subtle borders,
- no glassmorphism,
- no white terminal,
- no giant cards,
- no decorative dashboard noise.

Project colors are functional:

- SamVision = red
- GauzeMate = green
- Command Center = blue
- GYST = orange / amber
- MyFamilyExpenses = purple

Project colors are navigation/status cues, not decoration.

---

# 3. PRIMARY NAVIGATION

Keep primary navigation very small:

1. **Dashboard**
2. **Workspace**
3. **Task Manager**
4. **Activity / Logs**
5. **Files**
6. **Settings**

Do not create more primary navigation unless absolutely required.

Server/agent diagnostics can live under Settings, Activity/Logs, or a compact Ops section if already present.

---

# 4. DASHBOARD — MANAGER MORNING / NIGHT VIEW

When Command Center opens, Jay sees a dashboard split into equal project panels.

If 5 repositories are actively registered, display 5 panels intelligently in the available space.

Each project box uses its project color subtly.

Each panel answers:

### Latest update
Examples:
- Night shift completed
- Morning shift completed
- PR approved
- review failed
- implementation running
- deployment completed
- build blocked

### Needs Jay
Only decisions/actions Jay must take.

Examples:
- answer 3 questions
- choose UI option
- approve changed architecture
- review screenshots
- allow live deployment
- resolve ambiguity

### Active work
Small count or short list:
- planning
- implementing
- reviewing
- verifying
- ready to merge

### Went live
Only meaningful deployments/releases.

### Blockers
Only meaningful blockers.

Do NOT fill the dashboard with:
- generic repository statistics,
- vanity KPIs,
- unnecessary charts,
- commit counts,
- file counts,
- technical diagnostics.

The dashboard should make Jay feel like a manager arriving in the morning and checking what his agents accomplished overnight.

---

# 5. PROJECT / TASK TREE

Workspace has a permanent collapsible project/task tree on the left.

Behavior should resemble folder expansion:

```text
▼ SamVision
    Project Console
    SV-071   Needs Jay
    SV-074   Reviewing
    SV-079   Implementing

▶ GauzeMate

▼ Command Center
    Project Console
    CC-031   Planning
    CC-032   Implementing
```

Click project arrow:
- expand/collapse tasks.

Closed tasks:
- immediately leave the active tree,
- remain available under Task History.

Each active task row should show:
- ticket key,
- short title if room allows,
- small status square,
- concise stage.

Keep the list dense and readable.

No cards around every task.

---

# 6. TASK DETAIL / TASK DOSSIER

Single-clicking a task shows its task detail.

Double-clicking a task or clicking **Open Room** opens the live Task Room.

Task detail should be manager-readable, similar to a strong Jira issue.

Show:

## Why
Why does this task exist?

## Problem / Cause
What was broken or missing?

## Plan
The accepted implementation plan.

## Acceptance Criteria
What must be true to call it successful?

## Current Stage
One of the simplified visible stages.

## Questions
Current unresolved questions for Jay.

## Workflow History
Planning → implementation → review → rework → UI testing → verification → merge → deployment → close.

## Evidence
Where applicable:
- screenshots,
- images,
- links,
- file references,
- test evidence,
- PR,
- CI,
- deployment verification.

The default explanation must be understandable to a manager, not only a senior engineer.

A **Technical details** expansion can show SHAs, commands, stack traces, etc.

---

# 7. TASK PLAN + MODEL ASSIGNMENT

Default role model:

## Opus
Use for:
- research,
- investigation,
- architecture,
- planning,
- requirements clarification,
- difficult debugging,
- security reasoning,
- scope changes.

## Sonnet
Use for:
- implementation of an approved plan,
- mechanical code changes,
- executing a clearly defined fix,
- ordinary test writing/fixing.

A task should normally flow:

```text
OPUS
Investigate / Research / Plan
        ↓
Accepted Plan
        ↓
SONNET
Implement
        ↓
Fresh Reviewer
        ↓
Verification / UI
        ↓
Merge
        ↓
Deploy if applicable
        ↓
Close
```

Do NOT send every implementation defect back to planning.

Rules:

- normal code defect → back to Implementation,
- invalid assumptions / architecture / security / major scope change → back to Planning.

---

# 8. ACTIVE TASK CLAUDE SESSION

Every actively worked task receives its own Claude task session.

Examples:

- `sv-071`
- `gz-029`
- `cc-031`

The task Claude session:

- stays alive while the task is active,
- remains attached to the task's durable state,
- can wait for Jay without being closed,
- can be reattached after browser/UI detach,
- should not lose identity because the conversation title changes.

When the task becomes CLOSED:

1. persist final structured history,
2. persist final summary/evidence,
3. close the task Claude session,
4. close task Codex session if any,
5. safely release task worktree/resources,
6. retain all workflow records.

Do not keep closed-ticket Claude contexts alive unnecessarily.

The long-lived PROJECT COORDINATOR remains separate.

---

# 9. QUESTIONS FOR JAY

If Claude needs answers, create structured questions.

Example:

```text
Claude needs 3 answers

1. Should mobile use the same layout?
   [________________________]

2. Should this apply to CMA too?
   [________________________]

3. Which visual option do you prefer?
   [________________________]

[ Submit Answers ]
```

Multiple questions should be shown as separate form fields.

When Jay submits the final required answer:

### Normal case
Immediately resume the same task Claude session automatically.

### Scope guard
Before continuing, determine whether the answer materially changes:

- approved scope,
- architecture,
- security,
- data model,
- permissions/auth,
- major UX direction.

If NO:
- continue Implementation.

If YES:
- move task back to Planning,
- wake Opus,
- update the plan,
- update acceptance criteria,
- continue only after the revised plan is valid.

Answering a question must NEVER start a duplicate Claude session.

---

# 10. NOTIFICATIONS

Notifications are now a core requirement.

Top-right notification center.

Notify Jay only for meaningful events:

- task Needs Jay,
- question(s) waiting,
- permission required,
- review blocked,
- UI review ready,
- major failure,
- changed architecture/scope,
- live deployment waiting,
- critical server/repo problem.

Avoid dinging for:
- ordinary commits,
- every test pass,
- routine stage transitions.

Clicking a notification must take Jay directly to:
- the correct task,
- the correct Task Room,
- the exact question/action.

Use a sound/toast for attention-required events.

---

# 11. MANAGER-FRIENDLY BLOCKERS

When merge/deploy cannot proceed, explain first in management language.

Example:

```text
SV-071 cannot merge yet

What happened
The feature passed code review, but the final mobile UI test found that the
action buttons overlap on narrow screens.

Why it matters
Merging now would solve desktop but create a visible mobile regression.

Recommended action
Fix the mobile layout and rerun UI verification.

Estimated impact
Small. The current implementation can remain.

Options
[ Fix and continue ]
[ Re-plan ]
[ Show technical details ]
```

Do not make raw Git/CI terminology the primary explanation.

Technical details can be expanded below.

---

# 12. WORKSPACE — TMUX-STYLE CONTROL WALL

The Workspace is the main live working environment.

The right side is a tmux-like square task wall.

A Workspace window supports a maximum of **4 active rooms**.

Room layouts:

### 1 room
Full available work area.

### 2 rooms
Two equal side-by-side squares/rectangles.

### 3 rooms
2×2 grid with one empty/open slot.

### 4 rooms
2×2 grid.

No workspace-page scrolling inside the terminal/task wall.

Tiles resize to fit the viewport.

Dividers should be draggable where practical.

The left project/task tree remains available.

Task detail can expand/collapse beside the tree.

---

# 13. TASK ROOM

A Task Room is bound to a specific ticket.

Example:

```text
SV-071 · SamVision
Reviewing

[ Claude ✓ ] [ Codex ] [ Project ✓ ] [ Server ]
```

Available tools:

## Claude
The task-specific Claude session.

## Codex
Task-specific Codex worker/consultant if used.

## Project
Shell rooted in the task worktree.

## Server
Normal jay-server CLI.

Only start/attach tools actually requested.

Do not run all four merely because they are available.

---

# 14. TERMINAL PANE LAYOUT INSIDE A ROOM

A Task Room can show 1–4 terminal panes.

### One

```text
┌──────────────────────────────┐
│ CLAUDE                       │
│                              │
└──────────────────────────────┘
```

### Two

```text
┌──────────────┬───────────────┐
│ CLAUDE       │ PROJECT       │
│              │               │
└──────────────┴───────────────┘
```

### Three

```text
┌──────────────────────────────┐
│ CLAUDE                       │
├──────────────┬───────────────┤
│ CODEX        │ PROJECT       │
└──────────────┴───────────────┘
```

### Four

```text
┌──────────────┬───────────────┐
│ CLAUDE       │ CODEX         │
├──────────────┼───────────────┤
│ PROJECT      │ SERVER        │
└──────────────┴───────────────┘
```

Terminal surfaces stay dark.

No white terminal.

No horizontal page scroll.

Use xterm's own internal scrollback only.

---

# 15. POP-OUT TERMINAL — NEW REQUIRED FEATURE

Every terminal pane must have a small **Pop Out** button in its pane header.

Example:

```text
CLAUDE                         ↗
```

Clicking Pop Out:

1. detaches the pane visually,
2. opens it in its own Command Center terminal window,
3. attaches to the EXACT SAME backend session/PTY,
4. does NOT create another Claude/Codex/shell process,
5. frees the original pane slot,
6. replaces the original position with:

```text
+ Add Pane
```

The popped-out terminal can be dragged to a second monitor.

The popped-out window should contain:
- project/task name,
- terminal type,
- status,
- reattach option,
- close/detach control.

Closing a popped-out UI window must NOT silently kill the underlying work session.

Show a clear distinction:

- **Close Window / Detach**
- **End Session**

Ending a Claude/task session should require explicit appropriate action.

---

# 16. POP-OUT TASK ROOM — NEW REQUIRED FEATURE

A Task Room header must also support:

**Pop Out Room**

This is different from popping out one terminal pane.

If Workspace already has 4 Task Rooms and Jay needs another active task:

1. pop out one Task Room into a new Command Center window,
2. retain all of its current pane layout and task bindings,
3. free the slot in the original Workspace,
4. allow a new task/project console to use that slot.

This is required for multi-monitor operation.

A newly popped Task Room must attach to existing backend sessions.

Never duplicate Claude simply because the UI moved to another window.

---

# 17. NEW WORKSPACE WINDOW

A Workspace window can hold 4 rooms maximum.

If more are required:

```text
Workspace is full (4/4)

[ Pop Out Existing Room ]
[ Open New Workspace Window ]
```

A second Workspace window can be dragged to another monitor.

Example:

```text
MONITOR 1
SV-071 | GZ-029
MFE-018 | GYST-024

MONITOR 2
CC-031 | SV-080
```

Each browser/app window shares the same Command Center backend state.

---

# 18. PROJECT CONSOLE — NO TASK REQUIRED

A project must support work that is not tied to a special task.

Each project tree contains:

```text
Project Console
```

Example:

```text
▼ SamVision
    Project Console
    SV-071
    SV-074
```

Opening Project Console creates a normal room, but not a ticket room.

Available tools:

- Claude
- Codex
- Project
- Server

## Project Claude
Attach to the long-running project coordinator, e.g. `samvision`.

Use for:
- general repo questions,
- backlog review,
- architecture discussion,
- research,
- status,
- creating new tasks,
- discussing ideas before a ticket exists.

## Project Codex
Use as:
- UI/visual specialist,
- second opinion,
- design/3D specialist,
- repo-level consultant.

## Project CLI
Rooted in the registered project repo, not a task worktree.

## Server
Normal server shell.

A Project Console counts as one of the 4 visible Workspace rooms.

Project Console can also be popped out.

---

# 19. CODEX ROLE

Codex is not only a fallback implementer.

Supported modes:

## UI / Visual Specialist
Especially useful for:
- interface concepts,
- animations,
- 3D visual elements,
- visual experimentation,
- interactive design.

## Second Opinion
Claude may ask Codex:

- review an idea,
- challenge a plan,
- suggest alternatives,
- provide design feedback.

For second-opinion mode:
- send only relevant context,
- Codex returns advice,
- it does not modify files unless explicitly assigned implementation.

## Implementation Worker
Codex may implement bounded work where suitable.

Only ONE writer can own a worktree at a time.

---

# 20. CODEX → CLAUDE FALLBACK

If Codex hits:

- token/quota limit,
- rate limit,
- unavailable service,
- process failure,
- configured budget guard,

then create a durable checkpoint:

- ticket,
- branch,
- worktree,
- latest commit,
- dirty diff,
- changed files,
- tests run/results,
- decisions,
- blocker,
- remaining work.

Then:

1. release Codex write ownership,
2. attach Claude to the SAME worktree,
3. provide checkpoint context,
4. Claude resumes from the current state,
5. do not restart implementation from scratch.

---

# 21. FRESH CODE REVIEW IS MANDATORY

Any implementation — whether created by:

- Sonnet,
- Opus,
- Codex,
- Jay,
- another tool,

must receive a fresh independent Claude review before merge.

Reviewer checks:

1. Does this actually satisfy the task?
2. Is the implementation technically correct?
3. Are tests adequate?
4. Security implications?
5. Dependencies/API effects?
6. Blast radius?
7. Unexpected impact outside scope?
8. Does it still match acceptance criteria?

Review approval is tied to the exact final HEAD SHA.

Any material commit after approval invalidates the review.

Implementer cannot approve its own work.

---

# 22. MERGE / DEPLOY POLICY

Claude is authorized to merge clean work automatically when all applicable gates pass.

Required gates:

## Gate 1 — Technical
- tests pass,
- CI green where available,
- targeted blast-radius checks pass,
- no known blocking regression.

## Gate 2 — Independent Review
- fresh Claude reviewer approves exact HEAD.

## Gate 3 — Jay Acceptance
Required if:
- user-facing behavior,
- UI/design,
- architecture changed after approval,
- ticket is flagged `needsJay`,
- user review is required.

When gates pass:
- Claude may merge.

## Live Deployment
Before deployment to a LIVE environment:

**Jay must be notified first.**

Display:

```text
Ready for live deployment

What will go live
...

Verification completed
...

[ Deploy Live ]
```

Do not silently live-deploy while Jay is unaware.

Non-live/dev/preview deployment may follow configured automation policy.

After deployment:
- verify live,
- record evidence,
- then close.

---

# 23. WORKFLOW EVIDENCE / TASK RECORD

Every ticket requires a durable evidence trail.

Do not rely only on a Claude conversation.

Store structured state in Command Center and maintain a readable Markdown record in Command Center-managed storage.

Recommended:

```text
~/command-center/task-records/<PROJECT>/<KEY>/
    task.md
    workflow.md
    files/
```

Do NOT automatically write workflow documentation into product repositories.

### task.md

Stable task information:

```markdown
# SV-071 — Valuation Layout

## Why

## Problem

## Cause

## Requirements

## Plan

## Acceptance Criteria
- [ ] ...
```

### workflow.md

Lifecycle/evidence:

```markdown
# Workflow

## Planning
Model:
Result:

## Implementation
Model:
Branch:
Commit:

## Review round 1
Result:
Findings:

## Rework
...

## Review round 2
PASS

## UI Testing
Result:
Evidence:
- image
- file
- link

## Verification
PASS

## Merge

## Deployment

## Closed
```

Any backward movement must be captured.

Example:

```text
Review
→ failed
→ Implementation
→ fixed
→ Review
→ passed
→ UI Test
→ passed
```

Task History is therefore auditable.

---

# 24. TASK VISIBLE STAGES

Use a concise visible stage set:

- Planning
- Implementing
- Reviewing
- UI Testing
- Verifying
- Ready to Merge
- Deploying
- Needs Jay
- Blocked
- Closed

Backend canonical states may remain as required.

Do not expose internal workflow complexity unnecessarily.

---

# 25. CLOSED TASK BEHAVIOR

When a task closes:

- remove it from active Workspace tree immediately,
- remove it from active Activity view,
- retain it in Task History,
- close temporary task sessions,
- retain complete workflow/evidence.

Do not clutter active views with completed work.

---

# 26. FILES

Files are primarily for:

- inspection,
- uploading,
- downloading,
- drag/drop from Jay's laptop,
- task evidence,
- screenshots/design references.

Jay does not need Command Center to be a full code editor.

Preserve file tree + upload capability.

Editing in embedded Monaco is not a product priority.

Do not spend redesign time trying to beat VS Code.

Opening a file for viewing is useful.

If Jay needs serious editing:
- use terminal/nano,
- or provide Open in VS Code as an optional escape hatch if already cleanly supported.

---

# 27. DEVELOPER UNLOCK UX

Do NOT remove security separation.

But eliminate repetitive developer-unlock friction.

Desired behavior:

```text
Launch Command Center
→ authenticate Developer Mode once
→ active for current app/session
```

Developer Mode should cover:
- terminals,
- files/uploads,
- Claude interaction,
- project shell,
- server shell,
- Codex where applicable.

Show only a small status indicator.

Example:

```text
Developer ●
```

Do not repeatedly interrupt Jay for unlock during ordinary use.

Keep secure session expiry/explicit lock capability.

---

# 28. CONCURRENCY

Important distinction:

### Visible rooms
Up to 4 Task Rooms/Project Consoles per Workspace window.

### Heavy implementation concurrency
Keep server-safe execution limits independently.

Do not assume 4 visible rooms means 4 simultaneous heavy implementation lanes.

Waiting/question/review rooms may remain visible without consuming heavy implementation capacity.

Reuse the existing safe concurrency policy unless there is a proven reason to change it.

---

# 29. PRESERVE WORKING INFRASTRUCTURE

Do not unnecessarily rewrite existing working backend systems.

Preserve:

- Command Center ticket DB,
- pipeline V1,
- Needs Jay,
- GitHub linking,
- coordinator bindings by Claude session ID,
- Herdr,
- browser PTY architecture,
- Project terminal,
- Server terminal,
- clipboard behavior,
- files/uploads,
- attachments,
- Source Control where still used,
- Search where still used,
- Developer Unlock security separation,
- loopback-only service,
- Windows launcher,
- atomic frontend releases,
- audit/events,
- existing task migration,
- exact-head review semantics.

This is primarily a product/UI integration phase.

---

# 30. RECONCILE OLD COMMAND CENTER UI TICKETS

Inspect open CC tickets first.

Old UI acceptance work that is replaced by this approved redesign should NOT waste Jay's time.

For each old UI ticket:

- preserve genuine requirement,
- move requirement into this redesign if applicable,
- mark superseded if replaced,
- close if genuinely satisfied.

Do not silently lose requirements.

Reliability issues remain separate.

For example, temp-folder/test leaks remain real reliability work and should not be buried by redesign.

---

# 31. IMPLEMENTATION ORDER — MOVE FAST

Do not spend another multi-day architecture phase.

## Phase A — Freeze spec
Create:

`plans/COMMAND-CENTER-CONTROL-ROOM.md`

based on this exact spec.

No major redesign discussion after approval.

## Phase B — Dashboard
Implement approved manager project panels.

## Phase C — Workspace shell
Implement:
- project/task tree,
- task detail,
- 2×2 Task Room wall,
- max 4 rooms,
- no workspace page scrolling.

## Phase D — Task Room terminal system
Implement:
- Claude,
- Codex,
- Project,
- Server,
- dynamic 1–4 pane layout.

## Phase E — Pop-out
Implement:
- Pop Out terminal pane,
- free original pane slot,
- existing-session attach,
- Pop Out Task Room,
- new Workspace window.

## Phase F — Question flow
Implement:
- structured questions,
- multiple answer form,
- automatic same-task resume,
- scope-change routing.

## Phase G — Workflow evidence
Implement:
- task.md/workflow.md managed records,
- screenshots/files/links evidence,
- task history.

## Phase H — Notifications
Implement meaningful attention events.

## Phase I — Review / deploy gates
Wire exact-head independent review and live-deploy notice.

## Phase J — Final cleanup
Remove obsolete buttons/text/pages.

---

# 32. TESTS REQUIRED

## Task sessions
- task Claude session persists while active,
- question wait does not close session,
- answering resumes exact session,
- close task ends temporary session.

## Project Console
- attaches project coordinator,
- project CLI uses registered repo root,
- no task is required.

## Workspace
- 1 room,
- 2 rooms,
- 3 rooms,
- 4 rooms,
- room layout fits viewport,
- no page scrolling,
- fifth task offers pop-out/new window.

## Terminal pane layout
- 1 pane,
- 2 panes,
- 3 panes,
- 4 panes,
- toggle on/off cleanly,
- no duplicate process.

## Pop Out
- pane pops into new window,
- same backend PTY/session,
- original slot becomes available,
- closing popout UI does not kill session,
- reattach works,
- room popout works,
- second monitor/window behavior works.

## Questions
- 1 question,
- 3 questions,
- answers persist,
- normal answer resumes implementation,
- architecture/security/scope change returns to planning.

## Review
- fresh reviewer,
- exact SHA binding,
- new commit invalidates approval,
- blast-radius result persisted.

## Deployment
- clean merge can proceed automatically,
- live deploy always notifies Jay before action,
- verification recorded.

## Developer Mode
- one unlock supports normal app session,
- no repeated unnecessary prompts,
- security boundary remains intact.

---

# 33. DESIGN REVIEW STANDARD

Fresh UI reviewer must explicitly check:

- Is it simpler than current Command Center?
- Can Jay identify what needs him in seconds?
- Are project colors meaningful but restrained?
- Is the Dashboard manager-friendly?
- Does Workspace feel like a tmux control wall?
- Is terminal text readable?
- Are there too many buttons?
- Are recovery/debug controls hidden until relevant?
- Does every Task Room clearly identify project/task/status?
- Can the task explanation be understood without knowing what the agent did overnight?
- Does the layout work at normal desktop resolution without terminal-page scrolling?

Use the approved reference images.

Do not reinterpret this into another generic SaaS dashboard.

---

# 34. SPEED / AUTONOMY

Jay wants this finished ASAP.

Work autonomously.

Do not stop for small design choices already answered by this specification.

If an implementation detail has two safe equivalent solutions:
choose the simpler one.

Ask Jay only for:
- a genuinely new product decision,
- a security-sensitive irreversible action,
- an unavoidable blocker.

Safe reviewed Command Center work may be:
- committed,
- PR'd,
- reviewed,
- merged,
- deployed to Command Center live.

Do not live-deploy OTHER project applications without the required Jay notice/policy.

---

# 35. FINAL ACCEPTANCE

The redesign is successful when Jay can do this:

1. Open Command Center in the morning.
2. Read one screen and understand what happened across all projects.
3. See exactly what needs him.
4. Open Workspace.
5. See collapsible project/task tree.
6. Select a task and understand Why / Plan / Acceptance / History.
7. Open its Task Room.
8. Use Claude + Project side by side.
9. Open another task in the second tile.
10. Work on up to 4 tasks in one window.
11. Pop a terminal pane to another monitor and reuse its slot.
12. Pop an entire Task Room out and put another task in its old slot.
13. Open a Project Console without creating a ticket.
14. Answer Claude's 3 questions in a form.
15. Have the same Claude task automatically continue.
16. Receive a notification if another task needs him.
17. Let reviewed clean work merge automatically.
18. Be warned before a live deployment.
19. Review complete evidence/history later.
20. Never feel like Command Center is fighting him.

---

# 36. FINAL REPORT FORMAT

When implementation is complete, report only:

```text
COMMAND CENTER CONTROL ROOM

LIVE REVISION:
...

DASHBOARD:
...

WORKSPACE:
...

TASK ROOMS:
...

POP-OUT TERMINALS:
...

POP-OUT ROOMS:
...

PROJECT CONSOLE:
...

QUESTIONS / NEEDS JAY:
...

CODEX:
...

REVIEW / BLAST RADIUS:
...

MERGE / DEPLOY:
...

WORKFLOW EVIDENCE:
...

DEVELOPER MODE:
...

OLD UI CLEANUP:
...

TESTS:
...

REVIEWS:
...

JAY CHECK:
1.
2.
3.
4.
5.

BLOCKERS:
None
```

Keep Jay's manual acceptance checklist short.

Then stop.

Do not begin another redesign phase.
