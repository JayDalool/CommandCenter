# Engineering HQ — audit and migration plan

Status: **Stage A + B + C (prototype)**. Branch `claude/project-thread-gs2u2h`. No production file,
service, database, policy or deploy was touched. Everything new lives in `design/ui-prototypes/engineering-hq/`.

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

**Status: proposal only.** Nothing in this section exists in `server/`. The prototype's New Agent and New Project wizards write only to a local mock store (`src/data/org.ts`). Building any of this needs Jay's sign-off on the design first. It touches the capability broker, `security.py`, the policy files and agent permission rules, and some of it is Phase 2, which has not been started. Each numbered step in §7.8 is its own gated PR, off by default.

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
| D-024 | Referenced by Jay as the governing decision for agent onboarding. It is not in `policy/decisions/` on this branch (D-001 … D-009). Proposal: record it as a decision file before any of this is built, so profiles can cite it. |
| WorkerNodes (`workers.py`) | Worker grants and project eligibility reference approved node IDs only. A pending or revoked node is never eligible. |
| Capability Broker | The only enforcement point for effective permissions, merges and deploys. Onboarding writes grants; the broker reads them. |
| Actor tokens (`identity.py`) | Offboarding and pausing revoke or suspend the agent's tokens. Enforcing token ↔ `X-CCD-Actor` match is the Phase 2 prerequisite for §7.5. |
| Decisions / Approvals | "Approve repository creation" and stage promotion appear as Decisions items for Jay, the same as today's gates. |
| Audit chain (`audit.py`) | Every write above; domain events link to it. |
| Usage meter (`meter.py`) | Agent and project budgets read the meter. Budget breach → pause (not delete) and a Decisions item. Budgets are Phase 2. |
| Future deterministic runbooks | Repo creation, environment discovery and WorkerNode setup become runbooks Jay runs, each with its own approval, never side effects of onboarding. |

### 7.7 Risks found while building the prototype

1. **Self-asserted actor header.** Until actor-token enforcement exists, anything with ccd's token can claim to be Jay. The endpoints above must require Developer Unlock, not the header.
2. **Registry lives in code.** Adding projects at runtime needs a merged code+table registry with cross-checks for prefix collisions, including legacy prefixes and board IDs.
3. **Grant drift.** If templates change later, existing agents must not silently change. Hence versioned configs that copy grants, not references to templates.
4. **Offboarding orphans.** Open tickets, conversations, tokens and worker leases must all be handed over or revoked in one transaction.
5. **Confusable names.** "Nova" vs "N0va" in approvals and Slack messages. Warn on create; show the ID next to the name in approval surfaces.

### 7.8 Proposed order (each its own PR, off by default, after Jay's sign-off)

1. Record D-024 and a short ADR for this design.
2. Read-only `GET /api/agents` built from today's sessions and registry (no new writes).
3. Tables + `POST /api/agents` / lifecycle behind a feature flag, Developer Unlock required, no credentials.
4. Project creation as a proposed registry row + profile PR, observation only.
5. Broker reads agent grants (shadow mode first, measuring what it would refuse).
6. Enforcement, after Phase 2 actor-token enforcement is approved.
