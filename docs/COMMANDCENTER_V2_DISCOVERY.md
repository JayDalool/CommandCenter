# CommandCenter v2 — Discovery and Architecture Plan

Date: 2026-10-21 · Status: **DISCOVERY ONLY. Nothing here is implemented yet.** · Audited: `main` @ `a0e90e5`
(CC-052), plus every remote branch, with `claude/amazing-keller-fpy0qw` @ `e236ffa` and `p4b` read in detail.

Revision 2 (2026-10-21): Jay answered the blocking questions. His answers are recorded as policy decisions
**D-001 … D-006** in §0 and folded into the policy model (§8), threat model (§10), Slack strategy (§18), roadmap
(§21) and open questions (§25). Where this document and §0 disagree, §0 wins.

> Naming note. The repository already calls itself "Command Center V2" (README, repo description). The vision in
> this document is a third generation. This document says **v2** because that is what Jay asked for; if the work is
> approved, calling it **v3** (or "Control Plane") in code and ADRs avoids two different things both being "V2".

---

## Contents

0. Decisions recorded (policy inputs)
1. Executive Summary
2. Current Architecture
3. What Already Works
4. Current Limitations
5. Gap Analysis
6. Proposed v2 Architecture
7. Proposed Data Model
8. Autonomy Policy Model
9. Worker Architecture
10. Security Threat Model
11. Human Approval Architecture
12. Claude + Codex Review Model
13. UI Information Architecture
14. Suggested UX (wireframes)
15. PR / Release Composer
16. Learning Architecture
17. Pulse Architecture
18. Slack / Email Strategy
19. Storage Strategy
20. Build vs Buy (orchestration)
21. Implementation Roadmap
22. Migration Risks
23. Test Strategy
24. Observability Strategy (including token cost)
25. Open Questions
26. What should we build first, and why?

Appendix A — Audit inventory · Appendix B — Branch audit

---

## 0. Decisions recorded (policy inputs)

Jay's instruction: *these are policy inputs, not one-off answers.* Each one below is written in the shape of the
proposed `Decision` record (§7) so that it can be loaded unchanged into the Decision table in Phase 1, and each one
names the profile rules it produces. Agents cite these decisions instead of asking again. A decision changes only
through a new Decision that supersedes it, approved by Jay.

| ID | Question | Decision (Jay, 2026-10-21) | Becomes policy |
|---|---|---|---|
| **D-001** | Adopt the control-room branch's "agents may merge" approach, or keep ADR 0007's "agents never merge"? | **Neither, wholesale.** Keep the branch's useful pieces (GauzeMate pause, SamVision careful mode, UI test runs, bulk merge). Replace the global "agents never merge" rule with **per-project autonomy policies**: CommandCenter merges and deploys automatically; GYST merges and deploys automatically within safety boundaries; SamVision and MyFamilyExpenses get stricter release rules and need approval for major client-impacting work. | `merge` and `deploy` blocks in every profile (§8.3). Supersedes ADR 0007 rule 2 once implemented (new ADR). The *merger* is still the gatekeeper (Capability Broker), never an agent's own `gh` login: an agent proposes, the broker merges when the profile allows. |
| **D-002** | May AI jobs run on employer Java repositories? | **Yes.** Jay is permitted to use Anthropic and OpenAI with those repositories. Repo storage and secrets stay **laptop-only**; the server gets no clone unless Jay explicitly allows it. AI jobs on these repos are **not** refused. | `restricted` profile: `allowed_nodes: [laptop]`, `repo_storage: laptop_only`, `secrets: laptop_only`, `server_clone: requires_approval(jay)`, `model_providers: [anthropic, openai]`. The earlier "legal precondition denies every job" rule is removed. |
| **D-003** | Buy a paid GitHub plan for branch protection? | **No, not now.** Use the CommandCenter gatekeeper, CI, review rules and whatever repository protections the current plan offers. If a paid tier would materially improve safety or reliability later, raise a **Tool Proposal** (cost, benefits, free/self-hosted alternatives, why it is worth paying) before asking. | Broker-side enforcement is the primary control (§10 T2). Agents get tokens without merge rights where the current plan allows it. `spend_money` stays human-only; a future GitHub upgrade enters as a ToolProposal. |
| **D-004** | May SamVision deploy unattended at 01:00? | **Only safe, low-risk releases, and only after automatic health checks and rollback exist.** Meaningful downtime, migrations, high blast radius or client-facing workflow changes are prepared and **held for approval**. Until automatic rollback is ready, 01:00 means **release-ready, not auto-deploy**. | SamVision (and MFE) `release` block: `unattended_deploy: when [risk == low, no_migration, no_downtime, no_client_workflow_change] and capability [health_checks, auto_rollback]`; otherwise `hold_for: jay`. Capability flags start `false`, so today every window is release-ready only. |
| **D-005** | How much autonomy for GYST around personal data? | **Routine work stays autonomous.** Changes that affect the data model, retention, privacy, encryption, deletion, health/personal-data handling, authentication, or an irreversible migration **need approval**. Normal UI/API fixes around existing personal data stay automatic if reversible and tested. | GYST `require_approval_for` list plus path/keyword risk triggers (schema/migration files, auth, crypto, retention/deletion code). Reversible + tested + none of the triggers → auto merge and deploy. |
| **D-006** | Does Jay want to approve from his phone, and how? | **Yes.** **Slack is the first interface** for approvals, questions, "choose A/B", retry/pause and release notifications. **Do not weaken CommandCenter's local-access rule** to make mobile work. Later, design a secure mobile/remote access option (an authenticated secure tunnel or equivalent) without exposing CommandCenter publicly. | Slack via Socket Mode (outbound only, no public endpoint) moves forward to Phase 2 (§21). Approval classes by channel in §11/§18. Loopback-only stays a hard rule; remote access is a later, separately approved design. |

---

## 1. Executive Summary

**Do not rewrite CommandCenter.** It is already a serious, well-tested control plane for one server: a Python
daemon (`ccd`, ~9k lines), a React UI (~8k lines), a Go Windows launcher, 578 backend tests, 199 web tests, seven
ADRs, and a ticket pipeline with durable state, owner gates, head-SHA-bound reviews, an append-only audit trail
enforced by SQLite triggers, a pure merge-policy classifier, a night-shift supervisor with hard stops, and a
deliberately small, test-asserted API surface. Most of the v2 vision's *governance* ideas (gates, Needs Jay,
fresh independent review, evidence, release batches, policy per project) already exist in an early form. They
should be generalised, not replaced.

