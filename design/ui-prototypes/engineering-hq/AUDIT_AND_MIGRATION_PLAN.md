# Engineering HQ — audit and migration plan

Status: **Stage A + B + C (prototype)**, plus the onboarding groundwork Jay allowed on 2026-10-23 (§7.0). Nothing is
deployed, and no credential was issued. **D-024 is final** (Jay, 2026-10-24T06:51Z). At Jay's request (2026-10-23) the
work is in three PRs, each with its own approval:

| PR | Branch | Holds | State |
|---|---|---|---|
| #64 | `claude/project-thread-gs2u2h` | This prototype only (`design/ui-prototypes/engineering-hq/`) | Draft; not to be merged |
| #65 | `claude/d024-backend` | The groundwork: new server modules behind a flag that is off (`server/ccd/onboarding.py`, `server/ccd/budgets.py`, tasks.db migration 10, `server/ccd/migration_safety.py`), the rollback runbook and the docs | **Merged** 2026-10-24 with Jay's approval; flag off; not deployed |
| #66 | `claude/d024-policy` | D-024 v1.0 final: `docs/decisions/D-024.md`, `policy/decisions/D-024.toml`, ADR 0009 and the text test | Final text; the decision of record |

Making D-024 final approves the policy and design only. Production enforcement, agent activation, credentials,
Broker grants, budget holds, Slack buttons, Phase 2 enforcement and deployment each still need Jay's own approval.

## 1. What exists today (audit of `main` @ 693a556)

| Area | Today | Notes for the redesign |
|---|---|---|
| Frontend | React 19 + TS + Vite 8 at `web/app`, hash router (`lib/router.ts`), tiny external store | Prototype uses the same stack and versions; no new libraries. |
| Shell | 7 destinations: Dashboard, Needs You, Workspace, Task Manager, Activity/Logs, Files, Settings; old routes kept | New IA: My Office, Messages, Decisions, Teams, Company (Topology), Engineering, Revenue, + "Settings & more". All old routes must keep working. |
| Pop-outs | `screens/Popout.tsx` (RoomWindow, PaneWindow) + `workspace/rooms.ts`: localStorage layout, `storage` event, attach-by-session-name, `pagehide` → detach | Proven model for terminals/rooms. The prototype generalises it to any view (§3). |
| Auth | ccd token in memory/sessionStorage; handed to pop-outs over same-origin BroadcastChannel `cc-token`; never in a URL | Reused as-is in migration. The prototype carries no credentials at all. |
| Developer Unlock | Session id (never the token) shared over `cc-dev`; 2 h idle / 8 h max; LOCK in any window locks all | Pop-out windows must keep revalidating it for privileged writes. Unchanged. |
| Data | `/api/state`, tickets, live WS, usage meter, workers, audit, policies, autonomy shadow | Map to pages in §4. No chat store, no revenue source exist. |
| Policy truth | `server/ccd/registry.py`, `policy/projects/*.toml` | Used for prototype labels: GauzeMate **paused**; merge = owner (CC: low-risk docs/tests only); autonomy targets are **shadow only**; SamVision release windows Thu/Sat 01:00 America/Winnipeg. |

## 2. Where the concept art and the repo disagree (decisions for Jay)

1. **Project colours.** Repo tokens: SamVision red, GauzeMate green, CommandCenter blue, GYST orange, MFE purple. Concept art: SamVision mint, GYST purple, MFE orange, GauzeMate pink, CommandCenter blue. The prototype follows the **concept art**; one token change switches back. → *Jay to pick.*
2. **SamVision** is shown as real-estate/realtor tooling (art said computer vision).
3. **GauzeMate** is shown **Paused** (art said "Degraded / 2 agents working").
4. **Deploy buttons** in the art are shown as **Gated** / disabled: releases only through existing gates.
5. **Agent persona names** (Iris, Nova, Atlas, Pixel, Orion) are placeholders over real pipeline roles (plan, implement, independent review, UI test, release). Real names/models come from ccd sessions. → *Keep personas or show role + model only?*
6. **Revenue** has no data source. Default is *Not connected*; a fictional demo is opt-in and watermarked.
7. **Model usage/cost** on Engineering shows `$—` + Demo; live numbers come from ccd's meter (AI spend, kept separate from revenue).

## 3. Cross-window architecture (prototype, proposed for production)

