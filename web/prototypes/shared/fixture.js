/* Command Center V2 — shared design fixture.
 *
 * One realistic snapshot, shaped like ccd's GET /api/state (P2) plus the
 * entity model frozen in plans/COMMAND-CENTER-V2.md §8. Everything here is
 * invented for design review: no real client, property, or licensed data, no
 * tokens, no hostnames beyond "jay-server".
 *
 * Field provenance (so nothing is promised that ccd can't supply):
 *   ccd today  agents[id, name, project, status, cwd, sessionId, workspaceId,
 *              blockedSince], coordinators, projects[prs, tasks, main_ci],
 *              needs, alerts, host[cpu, load, mem, swap, disk, uptime,
 *              containers, oomKills24h], activity events, sources freshness
 *   §8 join    agent.role/model/state/task/branch/pr (herdr status joined with
 *              GitHub and the task index), pr.mergeable/review, task.stage
 *   small add  host.samples (ccd keeps the last hour of 120 s host polls),
 *              host.topProcesses, host.backups, host.worktrees
 *   deferred   agent.context — always null, rendered "—" (owner decision 10)
 */
(function () {
  const NOW = Date.parse("2026-10-03T03:52:10Z"); // 22:52:10 CDT, the snapshot instant
  const MIN = 60 * 1000;
  const ago = (m) => NOW - m * MIN;

  const projects = [
    { key: "samvision", name: "SamVision", repo: "JayDalool/SamVisionAI", branch: "main", model: "opus",
      mainCi: "pass", coordinator: "samvision", worktrees: 26, worktreeLimit: 6, lastActivityAt: ago(1) },
    { key: "gauzemate", name: "GauzeMate", repo: "JayDalool/GauzeMate", branch: "main", model: "opus",
      effort: "max", mainCi: "none", coordinator: "gauzemate", worktrees: 10, worktreeLimit: 6, lastActivityAt: ago(5) },
    { key: "gyst", name: "GYST", repo: "JayDalool/gyst-lifeops", branch: "master", model: "opus",
      mainCi: "pass", coordinator: null, worktrees: 20, worktreeLimit: 6, lastActivityAt: ago(9) },
    { key: "mfe", name: "MFE", repo: "JayDalool/MyFamilyExpenses", branch: "main", model: "sonnet",
      mainCi: "pass", coordinator: "mfe", worktrees: 3, worktreeLimit: 6, lastActivityAt: ago(26) },
  ];

  // state: the UI state (herdr status joined with GitHub / task index, §8)
  // status: the raw herdr status ccd reports today
  const agents = [
    { id: "wE:p2", name: "samvision", project: "samvision", role: "coordinator", model: "opus",
      status: "working", state: "WORKING", taskId: "SV-056", task: "Number fields accept spelled-out values",
      branch: null, pr: 94, startedAt: ago(12), lastEventAt: ago(1),
      lastEvent: "Split SV-056 into two implementation steps", sessionId: "5f0c2a91", workspaceId: "wE",
      cwd: "/srv/server/apps/samvisionai", ci: null, reviewer: null, blocked: null, context: null,
      events: [[ago(1), "Split SV-056 into two implementation steps"], [ago(9), "Opened lane sv-056"],
               [ago(11), "Planner handed back SV-056 plan"]] },
    { id: "wE:p7", name: "sv-056", project: "samvision", role: "implementer", model: "sonnet",
      status: "blocked", state: "BLOCKED", taskId: "SV-056", task: "Number fields accept spelled-out values",
      branch: "feat/sv-056-number-words", pr: null, startedAt: ago(11), lastEventAt: ago(3),
      lastEvent: "Asked to run the e2e suite", sessionId: "c71d04be", workspaceId: "wE",
      cwd: "/srv/server/worktrees/samvisionai/SV-056", ci: "none", reviewer: "samvision reviewer (queued)",
      blocked: { since: ago(3), kind: "permission",
                 question: "Allow Bash: npm run test:e2e -- --project=chromium --grep \"number fields\"?",
                 options: ["1  Yes", "2  Yes, and don't ask again for npm run test:e2e", "3  No, tell Claude what to do"] },
      context: null,
      events: [[ago(3), "Blocked: permission to run e2e suite"], [ago(4), "12 unit tests passing"],
               [ago(8), "Edited src/forms/number_input.py"], [ago(11), "Started from plan SV-056 step 1"]] },
    { id: "wE:p3", name: "samvision-rev", project: "samvision", role: "reviewer", model: "opus",
      status: "working", state: "REVIEW", taskId: "SV-059", task: "Comparable filters: keyboard navigation",
      branch: "feat/sv-059-filter-keys", pr: 93, startedAt: ago(4), lastEventAt: ago(1),
      lastEvent: "Reviewing diff — 6 of 9 files", sessionId: "0e9b33d7", workspaceId: "wE",
      cwd: "/srv/server/worktrees/samvisionai/SV-059", ci: "pass", reviewer: null, blocked: null, context: null,
      events: [[ago(1), "Reviewing diff — 6 of 9 files"], [ago(4), "Picked up PR #93 at a41c9e2"]] },
    { id: "wE:p5", name: "samvision-ver", project: "samvision", role: "verifier", model: "sonnet",
      status: "working", state: "VERIFYING", taskId: "SV-058", task: "Session timeout warning banner",
      branch: "main", pr: 90, startedAt: ago(7), lastEventAt: ago(2),
      lastEvent: "Health check passed; checking banner copy", sessionId: "9a41f0c2", workspaceId: "wE",
      cwd: "/srv/server/apps/samvisionai", ci: "pass", reviewer: null, blocked: null, context: null,
      events: [[ago(2), "Health check passed; checking banner copy"], [ago(7), "Verifying main after #90 merged"]] },
    { id: "wE:p9", name: "samvision-plan", project: "samvision", role: "planner", model: "opus",
      status: "done", state: "DONE", taskId: "SV-056", task: "Number fields accept spelled-out values",
      branch: null, pr: null, startedAt: ago(38), lastEventAt: ago(11),
      lastEvent: "Plan written: plans/SV-056-plan.md", sessionId: "44d7e810", workspaceId: "wE",
      cwd: "/srv/server/apps/samvisionai", ci: null, reviewer: null, blocked: null, context: null,
      events: [[ago(11), "Plan written: plans/SV-056-plan.md"], [ago(38), "Researching SV-056"]] },
    { id: "wE:p4", name: "gauzemate", project: "gauzemate", role: "coordinator", model: "opus",
      status: "idle", state: "IDLE", taskId: null, task: null, branch: null, pr: null,
      startedAt: ago(184), lastEventAt: ago(184), lastEvent: "Handoff written; waiting on Jay for #23",
      sessionId: "8d41e07a", workspaceId: "wE", cwd: "/srv/server/repos/GauzeMate", ci: null, reviewer: null,
      blocked: null, context: null, events: [[ago(184), "Handoff written; waiting on Jay for #23"]] },
    { id: "wE:pA", name: "gauzemate-rev", project: "gauzemate", role: "reviewer", model: "opus",
      status: "blocked", state: "BLOCKED", taskId: "#25", task: "Dependency update and board refresh",
      branch: "chore/deps-board", pr: 25, startedAt: ago(5), lastEventAt: ago(4),
      lastEvent: "Asked whether a major version bump is acceptable", sessionId: "b2e6c419", workspaceId: "wE",
      cwd: "/srv/server/repos/GauzeMate/.claude/worktrees/review-25", ci: "none", reviewer: null,
      blocked: { since: ago(4), kind: "question",
                 question: "PR #25 bumps vite 6.3 → 7.1 (major). The changelog drops Node 18. Approve the major bump, or hold it for a separate PR?",
                 options: ["approve", "hold"] },
      context: null,
      events: [[ago(4), "Blocked: question about vite major bump"], [ago(5), "Started review of PR #25"]] },
    { id: "w9:p2", name: "gyst-9", project: "gyst", role: "implementer", model: "opus",
      status: "idle", state: "WAITING", taskId: "GYST-VN-009", task: "Calendar sync: resolve edit conflicts",
      branch: "feat/gyst-vn-009-conflicts", pr: 44, startedAt: ago(18), lastEventAt: ago(6),
      lastEvent: "Pushed fix; waiting for CI", sessionId: "e18c5a07", workspaceId: "w9",
      cwd: "/srv/server/repos/gyst-lifeops/.claude/worktrees/gyst-9", ci: "pending", reviewer: null,
      blocked: null, context: null,
      events: [[ago(6), "Pushed fix; waiting for CI"], [ago(14), "Reproduced conflict in test"]] },
    { id: "wA:p2", name: "mfe-19", project: "mfe", role: "implementer", model: "sonnet",
      status: "idle", state: "FAILED", taskId: "#19", task: "Receipt totals round to the cent",
      branch: "fix/mfe-19-rounding", pr: 31, startedAt: ago(41), lastEventAt: ago(26),
      lastEvent: "CI failed: lint (2 errors)", sessionId: "3c90d2f1", workspaceId: "wA",
      cwd: "/srv/server/repos/MyFamilyExpenses/.claude/worktrees/mfe-19", ci: "fail", reviewer: null,
      blocked: null, context: null,
      events: [[ago(26), "CI failed: lint (2 errors)"], [ago(29), "Opened PR #31"]] },
    { id: "wA:p1", name: "mfe", project: "mfe", role: "coordinator", model: "sonnet",
      status: "unknown", state: "UNKNOWN", taskId: null, task: null, branch: null, pr: null,
      startedAt: ago(2), lastEventAt: ago(2), lastEvent: "herdr cannot classify this pane yet",
      sessionId: "a7f31e5c", workspaceId: "wA", cwd: "/srv/server/repos/MyFamilyExpenses", ci: null,
      reviewer: null, blocked: null, context: null, events: [[ago(2), "Detected; state not yet classified"]] },
  ];

  const tasks = [
    { id: "SV-065", project: "samvision", title: "Valuation report: page footer and print margins", stage: "PROPOSED", flags: [], pr: null, agent: null, updatedAt: ago(320) },
    { id: "SV-063", project: "samvision", title: "Nightly backup verification report", stage: "RESEARCHING", flags: [], pr: null, agent: null, updatedAt: ago(95) },
    { id: "SV-056", project: "samvision", title: "Number fields accept spelled-out values", stage: "IN PROGRESS", flags: [], pr: 94, agent: "wE:p7", updatedAt: ago(3) },
    { id: "SV-059", project: "samvision", title: "Comparable filters: keyboard navigation", stage: "REVIEW", flags: [], pr: 93, agent: "wE:p3", updatedAt: ago(4) },
    { id: "SV-061", project: "samvision", title: "Admin audit log export", stage: "MERGE", flags: ["needs:jay"], pr: 92, agent: null, updatedAt: ago(1) },
    { id: "SV-058", project: "samvision", title: "Session timeout warning banner", stage: "VERIFY", flags: ["needs:ui-review"], pr: 90, agent: "wE:p5", updatedAt: ago(2) },
    { id: "SV-055", project: "samvision", title: "Comparable search: stable sort order", stage: "DONE", flags: [], pr: 91, agent: null, updatedAt: ago(140) },
    { id: "#24", project: "gauzemate", title: "Offline cache for the dosage calculator", stage: "READY", flags: [], pr: null, agent: null, updatedAt: ago(200) },
    { id: "#25", project: "gauzemate", title: "Dependency update and board refresh", stage: "REVIEW", flags: [], pr: 25, agent: "wE:pA", updatedAt: ago(4) },
    { id: "#26", project: "gauzemate", title: "Searchable drug reference (web)", stage: "REVIEW", flags: [], pr: 26, agent: null, updatedAt: ago(190) },
    { id: "#23", project: "gauzemate", title: "Fix critical and serious accessibility violations", stage: "MERGE", flags: ["needs:jay"], pr: 23, agent: null, updatedAt: ago(184) },
    { id: "GYST-VN-014", project: "gyst", title: "Habit streaks respect the local timezone", stage: "PROPOSED", flags: [], pr: null, agent: null, updatedAt: ago(600) },
    { id: "GYST-VN-012", project: "gyst", title: "Weekly review template", stage: "RESEARCHING", flags: [], pr: null, agent: null, updatedAt: ago(52) },
    { id: "GYST-VN-007", project: "gyst", title: "Rotate the calendar OAuth client", stage: "READY", flags: ["owner-only"], youDoIt: true, pr: null, agent: null, updatedAt: ago(1300) },
    { id: "GYST-VN-009", project: "gyst", title: "Calendar sync: resolve edit conflicts", stage: "IN PROGRESS", flags: [], pr: 44, agent: "w9:p2", updatedAt: ago(6) },
    { id: "#19", project: "mfe", title: "Receipt totals round to the cent", stage: "IN PROGRESS", flags: [], pr: 31, agent: "wA:p2", updatedAt: ago(26) },
    { id: "#17", project: "mfe", title: "CSV export of monthly totals", stage: "DONE", flags: [], pr: 30, agent: null, updatedAt: ago(130) },
  ];

  // ci: pass | fail | pending | none   review: approved | changes | pending | none
  // mergeable: clean | blocked | conflicting | draft | unknown
  const prs = [
    { number: 94, project: "samvision", title: "SV-056: number fields accept spelled-out values", head: "feat/sv-056-number-words", sha: "7d2e0b1", ci: "pending", review: "none", mergeable: "draft", draft: true, updatedAt: ago(3), jay: null },
    { number: 93, project: "samvision", title: "SV-059: comparable filters keyboard navigation", head: "feat/sv-059-filter-keys", sha: "a41c9e2", ci: "pass", review: "pending", mergeable: "blocked", draft: false, updatedAt: ago(4), jay: null },
    { number: 92, project: "samvision", title: "SV-061: admin audit log export", head: "feat/sv-061-audit-export", sha: "e5b7714", ci: "pass", review: "approved", mergeable: "clean", draft: false, updatedAt: ago(1), jay: "MERGE" },
    { number: 26, project: "gauzemate", title: "Searchable drug reference (web)", head: "feat/drug-reference", sha: "19aa03c", ci: "none", review: "none", mergeable: "clean", draft: false, updatedAt: ago(190), jay: null },
    { number: 25, project: "gauzemate", title: "Dependency update and board refresh", head: "chore/deps-board", sha: "c0f4d58", ci: "none", review: "pending", mergeable: "clean", draft: false, updatedAt: ago(4), jay: "ANSWER" },
    { number: 23, project: "gauzemate", title: "Fix critical and serious accessibility violations", head: "fix/axe-critical", sha: "3be91f0", ci: "none", review: "approved", mergeable: "clean", draft: false, updatedAt: ago(184), jay: "MERGE" },
    { number: 44, project: "gyst", title: "GYST-VN-009: calendar sync conflict handling", head: "feat/gyst-vn-009-conflicts", sha: "8f13c6a", ci: "pending", review: "none", mergeable: "unknown", draft: false, updatedAt: ago(6), jay: null },
    { number: 31, project: "mfe", title: "Receipt totals round to the cent", head: "fix/mfe-19-rounding", sha: "52d0e9b", ci: "fail", review: "none", mergeable: "blocked", draft: false, updatedAt: ago(26), jay: null },
  ];

  // kind: MERGE | ANSWER | DO | REVIEW  — what Jay has to do, and where
  const needs = [
    { kind: "MERGE", project: "samvision", ref: "PR #92", text: "SV-061 admin audit log export — approved, checks green", where: "Merge in samvision's pane", target: { pr: 92 }, since: ago(1) },
    { kind: "ANSWER", project: "samvision", ref: "sv-056", text: "Implementer asks to run the e2e suite", where: "Answer here or in pane wE:p7", target: { agent: "wE:p7" }, since: ago(3) },
    { kind: "ANSWER", project: "gauzemate", ref: "reviewer", text: "Reviewer waiting: approve vite major bump on #25?", where: "Answer here or in pane wE:pA", target: { agent: "wE:pA" }, since: ago(4) },
    { kind: "DO", project: "gyst", ref: "GYST-VN-007", text: "Owner-only: rotate the calendar OAuth client", where: "docs/jay/MY_ACTIONS.md", target: { task: "GYST-VN-007" }, since: ago(1300) },
    { kind: "REVIEW", project: "samvision", ref: "SV-058", text: "UI approval: session timeout banner on staging", where: "docs/jay/UI_TESTS.md", target: { task: "SV-058" }, since: ago(2) },
    { kind: "MERGE", project: "gauzemate", ref: "PR #23", text: "Accessibility fixes — approved, no CI configured", where: "Merge in gauzemate's pane", target: { pr: 23 }, since: ago(184) },
  ];

  // cat: agents | tasks | prs | ci | jay | host
  const activity = [
    { seq: 1284, at: Date.parse("2026-10-03T03:51:02Z"), cat: "ci", project: "samvision", text: "Checks passed on PR #92", ref: "e5b7714" },
    { seq: 1283, at: Date.parse("2026-10-03T03:50:40Z"), cat: "jay", project: "samvision", text: "PR #92 is ready to merge", ref: "#92" },
    { seq: 1281, at: Date.parse("2026-10-03T03:49:31Z"), cat: "agents", project: "samvision", text: "Implementer sv-056 is waiting for you: run e2e suite?", ref: "wE:p7" },
    { seq: 1279, at: Date.parse("2026-10-03T03:48:12Z"), cat: "agents", project: "gauzemate", text: "Reviewer is waiting for you: vite major bump on #25", ref: "wE:pA" },
    { seq: 1276, at: Date.parse("2026-10-03T03:47:20Z"), cat: "agents", project: "gauzemate", text: "Reviewer started on PR #25", ref: "wE:pA" },
    { seq: 1272, at: Date.parse("2026-10-03T03:46:05Z"), cat: "prs", project: "gyst", text: "Fix pushed to PR #44 — checks running", ref: "8f13c6a" },
    { seq: 1270, at: Date.parse("2026-10-03T03:45:11Z"), cat: "tasks", project: "samvision", text: "SV-058 moved REVIEW → VERIFY", ref: "SV-058" },
    { seq: 1266, at: Date.parse("2026-10-03T03:44:52Z"), cat: "prs", project: "samvision", text: "PR #90 merged", ref: "#90" },
    { seq: 1262, at: Date.parse("2026-10-03T03:41:30Z"), cat: "agents", project: "samvision", text: "Planner completed SV-056", ref: "wE:p9" },
    { seq: 1260, at: Date.parse("2026-10-03T03:41:02Z"), cat: "tasks", project: "samvision", text: "SV-056 moved READY → IN PROGRESS", ref: "SV-056" },
    { seq: 1255, at: Date.parse("2026-10-03T03:40:10Z"), cat: "agents", project: "samvision", text: "Lane sv-056 opened in worktree SV-056", ref: "wE:p7" },
    { seq: 1249, at: Date.parse("2026-10-03T03:33:41Z"), cat: "host", project: null, text: "ccd started successfully", ref: "v0.1.0" },
    { seq: 1244, at: Date.parse("2026-10-03T03:26:18Z"), cat: "ci", project: "mfe", text: "Checks failed on PR #31: lint (2 errors)", ref: "52d0e9b" },
    { seq: 1240, at: Date.parse("2026-10-03T03:23:09Z"), cat: "prs", project: "mfe", text: "PR #31 opened", ref: "#31" },
    { seq: 1231, at: Date.parse("2026-10-03T03:10:44Z"), cat: "agents", project: "mfe", text: "Implementer mfe-19 exited its turn after CI failure", ref: "wA:p2" },
    { seq: 1219, at: Date.parse("2026-10-03T02:52:30Z"), cat: "jay", project: "gauzemate", text: "PR #23 is ready to merge", ref: "#23" },
    { seq: 1207, at: Date.parse("2026-10-03T02:41:16Z"), cat: "prs", project: "mfe", text: "PR #30 merged — CSV export of monthly totals", ref: "#30" },
    { seq: 1196, at: Date.parse("2026-10-03T02:12:03Z"), cat: "host", project: null, text: "Default boot target set to multi-user.target", ref: "systemd" },
    { seq: 1180, at: Date.parse("2026-10-03T01:32:40Z"), cat: "prs", project: "samvision", text: "PR #91 merged — stable sort order", ref: "#91" },
  ];

  // Inserted one by one while the prototype is open, to show live insertion.
  const scripted = [
    { cat: "ci", project: "gyst", text: "Checks passed on PR #44", ref: "8f13c6a", agentState: { id: "w9:p2", state: "WAITING" } },
    { cat: "agents", project: "samvision", text: "Reviewer finished PR #93 — approved", ref: "wE:p3", agentState: { id: "wE:p3", state: "DONE" } },
    { cat: "tasks", project: "gyst", text: "GYST-VN-012 moved RESEARCHING → READY", ref: "GYST-VN-012" },
  ];

  const alerts = [
    { id: "blocked:wE:p7", severity: "warn", source: "herdr", project: "samvision", text: "sv-056 implementer waiting for you", since: ago(3), ack: false },
    { id: "blocked:wE:pA", severity: "warn", source: "herdr", project: "gauzemate", text: "gauzemate reviewer waiting for you", since: ago(4), ack: false },
    { id: "merge:samvision:92:e5b7714", severity: "action", source: "github", project: "samvision", text: "PR #92 ready to merge", since: ago(1), ack: false },
    { id: "merge:gauzemate:23:3be91f0", severity: "action", source: "github", project: "gauzemate", text: "PR #23 ready to merge", since: ago(184), ack: false },
    { id: "ci:mfe:31", severity: "warn", source: "github", project: "mfe", text: "PR #31 checks failing (lint)", since: ago(26), ack: false },
    { id: "host:worktrees", severity: "info", source: "host", project: null, text: "3 projects over the worktree limit of 6", since: ago(340), ack: false },
  ];

  const GiB = 1024 ** 3;
  const samples = [];
  for (let i = 29; i >= 0; i--) {
    const t = NOW - i * 2 * MIN;
    const wave = Math.sin(i / 3.1) * 1.6 + Math.cos(i / 1.7) * 0.9;
    samples.push({ at: t, cpu: Math.max(1.2, 3.4 + wave + (i === 9 ? 9.5 : 0) + (i === 8 ? 4.2 : 0)),
                   mem: 7.2 + Math.sin(i / 5) * 0.18 + (i < 5 ? 0.2 : 0) });
  }

  const host = {
    hostname: "jay-server", os: "Ubuntu 26.04 · kernel 7.0", cpus: 6,
    cpuPct: 3.1, load: [0.21, 0.23, 0.28],
    memUsed: 7.4 * GiB, memTotal: 14.9 * GiB, swapUsed: 3.5 * GiB, swapTotal: 12 * GiB,
    diskUsed: 104e9, diskTotal: 226e9, uptimeS: 12 * 86400 + 4 * 3600 + 17 * 60,
    asOf: NOW - 34 * 1000,
    samples,
    containers: [
      { name: "samvision-web", state: "running", status: "Up 45 h (healthy)", mem: 141.9 },
      { name: "samvision-postgres", state: "running", status: "Up 2 months (healthy)", mem: 80.3 },
      { name: "minecraft", state: "running", status: "Up 22 h (healthy)", mem: 1641.0 },
      { name: "n8n", state: "running", status: "Up 12 days (healthy)", mem: 309.8 },
      { name: "n8n-postgres", state: "running", status: "Up 12 days (healthy)", mem: 33.7 },
      { name: "myfamilyexpenses-app-1", state: "running", status: "Up 24 h", mem: 110.9 },
      { name: "myfamilyexpenses-ocr-1", state: "running", status: "Up 46 h (healthy)", mem: 289.8 },
      { name: "myfamilyexpenses-db-1", state: "running", status: "Up 2 months (healthy)", mem: 27.7 },
      { name: "gyst-lifeops", state: "running", status: "Up 46 h", mem: 13.0 },
      { name: "gyst-caddy", state: "running", status: "Up 9 days", mem: 22.9 },
      { name: "uptime-kuma", state: "running", status: "Up 2 months (healthy)", mem: 104.7 },
      { name: "nginx-proxy-manager", state: "running", status: "Up 2 months", mem: 93.4 },
      { name: "cloudflared", state: "running", status: "Up 2 months", mem: 25.0 },
      { name: "portainer", state: "running", status: "Up 2 months", mem: 28.2 },
      { name: "fms-web", state: "running", status: "Up 2 months", mem: 41.6 },
      { name: "fms-api", state: "running", status: "Up 2 months", mem: 25.0 },
      { name: "fms-postgres", state: "running", status: "Up 2 months (healthy)", mem: 12.4 },
      { name: "samvision-staging-old", state: "exited", status: "Exited (255) 5 months ago", mem: 0 },
      { name: "scratch-runner", state: "exited", status: "Exited (0) 4 months ago", mem: 0 },
    ],
    topProcesses: [
      { pid: 1374347, user: "jay", rss: 1621.8, cmd: "java -Xmx3G -Xms3G -jar fabric-server-launcher.jar" },
      { pid: 3159511, user: "jay", rss: 527.9, cmd: "node  vscode-server (extension host)" },
      { pid: 3163878, user: "jay", rss: 442.0, cmd: "claude  (command-center)" },
      { pid: 3193047, user: "jay", rss: 310.2, cmd: "claude --resume … -n gauzemate" },
      { pid: 3192431, user: "jay", rss: 305.5, cmd: "claude --resume … -n samvision" },
      { pid: 3477373, user: "10001", rss: 289.6, cmd: "uvicorn app:app --workers 1" },
      { pid: 3840380, user: "jay", rss: 251.9, cmd: "node /usr/local/bin/n8n" },
      { pid: 3173205, user: "jay", rss: 155.5, cmd: "pyright-langserver --stdio" },
      { pid: 6854, user: "root", rss: 120.6, cmd: "dockerd -H fd://" },
      { pid: 3301855, user: "jay", rss: 40.9, cmd: "python -m ccd" },
    ],
    oom: [
      { at: Date.parse("2026-10-02T03:40:27Z"), victim: "chrome", rss: "33.0 MB", trigger: "git" },
      { at: Date.parse("2026-10-02T03:40:33Z"), victim: "chrome", rss: "20.2 MB", trigger: "herdr" },
      { at: Date.parse("2026-10-02T03:41:00Z"), victim: "chrome", rss: "19.6 MB", trigger: "asyncio" },
      { at: Date.parse("2026-10-02T03:41:14Z"), victim: "chrome", rss: "17.1 MB", trigger: "asyncio" },
    ],
    backups: [
      { name: "postgres · all databases", schedule: "03:30 daily", lastAt: Date.parse("2026-10-02T08:30:12Z"), ok: true, size: "412 MB" },
      { name: "samvision · tenants", schedule: "04:00 daily", lastAt: Date.parse("2026-10-02T09:00:41Z"), ok: true, size: "188 MB" },
      { name: "mfe · uploads", schedule: "03:40 daily", lastAt: Date.parse("2026-10-02T08:40:05Z"), ok: true, size: "2.1 GB" },
      { name: "mfe · maintenance", schedule: "03:45 daily", lastAt: Date.parse("2026-10-02T08:45:02Z"), ok: true, size: "—" },
    ],
  };

  const sources = {
    herdr: { ok: true, lastEventAt: NOW - 4 * 1000, lastSnapshotAt: NOW - 11 * 1000 },
    github: { ok: true, asOf: NOW - 98 * 1000, nextIn: 22 },
    git: { ok: true, asOf: NOW - 141 * 1000 },
    host: { ok: true, asOf: NOW - 34 * 1000 },
  };

  window.CC_FIXTURE = {
    now: NOW, seq: 1284, version: "0.1.0",
    connection: { endpoint: "127.0.0.1:7777 via ssh -L", state: "live" },
    projects, agents, tasks, prs, needs, activity, scripted, alerts, host, sources,
    stages: ["PROPOSED", "RESEARCHING", "READY", "IN PROGRESS", "REVIEW", "MERGE", "VERIFY", "DONE"],
    states: ["WORKING", "BLOCKED", "WAITING", "REVIEW", "VERIFYING", "FAILED", "UNKNOWN", "IDLE", "DONE"],
  };
})();