What CommandCenter is **not** yet is an *execution* control plane. Today `ccd` owns no agent by rule ("herdr owns
every pane"). Autonomous work happens because long-lived interactive Claude sessions in herdr panes are sent
text (`agent.prompt`) and ccd reads their screens to decide whether they are idle. That design was right for a
supervised fleet; it is the main thing standing between today's system and bounded autonomy, because:

- there is no job, lease, retry or resume model — work survives restarts only because the ticket record does;
- several hard guarantees rest on **message text and convention**, not enforcement (ADR 0006/0007 say so
  plainly): agents run as the same Unix user as Jay, can read the ccd token, can edit `config.json`, and their
  `gh` is logged in as Jay;
- execution is tied to one machine (jay-server); there is no concept of a worker node, so a laptop-only
  restricted repository cannot be modelled;
- policy is spread across `registry.py`, `merge_policy.py`, `pipeline.policy()`, skill Markdown
  (`night-shift/SKILL.md`, `careful.md`) and ADR prose;
- there is no token/cost metering at all, which matters given Jay's recent heavy usage.

**Recommendation in one paragraph.** Keep ccd, tasks.db, the pipeline state machine, the gate → Needs Jay flow, the
classifier pattern, herdr for *interactive* sessions, the Workspace/Task Rooms and the security posture. Add, in
this order: (1) versioned **Project Operating Profiles** and a pure **Autonomy Engine** that every
boundary-crossing action must pass; (2) first-class **Decision** and **Approval** records that subsume today's
gates and questions; (3) a **WorkerNode** model and a simple SQLite-backed **job/lease** table so headless agent
runs (`claude -p`, Agent SDK, `codex exec`) can execute on the server or Jay's laptop and resume safely; (4) a
**separate agent identity** (Unix user + GitHub App) so "agents never merge" becomes a technical fact; (5) cost
metering and budgets. Stay on SQLite. **Do not adopt Temporal, NATS or Redis** — the workload (a handful of
concurrent jobs, one control-plane host) does not justify them, and the existing transactional state machine is
already most of a durable workflow engine.

**Five things to challenge in the vision** (detail in §4, §15, §25):

1. *Unattended 01:00 production releases for SamVision* conflict with today's rule that a live deploy always
   waits for Jay, and nobody is awake if it fails. Either automated health-checked rollback must exist first, or
   the window should be when Jay is awake. **Resolved by D-004:** low-risk only, and only once health checks and
   rollback exist; until then 01:00 means release-ready.
2. *Grouping many tasks into one PR* is the right call for SamVision release trains, but the wrong default for
   CommandCenter/GYST: small auto-merged PRs are easier to review, bisect and revert. The flood Jay wants to
   avoid is a **notification** problem; solve it with release summaries, not bigger PRs.
3. *Claude + Codex review of every plan* doubles cost for little gain on routine work. Make the second reviewer
   risk-triggered.
4. *Specialist agents debating* is the fastest way to burn tokens and create "agent chaos". Discussions should be
   rare, bounded (one round), and triggered only by disagreement or high risk.
5. *Employer Java repositories* on a laptop worker raise a question no architecture can answer: whether Jay's
   employer permits sending that code to Anthropic/OpenAI at all. **Resolved by D-002:** permitted; repos and
   secrets stay laptop-only.

---

## 2. Current Architecture

### 2.1 Diagram (as built, `main` @ a0e90e5)

```text
                                   jay-server  (Linux, systemd --user, Linger=yes)
 ┌──────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                              │
 │  herdr.service ── owns every pane ── coordinators (1 per project, Opus)  task sessions (sv-071) │
 │       │  ~/.config/herdr/herdr.sock  (unix, same user, method allowlist in ccd)              │
 │       ▼                                                                                      │
 │  ccd.service  (python, starlette/uvicorn, 127.0.0.1:7777 hard-coded)                         │
 │   ├─ herdr.py     snapshot + events.subscribe, 30 s reconcile                                │
 │   ├─ sources.py   gh graphql 1 call/repo/120 s · git 300 s · /proc + docker ps 120 s          │
 │   ├─ model.py     derive() → state (agents, PRs, needs, alerts)                              │
 │   ├─ daemon.py    7 loops: herdr, github, git, host, derive, housekeeping, night             │
 │   │               ticket automation · auto-merge (gh pr merge, off by default) · Go Live     │
 │   ├─ pipeline.py  ticket state machine: plan/start/review/verify/confirm/ask/rework/deploy…  │
 │   ├─ merge_policy.py  pure classifier (paths, size, head, CI) → ok | no | wait              │
 │   ├─ nightshift.py    supervisor: reminders with hard stops, morning report                   │
 │   ├─ pty.py       browser terminals (repo/claude/codex/server) in systemd scopes             │
 │   ├─ files.py     registered-root explorer/editor, protected-file lists, atomic writes       │
 │   ├─ records.py   task.md / workflow.md renderings outside repos                             │
 │   ├─ worktree_cleanup.py  removes DONE worktrees only after ~15 checks                       │
 │   └─ api.py       REST + WS /api/events (seq replay) + serves the built UI                   │
 │        │                                                                                     │
 │   ccd.db (ops: events 30 d, kv caches, alerts)   tasks.db (product: tickets, audit, work)    │
 │   attachments.db + ~/.local/share/command-center/attachments/                                │
 │   ~/command-center/{night-shift,task-records,deploys,state}/                                 │
 │                                                                                              │
 │  self-hosted GitHub Actions runner (ci.yml: backend unittest, web typecheck+vitest)          │
 └───────────────▲──────────────────────────────────────────────────────────────────────────────┘
                 │ ssh -N -L 7777:127.0.0.1:7777   (+ scripts/cc-session sign-in over the same SSH login)
 ┌───────────────┴───────────────┐
 │ Windows: CommandCenter.exe     │  Go launcher: tunnel, tray, gate notices from /api/health (no token)
 │ Edge/Chrome → 127.0.0.1:7777  │  React 19 + TS + Vite, xterm, Monaco; no component library
 └───────────────────────────────┘
```

### 2.2 Components

| Component | Where | Role today |
|---|---|---|
| ccd daemon | `server/ccd/daemon.py` (2.4k lines) | Observer + automation. Owns no agent. Seven asyncio loops. |
| Ticket system | `server/ccd/tasks.py`, `tasks.db` | Tickets, labels, relations, comments, links, events (append-only), findings, questions, evidence, `ticket_work`. Forward-only migrations, triggers forbid delete/rewrite. |
| Pipeline | `server/ccd/pipeline.py` (1.1k) | Deterministic state machine with gates `plan · merge · ui · deploy · failure`, lane limit (2/project), review bound to head SHA, 2-cycle rework limit, writer/checkpoint, deploy request/record, release. |
| Agent write path | `server/ccd/pipeline_cli.py` | CLI agents call (`plan`, `review`, `verify`, `ask`, `block`, …) → loopback API with the ccd token, `X-CCD-Actor` self-asserted. |
| Project registry | `server/ccd/registry.py` | Identity, ticket prefix, root, GitHub slug, pipeline overrides (`merge: owner|low-risk`). **Code, not config.** |
| Merge policy | `server/ccd/merge_policy.py` | Pure function; allowlist/denylist; denylist covers policy files themselves. |
| Night shift | `server/ccd/nightshift.py`, `skills/night-shift/SKILL.md` | Sends a skill to idle coordinators; supervisor reminds (≤6, cutoff 07:00, 3 quiet); report = release candidate. |
| Go Live | `daemon.py`, `scripts/go-live.sh`, ADR 0006 | Approves deploy gates and asks the coordinator to *prepare*; Jay confirms in the pane. `go-live.sh` deploys CC itself from `origin/main` with tasks.db backup + printed rollback. |
| Terminals / Task Rooms | `pty.py`, `web/app/src/workspace/*` | Real PTYs (Developer Unlock), pop-outs, ≤4 rooms per window. |
| Auth | `security.py`, `signin.py`, ADR 0003 | Loopback + Host/Origin checks + ccd token + Developer Unlock (second credential) + SSH sign-in code handoff. |
| Launcher | `launcher/*.go` | Windows tray app, SSH tunnel, gate balloons; holds no token (test-enforced). |
| UI | `web/app/src` | Dashboard, Workspace, Task Manager, Activity/Logs, Files, Settings (+ diagnostics routes). |
| CI | `.github/workflows/ci.yml`, `launcher.yml` | Self-hosted runner for backend/web; GitHub-hosted for launcher. Not a required check (free plan). |

### 2.3 Data flow

1. herdr events + snapshots → `daemon` → `model.derive()` → diff → `ccd.db.events` (seq) → WS subscribers.
2. GitHub poll (graphql) → PR state → `_ticket_automation` → pipeline transitions (PR open → IN_REVIEW,
   approved+green → READY_TO_MERGE, merged → VERIFYING), each an audited `ticket_events` row.
3. Agents → `pipeline_cli` → `/api/tasks/{key}/work/*` → `Pipeline` op in one SQLite transaction → 409 if the
   current state does not allow it.
4. Jay → browser → REST (ccd token) and owner ops (Developer Unlock) → gates confirmed → fixed-text message into the
   relevant herdr pane.
5. Night: `night_loop` → read coordinator pane → idle and empty prompt → fixed reminder via `agent.prompt`.

### 2.4 Runtime / deployment model

- Single host (jay-server). `ccd` and `herdr` as `systemd --user` units with lingering.
- Release of CommandCenter itself: `scripts/go-live.sh` (origin/main only, backup tasks.db, switch checkout,
  build UI, restart ccd, print rollback). UI-only: `scripts/deploy-web.sh` (atomic `current` symlink, keeps
  assets of the last 3 releases).
- Access: SSH tunnel only. No public listener, no Tailscale Serve, no Cloudflare.
- Notifications: launcher tray balloon from `/api/health` gate counter; ntfy URL exists in config (redacted).

---

## 3. What Already Works — retain

| Keep | Why it matters for v2 |
|---|---|
| **tasks.db with trigger-enforced invariants** (never delete, append-only events/findings/evidence, answer-once questions, forward-only migrations with backup) | This is the audit trail v2 needs. Generalise the pattern to decisions/approvals/executions. |
| **Pipeline state machine** (`pipeline.py`) with 409-on-wrong-state, head-SHA-bound review, rework cycle limit, lane limit, writer ownership + checkpoint | This *is* a durable workflow engine for one work item. v2's orchestrator should be built on it, not beside it. |
| **Gates → one Needs Jay queue** | Becomes the Approval inbox ("Needs You"). Same idea, more types, policy-driven. |
| **Pure classifier pattern** (`merge_policy.classify`: dicts in, decision out, denylist wins, policy files can never auto-merge) | Exactly the shape the Autonomy Engine should have. |
| **Fresh independent review bound to exact head** | Core of the Claude + Codex review model. |
| **Night-shift report as a release candidate** (ready to deploy / migrations / rollback / waiting for Jay / findings) | The seed of the Release Composer and the release summary. |
| **Go Live prepares only; guards on the server** (ADR 0006) | Right instinct; v2 replaces "rests on message text" with a capability broker. |
| **Security posture**: loopback, Host/Origin/CSRF, token never in URL/log, Developer Unlock, SSH sign-in, protected files, PTY env scrubbing and scopes, redacted tails, no transcripts in SQLite | Keep all of it. Extend to workers. |
| **Worktree cleanup with exhaustive safety checks** | Model for any destructive automation: many checks, no `--force`, kill switch, recorded reason. |
| **Task records outside repos** (`records.py`) | Becomes artifact storage for work items. |
| **Project registry as the single source of identity** | Evolves into the Project Operating Profile. |
| **herdr for interactive sessions; Task Rooms; pop-outs** | Jay still needs to drop into a live session. Keep herdr for humans; stop using it as the autonomous execution engine. |
| **ADR habit, `docs/jay/*` operator docs, dev instance with fake herdr, canary script** | Keep. v2 decisions should become ADRs *and* Decision records. |
| **Atomic UI releases** (`deploy-web.sh`) and `go-live.sh` with printed rollback | Template for CommandCenter's own autonomous deploy. |

---

## 4. Current Limitations

Ordered by how much they block v2.

1. **No execution layer.** ccd cannot start, own, time out or resume agent work. Autonomy depends on a
   persistent coordinator session being nudged by pasted text, with idle detection by **reading screen text**
   (ADR 0006 calls it best-effort). There is no job, lease, heartbeat, retry or idempotency key.
2. **Enforcement is by convention.** Same Unix user for agents and Jay; ccd token readable by agents; `X-CCD-Actor`
   self-asserted; agents' `gh` is Jay's identity; `config.json` and the auto-merge stop file are agent-writable;
   live-deploy approval lets *any* agent record `deployed`. The docs are honest about this. Bounded autonomy with
   real merge/deploy rights cannot rest on it.
3. **Single node.** Paths like `/srv/server/repos/...` are hard-coded in `registry.py`. No notion of where work may
   run, where a repo may live, or where secrets are.
4. **Policy is fragmented and partly prose.** Registry dicts, classifier lists, `PIPELINE_DEFAULTS`, skill
   Markdown, careful-mode Markdown, ADRs. No version, no hash recorded with each decision, no single place Jay can
   read "what may agents do in SamVision?".
5. **No decision memory.** Questions/answers and findings are stored per ticket but are not searchable as
   precedent, have no rationale/alternatives/reconsider-date fields, and agents are not given them.
6. **No cost visibility.** No per-job token or dollar metering, no budgets, no model tiering policy in code
   (the plan names Opus/Sonnet per role in prose only).
7. **Release ≠ concept.** There is a `release` op and a night report, but no Release entity grouping tickets/PRs
   with version, notes, risk, rollback and deployment record. One PR is linked by a key leading the PR title,
   so many-tickets-to-one-PR is awkward.
8. **Notification surface is thin.** Tray balloon with two integers; ntfy configured; no Slack/email; no digest.
9. **CI is weak as a gate.** Not a required check (free plan), runs on a self-hosted runner that is very likely
   jay-server itself — so agent-authored PR code executes on the production control-plane host. No branch
   protection.
10. **Branch drift.** `claude/amazing-keller-fpy0qw` holds 4 unmerged commits (85 behind main) that change
    policy in the *opposite* direction of ADR 0007 (see Appendix B). Operator docs (`docs/jay/MORNING.md` dated
    2026-10-06, `MY_ACTIONS.md`) are stale; it is unclear whether `auto_merge` was ever switched on live.
11. **UI is a cockpit, not an inbox.** Six nav items built around terminals and tasks; no Decisions, Releases,
    Fleet/Workers, Learning areas.

---

## 5. Gap Analysis

Legend: ✅ exists and is reusable · 🟡 partial / seed exists · ❌ missing.

| v2 capability | Today | Gap / reuse |
|---|---|---|
| Idea → clarification → research → plan | 🟡 `plan` op, `ask` questions, planner role, careful-mode research rules | Need a structured intake/clarify step and a plan *package* schema. |
| Specialist-agent discussion | ❌ | New `Discussion` record. Keep rare. |
| Policy-driven approvals | 🟡 gates (plan/merge/ui/deploy/failure), derived from labels/flags | Generalise into Autonomy Engine + Approval records. |
| Implementation / test | ✅ via coordinator/implementer sessions in worktrees, lane limit | Move autonomous runs to headless jobs on workers. |
| Design review w/ screenshots | 🟡 UI gate; `docs/jay/UI_TESTS.md`; control-room branch has a UI-test skill | Need screenshot capture (Playwright on worker) + artifact storage. |
| Security review | 🟡 reviewer checklist mentions security; denylist | Add a security reviewer *pass* (not necessarily a separate agent) on risk triggers. |
| PR / release composition | 🟡 night report, `release` op | New Release entity + composer. |
| Merge / deploy where authorized | 🟡 low-risk CC auto-merge (off by default); deploy recorded, never run | Capability broker with bot identity; per-project deploy runners. |
| Release summary / lessons / self-evaluation | 🟡 morning report; findings table | New Release summary, AgentReview, scorecards. |
| Project operating modes | 🟡 `merge: owner|low-risk`, `night: careful`, `paused` (branch) | ProjectOperatingProfile. |
| Hard human-only boundaries | 🟡 enforced partly (Developer Unlock for owner ops), partly by text | Autonomy Engine deny rules + broker + separate identity. |
| Tool proposals | ❌ | New record + template + PDF render. |
| Worker fabric (server/laptop) | ❌ | WorkerNode + jobs/leases + worker agent. |
| Decision memory | 🟡 questions/answers, findings | Decision record + retrieval into context packs. |
| Jay Delegate | ❌ | Later; shadow mode first. |
| Slack / email | ❌ (ntfy only) | Phase 2, Slack first for phone approvals (D-006); Socket Mode keeps loopback-only. |
| Artifacts + Drive | 🟡 attachments, task records, reports | Artifact metadata table + storage policy + Drive mirror. |
| Academy / Pulse | ❌ | Later phases, batch-generated. |
| Cost control | ❌ | Metering in Phase 1; budgets in Phase 2. |
| Observability | 🟡 JSON log, events, alerts, health | Per-execution traces, cost, outcomes. |

---

## 6. Proposed v2 Architecture

### 6.1 Shape

```text
                        ┌──────────────────────── CONTROL PLANE (jay-server, ccd) ────────────────────────┐
  Jay ── browser/exe ──▶│  API + UI  ─────────────▶  Autonomy Engine (pure)  ◀── Project Operating Profiles  │
  Jay ── Slack/email ──▶│  Notifier (outbound)       ▲        │                    (versioned, hashed)       │
                        │                            │        ▼                                             │
                        │  Orchestrator ── WorkItem state machine (today's pipeline, generalised)            │
                        │      │   Decisions · Approvals · Discussions · Releases · Artifacts (metadata)     │
                        │      ▼                                                                             │
                        │  Job queue (SQLite: jobs + leases + heartbeats)   Capability Broker (merge/deploy) │
                        │      │                                                 │  GitHub App identity      │
                        └──────┼─────────────────────────────────────────────────┼───────────────────────────┘
                 pull (HTTPS over SSH tunnel)                                   GitHub / deploy targets
              ┌────────┴─────────┐                ┌──────────────────┐
              │ Server worker     │                │ Laptop worker     │  (WSL; outbound only; may vanish)
              │ user: ccagent     │                │ user: jay (WSL)   │
              │ claude -p / codex │                │ claude -p / codex │
              │ worktrees, tests, │                │ local repos,      │
              │ Playwright        │                │ local secrets     │
              └───────────────────┘                └──────────────────┘
   herdr stays: Jay's interactive sessions and Task Rooms (attach to a job's worktree when needed)
```

### 6.2 Control plane (ccd, extended)

- **Stays one process, one host, SQLite.** New modules sit beside today's: `profiles.py`, `autonomy.py`,
  `decisions.py`, `jobs.py`, `broker.py`, `releases.py`, `notify.py`, `artifacts.py`.
- **Orchestrator = today's `Pipeline`, generalised.** A WorkItem's stages become data in the profile (which stages
  apply, which gates), but transitions stay deterministic code with 409 on wrong state. No LLM decides a
  transition; LLMs produce *records* (plan, verdict, evidence) that transitions consume. This is the single most
  important anti-chaos rule and the current system already follows it.
- **The coordinator becomes a job type, not a pane.** A "coordinator run" is a short headless job that reads a
  compact context pack (ticket work record, profile, relevant decisions) and returns structured output. Persistent
  per-project Opus coordinators in herdr become optional (for Jay's interactive use).

### 6.3 Execution workers

Pull-based agents (the Buildkite / GitHub-runner model): a worker registers, heartbeats, claims a job with a
lease, runs it in an isolated worktree under a restricted identity, streams status, uploads artifacts per policy,
and completes or fails the job. See §9.

### 6.4 Agent orchestration

- **Roles are prompts + tool permissions + model, not processes.** Seven roles, as Jay proposed, but
  implemented as job *profiles*: Coordinator, Product/UX, Architect, Builder, QA, Security, Reviewer.
- **Collapse where possible.** Architect and Product/UX run only on plan-package work. Security runs as a review
  pass on risk triggers (paths, dependencies, auth, migrations) — not on every change. QA is the Builder's
  test step plus the Verifier job that exists today.
- **Communication is records, not chat.** Each job reads records and writes records (plan, finding, position,
  verdict). Discussions are explicit and bounded (§12.4).

### 6.5 Approvals and decisions

Every action that crosses a boundary calls `autonomy.decide(action, context, profile)` → `allow`,
`approve(by=…)`, or `deny`. `approve` creates an Approval request (today's gate) bound to a subject hash (plan
hash, head SHA, release id). Approvals are consumed by the Capability Broker, which is the only component that
holds merge/deploy credentials. Detail in §8 and §11.

### 6.6 Artifacts

Metadata in SQLite (`artifacts`), bytes on disk under `~/.local/share/command-center/artifacts/<project>/…`,
optional Drive mirror by policy, never in a product repo (same rule as task records). Restricted projects keep
bytes on the laptop; the control plane stores only title, hash, size and node.

### 6.7 Notifications

One `notify.py` outbox table (transactional outbox pattern): rows written in the same transaction as the event,
delivered by a loop to tray/ntfy/Slack/email with retry and dedupe. Messages link back to CommandCenter.

### 6.8 Integrations

GitHub (poll stays; GitHub App for writes), Claude Code CLI / Agent SDK and Codex CLI on workers, Slack (Socket
Mode), email (SMTP/Gmail API), Google Drive (service connector), Playwright (on workers). Each integration is
behind a small adapter like today's `gh_cli` so tests inject fakes.

### 6.9 Cost model (design constraint, not an afterthought)

| Lever | Effect |
|---|---|
| Short headless jobs with compact **context packs** (the existing `GET /api/tasks/{key}/work` handoff, plus relevant decisions) instead of long-lived coordinator contexts | Avoids replaying large contexts every turn; jobs end. |
| **Model tiering in the profile**: small model for triage/classification/summaries/notifications; mid model for building and routine review; top model for plans, architecture, high-risk review | Most tokens go to the cheapest adequate model. |
| `--max-turns`, wall-clock timeout and per-job **budget** from the profile; job fails to `needs_attention` rather than looping | Bounds runaway runs. |
| Second reviewer (Codex) and Discussions only on risk triggers | Avoids doubling every review. |
| Review on a **review pack** (diff, plan, tests, acceptance), not a repo crawl | Smaller inputs. |
| Remove the screen-reading reminder loop for autonomous work | No re-prompting idle sessions. |
| Pulse/Academy batch weekly/daily with fixed caps | Predictable spend. |
| Metering on every job (`claude -p --output-format json` reports usage and cost; `codex exec --json` reports usage) | You cannot reduce what you do not measure. Subscription plans expose limits rather than dollars, so track tokens and turns as the primary unit. |

---

## 7. Proposed Data Model (conceptual)

All in `tasks.db` (product data), new forward-only migrations, same trigger conventions. Existing tables stay;
`tickets` is the WorkItem.

```text
ProjectOperatingProfile ──< WorkItem (= tickets) ──< Execution ──< Artifact
        │                       │   │                    │
        │                       │   └──< Decision >── Approval
        │                       │          │
        │                       └──< Discussion ──< Position
        │                                    
        └── Release >──< WorkItem (via release_items) ── PR links (ticket_links)
Agent ──< AgentReview      WorkerNode ──< Execution      ToolProposal ── Decision      LearningItem ── WorkItem/Decision
PulseItem ── LearningItem  BudgetLedger ── Execution     AuditEvent (global, append-only)
```

| Entity | Key fields | Notes / reuse |
|---|---|---|
| **ProjectOperatingProfile** | project key, mode (`experimental_autonomy · autonomous_product · controlled_production · restricted`), version, content hash, stages, gates, merge policy, deploy policy, release windows, execution policy, artifact policy, learning level, budgets, model tiers | Source of truth is a YAML file in the CC repo (`policy/projects/<key>.yaml`), loaded at start, hash recorded on every decision. Replaces policy bits of `registry.py`; identity (prefix, legacy) stays in the registry. |
| **Agent** | role, version, prompt ref (skill path + hash), model tier, allowed tools, max autonomy | Today: role strings in `ticket_work.roles`. |
| **WorkerNode** | id, kind (`server · laptop · gpu · cloud`), owner, capabilities (tools, OS, repos present), labels, status, last heartbeat, version, public key | New. |
| **WorkItem** | existing ticket + `profile_version`, `risk_class`, `origin` (Jay idea, agent finding, Pulse), `parent goal` | `tickets` + `ticket_work`. A *Goal* is a parent WorkItem (relations exist). |
| **Execution** (job) | id, work item, role, node constraint, state, lease owner, lease expiry, attempt, idempotency key, input pack hash, outputs, usage (tokens, cost, turns), timings, exit reason | New; replaces "a pane is working on it". |
| **Decision** | project, work item, question, options, decision, rationale, alternatives + why rejected, recommended by, decided by (`jay`, `policy:auto`, `delegate:shadow`), evidence refs, risk, reversible?, decided at, reconsider at/when, supersedes, related PR/release, profile hash | Subsumes `ticket_questions` (keep as view). Append-only; change = new Decision that supersedes. |
| **Approval** | subject type + id + **subject hash** (plan hash, head SHA, release id), action, required approver class, state, approved by, via (UI + Developer Unlock / Slack button / policy), expires at, consumed at | Generalises `ticket_work.gate`. Single-use and hash-bound. |
| **Discussion / Position** | topic, trigger, participants, positions (agent, stance, one-paragraph argument, evidence), resolution, rationale, rounds | Stores concise rationale only, never transcripts. |
| **Artifact** | kind (plan pdf, screenshot, report, deck, release notes, lesson), owner record, storage location(s), hash, size, node, retention, visibility, Drive id | Generalises attachments/records. |
| **ToolProposal** | problem, tool, alternatives (free, self-host, hosted, AWS, Azure), cost, security, lock-in, maintenance, recommendation, status, decision id | Paid → always Jay. |
| **Release** | project, version, items, PRs, risk, notes (technical + client-facing), screenshots, migrations, rollback, window, deploy record, verification, outcome | New; composer output. |
| **AgentReview** | agent, period, metrics (rework, findings escaped, CI failures, unnecessary escalations, cost), wins/blockers/risks/lessons, proposed improvements | Built from data, not self-reported prose. |
| **LearningItem** | topic, depth (quick/coach/deep), source (decision, work item, Pulse), content artifact, exercise, quiz, status | Later phase. |
| **PulseItem** | source, what changed, why it matters, evidence quality, relevance, projects, class (Ignore/Know/Assess/Experiment/Adopt) | Later phase. |
| **BudgetLedger** | project, day, tokens/cost by model and role, limit | Phase 1–2. |
| **AuditEvent** | global append-only: actor (verified), action, subject, policy hash, result | Extends `ticket_events` pattern beyond tickets. |

**Identity rule.** `actor` must become *verified*: per-worker and per-job tokens minted by ccd, so `agent:builder@server/job-123`
is something ccd issued, not something a process claimed.

---

## 8. Autonomy Policy Model

### 8.1 Engine

```text
decide(action, subject, context, profile) → Allow | RequireApproval(class, reason) | Deny(reason)
```

- **Pure** (same discipline as `merge_policy.classify`): no I/O, exhaustively unit-tested, table-driven.
- **Action taxonomy** (closed enum): `read_repo, write_branch, run_tests, open_pr, merge_pr, deploy(env), run_migration(env),
  modify_prod_data, add_dependency, add_tool(free|paid), change_ci, change_policy, change_secret, spend_money,
  external_message, ui_change(minor|major), create_release, delegate_decision`.
- **Merging is a per-project policy, not a global ban (D-001).** The old global rule "agents never merge"
  (ADR 0007) is replaced by each profile's `merge` and `deploy` blocks. What stays global is *who presses the
  button*: the Capability Broker merges and deploys when the engine says `Allow`; an agent's own credentials never
  carry merge or deploy rights.
- **Global hard denies / human-only** are compiled in code, not in profiles, so no profile edit can remove them:
  `spend_money, change_secret, modify_prod_data(destructive), legal_decision, change_policy, change_agent_permissions,
  major_live_client_redesign, irreversible_high_risk` → always `RequireApproval(jay)`; `delegate_decision` on any of
  those → `Deny`.
- **Profiles can only tighten** the global rules and choose among allowed options for the rest.
- **Policy changes are themselves human-only**: `policy/**` is in the merge denylist (as `merge_policy.py` already
  does for itself), and ccd records the loaded profile hash; a profile whose hash changed without a matching
  Jay-approved Decision loads as *read-only/most-restrictive* and raises an alert.

### 8.2 Risk classification

Deterministic first, LLM second: paths touched, dependency/manifest changes, migrations present, auth/security
paths, UI paths, lines changed, environment. An LLM may *raise* a risk class, never lower it.

### 8.3 Sample profiles

```yaml
# policy/projects/commandcenter.yaml
project: commandcenter
mode: experimental_autonomy
decisions: [D-001]
stages: [plan, build, review, merge, verify, deploy, release_note]
plan_approval: none                 # agents plan and proceed
review:
  claude: always
  codex: on_risk [high]             # second reviewer only for high risk
merge:
  policy: auto                      # broker merges when gates pass
  requires: [ci_green, review_approved_at_head, risk <= medium]
  never_auto_paths: [policy/**, server/ccd/security.py, server/ccd/autonomy.py, server/ccd/broker.py, .github/**]
deploy:
  env: live
  policy: auto
  requires: [merged, verify_pass, canary_health_ok]
  rollback: scripts/go-live.sh --rollback   # must exist before auto deploy is enabled
  window: any
notify: { release: concise, action_required_only: true }
execution: { allowed_nodes: [server], preferred_node: server, repo_storage: server, secrets: server-scoped }
artifacts: { store: server, drive_mirror: releases_only }
learning: contextual
budget: { daily_tokens: 2_000_000, per_job_turns: 40 }
models: { triage: small, build: mid, plan: top, review: mid, review_high_risk: top }
```

```yaml
# policy/projects/gyst.yaml
project: gyst
mode: autonomous_product
decisions: [D-001, D-005]
plan_approval: on_risk [high]
review: { claude: always, codex: on_risk [high], security: on_paths [auth/**, **/migrations/**, deps, crypto/**] }
merge: { policy: auto, requires: [ci_green, review_approved_at_head, security_pass_if_required, risk <= medium] }
deploy: { env: live, policy: auto, requires: [verify_pass, health_ok], rollback: required }
personal_data:                       # D-005
  require_approval_for: [data_model_change, retention, privacy, encryption, deletion,
                         health_or_personal_data_handling, authentication, irreversible_migration]
  auto_allowed: ui_or_api_fix_on_existing_personal_data if [reversible, tests_pass, no require_approval_for trigger]
  triggers: { paths: [**/migrations/**, **/models/**, **/schema*, auth/**, crypto/**],
              keywords_in_diff: [retention, delete, purge, encrypt, decrypt, token, password] }   # can only raise risk
data: { prod_destructive: jay }
execution: { allowed_nodes: [server], repo_storage: server }
notify: { release: summary, needs_you: slack_immediate }
learning: contextual
```

```yaml
# policy/projects/samvision.yaml   (myfamilyexpenses: same mode, own windows)
project: samvision
mode: controlled_production
decisions: [D-001, D-004]
plan_approval:
  required_for: [ui_change.major, ui_change.minor_client_visible, workflow_change, api_change, migration, risk >= medium]
  package: full                       # §11.3 Plan Approval Package
  reviewers: [claude, codex]          # both, before Jay
  flow: plan -> claude -> codex -> jay -> build
small_safe_changes: { batch: true, max_risk: low, examples: [copy, internal refactor with tests, bug fix no UI] }
merge: { policy: owner_or_release_train }   # Jay accepts the release PR, not each task
release:                              # D-004
  train: weekly_windows
  windows: ["Thu 01:00 America/Winnipeg", "Sat 01:00 America/Winnipeg"]
  unattended_deploy:
    allowed_when: [risk == low, no_migration, no_meaningful_downtime, low_blast_radius, no_client_workflow_change]
    requires_capabilities: [health_checks, auto_rollback]   # both false today → every window is release-ready only
  otherwise: prepare_and_hold_for_jay   # migrations, downtime, high blast radius, client-facing workflow change
  client_note: required
research: careful                     # today's careful.md: evidence-backed plans
constraints:
  never: [prod docker compose up/down/build/restart, prod database, licensed data in outputs, property records in screenshots]
execution: { allowed_nodes: [server], repo_storage: server }
artifacts: { store: server, drive_mirror: plan_packages_and_releases, redact: [property_records] }
learning: deep
```

```yaml
# policy/projects/employer-java-example.yaml   (restricted)
project: acme-java
mode: restricted
decisions: [D-002]                                      # AI use permitted by Jay's employer
execution:
  allowed_nodes: [laptop]
  preferred_node: laptop
  repo_storage: laptop_only
  server_repo_access: prohibited
  server_clone: requires_approval(jay)                  # only if Jay explicitly allows it, per repo
  secrets: laptop_only
  model_providers: [anthropic, openai]                  # AI jobs are NOT refused
artifacts:
  store: laptop_only
  control_plane_metadata: [title, status, hash, size]    # no code, no diffs, no screenshots leave the laptop
  drive_mirror: never
plan_approval: always
merge: { policy: owner }
deploy: { policy: never }
notify: { slack: titles_redacted, email: off }
learning: contextual   # lessons generalised; no employer code quoted
```

---

## 9. Worker Architecture

### 9.1 Model

Pull, lease, heartbeat — the pattern GitHub Actions runners, Buildkite agents and Temporal workers all share,
implemented on SQLite.

```text
worker ──register(pubkey, caps)──▶ ccd  (Jay approves a new node once: Approval{action:add_worker})
worker ──claim(node, caps)───────▶ ccd: UPDATE jobs SET lease_owner=?, lease_until=now+90s, attempt=attempt+1
                                         WHERE state='queued' AND node constraint matches LIMIT 1   (one transaction)
worker ──heartbeat(job, progress)─▶ ccd: extend lease (every 30 s)
worker ──checkpoint(job, data)────▶ ccd: durable progress (branch, commit, step), reuses `writer` checkpoint idea
worker ──complete/fail(job, out)──▶ ccd: transition WorkItem via Pipeline op (idempotency key = job id + attempt)
reaper loop: lease_until < now → job back to 'queued' (attempt+1) or 'needs_attention' after N attempts
```

- **Transport.** Workers call ccd's API; never the DB. ccd stays loopback-only. The server worker is local. The
  laptop worker reaches ccd through an outbound SSH tunnel (the launcher already does this from Windows; the WSL
  worker can use the same `ssh -N -L`). No inbound port on the laptop.
- **Auth.** Each node has its own token (minted at enrolment, scoped to `jobs/*` for its node and its projects);
  each job gets a short-lived job token scoped to its work item. Neither can call owner ops.
- **Isolation.** Server worker runs as a separate Unix user `ccagent` (no access to `~jay/.config/command-center`,
  no Jay `gh` login, no prod compose). Each job: own worktree, reduced env (as `pty.py` already does), systemd
  transient scope with CPU/memory/time limits, network egress allowlist where practical.
- **Agent runners.** `claude -p` (or the Agent SDK) with explicit `--allowedTools`, permission mode and
  `--max-turns`; `codex exec` with its sandbox mode. Both return JSON with usage.

### 9.2 Laptop worker (Windows + WSL)

- Runs inside WSL as a user service (`systemd` in WSL or a small supervisor started by the launcher).
- Advertises only the repos that exist locally and the tools installed.
- Restricted projects: the job payload contains only the work item text and profile; the worker clones/uses the
  local repo; results returned are metadata + summaries filtered by the profile (`control_plane_metadata`).
- Secrets come from the laptop (Windows Credential Manager / WSL keyring / `.env` the user keeps), never from ccd.

### 9.3 Disconnect, retry, failure

| Situation | Behaviour |
|---|---|
| Laptop sleeps mid-job | Lease expires after 90 s without heartbeat → job `queued` again with `attempt+1` but **pinned** to the laptop (only node allowed). On reconnect the worker reports its local state; if the worktree has a checkpoint, the new attempt resumes from it instead of restarting. |
| Worker crashes | Same as above; the reaper requeues. Idempotency keys make the `complete` call safe to repeat. |
| ccd restarts | Jobs are rows; leases continue; workers retry API calls with backoff (today's WS client already does this). |
| Job loops / overspends | `max_turns`, timeout, budget → `needs_attention` + Needs You item. Never auto-retried past N=2. |
| Side effects (push, PR) | Only after a checkpoint; PR open is idempotent by branch; merges/deploys never done by workers (broker only). |
| Two workers claim | Impossible: claim is a single conditional UPDATE in SQLite (serialized writer). |
| Node offline > policy limit | Work items for laptop-only projects show "waiting for laptop" in Needs You (no alarm unless overdue). |

### 9.4 What runs where

| Work | Server worker | Laptop worker | Control plane |
|---|---|---|---|
| CC / GYST / SamVision / MFE build, test, screenshots | ✅ | optional | — |
| Restricted repo build/test | ❌ prohibited | ✅ | metadata only |
| Merge, deploy | ❌ | ❌ | broker (GitHub App / deploy runner with its own creds) |
| Pulse fetch, Academy generation | ✅ (low priority) | — | — |

---

## 10. Security Threat Model

Assets: Jay's GitHub identity, production hosts (SamVision stack on jay-server), customer/licensed property
data, employer code, secrets (.env, API keys, Claude/Codex credentials), ccd tokens, tasks.db, policy files.

| # | Threat | Today | v2 control |
|---|---|---|---|
| T1 | **Agent escalates authority** (edits policy/config, turns on auto-merge, writes stop file, reads token) | Same Unix user; mitigated only by rules and review (ADR 0007 says so) | Separate `ccagent` user; policy files root-of-trust in CC repo + denylist + hash check; ccd config not writable by agents; per-job tokens; owner ops need Developer Unlock (keep). |
| T2 | **Agent merges/deploys** | Agent `gh` = Jay; "agents never merge" is a rule | Agents get a GitHub token with `contents:write` on branches only (fine-grained PAT or App installation token without merge rights); Broker holds merge/deploy creds and only acts on a consumed, hash-bound Approval or an `Allow` from the engine. **No paid GitHub plan (D-003):** enforcement is broker-side plus CI, review rules and whatever protections the current plan offers; a paid tier comes back only as a Tool Proposal if it would materially improve safety. Residual risk: a process running as Jay with Jay's `gh` login could still merge; Phase 2 removes that login from agent jobs (`ccagent` user). |
| T3 | **Arbitrary code execution from PRs on prod host** | Self-hosted CI runner likely on jay-server | Move CI to GitHub-hosted runners, or a dedicated VM/container user with no access to prod/compose/ccd state. |
| T4 | **Prompt injection** (issue text, PR comments, web pages in Pulse, dependency READMEs, tool output) | Fixed-text messages to panes; free text never typed into Claude (good) | Treat all fetched content as data: context packs mark untrusted sections; agents' tool permissions are minimal per role; any action from an agent passes the engine, so an injected instruction still cannot merge/deploy/spend. Pulse runs in a no-tools, no-repo job. |
| T5 | **Malicious dependency / skill / MCP server / plugin** | Merge denylist covers manifests, lockfiles, `.claude/`, `SKILL.md`, `.mcp.json` | Keep; add `add_dependency` and `add_tool` actions (free → lightweight review incl. maintainer/age/download/advisory checks; paid or MCP with network/secret access → ToolProposal → Jay). Pin versions; lockfile diff shown in review pack; `npm ci`/`pip install --require-hashes` where feasible. |
| T6 | **Secret leakage** into tickets, reports, Slack, Drive, artifacts | Redactor on tails; protected file list; "no secrets in SQLite" | Same redactor on every outbound record and notification; artifact scanner (secret patterns) before Drive/Slack; restricted profiles never send content. |
| T7 | **Employer code exfiltration** | N/A | Laptop-only execution; no server clone; metadata-only control plane; model providers Anthropic and OpenAI (permitted, D-002); server clone only with explicit Jay approval; Slack titles redacted. |
| T8 | **Laptop worker compromised** | N/A | Node token scoped to its node; cannot claim server jobs; Jay approves enrolment; revocation in UI; worker cannot call owner ops. |
| T9 | **ccd token theft** (another local user, browser) | Strong controls (Host/Origin, 0600, no URL tokens, CSP) | Keep; add per-actor tokens so a leaked agent token ≠ Jay. |
| T10 | **Jay Delegate abuse / drift** | N/A | Delegate may only act on actions the engine marks `delegable` (reversible, low risk, not on the hard list); compiled deny on money/secrets/destructive/legal/major redesign/permissions; shadow mode first with measured accuracy; every delegated decision is a Decision with `decided_by: delegate`, visible in a daily digest, one-click revert; Jay can disable instantly (kill switch file + UI). Delegate cannot change its own scope (that is `change_agent_permissions`). |
| T11 | **Destructive automation** (worktree removal, data ops) | Exhaustive checks, no `--force`, kill switches | Keep the pattern for every new destructive action; prod data ops always Jay. |
| T12 | **Notification channel spoofing** (approve via Slack) | N/A | Approvals accepted only from the Slack user id bound to Jay, in a DM or the project channel, verified by Slack's signed Socket Mode payloads; each button carries the Approval id + subject hash and expires; see the channel matrix in §11.4. |
| T13 | **Supply chain of CC itself auto-deploying** | `go-live.sh` from main only | CC auto-deploy requires the broker, CI green on GitHub-hosted runners, verify, canary health, automatic rollback; changes to `autonomy.py`, `broker.py`, `security.py`, `policy/**` never auto-merge. |

---

## 11. Human Approval Architecture

### 11.1 Flow

```text
Agent proposes action ──▶ autonomy.decide ──Allow──▶ broker/worker executes ──▶ AuditEvent
                                  │
                                  ├─RequireApproval(class)─▶ Approval(subject hash) ──▶ Needs You (+ notify per policy)
                                  │                              │ Jay approves (UI+Developer Unlock | Slack for low/med)
                                  │                              ▼
                                  │                         Approval consumed once by broker ──▶ executes ──▶ AuditEvent
                                  │                              │ subject changed (new head, new plan hash) → Approval void
                                  └─Deny──▶ recorded; agent told why; Needs You only if it blocks the work item
```

### 11.2 Rules

- **Hash-bound and single-use** (today's review-at-head idea applied everywhere).
- **Expiring.** Approvals expire (default 72 h; release approvals at window end).
- **Batched.** Needs You groups by project and decision type; "approve all low-risk in this release" is one click
  where policy allows.
- **One action per card** (today's "the one action" principle).
- **Revisions loop**: Jay "request changes" → WorkItem back to plan → re-review per profile → new Approval.
- **No stale asks**: before asking, the engine searches Decisions for a precedent with matching question signature
  and still-valid reconsider date; if found, it applies it (`decided_by: precedent`) and cites it.

### 11.3 Plan Approval Package (controlled production)

Fields exactly as Jay listed (goal, problem, solution, affected screens/APIs, architecture impact, blast radius,
downtime, DB/migration, data/security, rollback, tests, before screenshots, proposed after mockups, discrepancies,
new ideas, client impact, client-facing note, Claude verdict, Codex verdict, risk). Stored as a structured record
plus a rendered artifact (HTML/PDF). The Approval's subject hash is the package hash, so any change after Jay
approves re-opens it.

### 11.4 Approval channels (D-006: Slack first, phone included)

Slack is the first interface for approving from the phone. CommandCenter stays loopback-only; Slack reaches
ccd through Socket Mode (an outbound connection from ccd), so nothing new is exposed. Proposed matrix (Claude's
proposal, to be confirmed by Jay):

| Approval class | Slack (phone) | CommandCenter UI (Developer Unlock) |
|---|---|---|
| Questions, "choose A/B", retry / pause / resume a job, acknowledge a release | one tap | ✅ |
| Low / medium risk: plan approvals, release-ready → deploy within policy, merge of a held PR | one tap, card shows summary + risk + link | ✅ |
| High risk: major client-impacting change, migration, downtime, GYST personal-data triggers (D-005) | tap **plus** a Slack confirmation dialog that repeats what will happen and the short subject hash | ✅ |
| Hard human-only boundaries: money / paid service, credentials or secrets, destructive production data, legal | Slack shows the request and can **reject or defer**; approval waits for the UI until a secure remote-access option exists (Phase 6) | ✅ |
| Policy / profile changes, agent permission changes | never from Slack | ✅ only |

Every Slack approval records `via: slack`, the Slack user id, message ts and the Approval subject hash; a stale
button (subject changed, expired, already consumed) answers "this request changed, open the new one".

---

## 12. Claude + Codex Review Model

### 12.1 Principles

1. **Independence = different context, not necessarily different vendor.** A fresh Claude session that did not
   write the code already catches most issues (this is today's rule, and the CC-026/SV-064 pilots show it working).
   A second vendor adds value mostly on *plans* and *high-risk* diffs where correlated blind spots matter.
2. **Review the pack, not the repo.** Reviewers get: plan/acceptance criteria, diff, test results, risk report,
   relevant decisions. They may read more files, but the default budget is small.
3. **Bound to the subject hash.** Same as today: verdict at exact head SHA or plan hash.

### 12.2 When each reviewer runs

| Subject | Claude reviewer | Codex reviewer | Security pass | Design pass |
|---|---|---|---|---|
| Routine code change, risk low | ✅ (mid model) | — | — | — |
| Code change, risk medium | ✅ | — | if trigger paths/deps | if UI paths |
| Code change, risk high | ✅ (top model) | ✅ | ✅ | if UI |
| Plan package (controlled production) | ✅ | ✅ (profile says both) | if trigger | ✅ with screenshots |
| CC self-change touching autonomy/broker/security/policy | ✅ | ✅ | ✅ | — + Jay (never auto) |

### 12.3 Disagreement

Reviewers return structured verdicts (`APPROVE | REQUEST_CHANGES`, findings with severity and evidence). If they
disagree on a blocking finding: one reconciliation round where each sees the other's finding and answers in ≤150
words; still split → Needs You with both positions side by side. Never more than one round.

### 12.4 Discussions (specialist agents)

Triggered only by: reviewer disagreement, a plan with risk ≥ medium where Architect and Product/UX are both
required, or an agent explicitly challenging a Jay instruction. Format: proposer + ≤3 consulted roles, one
position each (stance + ≤150-word argument + evidence), resolution by deterministic rule (unanimous → proceed;
split → escalate per profile). UI shows "3 agree · 1 concern resolved"; expand shows positions and final
rationale. No transcripts, no chain-of-thought.

### 12.5 Cost guard

Each review job has a turn and token cap; the profile's `review.codex: on_risk` is the main saving. Track
"findings per 1k tokens" per reviewer in AgentReview to see whether the second reviewer earns its cost.

---

## 13. UI Information Architecture

Jay's proposed ten areas (Command, Projects, Needs You, Decisions, Agents, Reviews, Pulse, Academy, Artifacts,
Settings) are too many top-level destinations for a one-person operator; Reviews and Artifacts are facets of work,
not places, and the current UI already learned this (it went from ten sections to six, ARCHITECTURE.md). Proposal:
**seven** areas, inbox-first (the pattern used by Linear, GitHub's notifications, and incident tools):

| Area | Answers | Absorbs |
|---|---|---|
| **Home** | What needs me, what shipped, what's in flight, is anything broken | Command; today's Dashboard |
| **Needs You** (badge; also top of Home) | Every approval/question/blocker, grouped, one action each | Today's Needs Jay; plan approvals; tool proposals awaiting Jay |
| **Work** | Projects → goals → work items → executions; reviews and artifacts *inside* each item | Projects, Task Manager, Reviews, Development, Artifacts (as a tab) |
| **Releases** | Release trains per project, what's going out, release notes, deploy status | PR/Release composer |
| **Decisions** | Searchable institutional memory, discussions, precedents, reconsider-due | Decisions |
| **Fleet** | Agents (roles, scorecards, weekly review), workers/nodes, budgets and cost | Agents, Server, worker status |
| **Learn** | Today's lesson, weekly lecture, curriculum, Pulse briefing | Academy + Pulse (Pulse items feed lessons) |
| Workspace | (kept as a tool, reachable from any work item and Ctrl+K) | Today's Workspace/Task Rooms/Files |
| Settings | Policies (read-only view + proposal flow), integrations, tools, tokens | Settings, Diagnostics |

Workspace and Settings are utilities (icons), not part of the seven.

---

## 14. Suggested UX (ASCII wireframes)

### 14.1 Home

```text
┌ CommandCenter ─────────────────────────────────────────────── ● server  ◐ laptop(offline)  $ 41% of week ┐
│ Home  Needs You (3)  Work  Releases  Decisions  Fleet  Learn                              ⌘K   ⚙        │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ NEEDS YOU (3)                                       │ SHIPPED SINCE YESTERDAY                            │
│ ▸ SamVision · Plan approval · Rental analysis v2    │ CommandCenter 0.14.2 · 3 features · 2 fixes · no action│
│   risk MED · Claude ✓ Codex ✓ · [Review plan]       │ GYST 2026.10.20 · 1 feature · deployed 02:14 ✓      │
│ ▸ GYST · Tool proposal · Postmark ($15/mo) [Decide] │                                                    │
│ ▸ SamVision · Release Thu 01:00 · 6 items [Open]    │ IN FLIGHT                                          │
│                                                     │ SV-112 building ▓▓▓▓░ server · 18 min · 41k tok    │
│ BROKEN                                              │ CC-061 review (Claude) · server                    │
│ ✓ nothing broken · CI green · all deploys healthy   │ ACME-7 waiting for laptop                          │
├─────────────────────────────────────────────────────┴────────────────────────────────────────────────────┤
│ TODAY'S LESSON (6 min) · Leases vs locks: why your job queue doesn't need Redis        [Start]   [Later] │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 14.2 Project

```text
┌ Work › SamVision ─────────────────────── mode: CONTROLLED PRODUCTION · next window Thu 01:00 · policy v7 ┐
│ Goals              │ Rental analysis feels like an expert REALTOR tool             ▓▓▓░░ 3/7 items    │
│  ▸ Rental analysis │  SV-110 Comparable rent bands      DONE   PR #131 merged                       │
│  ▸ Valuation PDF   │  SV-111 Cap-rate explanation card  REVIEW Claude ✓ Codex …                     │
│                    │  SV-112 Vacancy assumptions panel  BUILD  server · 18 min                      │
│ Release train      │  SV-113 Rent roll import           PLAN   needs your approval ●                │
│  Thu: 4 items      │                                                                               │
│  Sat: 2 items      │ Decisions in this project (12)  ·  Artifacts (9)  ·  Cost this week 1.2M tok  │
└────────────────────┴───────────────────────────────────────────────────────────────────────────────┘
```

### 14.3 Needs You

```text
┌ Needs You ─────────────────────────────── group: [project ▾]  filter: [all risks ▾]  ⎘ approve all LOW ┐
│ SAMVISION                                                                                            │
│  ● Plan approval   SV-113 Rent roll import        MED  Claude ✓ Codex ✓  2 h ago   [Review]          │
│  ● Release         Thu 01:00 window · 6 items     MED  verify ✓ · rollback ready   [Open release]     │
│ GYST                                                                                                 │
│  ● Tool proposal   Postmark transactional email   $15/mo · free alt: SES ($0.10/1k) [Decide]          │
│ COMMANDCENTER                                                                                        │
│  ○ FYI             0.14.2 deployed · no action                                     [Dismiss]          │
│ ACME-JAVA                                                                                            │
│  ● Question        ACME-7 Which module owns retry config?   (asked once; no precedent) [Answer]       │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 14.4 Plan approval

```text
┌ SV-113 · Rent roll import — PLAN APPROVAL ─────────────────── risk MED · package v2 · hash 3f9a… ┐
│ Goal  Import a landlord's rent roll (CSV/XLSX) so rental analysis uses actual rents.            │
│ Problem  Agents type rents by hand; errors common.        Client impact  New button on Analysis │
│ ┌ Before ─────────────┐ ┌ After (mockup) ─────────┐     Blast radius  Analysis page, /api/rents │
│ │ [screenshot]        │ │ [mockup]                │     Migration  +1 table, reversible          │
│ └─────────────────────┘ └─────────────────────────┘     Downtime  none  · Rollback  feature flag │
│ Reviews   Claude APPROVE (2 notes)   Codex APPROVE (1 concern: XLSX macro files → resolved)      │
│ Discussion  3 agents agree · 1 concern resolved  [expand]                                       │
│ Client note  "You can now upload a rent roll…"                                                  │
│ Tests  parser unit tests, 3 fixture files, e2e upload                                           │
│                       [Request changes…]   [Approve plan]  (Developer Unlock)                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 14.5 Decision discussion

```text
┌ Decision D-0214 · SamVision · "Store rent rolls as rows or as the original file?" ───────────────┐
│ Decision  Rows + keep original file as artifact (90 days)        Decided by  Jay · 2026-10-21    │
│ Recommended by  Architect   Agree: Builder, Security   Concern: Product/UX (resolved)            │
│ ▾ Positions                                                                                       │
│   Architect   ROWS — queryable, validates on import; original kept for audit.                    │
│   Product/UX  CONCERN — users want to re-download what they uploaded → resolved: keep original.  │
│   Security    ROWS — original may hold tenant PII; 90-day retention, not in Drive.               │
│ Alternatives rejected  File only (not queryable) · Rows only (no audit trail)                     │
│ Reconsider  when multi-property imports ship · Related  SV-113, PR #134                           │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 14.6 Agent review (weekly, Saturday 08:00)

```text
┌ Fleet › Weekly review · week 43 ──────────────────────────────────────────────────────────────────┐
│ Wins      12 items shipped · 0 escaped defects · CC auto-deploy 9/9 healthy                       │
│ Blockers  laptop offline 3 days (ACME-7 waiting)                                                  │
│ Risks     Builder rework rate up 18% → 27% on SamVision UI items                                  │
│ Lessons   Screenshots missing on 2 plan packages (Product/UX) → checklist item added (auto, low)   │
│ Next week Rent roll import; Pulse: evaluate new Claude Code hooks                                 │
│ ───────────────────────────────────────────────────────────────────────────────────────────────── │
│ Agent        items  rework  escaped  unneeded esc.  tokens   trend                                │
│ Builder        14    27%      0          1          3.1M     ▲ rework                             │
│ Reviewer       19     —       0          0          1.2M     ─                                    │
│ Codex review    4     —       0          —          0.6M     findings/1k tok 0.4  (keep? → Q)     │
│ Proposed improvements: 1 auto-applied (low) · 1 needs you (give Builder Playwright) [Review]      │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 14.7 Worker / node status

```text
┌ Fleet › Workers ─────────────────────────────────────────────────────────────────────────────────┐
│ NODE            KIND    STATUS     HEARTBEAT  RUNNING            PROJECTS             VERSION     │
│ jay-server      server  ● online   2 s        SV-112, CC-061     cc, gyst, sv, mfe    0.3.1       │
│ jay-laptop-wsl  laptop  ○ offline  3 d        —  (ACME-7 queued) acme-java            0.3.0 ⚠     │
│ ──────────────────────────────────────────────────────────────────────────────────────────────── │
│ Queue: 2 queued · 2 running · 0 needs attention     Leases: 90 s · heartbeat 30 s                │
│ [Enrol a node]  [Revoke]  [Drain]                                                                 │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 15. PR / Release Composer

**Challenge first.** "Internal tasks ≠ PRs" is right; "group 17 tasks into one PR" is right only for some
projects. Large PRs are harder to review well (reviewer quality drops with diff size — this is why today's
low-risk classifier caps at 10 files / 300 lines), harder to bisect and harder to revert. The thing Jay wants to
avoid is *being notified about* 17 PRs.

Design:

| Mode | PR shape | What Jay sees |
|---|---|---|
| experimental_autonomy (CC) | Small PRs per coherent change; auto-merged by broker | One release notification: version, features, fixes, action required yes/no |
| autonomous_product (GYST) | Small PRs; auto-merged | Release summary per deploy |
| controlled_production (SamVision, MFE) | Work merges into a **release branch** per window (`release/sv-2026-10-23`) via small reviewed PRs; one **release PR** release → main composed for Jay | One release PR with: what changed, why, affected areas, risk, screenshots, tests, deployment impact, client note |
| restricted | Per employer process | Per employer process |

Composer job (small model + deterministic assembly): takes merged items since last release, groups by goal/area,
writes the summary from the records (plans, verdicts, evidence — not from re-reading the code), attaches
screenshots, computes risk = max(item risks), lists migrations and rollback, and produces the client-facing note.
Large isolated or high-risk items get their own release PR. Many-tickets-to-one-PR needs `ticket_links` matching
by explicit link (not only title-leading key) — a small change to the existing automation.

---

## 16. Learning Architecture

- **Source of lessons = real work.** Each day the system has Decisions, review findings and Discussions with
  rationale. A nightly small-model job picks ≤1 candidate concept (e.g. "leases", "transactional outbox",
  "head-bound approvals") using the profile's learning level, and drafts a 5–10 minute lesson tied to that record.
- **Depth selection.** Deterministic first: Off → nothing; Contextual → QUICK/COACH in the work item itself
  ("why we chose X", 3–6 sentences); Deep → a LearningItem with DEEP DIVE template (concept, mental model,
  terminology, industry practice, AWS/Azure/self-host equivalents, mistakes, application to Jay's project,
  exercise, quiz, resources). Jay can override per item.
- **Curriculum.** A static YAML curriculum (Jay's topic list) with coverage tracking; the weekly lecture fills the
  least-covered topic that the week's work touched. Quiz results feed spaced repetition (simple Leitner boxes —
  no ML needed).
- **Cost.** Daily lesson ≈ one small/mid model call with a short context; weekly lecture one top-model job, capped.
- **Videos/resources.** Recommended links only from a curated allowlist of sources, verified to exist at generation
  time; never fabricated.

---

## 17. Pulse Architecture

- **Weekly batch, not a feed.** Fetch from a fixed source list (vendor changelogs/RSS, GitHub releases of tools
  in use, security advisories for dependencies in Jay's lockfiles, a few curated blogs, HN front page top-N,
  arXiv categories) into a staging table.
- **Pipeline.** Dedupe → relevance filter against Jay's stack (lockfiles, tools in profiles, Academy topics) with a
  small model → top ≤10 items get a mid-model write-up answering: what changed, why it matters, evidence quality,
  relevance, projects, recommendation, class (Ignore/Know/Assess/Experiment/Adopt).
- **Security advisories are not Pulse.** A CVE in a dependency becomes a WorkItem directly (deterministic match).
- **Adopt/Experiment** creates a ToolProposal or a WorkItem; never a change by itself.
- **Injection safety.** Pulse jobs run with no tools besides fetch, no repo, no secrets; output is a record.

---

## 18. Slack / Email Integration Strategy

- **Slack is the first phone interface (D-006), so it moves to Phase 2**, right after Approvals exist (Phase 1).
  One bot posts to `#commandcenter`, `#samvision`, `#gyst` (plus a DM to Jay for anything that needs him) from the
  notification outbox: Needs You, questions, choose A/B, blockers, plan ready, release ready, deployed, major
  failures, weekly report. Every message links to the CommandCenter record. Dedupe and quiet hours from the profile.
- **Slack Socket Mode** for interactivity (buttons, dialogs, retry/pause, later `@architect`) keeps CommandCenter
  loopback-only: ccd opens an outbound WebSocket to Slack; no public endpoint, no change to the local-access rule.
- **Buttons** follow the channel matrix in §11.4, bound to Jay's Slack user id.
- **Secure remote access later (Phase 6, separate design and approval).** Options to compare then: a private
  tailnet (Tailscale/Headscale) reaching the existing SSH tunnel, or an identity-aware tunnel (Cloudflare Access).
  Requirements: never publicly reachable, device + identity authentication in front of ccd's own token and
  Developer Unlock, revocable per device. AWS analogue: Verified Access / Client VPN; Azure: Entra Private Access /
  Point-to-site VPN.
- **@agent chat** (later): a Slack message becomes a `question` record routed to a role job; the answer is posted
  back with a link. Canonical data stays in CommandCenter.
- **Links work only where the tunnel exists.** Today CommandCenter is reachable only through SSH from Jay's
  Windows machine, so Slack cards must carry enough to decide on the phone (summary, risk, what happens, key
  screenshot thumbnails where the profile allows); the CommandCenter link is for the desk.
- **Email**: a daily digest + release summaries via SMTP/Gmail; no inbound email commands.
- **Restricted projects**: titles redacted or channel disabled per profile.

---

## 19. Storage Strategy

| Data | Where | Notes |
|---|---|---|
| Control-plane state | `tasks.db` (product), `ccd.db` (ops, pruned) | SQLite WAL; nightly online backup (SQLite backup API, as import/go-live already do) to a second disk + offsite (Drive or object storage) |
| Artifacts (internal) | `~/.local/share/command-center/artifacts/<project>/<record>/<hash>.<ext>` | Content-addressed; metadata row; retention per kind |
| Artifacts (shareable) | Google Drive folder per project, mirrored by policy (`releases_only`, `plan_packages_and_releases`) | Drive id stored on the artifact; CommandCenter remains the index |
| Restricted project artifacts | Laptop only; control plane stores title/hash/size/node | Never mirrored |
| Repos | Server: `/srv/server/repos/*` (today); laptop: local paths advertised by the worker | Profile `repo_storage_policy` |
| Secrets | Never in CommandCenter. Server: per-service env files readable only by the service user; laptop: local | Agents get scoped tokens only |
| Transcripts | Not stored (today's rule). Execution keeps usage, outputs, summaries | Keep the rule |

---

## 20. Build vs Buy — orchestration and durable execution

The requirement is: a few concurrent jobs (2 lanes per project × ~5 projects), minutes-to-hours long, on 1–2
nodes that may disconnect, with resumability, exactly-once *effects* (merge, deploy), audit, and a human in the
loop for hours or days. One control-plane host.

| Option | Fit | Ops cost | Notes | AWS / Azure analogue |
|---|---|---|---|---|
| **A. SQLite state machine + jobs/leases table in ccd** (extend today) | ✅ Good | None new | The pipeline already provides transactional transitions, 409 on wrong state, audit. Add `jobs` with lease/heartbeat/attempt/idempotency, a reaper loop, and a notification outbox. Human waits are just states. | Step Functions + DynamoDB conditional writes; Durable Functions + Table storage |
| B. Postgres + a queue library (pg-boss, River, Procrastinate) or DBOS | 🟡 Good later | Postgres service, backups, migration | Worth it only if CommandCenter becomes multi-host or many writers. DBOS (durable workflows on Postgres) is the lightest "real" durable-execution option if A outgrows itself. | RDS/Aurora + SQS; Azure Database for PostgreSQL + Service Bus |
| C. Redis + RQ/BullMQ/Celery | ❌ Poor | Redis, persistence tuning | Adds a second source of truth; job state must still be mirrored into SQLite for audit; durability depends on Redis config. Solves throughput, which is not the problem. | ElastiCache + SQS; Azure Cache for Redis |
| D. NATS JetStream | ❌ Poor | NATS server | Great messaging fabric for many services/edges; here there is one service. Leases/heartbeats are easier in a DB. | Amazon MQ / EventBridge; Event Grid / Service Bus |
| E. Temporal (self-hosted or Cloud) | ❌ Overkill now | Self-host: server + Postgres/Cassandra + UI, upgrades; Cloud: paid | Best-in-class durable execution, deterministic workflow code, timers, signals for human approval. Real cost: a second state store that must agree with tasks.db, a new programming model, and ops. Reconsider if workflows become long, branching and numerous. | Step Functions; Durable Functions (closest) |
| F. Inngest / Hatchet / Restate | 🟡 Interesting | Another service | Event-driven durable steps; nice DX; still a second state store. | — |
| G. LangGraph-style agent graphs | ❌ Not infra | — | Checkpointed agent graphs inside one process; useful pattern for multi-step agent jobs, not a job system. | Bedrock Agents; Azure AI Agent Service |
| H. GitHub Actions as the executor | 🟡 Partial | None | Good for CI and could run server-side agent jobs; cannot run restricted laptop work without exposing metadata to GitHub; minute limits on free plan. | CodeBuild; Azure Pipelines |

**Recommendation: A.** Concretely ~3 new tables (`jobs`, `worker_nodes`, `outbox`) and two loops (reaper, outbox
delivery). Revisit B (Postgres/DBOS) if: more than one control-plane host, sustained >1 job/second, or SQLite
write contention shows in metrics. Revisit E only if workflows grow into many long-running, branching, timer-heavy
processes that A expresses badly. Record this as an ADR with those reconsider triggers.

---

## 21. Implementation Roadmap

Every phase ships behind kill switches, keeps the old path working, and is dogfooded on CommandCenter first.

### Phase 0 — Reconcile (1–2 days)

- Port the wanted pieces of `claude/amazing-keller-fpy0qw` onto current main (D-001): GauzeMate pause, SamVision
  careful mode, UI test runs, bulk "Merge ready", and the night-shift reminder fix. **Drop** its global
  `merge: "auto"` default; per-project merge policy arrives with the profiles in Phase 1.
- Confirm what is live on jay-server (sha), whether `auto_merge` is on, refresh `docs/jay/*`.
- Prune merged branches (≈50 remote branches, all merged).
- ~~Answer the blocking open questions~~: done (D-001 … D-006).

### Phase 1 — Foundation (control-plane records; no new execution yet)

1. **ProjectOperatingProfile**: YAML under `policy/projects/`, schema-validated at start, hash recorded; registry
   keeps identity; profile view in Settings (read-only). Today's `merge`, `night: careful`, `paused`, lanes move here.
   The first versions of the five profiles (CommandCenter, GYST, SamVision, MyFamilyExpenses, the restricted
   laptop profile) are generated from §8.3, and D-001 … D-006 are loaded as the first Decision records that those
   profiles cite. A new ADR records that per-project policy supersedes ADR 0007's global "agents never merge".
2. **Autonomy Engine** (`autonomy.py`): pure `decide()`, compiled hard boundaries, exhaustive table tests;
   initially wired to the existing decisions (plan gate, merge gate, auto-merge, deploy gate) so behaviour is
   unchanged but now policy-driven and logged.
3. **Decision + Approval records**: new tables; today's gates and questions become Approvals/Decisions (views keep
   the old API working); hash-bound, single-use, expiring.
4. **WorkerNode model**: table + enrolment + heartbeat; the server registers itself; UI Fleet › Workers (read-only).
5. **Needs You v2**: one inbox over Approvals/Questions/blockers, grouped, one action each, precedent lookup.
6. **Audit trail**: global append-only `audit_events` with verified actor and profile hash; per-actor tokens for
   agents (start with per-session tokens issued by ccd; `X-CCD-Actor` must match the token).
7. **Cost metering**: record usage on every recorded role step where available; budget table; Fleet shows it.

Exit criteria: CC runs a week with every gate decision coming from the engine, zero behaviour regressions, Jay can
read each project's policy on one page.

### Phase 2 — Execution fabric and enforced boundaries

- `jobs` + leases + reaper; headless runner (`claude -p` / `codex exec`) on the **server worker** under `ccagent`.
- GitHub App (or fine-grained token) for agents without merge; **Capability Broker** holds merge/deploy.
- Move CI off the production host (or isolate the runner).
- Budgets enforced; night shift reimplemented as scheduled jobs (retire screen-reading reminders for autonomous
  work; herdr stays for Jay).
- **Slack (D-006)**: outbox → Slack via Socket Mode; approvals, questions, choose A/B, retry/pause, release
  notifications, per the §11.4 matrix.
- **Laptop worker** (WSL): pilot on a personal repo for a few days, then the employer repos (D-002: AI permitted,
  laptop-only storage and secrets).

### Phase 3 — Planning, review, release

- Plan Approval Package + rendering; Playwright screenshots on workers; Claude + Codex risk-triggered review;
  bounded Discussions.
- Release entity + composer; release branches/windows for SamVision; CC auto-deploy with canary + rollback.
- SamVision/MFE health checks and automatic rollback; only when both pass a rehearsal does the profile flip
  `health_checks`/`auto_rollback` to true and low-risk 01:00 releases deploy unattended (D-004).
- Lightweight ToolProposal record + template (PDF/deck rendering later).

### Phase 4 — Surfaces and artifacts

- Email digest; Slack `@agent` chat; Artifacts table + Drive mirror policy.

### Phase 5 — Memory and self-improvement

- Decision retrieval in context packs; precedent auto-apply; AgentReview + weekly Saturday 08:00 report;
  low-risk auto-improvements (checklists, prompt notes) with audit.
- **Jay Delegate in shadow mode** (predict + show confidence on Needs You cards; measure agreement; no actions).

### Phase 6 — Learning and Pulse

- Academy (daily/weekly), curriculum, quizzes; Pulse weekly briefing; Delegate allowed to act on `delegable`
  classes only if shadow accuracy meets a bar Jay sets.
- Secure mobile/remote access design (D-006), presented to Jay before anything is built.

---

## 22. Migration Risks

| Risk | Mitigation |
|---|---|
| Re-implementing gates as Approvals changes behaviour silently | Phase 1 runs engine and old logic side by side ("shadow decide"), alert on any difference before switching. |
| tasks.db migration failure | Today's pattern: forward-only, one transaction, backup before apply, newer-schema refusal. Keep. |
| Two policy sources during transition | Registry policy fields removed in the same PR that introduces the profile; startup error if both present. |
| Moving agents to `ccagent` breaks repo permissions/worktrees | Group ownership on repo dirs; pilot on CC; keep herdr sessions as jay for interactive use. |
| GitHub branch protection unavailable on free private repos | Broker-side enforcement + agent token without merge rights is the control (D-003); a paid tier only via a Tool Proposal. |
| Night shift users depend on current behaviour | Keep the button; reimplement under it; same report format. |
| Divergent branch (`amazing-keller`) merged later reintroduces `merge: auto` | Decide in Phase 0; cherry-pick wanted pieces (UI tests, bulk merge UI) onto current main deliberately. |
| Agent chaos as autonomy rises | Lanes, budgets, one-round discussions, deterministic transitions, kill switches per project (`paused` already exists on the branch). |
| Cost spike during migration (both systems running) | Metering in Phase 1 before any new job type ships. |

---

## 23. Test Strategy

- **Keep** the current discipline: unittest + vitest, fake herdr speaking the real protocol, route-table assertion,
  trigger tests, dev instance, canary.
- **Autonomy Engine**: table-driven tests for every (mode × action × risk) cell; property tests that no profile can
  produce `Allow` for a hard-boundary action; a test that `policy/**`, `autonomy.py`, `broker.py` are never
  auto-mergeable.
- **Jobs/leases**: deterministic clock; tests for lease expiry, double-claim impossibility, idempotent complete,
  resume from checkpoint, laptop-pinned requeue, reaper limits.
- **Fake agent runner** that returns scripted JSON (like `fake_herdr.py`), so pipeline-to-job flows run in CI
  without tokens.
- **Broker**: injectable `gh`/deploy runners (pattern exists: `gh_cli`); tests that it refuses without a consumed,
  hash-matching Approval.
- **Migration tests** on copies of real-shaped databases (pattern exists).
- **Security tests**: agent token cannot call owner ops; restricted project never emits content fields; redactor on
  outbox.
- **UI**: component tests for Needs You, plan package, decision view; Playwright smoke on the dev instance for the
  main flows; screenshot artifacts reused as UI-review evidence.
- **Evals for agent quality** (later): a small fixed set of past tickets replayed against role prompts to detect
  regressions when prompts/models change — cheap, run weekly, not per PR.

---

## 24. Observability Strategy

- **Keep** JSON-lines log (rotated), event stream with seq, alerts, `/api/health`.
- **Per-execution record**: start/end, node, attempt, exit reason, turns, tokens in/out/cached, cost or quota units,
  model, role, outcome (merged, reworked, failed). This is the main new telemetry and also feeds AgentReview.
- **Dashboards in Fleet** (no external stack needed): jobs by state, lease expiries, worker uptime, cost per
  project/role/day vs budget, review findings per 1k tokens, rework rate, escaped defects (verify fail / revert
  after merge), mean time Needs You items wait.
- **Alerts**: budget 80%/100%, job stuck in needs_attention, worker offline beyond policy, deploy health fail,
  engine/legacy disagreement (Phase 1 shadow), profile hash mismatch.
- **Tracing**: OpenTelemetry is optional; a `trace_id` per WorkItem carried through jobs, broker and notifications
  is enough to reconstruct a story. If later exported: self-host Grafana/Tempo; AWS X-Ray/CloudWatch; Azure
  Monitor/Application Insights.
- **Deploy health** for autonomous projects: post-deploy probes defined in the profile; failure → automatic rollback
  where the profile allows, then Needs You.

---

## 25. Open Questions (need Jay)

**Answered (2026-10-21), now policy:** Q1 control-room branch → D-001 · Q2 SamVision 01:00 → D-004 · Q3 employer
repos → D-002 · Q4 phone access → D-006 · Q5 GYST personal data → D-005 · Q6 GitHub plan → D-003. See §0.

**Still open (none block Phase 0 or Phase 1)**

- **Q7 · GauzeMate.** Not in the vision; paused on the control-room branch (that pause is being kept). Keep it
  paused with a placeholder profile, or give it a mode now?
- **Q8 · CommandCenter self-protection.** CommandCenter merges and deploys automatically (D-001). Proposal: changes
  to the autonomy engine, the gatekeeper, `security.py` and `policy/**` still need Jay, because "no agent may expand
  its own authority". Agreed?
- **Q9 · Slack approval matrix.** Confirm §11.4, especially: high-risk approvals from Slack need a confirmation
  dialog, and money/secrets/destructive-data/legal approvals wait for the CommandCenter UI until secure remote access
  exists. Also: which Slack workspace, and is a bot install acceptable?
- **Q10 · MyFamilyExpenses windows.** Same 01:00 Thu/Sat windows as SamVision, or its own?
- **Q11 · Budget.** Weekly token/usage budget per project. Can wait for a week of metering data from Phase 1.

---

## 26. What should we build first, and why?

**Build Phase 1 exactly: Project Operating Profiles + the Autonomy Engine, then Decision/Approval records, WorkerNode
registration, Needs You v2, verified-actor audit, and cost metering — all inside today's ccd and tasks.db.**

Why this first:

1. **It is the safety rail every later feature depends on.** Auto-merge, auto-deploy, laptop workers, Jay Delegate
   and Slack approvals are all "an actor wants to do X". Without one engine that answers Allow / Approve / Deny from
   a versioned policy, each feature grows its own rules — which is how the policy got fragmented across five places
   today.
2. **It changes no behaviour on day one.** Wire the engine to the existing gates in shadow mode, compare, then switch.
   Low risk, high information.
3. **It reuses what exists.** The classifier pattern, the gate model, the trigger-enforced audit trail and Needs Jay
   are already 60% of it.
4. **It is cheap in tokens.** No new agent work runs in Phase 1. Metering lands *before* the features that spend.
5. **It makes Phase 2 safe.** Once boundaries are enforced in one place and every actor is verified, giving agents a
   job runner and a bot identity is a controlled step rather than a leap of faith.

What *not* to build first: Temporal or any new infrastructure, multi-agent discussions, Pulse, Academy, Jay
Delegate, Slack chat. They are valuable, but each multiplies cost or risk unless Phase 1's rails exist.

---

## Appendix A — Audit inventory (main @ a0e90e5)

| Area | Files (lines) | Notes |
|---|---|---|
| Daemon core | `daemon.py` 2399, `api.py` 973, `model.py` 351, `store.py` 177, `config.py` 115 | 7 loops; strict route table |
| Tasks / pipeline | `tasks.py` 1145, `pipeline.py` 1083, `pipeline_cli.py` 163, `records.py` 253, `importer.py` 444 | schema with ~20 triggers |
| Policy | `registry.py` 194, `merge_policy.py` 260, `nightshift.py` 260, `skills/night-shift/SKILL.md` | |
| Integrations | `herdr.py` 172, `sources.py` 476, `github.py`, `gitops.py` 338, `coordid.py` 256, `coordinators.py` 177 | gh CLI, git subprocesses |
| Workspace | `pty.py` 521, `files.py` 539, `search.py` 225, `attachments.py` 145 | Developer Unlock gated |
| Security | `security.py` 186, `signin.py`, `worktree_cleanup.py` 301 | |
| Web | `web/app/src` (~8k): screens, workspace, tickets, store, api | React 19, xterm, Monaco |
| Launcher | `launcher/*.go` (~3k incl. tests) | Windows tray, tunnel, gates |
| Tests | 578 backend test functions, 199 web tests, Go tests | CI on PRs to main |
| Docs | README, ARCHITECTURE, API, SECURITY, KEYBOARD, ADR 0001–0007, plans (pipeline, control room spec 1529 lines) | high quality, current to ~2026-10-12 |
| Deploy | `go-live.sh`, `deploy-web.sh`, `install-user-unit.sh`, `ccd.service`, `herdr.service` | single host |
| Not present | Slack, email, Drive, Postgres/Redis, worker nodes, cost metering, Decision/Release entities | |

Concepts confirmed in code: night-shift reports (`nightshift.py`, `~/command-center/night-shift/<project>/<date>.md`),
herdr panes (`herdr.py`, allowlisted methods), task-named sessions (`coordid.task_session`, e.g. `sv-071`), the ccd
daemon, `scripts/deploy-web.sh` and `scripts/go-live.sh` on jay-server. "Repo board routines" appear as the legacy
board (`~/command-center`, Textual) reading `/api/state` and the GitHub/git polls; no separate routine scheduler
exists in this repository.

## Appendix B — Branch audit

| Branch | State | Finding |
|---|---|---|
| `p4b` (PR #1) | **Merged** 2026-10-04 (0 commits ahead of main) | The project note said PR #1 was unmerged; GitHub shows it merged by Jay. Nothing to recover. |
| `claude/amazing-keller-fpy0qw` @ e236ffa | 4 commits ahead, **85 behind** main; never merged; no open PR | Commits: *Pause GauzeMate; SamVision night shift in careful mode* · *Merge ready: one press merges every reviewed, green PR* · *UI test runs on request* · *Night shift: a reminder no longer counts the work it causes as progress*. Its `registry.py` sets `PIPELINE_DEFAULTS["merge"] = "auto"` for every project. **Decided (D-001):** port the four useful pieces onto main in Phase 0; drop the global default; merge rights come from per-project profiles instead. |
| `cc-control-room-v1` | merged (0 ahead) | — |
| `workstation`, `native-terminals`, `ui-releases`, `CC-0xx-*`, `cc-0xx-*`, docs branches | all merged (0 ahead) | ≈50 stale remote branches; safe to prune after Jay confirms. |

No open pull requests exist in the repository at the time of this audit.