- **Stable view ids**: `page:<page>`, `dm:<conversation>`, `task:<KEY>`, `term:<KEY>`, `panel:<name>`; validated by a strict regex. The pop-out URL is `#/pop/<id>` — no credentials, no parameters.
- **One owner** per view in a small shared record (`owners`): BroadcastChannel for live sync + localStorage for late joiners, shape-checked on receipt. Non-owners render a shaded placeholder (Focus window / Return here), so there are never two interactive copies or duplicate subscriptions.
- **Liveness**: each pop-out holds a Web Lock `hq-view:<id>` for its life (released by the browser on close/reload/crash, immune to background timer throttling); heartbeat fallback where Web Locks are missing. `pagehide` marks *closing*; a reload re-claims within the grace period; otherwise the view returns home with a notice. A pending pop that never loads is reclaimed after 8 s.
- **Re-pop** of a popped view focuses its window (named windows also make a duplicate impossible).
- **Main window gone**: pop-outs detect no `hq-main:*` lock, keep working, and can become the main window.
- **Shared UI state** (selected sub-tab, filters, drafts, inspector selection) is synced per view id, so a view keeps its context when it moves; chat sends are idempotent by client id.
- **Production rule kept**: closing any window only detaches. In the real app a Task Room / terminal view attaches to the same ccd/herdr session by name (`rooms.ts`); End Session stays a separate confirmed action.
- **Migration**: `rooms.ts` room/pane pop-outs become two view kinds of this manager; its `storage`-event layout stays the source for wall slots. Token and Developer Unlock handoff stay in `api/auth.ts` / `api/developer.ts` unchanged.
- **Limits**: browsers cannot place a window on a chosen monitor, and may refuse `focus()` — the UI then says where to find the window. Exact monitor placement would need a native (Tauri) proposal.

## 4. Pages → data (for the live build; all read-only first)

| Page | Live source | New backend needed? |
|---|---|---|
| My Office | `/api/state` (projects, needs-you queue, alerts), tickets, sessions | No (read-only). "Updates from leads" needs a lead-summary feed → proposal. |
| Messages | — | **Yes**: conversation store, indexing, retention, access rules. Separate security review; never in ccd operational metadata without it. |
| Decisions | tickets questions/gates, policy files, evidence/attachments | Recording an answer reuses existing question/gate endpoints and session routing. |
| Teams | registry, tickets by stage/owner, session presence | Presence must report Disconnected/Unknown on stale streams (prototype already does). |
| Topology | projects, tickets→stages, workers, release readiness | No for read-only. Layout is custom SVG + HTML (no graph library). |
| Engineering | tickets, PRs/CI, release gates, usage meter, workers | No. New Task stays disabled until an approved create API. |
| Revenue | — | **Yes**: provider-neutral read-only adapter; provider chosen by Jay; server-side restricted key. |

## 5. Phased migration (each step is its own gated PR; nothing auto-deploys)

> **Superseded 2026-10-25** by the integration roadmap (Claude Doc): https://claude.ai/artifact/3SUAvgfk4Dy63JiFebrkQi.
> It splits this plan into 25 small PRs with eight approval gates. The list below is kept for history.

1. Jay reviews the prototype; decisions in §2.
2. Tokens + shell (sidebar, top bar, tab strip) behind a `?ui=hq` flag; old UI default.
3. Window manager in `web/app`, wrapping existing Room/Pane pop-outs; regression tests that closing never calls `ptyClose`.
4. Pages one at a time on read-only data: Topology → Office → Engineering → Teams → Decisions.
5. Messages and Revenue only after their backend proposals are approved.
6. Flip the default after Jay signs off; old screens remain reachable.

## 6. Tool proposals

None needed so far. Possible later: `@playwright/test` as a dev dependency for CI (tests currently use the globally installed Playwright). Not added without Jay's approval.

## 7. Agent onboarding and project creation: backend proposal (not implemented)

