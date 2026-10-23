# Engineering HQ — audit and migration plan

Status: **Stage A + B + C (prototype)**, plus the onboarding groundwork Jay allowed on 2026-10-23 (§7.0). Branch
`claude/project-thread-gs2u2h`, draft PR #64, not merged or deployed. No policy file, credential or deploy was touched.
The prototype lives in `design/ui-prototypes/engineering-hq/`; the groundwork is new server modules behind a flag that
is off (`server/ccd/onboarding.py`, `server/ccd/budgets.py`, tasks.db migration 10).

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

1. Jay reviews the prototype; decisions in §2.
2. Tokens + shell (sidebar, top bar, tab strip) behind a `?ui=hq` flag; old UI default.
3. Window manager in `web/app`, wrapping existing Room/Pane pop-outs; regression tests that closing never calls `ptyClose`.
4. Pages one at a time on read-only data: Topology → Office → Engineering → Teams → Decisions.
5. Messages and Revenue only after their backend proposals are approved.
6. Flip the default after Jay signs off; old screens remain reachable.

## 6. Tool proposals

None needed so far. Possible later: `@playwright/test` as a dev dependency for CI (tests currently use the globally installed Playwright). Not added without Jay's approval.

## 7. Agent onboarding and project creation: backend proposal (not implemented)

**Status: groundwork built, enforcement not.** Jay's decision of 2026-10-23 allows the policy-independent parts behind a disabled flag (§7.0). Everything that grants, activates or enforces stays a proposal until Jay makes D-024 final and approves each switch; the final proposal is the [D-024 final proposal](https://claude.ai/artifact/3QArYLzEbEnzBV1geGUxXN) doc. The prototype's wizards still write only to the local mock store (`src/data/org.ts`); they do not call ccd.

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

Writes need Jay and Developer Unlock; agents are refused in the daemon, the module and the schema. 21 server tests in `server/tests/test_onboarding.py`.

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
| `agent_memberships` | `agent_id`, `project_key`, `role` (lead/member), `reports_to` (agent id or `jay`), `since`, `until` | At most one open lead per project (partial UNIQUE index). Reporting must form a tree rooted at `jay` (checked on write). |
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
| D-024 | Project and agent onboarding. Still proposed; the final wording with its implications is the [D-024 final proposal](https://claude.ai/artifact/3QArYLzEbEnzBV1geGUxXN) (clauses 10 to 14 add agents, Slack and budgets). Once Jay makes it final, record it in `policy/decisions/` so profiles can cite it. |
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
2. Jay makes D-024 final; record it in `policy/decisions/` with a short ADR.
3. Merge the groundwork (this draft PR or its own) with the flag still off in production; turn it on in a dev ccd first.
4. Shadow: the onboarding engine path and the budget evaluator record what they would allow, refuse or hold.
5. Slack requests with the secure link (§8, step 1), once the approval screen is reachable over Jay's private path.
6. After Phase 2 actor-token enforcement: each switch on its own (engine `onboarding` mode, Broker credential withholding, agent activation and grants, budget holds).
7. Last: low-risk approvals inside Slack (§8, step 2).

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
| Alerts before the limit | `assess`: default 50/75/90 %, per scope; plus `onCourseToHold` when the run rate reaches the limit before the period ends |
| Hard limit holds its own scope only | `would_start`: an agent hold stops that agent; a project hold that project; the company hold all billable work |
| Safety is separate | `SAFETY_KINDS` (health checks, monitoring, incident response, rollback, restore, backup checks, recovery) always start; the engine tags them by action type, an agent cannot |
| Running work checkpoints | A hold acts only at scheduling; running work finishes its step and checkpoints (D-027); deploys, migrations, rollbacks and pushes in flight are never cut |
| Override and adjustment | `effective_limit`: a temporary override adds to a limit until it expires and can never lower or remove it; an adjustment is a new configuration version |
| Resume | After an override or the period reset, held work resumes from its checkpoints in queue order, re-verifying facts D-031 requires at use |
| A hold is not a safety event | It never changes a project's mode, never triggers D-026 tightening, never opens a D-023 incident |

### 9.2 Gaps

- The meter prices Claude at list prices (an estimate) and has no Codex price, so token limits sit beside USD limits and unpriced replies are counted.
- Measured usage is tied to projects and tickets, not agents. Agent lines count only usage a work step reported, and say so. Attributing sessions to registered agents is a Phase 2 item.

### 9.3 Prototype

The **Budgets** page (sidebar, `#/budgets`) shows company, project and agent budgets with alert thresholds, four demo scenarios (a held agent beside its still-running project, a held project, a held company), which new work would start, the safety exemption, and an override dialog that files a request on the Approvals page, all as mock data. The page uses a TypeScript copy of the server rules (`src/data/governance.ts`), and the same tests cover both: an agent hold leaves its project running, safety work starts at the company limit, and an approved override lifts only its own line.