**Status: D-024 final, groundwork merged with its flag off, enforcement not built or enabled.** Jay made D-024 final on 2026-10-24T06:51Z. **The text of record is `docs/decisions/D-024.md` version 1.0** (#66), with Annexes A to C, the clause audit and the decision of record `policy/decisions/D-024.toml`. The [D-024 final proposal](https://claude.ai/artifact/3QArYLzEbEnzBV1geGUxXN) doc explains it. The groundwork merged in #65 behind the off flag (§7.0). Everything that grants, activates or enforces still needs Jay's approval for each switch, after the prerequisites in clause 18. The prototype's wizards still write only to the local mock store (`src/data/org.ts`); they do not call ccd.

### 7.0 What exists now (off by default)

| Piece | Where | What it does | What it does not do |
|---|---|---|---|
| Flag | `config.json` `"onboarding_groundwork": true` | Turns the routes on; read at start | Off: every `/api/onboarding` route is a 404 and ccd behaves as before |
| Agent registration | `agent_registrations`, `agent_config_versions` (tasks.db v10) | Immutable `agent:<slug>`, status `registered` or `retired`, append-only config with the permissions it **requests** | No active state, no grants, no credential, no session |
| Drafts | `onboarding_drafts` | Agent and project drafts with revisions (no silent overwrite) | Reserve nothing; a project draft never becomes a project here |
| Validation | `onboarding.validate_agent`, `validate_project` | §7.5's rules server-side: IDs, reserved/retired IDs, duplicates, look-alike names, hard ceilings, known projects, registry prefixes and repos, secrets refused whole | Decide authority |
| Audit | `onboarding_events` + the existing audit chain | One event per change in the same transaction; every HTTP write audited | |
| Reads | `GET /api/onboarding/*` (docs/API.md) | Lists, details, events, validation | |
| Budgets | `ccd/budgets.py`, `GET /api/onboarding/budgets` | D-033 arithmetic and a shadow report (§9) | Hold or stop anything |
| Migration safety | `ccd/migration_safety.py`, `tasks.downgrade` | Rehearses migration v10 on a copy; undoes it in place (§7.11) | Run by itself; the daemon never imports it |

Writes need Jay and Developer Unlock; agents are refused in the daemon, the module and the schema. 22 server tests in `server/tests/test_onboarding.py` and 12 in `server/tests/test_migration_safety.py` (#65), and 5 in `server/tests/test_d024_text.py` (#66).

### 7.1 Principles

1. **Approval is a person, not a request.** Creating, activating, re-permissioning or offboarding an agent, and creating or promoting a project, need Jay with a valid Developer Unlock session (`identity.identify` → `developer`). An actor token is never enough.
2. **Records, not power.** Creating an agent writes an identity record. It issues no credential, token, SSH key or GitHub access. Creating a project writes a registry and profile proposal. It provisions no repository, environment, WorkerNode or cloud resource. Each of those is a separate, separately approved action.
3. **Immutable identity.** IDs (`agent:<slug>`, project `key`, ticket `prefix`) are assigned once and never reused, even after offboarding. Names and personas can change; history keeps pointing at the ID.
4. **The broker decides.** Effective permission = agent grant ∩ project rules ∩ WorkerNode capability ∩ task-mode cap, computed and enforced by the Capability Broker at action time, never by the UI. The UI only shows what the broker would decide.
5. **Everything is audited.** Every write goes through `audit.py` (hash chain, actor, verification level, policy fingerprint), plus a typed domain event (§7.5).

### 7.2 Agent data model (new tables in ccd's SQLite; append-only where marked)

| Record | Fields | Notes |
|---|---|---|
| `agents` | `id` (immutable `agent:<slug>`), `display_name`, `glyph`, `color`, `created_at`, `created_by` (CHECK = `jay`), `life` (`draft`/`active`/`paused`/`offboarded`), `life_reason` | One row per identity. `id` UNIQUE, never deleted. Offboarded slugs stay reserved. |
| `agent_config_versions` (append-only) | `agent_id`, `version`, `template`, `persona` (role, tone, instructions text), `model` (provider, model id, reasoning tier), `budgets` (daily/monthly caps, per-task cap), `config_sha`, `approved_by`, `approved_at`, `note` | Current config = highest approved version. Edits create a new version; old versions stay for attribution. |
| `agent_memberships` | `agent_id`, `project_key`, `role` (`project_lead`/`lead`/`member`), `specialization` (frontend, backend, security, qa, devops, …), `reports_to` (agent id or `jay`), `since`, `until` | One open Project Lead per project (partial UNIQUE index), reporting to `jay`. Specialization leads report to it; members to a specialization lead or the Project Lead. Three levels at most, no cycles (checked on write). Reporting lines carry work, never permission (§7.9). |
| `agent_grants` (versioned with config) | `agent_id`, `capability`, `scope` (project/repo/worker), `level` (`allow`/`approval`/`deny`) | Capability names come from a fixed list in policy (the prototype's 25 `PERMISSIONS`). Hard-boundary capabilities have a `deny`-only ceiling that no grant can raise. |
| `agent_repo_grants`, `agent_worker_grants` | `agent_id`, `repo` / `worker_id`, `level` | Repo must be bound to a project the agent belongs to; worker must be an approved, agent-eligible node. |
| `agent_events` (append-only) | `agent_id`, `kind` (`created`, `activated`, `config_versioned`, `renamed`, `paused`, `resumed`, `reassigned`, `offboarded`, `grant_changed`), `actor`, `verified`, `detail_keys`, `at`, `audit_seq` | Links to the `audit_events` row that caused it. |
| `task_attribution` | existing ticket rows gain `owner_agent_id` + a `former_owners` history | Work stays attributed to the agent ID after rename or offboarding. |

### 7.3 Project data model

| Record | Fields | Notes |
|---|---|---|
| `registry.py` row (code) / `projects` table | `key` (immutable), `name`, `prefix` (immutable once a ticket is minted), `type`, `color`, `icon` | Today the registry is code. Proposal: keep code as the source for existing projects; new projects go into a table that `registry.py` merges, still refusing duplicate keys/prefixes across both (and across `legacy` and `board_ids`). |
| `project_onboarding` | `key`, `stage` (the prototype's `ONBOARDING_STAGES`: proposed → observation → …), `stage_since`, `admission_review` (checklist results), `promoted_by` (CHECK = `jay`) | New projects start in **observation only**. Only Jay can promote. |
| `project_repo_binding` | `key`, `repo` (`owner/name`), `state` (`existing`/`proposed`), `bound_at` | One repo binds to at most one project (UNIQUE). `proposed` creates a "Needs Jay" ticket; nothing is created on GitHub. |
| `project_environments` | `key`, `env` (dev/staging/prod), `url`, `protected` (bool), `discovered` (bool) | Production is protected by default. URLs only, never credentials. |
| `project_worker_eligibility` | `key`, `worker_id`, `allowed` | Employer projects cannot be eligible on the shared server (validation in the prototype; enforced here). |
| Operating Profile | `policy/projects/<key>.toml`: `[enforced]` + `[target]`, `default_task_mode`, budget, deploy rules | Written as a **proposed file in a PR for Jay to merge**, never by ccd at runtime. `profiles.py` already validates and fingerprints it; `drift()` keeps reporting. |
| `project_events` (append-only) | `key`, `kind` (`proposed`, `created`, `repo_bound`, `stage_changed`, `profile_proposed`, `paused`), actor, `audit_seq` | |

### 7.4 API (all under ccd's existing token, Host/Origin and JSON content-type checks)

| Method & path | Who | Effect |
|---|---|---|
| `GET /api/agents`, `GET /api/agents/{id}` (+ `/versions`, `/events`, `/effective?project=&worker=&mode=`) | any token holder | Read. `effective` returns the broker's computed decision table, so the UI never computes permissions itself. |
| `POST /api/agents/drafts`, `PUT/DELETE /api/agents/drafts/{draft_id}` | Jay (Developer Unlock) | Drafts are stored server-side, separate from `agents`. A draft is not an identity and reserves nothing. |
| `POST /api/agents` | Jay + Developer Unlock | Validates (same rules as `validate.ts`, server-side), reserves the ID, writes `agents` + config v1 + memberships + grants in one transaction, `life=active` only if `activate: true`. Idempotency key required. Issues **no** credential. |
| `POST /api/agents/{id}/versions` | Jay + Developer Unlock | New config version (model, persona, budgets, grants). Grant widening is shown as a diff and needs explicit confirmation (`confirm_widen: [capabilities]`). |
| `POST /api/agents/{id}/pause` / `resume` / `reassign` / `offboard` | Jay + Developer Unlock | Offboard: revokes the agent's actor tokens (`ActorTokens.revoke`), closes memberships, hands open tickets to a named agent (recorded in `former_owners`), archives conversations, keeps history. Final for the ID. |
| `GET /api/projects/onboarding`, `POST /api/projects` | Jay + Developer Unlock | Creates the registry/table row, onboarding state (observation), kickoff tickets, lead conversation and a **proposed** profile TOML as a branch/PR for Jay. Provisions nothing. |
| `POST /api/projects/{key}/stage` | Jay + Developer Unlock | Promotion out of onboarding. Requires admission review to pass and a merged profile whose fingerprint matches. |

Errors are typed (`duplicate_id`, `reserved_id`, `confusable_name`, `ceiling_exceeded`, `repo_already_bound`, `not_unlocked`, `self_action`) so the UI can show the same messages as the prototype.

### 7.5 Security controls

- **Who can act.** Every write above requires `verified == developer` (Jay + Developer Unlock). Requests verified only by an actor token are refused with `403 not_unlocked` and audited. This is enforcement, not the Phase 1 "measure only" mode, so it depends on actor-token enforcement (Phase 2) being approved.
- **No self-service.** The broker refuses when the target agent equals the acting agent, or when the request comes from any agent at all: an agent cannot create agents, approve itself, change its own config or grants, change its reporting line, or promote a project. Schema CHECKs (`created_by = 'jay'`, `approved_by = 'jay'`, `promoted_by = 'jay'`) back this up, as `workers.py` already does for node approval.
- **No privilege escalation by template.** Templates are presets in the UI only. The server validates the final grants against hard-boundary ceilings (production deploy, secrets read, billing, branch protection, deleting repos, etc. are deny-only) and against project rules.
- **Duplicate and impersonation protection.** UNIQUE IDs, reserved list (`jay`, `system`, `ccd`, `admin`, existing and offboarded slugs), case-folded and confusable-name check (edit distance ≤ 2 against active names) as a warning that Jay must acknowledge.
- **Policy fingerprinting.** Every agent config version and project creation records the `profiles.Policy` fingerprint in force. Changing policy files changes the fingerprint and is visible in the audit trail.
- **No plaintext secrets.** No API, record or draft accepts a secret, token, password or URL with credentials (`security.redact` + a validator that rejects `ghp_`, `sk-`, `://user:pass@`, etc.). Model-provider and GitHub credentials stay with the broker; agents receive scoped, short-lived capabilities at action time only.
- **Credentials are separate.** Issuing an actor token stays the existing `identity.ActorTokens.issue` flow (Jay + Unlock, shown once, hashed, expiring). Creating an agent does not call it.
- **Auditability.** Each write produces one `audit_events` row (existing hash chain) plus one domain event row that references it. `GET /api/audit/verify` already detects tampering.
- **UI cannot lie about status.** Status comes only from session/heartbeat evidence. A new agent is `not_started` until a real session reports; stale feeds show `unknown`. Same rule as the prototype's `statusOf`.

### 7.6 Integration points

| System | How onboarding uses it |
|---|---|
| Project Operating Profiles (`profiles.py`, `policy/projects/*.toml`) | New project = proposed profile file in a PR. Default task mode and deploy rules come from it. Onboarding projects use the most restrictive profile until Jay merges theirs. |
| D-024 | Project and agent onboarding. **Final** (Jay, 2026-10-24T06:51Z): `docs/decisions/D-024.md` v1.0 and `policy/decisions/D-024.toml`, so profiles can cite it. Clauses 10 to 13 add agents, Slack and budgets; 14 to 17 the hierarchy, independent review, repository authority and incomplete budget data; 18 keeps everything off until each switch is approved. |
| D-032 | Slack mobile approvals (§8). |
| D-033 | Budgets at agent, project and company level (§9). |
| WorkerNodes (`workers.py`) | Worker grants and project eligibility reference approved node IDs only. A pending or revoked node is never eligible. |
| Capability Broker | The only enforcement point for effective permissions, merges and deploys. Onboarding writes grants; the broker reads them. |
| Actor tokens (`identity.py`) | Offboarding and pausing revoke or suspend the agent's tokens. Enforcing token ↔ `X-CCD-Actor` match is the Phase 2 prerequisite for §7.5. |
| Decisions / Approvals | "Approve repository creation" and stage promotion appear as Decisions items for Jay, the same as today's gates. |
| Audit chain (`audit.py`) | Every write above; domain events link to it. |
| Usage meter (`meter.py`) | Budgets read the meter (§9). A hard limit holds new billable work in its own scope only; it never pauses a project or changes its mode. Shadow report today; enforcement after Phase 2. |
| Future deterministic runbooks | Repo creation, environment discovery and WorkerNode setup become runbooks Jay runs, each with its own approval, never side effects of onboarding. |

### 7.7 Risks found while building the prototype

1. **Self-asserted actor header.** Until actor-token enforcement exists, anything with ccd's token can claim to be Jay. The endpoints above must require Developer Unlock, not the header.
2. **Registry lives in code.** Adding projects at runtime needs a merged code+table registry with cross-checks for prefix collisions, including legacy prefixes and board IDs.
3. **Grant drift.** If templates change later, existing agents must not silently change. Hence versioned configs that copy grants, not references to templates.
4. **Offboarding orphans.** Open tickets, conversations, tokens and worker leases must all be handed over or revoked in one transaction.
5. **Confusable names.** "Nova" vs "N0va" in approvals and Slack messages. Warn on create; show the ID next to the name in approval surfaces.

### 7.8 Order (each step its own approval; nothing turns on by itself)

1. **Done, off:** groundwork behind `onboarding_groundwork` (§7.0). Routes live under `/api/onboarding`, not `/api/agents`, which already serves pane tails.
2. **Done:** Jay made D-024 final (2026-10-24T06:51Z); recorded in `policy/decisions/D-024.toml` with ADR 0009 (#66).
3. **Done:** the migration drill (§7.11) passed on a copy of the live tasks.db (2026-10-24, 28 of 28 checks), and its redacted report is attached to the project thread.
4. **Done:** the groundwork merged (#65, 2026-10-24) with the flag still off in production. Next, turning it on in a dev ccd first; then, still behind the flag: the hierarchy checks (§7.9) and the additive migration that lets leads file staffing proposals, each with its own drill.
5. Shadow: the onboarding engine path, reviewer independence and the budget evaluator record what they would allow, refuse or hold.
6. Slack requests with the secure link (§8, step 1), once the approval screen is reachable over Jay's private path.
7. Each switch on its own (engine `onboarding` mode, Broker credential withholding, agent activation and grants, budget holds), and none asked for before all four prerequisites of D-024 clause 18 hold: Phase 2 actor-token enforcement, a shadow-mode validation, the D-030 laptop runner isolation check (D-045), and the private authenticated approval path.
8. Last: low-risk approvals inside Slack (§8, step 2).

### 7.9 Engineering hierarchy and independent review (D-024 clauses 14 and 15; proposed, not built)

- **Shape.** One Project Lead per project, answering to Jay. It may supervise specialization leads (Frontend, Backend, Security, QA, DevOps, others), who coordinate the agents that report to them. Three levels at most, no cycles; an agent can work in several projects, with a lead in each.
- **Routine work without Jay.** Within the project profile and its current mode, a Project Lead writes task requirements, acceptance criteria and implementation plans, and splits, orders and assigns work. Plans the profile marks (production, data, security, D-007 paths) still go to Jay. In onboarding, routine means planning and proposals.
- **Work, never authority.** An assignment runs with the assignee's own grant as the Broker computes it; a lead assigns only inside its own project and specialization, and only to agents that report to it.
- **Staffing by proposal.** No agent approves its own activation, widens a permission, or creates, registers or activates an agent (the groundwork already refuses all of these from agents). Leads and agents may propose adding, changing or retiring an agent, with reason, role, reporting line, permissions and budget; it reaches Jay as an approval request (registration Low tier, activation Standard or High by its grants). Today's drafts table is written by Jay only, so proposals need one more additive migration after D-024 is final.
- **Independent review.** The reviewer is not the implementer, a commit author, the plan's author or the lead who assigned the work; the engine picks it, never the implementer or its lead. It reviews in a fresh session from the diff, ticket, plan and acceptance criteria, binds to the commit it read, and only the reviewer or Jay closes a finding. High-risk changes and D-007 paths get a reviewer on a different model family. Until Phase 2 actor tokens, independence is recorded in shadow.

### 7.10 Repository authority during onboarding (D-024 clause 16)

The Broker refuses anything not listed; onboarding holds no credential for the rest.

| Operation | Jay's own repositories | Employer and client repositories |
|---|---|---|
| Read and clone | Read-only token | Laptop only (D-002); a server clone needs Jay |
| Edit, commit, branch locally | Allowed (D-025) | Laptop, directed style (D-022) |
| Push a branch | Only its own `cc/onboarding/` proposal branches, through the Broker, after a clean push-safety check; never a force push | Never; patches stay local and are shown to Jay |
| Open a pull request | Draft only, from a proposal branch, at most 5 open per project; never marked ready, no reviewers, no auto-merge | Never |
| Comment | Only on its own draft PRs | Never |
| CI configuration (`.github/workflows/**` and equivalents) | Never pushed without Jay's High-tier approval, per change | Never; their runners are observe-only (D-029) |
| Start or re-run CI | Never by itself; reading results is allowed | Never |
| Merge, rebase shared branches, delete others' branches, rewrite history; tags, releases, packages; settings, protection, webhooks, deploy keys, secrets, environments, collaborators; create, fork, rename, archive or delete a repository | Never | Never |

A branch push can start the repository's CI, so a repository whose CI runs on our self-hosted runners (today CommandCenter, GYST, SamVision) always asks Jay first. A repository's class (own, employer, client) is set when it is added, and an unknown class is treated as client. For employer and client repositories, Slack requests carry identifiers and the risk summary only, and an agent session on one is never reused in another project.

### 7.11 Migration v10 safety (Jay, 2026-10-23: demonstrate before the backend merges)

`python -m ccd.migration_safety drill --snapshot COPY.db --out DIR [--old-ccd OLD_CHECKOUT/server]` rehearses migration v10 on copies of a v9 snapshot (opened read-only, never written) and writes `drill.json` and `drill.md` (exit 0 PASS, 1 FAIL, 2 cannot run: missing snapshot, unmerged write-ahead log, snapshot inside the output folder, or already newer than v9).

| Area | What it proves |
|---|---|
| Backup | SQLite's online backup of the snapshot holds exactly the same rows in every table |
| Upgrade | v9 → v10 adds only the four onboarding tables and their own indexes and triggers; every existing table, row, index and trigger is unchanged; integrity, foreign keys and the audit hash chain check; reopening applies nothing |
| Backward compatibility | A v9 ccd refuses the v10 file and changes nothing (in process, and with `--old-ccd` a real older checkout in its own process) |
| Rollback | `tasks.downgrade(db, 9)` after new work was written at v10: exactly the v9 schema again, the new work kept, a v9 ccd opens it; refused, changing nothing, while an onboarding table holds a row |
| Restore | Copying the backup back gives the snapshot's rows exactly, and a v9 ccd opens it |
| Recovery | Interrupted part-way, or its process killed part-way with uncommitted pages already in the write-ahead log, it leaves v9 exactly; killed straight after its commit it leaves v10 complete; either way the next start finishes the job |

Results on this branch: a populated v9 fixture (22 tables, 77 rows) and a 5,009-ticket one (15,070 rows; upgrade 2 ms, whole drill about 1 s) both PASS, and the `origin/main` ccd run as the older checkout refused v10 and opened the rolled-back file. The tests run the drill in CI and show it fails a migration that changes existing rows or adds an index to an existing table.

**The way back.** Stop ccd, then `python -m ccd.migration_safety rollback --db tasks.db --to 9 --backup-dir DIR`: it takes a backup first, then drops only the empty tables v10 added, in one transaction, and commits only if the result is exactly v9 with integrity and foreign keys intact. It refuses when any of those tables holds a row (history is never dropped), when the schema has an unknown change, and for any step without a downgrade. With records present the way back is rolling forward, or restoring the backup after `export-onboarding` has copied the records out read-only. The full procedure, including an older ccd that refuses a v10 file, is `docs/runbooks/tasks-db-v10-rollback.md` (merged in #65). The drill's `--redact --label` report names no path, host or user, and `--clean` removes the data copies.

**On the live database (2026-10-24): PASS, 28 of 28 checks.** The backup was taken at 05:39:31Z from the live v9 tasks.db (22 tables, 53,113 rows, 335 tickets) through one read-only connection with SQLite's backup API. The drill ran on that copy in a private temporary folder, with drill code e2c2ee8 and the deployed ccd (693a556) as the older ccd. The upgrade took 0.7 ms. The copy was deleted afterwards, and the live database, checkout and service were unchanged. Take any later backup the same way, never with `cp` or the `sqlite3` command line on the live file.

## 8. Slack mobile approvals (D-032)

**Decision (Jay, 2026-10-23):** yes to approvals from his phone. First, Slack carries detailed onboarding requests with a secure link to an authenticated CommandCenter approval screen. Later, low-risk approvals inside Slack, only with verified identity, authorization, short-lived actions and an audit trail. High-risk permissions, repository access, policy changes and production capabilities need stronger confirmation inside CommandCenter. The local ccd API is never exposed publicly. Slack stays off until Jay approves turning it on.

### 8.1 Shape

```
ccd ──(outbound Socket Mode, bot token held by ccd)──▶ Slack ──▶ Jay's phone
                                                                   │ taps the link
Jay's phone ──(private authenticated path, D-006; never public)──▶ CommandCenter approval screen ──▶ ccd
```

- **Outbound only.** ccd opens the Slack connection (Socket Mode). No Slack webhook reaches ccd and no port is opened; the Slack bot token lives with ccd's other credentials, never in a browser or an agent.
- **The message.** What is asked, the agent ID beside its display name (look-alike names cannot pass), risk tier, a short change summary, the request hash (first 8 characters) and its expiry. No secret, token, path with credentials or production URL.
- **The link.** `…/approve/<request id>`: an opaque random ID, single purpose, not a credential. Opening it still needs Jay's sign-in. It resolves only over the private authenticated path; from the open internet it does not open, by design.
- **The screen.** Shows the whole request and its diff, the tier, and what approving does. The approval binds to the request's hash; a changed request voids it (as Admission Reviews do). Every view and decision is audited.

### 8.2 Risk tiers

| Tier | Examples | Where it can be approved |
|---|---|---|
| Low | Acknowledge a budget alert; register an agent record (no credential); a temporary budget override inside a ceiling Jay set; pause an agent or hold work | The approval screen now; inside Slack after step 2 is approved |
| Standard | Activate an agent with read-only grants; reassign an agent; resume after a budget hold | The approval screen |
| High | Widen any permission; repository access; policy changes; production capabilities; an Admission Review mode choice; raise a hard budget limit | CommandCenter only: Developer Unlock, a typed confirmation of the ID, approval bound to the exact diff; never from Slack |

Pausing and holding only reduce authority, so they never need more than Low.

### 8.3 Step 2: in-Slack buttons (later, separately approved)

A button works only when ccd verifies, at the moment it is pressed: the Slack user, workspace and app match the identity Jay registered; the action carries a single-use code that expires within minutes and is bound to the request hash; the request is still Low tier and unchanged. The audit row keeps the Slack user, workspace, code ID and request hash. High-tier messages never carry a button.

### 8.4 Prototype

The **Approvals** page (sidebar, `#/approvals`) shows the request queue, the approval screen with the three tiers (high risk needs Developer Unlock and a typed confirmation), a hash that voids approval when the request changes, and a phone preview of the Slack message, all as mock data. Nothing connects to Slack. Tests: `tests/governance.test.tsx` (tiers, unlock and typed confirmation, hash binding, expiry) and three browser checks in `e2e/run.mjs`, including the approval screen at phone width.

## 9. Budgets (D-033)

**Decision (Jay, 2026-10-23):** configurable budgets at agent, project and company level, with advance alerts. At a hard limit: stop scheduling new billable work in that scope; let in-progress work reach a safe checkpoint; notify Jay and the project lead; allow an authorized adjustment or temporary override; resume safely after authorization or reset. One agent over its limit must not stop the whole project. Safety monitoring, rollback and recovery stay separate from spending limits.

### 9.1 Rules (`server/ccd/budgets.py`)

| Rule | Implementation |
|---|---|
| Three scopes, each with a period (day, month) and USD and/or token limits | `lines_for`: company from `config.json` `budgets.company`, project from the profile's `[target.budget]`, agent from its registered configuration |
| Alerts before the limit | `assess`: 50% information, 80% warning, 95% urgent, 100% the hard hold (approved defaults, D-024 B4), per scope; plus `onCourseToHold` when the run rate reaches the limit before the period ends |
| Missing data never lowers spend | `report`: a reply with no known price counts at the highest listed price (`fallback_prices`: $10 input, $50 output per million tokens) as `unpricedUsdAtFallback`; usage tied to no project counts toward the company as `unattributedUsd`; each line is judged on `assessedUsd` |
| Hard limit holds its own scope only | `would_start`: an agent hold stops that agent; a project hold that project; the company hold all billable work |
| Safety is separate | `SAFETY_KINDS` (health checks, monitoring, incident response, rollback, restore, backup checks, recovery) always start; the engine tags them by action type, an agent cannot |
| Running work checkpoints | A hold acts only at scheduling; running work finishes its step and checkpoints (D-027); deploys, migrations, rollbacks and pushes in flight are never cut |
| Override and adjustment | `effective_limit`: a temporary override adds to a limit until it expires and can never lower or remove it; an adjustment is a new configuration version |
| Resume | After an override or the period reset, held work resumes from its checkpoints in queue order, re-verifying facts D-031 requires at use |
| A hold is not a safety event | It never changes a project's mode, never triggers D-026 tightening, never opens a D-023 incident |

### 9.2 Incomplete data, the 5% overrun and expensive steps (D-024 clause 17)

- **Incomplete pricing or attribution brings a hold sooner** (built, shadow report). Unpriced usage counts at the highest listed price and unattributed usage counts toward the company; with no successful meter pass for 15 minutes a line is Unknown and one at 80% of its limit or more would hold; `dataAlerts` names a stale meter, a price list older than 90 days, unpriced usage, unattributed usage above 10% of the month, and unattributed usage with no company budget to count it. Agent lines count only what work steps report until Phase 2 ties sessions to registered agents, so project and company limits are the ones that hold.
- **The 5% overrun** is room for steps already running at a hard limit to reach a checkpoint, nothing more: no new work starts on it; it is per scope and period and does not stack (the tightest cap wins); at the limit plus 5% running billable steps stop at the next tool-call boundary, and only a deploy, migration, rollback or push under way may finish past it. It is measured on the meter's estimate, which lags and uses list prices, and on a small limit it is small ($1 on $20).
- **No dollar limits yet** (D-024 B5): the evaluator runs in shadow or soft-warning mode first; agent, project and company limits are then proposed to Jay from measured usage, with evidence.
- **Expensive steps (approved defaults, not built):** each billable step reserves its estimate and starts only if it fits every budget around it; a per-step cap (25% of the agent's daily limit or $10, whichever is lower) stops it at a checkpoint and asks its lead; estimates above $10 need the Project Lead, above $25 Jay; a scope spending more than 25% of its daily limit within an hour trips the burn-rate breaker: no new billable step starts, running work reaches a checkpoint, Jay is alerted and the cause is investigated; a step repeating a failing action or making no progress for 10 turns stops; long steps checkpoint at least every 15 minutes. A critical operation declares its cost and starts only with that much room left.

### 9.3 Prototype

The **Budgets** page (sidebar, `#/budgets`) shows company, project and agent budgets with alert thresholds, four demo scenarios (a held agent beside its still-running project, a held project, a held company), which new work would start, the safety exemption, and an override dialog that files a request on the Approvals page, all as mock data. The page uses a TypeScript copy of the server rules (`src/data/governance.ts`), and the same tests cover both: an agent hold leaves its project running, safety work starts at the company limit, and an approved override lifts only its own line. An **Approved defaults** panel lists Jay's 2026-10-24 defaults (alert levels, the checkpoint-only overrun, the per-step cap, who approves large steps, the burn-rate breaker), each agent row shows its step cap, and the page says the dollar limits are examples, since none are set yet. The New Agent flow's budget step shows the same rules. In **Teams**, CommandCenter, GYST, SamVision and MFE are led by the Claude Project Lead, and paused GauzeMate shows no active Project Lead.
