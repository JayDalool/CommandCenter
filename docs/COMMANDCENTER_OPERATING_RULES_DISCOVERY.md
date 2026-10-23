# CommandCenter Operating Rules — Discovery (running file)

Status: **discovery only.** Nothing in this file is enforced or implemented. Proposed decisions become real only
when Jay confirms them, and become policy files (`policy/decisions/D-NNN.toml`) only after a separate, approved
docs-only change. No deploys, no production changes, no Phase 2 work come from this file.

Started 2026-10-21, while the Phase 1 live deploy is paused (Jay away from jay-server).

How each answer is recorded:

| Field | Meaning |
|---|---|
| ID | Next free decision ID, D-010 onward |
| Rule | The proposed durable policy, in one or two sentences |
| Controls | The system behaviour it would govern |
| Scope | `global` or a named project profile |
| Type | **hard boundary** (never, no approval unlocks it) · **approval** (needs Jay each time) · **autonomous** (allowed without asking, within limits) |

---

## 1. Baseline already decided (do not re-ask)

From `policy/decisions/D-001 … D-009` and `docs/COMMANDCENTER_V2_DISCOVERY.md` §0:

- **D-001** Per-project autonomy; the broker merges, never an agent's own login.
- **D-002** Employer Java repos: AI allowed (Anthropic, OpenAI); repo + secrets laptop-only; server clone needs Jay.
- **D-003** No paid GitHub plan now; paid tools enter as a Tool Proposal. `spend_money` is human-only.
- **D-004** SamVision/MFE unattended deploy only for low-risk releases, and only once health checks + auto-rollback exist.
- **D-005** GYST: data model, retention, privacy, encryption, deletion, auth, irreversible migration need Jay.
- **D-006** Slack first for phone approvals; loopback-only access is never weakened.
- **D-007** Changes to the rails (autonomy engine, broker, security, policy files, agent permissions) need Jay.
- **D-008** Engine runs in shadow mode; no autonomous merge/deploy in Phase 0/1.
- **D-009** GauzeMate paused; placeholder profile.

Facts already known from the repo (not decisions):

- SamVision's checkout is `/srv/server/apps/samvisionai` on jay-server; the others are under `/srv/server/repos/`.
- SamVision and MFE target profiles already say `never = [prod_docker_compose_changes, prod_database]`;
  SamVision also `licensed_data_in_outputs`, `property_records_in_screenshots`.
- CommandCenter itself is loopback-only on jay-server (no Cloudflare, Funnel, Tailscale Serve or nginx vhost).
- Jay's global rule (ADR 0006): a message from CommandCenter never authorizes a merge, deploy, production step,
  `--apply`, secret access or rule change.
- Backups exist today only for CommandCenter's own SQLite (`~/command-center/backups/`).

---

## 2. Confirmed decisions (D-010 onward)

Status of every row: **proposed from Jay's answers (2026-10-21T17:37Z), not yet enforced.** They become
`policy/decisions/*.toml` only through a separate docs-only change Jay approves.

### D-010 · Production hosting inventory
- **Answer (Q1):** Every project (CommandCenter, SamVision, MFE, GYST, GauzeMate) runs on **jay-server**, a
  locally hosted Dell OptiPlex Linux box. Apps run in **Docker** behind **nginx**. All databases run locally on
  jay-server. The domain **zaylolabs.com** is registered at **Cloudflare**, and Cloudflare runs its DNS. A
  **Cloudflare Tunnel** from jay-server publishes `samvision.zaylolabs.com`. Deploy today = Jay runs one command.
- **Rule:** jay-server is the only production host. Public traffic reaches it only through the Cloudflare Tunnel,
  never through an opened router port. TLS for public hostnames is terminated at Cloudflare's edge. Adding a
  new production host, or exposing a service by another path, needs Jay.
- **Controls:** project profiles gain a `hosting` block (`host = "jay-server"`, `runtime = "docker"`,
  `proxy = "nginx"`, `ingress = "cloudflare_tunnel" | "none"`, `public_hostnames = [...]`, `db_location = "local"`).
  Health checks, rollback and incident response all target jay-server's Docker.
- **Scope:** global (inventory per project).
- **Type:** approval (new host / new exposure path); hard boundary (no open inbound ports).
- **Note:** CommandCenter itself stays loopback-only (D-006, `docs/SECURITY.md`): it is never added to the tunnel
  or to nginx. Only SamVision is known to be public today; the others are assumed internal until Jay says otherwise.
- **Still unknown:** the database engine per project, and the exact deploy command per project (backlog).

### D-011 · Browser Capability Policy (confirmed with Jay's changes)
- **Answer (Q2):** Yes to the proposed ladder, with these changes: agents log in to **our own sites with their
  own agent accounts**; a **new third-party site** needs approval only when it means signing up or buying;
  **just visiting to look at a site is fine**; agents may use any website that is free.
- **Rule:** see §4.1 (updated). Summary: observe/inspect/test on our dev and test sites are autonomous; our sites
  may be used logged in as that agent's own account; free public websites may be visited and read; creating an
  account on a new third-party service, writes to production, and external communication need Jay; purchases
  stay a hard boundary for agents.
- **Controls:** the browser tool wrapper checks the tier of each action against the target (our dev, our prod,
  third-party, paid) before acting; it refuses Jay's own logged-in browser profile.
- **Scope:** global; project profiles may tighten it (SamVision: no property records in screenshots).
- **Type:** mixed: autonomous (observe, inspect, test, free browsing), approval (modify_production,
  external_action, new third-party sign-up), hard boundary (financial_action).

### D-012 · One account per agent on our sites
- **Answer (Q2):** "Every agent of ours will have its own account in our sites."
- **Rule:** each agent identity (e.g. `agent-claude-sv`, `agent-codex-gyst`) has its own login on each of our apps,
  with the least role it needs. Agents never use Jay's account or Jay's browser session. Agent accounts on
  production get no admin role unless Jay grants it.
- **Controls:** agent identity registry; audit logs on our apps attribute every agent action; revoking one agent
  does not affect others.
- **Scope:** global; one account set per project.
- **Type:** autonomous (use of its own account); hard boundary (never Jay's session); approval (admin role on
  production, because D-007 says no agent expands its own authority).
- **Open:** whether agent accounts on *production* are allowed at all, or only on dev/test (asked later with staging).

### D-013 · Paid tools: a short proposal, Jay decides
- **Answer (Q2):** "If we need a paid sub, make a small proposal of why we need it and send it to me to decide."
- **Rule:** when work needs anything paid (SaaS, subscription, plan upgrade, paid API), the agent stops and sends
  a short Tool Proposal: what, monthly cost, why, what it unblocks, the free/self-hosted alternative and why it is
  not enough. Jay decides. Agents never enter payment details. Extends D-003.
- **Controls:** a `ToolProposal` Needs You item (Slack per D-006); `spend_money` stays human-only.
- **Scope:** global.
- **Type:** approval (proposal → Jay); hard boundary (agents never pay).

### D-014 · Where secrets live and who may read them
- **Answer (Q3):** Yes to the proposed rule. Secrets live in a **`.env` per repo** on jay-server today.
- **Rule:** agents may read dev/test secrets of the project they are working on. Production credentials are
  never readable by an agent; only the deploy runner/broker uses them. Secrets never go into tickets, logs,
  Slack, screenshots or model prompts.
- **Controls:** separate dev and prod env files per repo; the agent sandbox mounts only the dev/test one; the
  existing secret-path denylist (`docs/SECURITY.md`) stays.
- **Scope:** global; restricted employer profile stays laptop-only (D-002).
- **Type:** autonomous (dev/test read); hard boundary (no agent reads production credentials).

### D-015 · Creating or rotating credentials: allowed, with an Immediate Attention report
- **Answer (Q3):** "Creating or rotating a credential doesn't need me, but requires a report back to me with
  Immediate Attention text and a red banner to let me know what we did and why."
- **Rule:** CommandCenter may create or rotate a credential without asking. Every time, it sends Jay an
  **Immediate Attention** report (red banner in CommandCenter, Slack message marked urgent) that says which
  credential, which project, what changed, why, where the new value is stored, and how to undo it. The report
  never contains the secret value.
- **Limits (from earlier decisions):** this does not let an agent give itself more access (D-007): a credential
  that widens an agent's permissions still needs Jay. A production credential is rotated by the broker/deploy
  runner, so the agent never sees its value (D-014). Employer credentials stay laptop-only (D-002).
- **Controls:** new `credential_change` event type → Immediate Attention alert; audit record kept forever.
- **Scope:** global.
- **Type:** autonomous, with a mandatory urgent report.

### D-016 · A password manager for important passwords (intent)
- **Answer (Q3):** "I want to make a password manager that has all of our important passwords there."
- **Rule (proposed):** important passwords and production credentials move into one password manager. Proposed
  default: a self-hosted, free option on jay-server (e.g. Vaultwarden), behind the tunnel or loopback only, raised
  first as a Tool Proposal. Agents get scoped access only to the entries D-014 allows; Jay's personal vault is
  never readable by agents.
- **Controls:** later, the broker reads production secrets from the manager instead of `.env` files.
- **Scope:** global.
- **Type:** approval (choosing and setting it up is Jay's call); not part of Phase 1 or 2.

### D-017 · Remote-hosted projects are first-class
- **Answer (2026-10-21T19:53Z):** "Think about the case where we have a new project hosted remotely ... it should
  also be a way in our software."
- **Rule:** a project's host is a profile field, not an assumption. `hosting.host` is `jay-server` or
  `remote:<name>`. Every rule in this file (deploy, backups, health checks, restarts, rollback, secrets, browser)
  applies the same way to a remote host. CommandCenter reaches a remote host only through the access method in
  that project's profile (decided in Q7), never through Jay's own login.
- **Controls:** profile `hosting` block gains `host`, `provider`, `access`, `health_url`; the operations page
  (D-019) shows each host; onboarding (Q8) detects remote hosting.
- **Scope:** global (schema), set per project.
- **Type:** requirement; access rules pending Q7.

### D-018 · Databases and backups
- **Answer (Q4):** The projects use a mix of **Postgres, MySQL and SQLite**. **MFE is backed up, Jay believes
  daily. SamVision is backed up about weekly.** Others are unknown. Verify on jay-server when it is reachable (§8).
- **Rule (proposed, Jay did not object):** an automatic backup runs before every deploy or migration that touches a
  database; retention 14 daily + 8 weekly on jay-server plus one off-server copy; a test restore into a throwaway
  container runs weekly. Restoring over production, dropping, truncating or bulk-deleting production data needs
  Jay every time. A project whose database has no backup counts as **not release-ready** for anything that touches data.
- **Controls:** pre-deploy backup step in the deploy runner; backup and restore-test jobs on a schedule; results
  feed the operations page (D-019).
- **Scope:** global; per-project engine and schedule recorded in each profile (`db = { engine, location, backup }`).
- **Type:** autonomous (backups, test restores into throwaway containers); approval (restore over production,
  destructive production operations).
- **Update (repo evidence, not rechecked):** SamVision `docs/backups.md` says backups run nightly at 04:00 with read-back
  verification, 14-day retention and a restore check, but no offsite copy; MFE is backed up nightly at 03:30 by
  `/srv/server/scripts/backup-postgres.sh`. So SamVision already meets the daily rule; the gap is offsite.

### D-019 · Operations page: backups, restores, health checks, schedule
- **Answer (Q4):** "We also need an indicator page for our backups and restores, health check and schedule."
- **Rule:** CommandCenter gets one page that shows, per project and host: last backup (time, size, age warning),
  last restore test (pass/fail), current health check result, and the schedule of upcoming backups, restore tests,
  release windows and maintenance. Stale or failed items show red and raise a Needs You item.
- **Controls:** a read-only page and API; no buttons that change production in its first version.
- **Scope:** global.
- **Type:** feature requirement (build later, not Phase 1).

### D-020 · Production operations without a code change
- **Answer (Q5):** "Yes, agents are allowed, but to restart, send me a message first on why, then restart."
- **Rule:** agents may read logs and run health checks anytime. Before restarting a container or service, the agent
  sends Jay a message saying which service, what it saw, and why it is restarting, and then restarts it. It does
  not wait for a reply (reading of "send me a message first, then restart"). One restart per incident; if the
  service is still unhealthy, it stops and alerts Jay. After a failed post-deploy health check, it may roll back to
  the last good image and reports it. Rebuilding images, clearing caches, and changing docker-compose or nginx
  config need Jay (SamVision/MFE already forbid compose and DB changes).
- **Controls:** a `restart` action that first emits a Slack/Needs You notice, then runs; a per-incident restart
  counter; rollback only to an image recorded as last good.
- **Scope:** global; applies to jay-server and remote hosts (D-017).
- **Type:** autonomous (logs, health checks, rollback with report); autonomous after notice (restart, once);
  approval (rebuild, cache clear, config change).

### D-021 · Preview subdomains
- **Answer (Q6):** "Yes, absolutely."
- **Rule:** CommandCenter may create private preview hostnames under `*.dev.zaylolabs.com` (tunnel route, nginx
  config, container) protected so only Jay and agent accounts can open them, and reports each one. Creating or
  changing a public production hostname, and editing any existing DNS record, needs Jay.
- **Controls:** a Cloudflare API token scoped to the `dev` zone records only; a register of previews with an
  owner and expiry; previews older than 14 days with no activity are torn down and reported.
- **Scope:** global.
- **Type:** autonomous with report (previews); approval (public hostnames, existing records).

### D-022 · Remote hosts and the directed working style
- **Answer (Q7, 2026-10-21T20:36Z):** A rented server would be **DigitalOcean or AWS**; app hosting probably
  **Vercel**; or a **client's own server**. Permissions are set per project. For a client's server or a
  production site, Jay would "set it to get back to me on changes and I will dictate tasks", working like the
  employer Java repos today: the agent explains every step and decision, asks what to work on next, and asks
  the questions a developer would ask.
- **Rule:** remote providers expected: DigitalOcean, AWS, Vercel, client-owned servers. CommandCenter connects to
  a remote host only with a credential made for that one project (a provider token scoped to the project, or SSH as
  a deploy-only user with its own key), never Jay's personal login or root. A client-owned server gets no write
  access without Jay's approval. Profiles gain an `interaction_style` field: `directed` (explain each step and
  decision, propose next tasks, ask before acting, Jay dictates the work) or `autonomous`. Client servers and
  production-facing remote sites default to `directed`.
- **Controls:** `hosting.provider` in `{jay-server, digitalocean, aws, vercel, client}`; `interaction_style` in the
  profile; the engine treats `directed` as "propose and wait" for anything beyond observe/inspect.
- **Scope:** global schema; set per project.
- **Type:** approval (client-server write access, every task in `directed` style); hard boundary (no personal or
  root credentials on remote hosts).

### D-023 · Incident pause, full stop, and a full incident report
- **Answer (Q9):** "Yes, and when that happens I need a full incident report sent to me."
- **Rule:** two failed deploys or two rollbacks in 24 hours pause that project's autonomy and raise an Immediate
  Attention alert. Everything stops (all agents, all projects) when an agent acts outside its policy, production
  data is deleted unexpectedly, a secret leaks somewhere it cannot be rotated, or a web page or file instruction
  leads an agent to take an action. Only Jay restarts after a full stop. Every pause and every full stop produces a
  **full incident report** sent to Jay: timeline, what triggered it, what CommandCenter did automatically, current
  state, impact (projects, data, users), what is still at risk, the evidence (logs, events, commits; never secret
  values), the proposed fix, and what Jay must decide to resume.
- **Controls:** a `pause` and a global `halt` switch in the engine; an incident record type; the report goes to
  Slack (D-006) and the Needs You page with the red Immediate Attention banner (as D-015).
- **Scope:** global.
- **Type:** autonomous (pausing and halting are always allowed); approval (resuming after a full stop).

### D-024 · New project onboarding (proposed, Jay agreed with the design)
- **Status:** Jay agreed with the design and the pushback (2026-10-21T21:15Z): pushes and PRs are not automatically low
  risk; discovery never runs code with the project's normal environment or secrets; evidence grades instead of AI
  confidence numbers; boundaries enforced by missing credentials wherever possible. Stays **proposed** until Q15
  (fact ageing) is answered.
- **Design:** Project Onboarding Design doc (https://claude.ai/artifact/AR9b53F8irK2VB3d8fzAmu): `onboarding` mode,
  Project Fingerprint, First Audit, draft profile, proposal PRs, graduation evidence, Admission Review.
- **Existing projects (Q12):** baseline admission audit instead of seven days; current permissions unchanged except
  that D-026 tightening still applies. Facts graded imported verified / newly verified / observed / inferred /
  unknown; old facts keep their original date until rechecked. Order after Phase 1 is deployed: CommandCenter,
  GYST, SamVision, MyFamilyExpenses; GauzeMate only when resumed. CommandCenter's own admission also gets a Codex
  second opinion, and every finding on a D-007 path goes to Jay.
- **Groundwork allowed (Jay, 2026-10-23T02:54Z):** policy-independent backend infrastructure may be built behind a
  disabled feature flag (agent registration records, onboarding drafts, validation, audit trails, read-only APIs).
  Before any policy-dependent function is activated, D-024 is shown to Jay as a final proposal with its
  implications and approved. No permissions granted, no agents started, no proposed policy enforced as if approved.
- **Scope:** global. **Type:** hard boundary (authority actions during onboarding), approval (graduation),
  autonomous (observe, inspect, sandbox, audit, safe draft PRs).

### D-025 · Pushing and opening a PR are boundary actions
- **Answer (Q10):** yes, with Jay's added restriction.
- **Rule:** four separate actions: edit files locally, create a local branch (both automatic), push the branch, open a
  PR (both boundary-crossing). On Jay's own repos during onboarding, a push or draft PR is allowed only after a
  deterministic push safety check proves it will not deploy code, run privileged CI, expose production secrets,
  call production webhooks, change production infrastructure or data, send external communication, create
  meaningful cost, or reach another project. True or unknown on any line: stop and ask Jay before pushing. Client
  and employer repos: no automatic push or PR during onboarding; patches stay local and are shown to Jay; a
  permanent profile may grant PR rights later. CI configuration (`.github/workflows/**` and equivalents) is
  privileged infrastructure: never pushed or opened as a PR during onboarding without Jay's approval; after
  graduation the profile decides routine CI edits, but runner, secret, permission and security CI changes stay protected.
- **Note:** a repo whose `pull_request` CI runs on our self-hosted runners counts as privileged CI, so every
  onboarding push to it will stop and ask. Intended.
- **Controls:** a push-safety checker before every push; branch-only token from the Broker; `.github/**` already in
  CommandCenter's protected paths.
- **Scope:** global. **Type:** approval (push/PR when the check is not clean; any CI change during onboarding);
  autonomous (local work; clean pushes and draft PRs on Jay's repos).

### D-026 · Authority only moves down automatically
- **Answer (Q11):** yes.
- **Rule:** CommandCenter may make a project more restrictive automatically on verified evidence, never less.
  Autonomous Product → Controlled Production → Restricted → Paused; only Jay moves a project up.
  Down to **Restricted** on: unknown production connection, unexpected credential exposure, new sensitive-data
  handling, deploy mechanism changed, CI gained privileged credentials, production environment ambiguous, policy
  drift, new external side effect, an important hosting/DB/DNS fact no longer verified. Full report immediately.
  **Pause** on: active or suspected security incident, secrets exposed, production integrity uncertain, unexpected
  destructive action, project identity or hosting target ambiguous before a write, policy enforcement broken,
  worker or agent identity unverifiable, possible autonomy bypass. When paused: stop new autonomous writes, keep
  state and worktrees, no automatic recovery across a security boundary, keep safe observation, full D-023 report.
  LLM opinion, graph intelligence or unverified inference alone never restricts or pauses; it raises a finding that
  triggers a deterministic check.
- **Pushback (Q15):** "fact no longer verified" should first trigger re-verification, and tighten only if that fails
  or finds a change; otherwise projects drop to Restricted on a calendar.
- **Scope:** global. **Type:** autonomous (tightening); approval (any loosening).

### D-027 · Task execution modes and one writer
- **Answer:** Jay restated the model as required.
- **Rule:** the project profile sets the maximum authority; each task is Manual, Assisted or Autonomous and may be
  stricter than its project, never more permissive. One writer per worktree or task at a time: `jay` or
  `agent:<job-id>`. Commands: Take over myself, Give back to CommandCenter, Pause agent, Resume, Help me with this,
  Review what I changed, Finish this for me, I will finish this myself. Every ownership change checkpoints branch,
  worktree, commit, uncommitted diff, tests, plan, decisions and pending work. Conflicting human and agent edits are
  never resolved silently.
- **Proposed detail:** in Assisted mode ("Help me with this") the agent writes only patches or a scratch branch that
  Jay applies, so the worktree keeps one writer.
- **Controls:** extends the existing writer/checkpoint fields in `ccd/pipeline.py`.
- **Scope:** global. **Type:** hard boundary (one writer; task never above project).

### D-028 · Derived code intelligence is evidence, not authority (proposed)
- **Source:** Jay's Graphify brief. Full evaluation: Graphify Tool Proposal doc
  (https://claude.ai/artifact/M881qmRtEeRxRwuDohAP5B).
- **Rule:** Git is source-code truth; CommandCenter SQLite is operational, task, policy, approval, decision,
  execution and audit truth; Graphify or any code graph or index is derived data. CommandCenter works fully without
  it. Graph intelligence may raise risk, may never lower deterministic risk, never authorizes merge or deploy, never
  bypasses approval. A missing or stale graph counts as no evidence. A raise asks for more scrutiny; it does not
  restrict or pause on its own (D-026).
- **Tool proposal (TP-001, Graphify-Labs/graphify):** recommendation **LOCAL SANDBOX EXPERIMENT, CLI only**: never
  `graphify install`, `claude install`, `codex install` or `hook install` (they edit CLAUDE.md, AGENTS.md, hook
  settings and git hooks); `GRAPHIFY_BACKEND=none`, `--code-only`, pinned version, no model keys, output never
  committed. Explicit refresh only (onboarding, entering review, handoff, a refresh button); no watch mode or hooks.
  Multi-repo option D. Restricted repos laptop-only, never in a shared or cloud graph. Not installed; awaits Q14.
- **Experiment approved (Q14, 2026-10-22T17:51Z):** the local sandbox experiment may run **after Phase 1 is
  deployed and verified**, not before. Throwaway copy of CommandCenter; local, CLI only; no Graphify Cloud, no source
  upload, no paid services, no AI backend unless separately approved; no `graphify install`; no change to CLAUDE.md,
  AGENTS.md, Claude hooks, git hooks or agent settings; no production repo mutation; no effect on ccd or CI; no
  secrets. Measures indexing time, CPU, RAM, disk, graph size, stack coverage, accuracy, stale-graph behaviour
  (including whether Claude notices staleness with the SHA check off), architecture and change-impact answer
  quality, context/token use vs ordinary inspection, fallback, and clean uninstall. Approval of the experiment is
  not approval to adopt: Jay decides ADOPT LOCAL, WATCH or REJECT from the evidence. No automatic promotion.
- **Scope:** global. **Type:** hard boundary (graph never lowers risk or authorizes).

### D-029 · Local CI runner operations (proposed)
- **Source:** Jay's local CI brief. Full design: Local CI Runner Operations doc
  (https://claude.ai/artifact/BVqfMHUwKTDYSwaxe12rgE).
- **Current setup (from the repos, 2026-10-21):** CommandCenter, GYST and SamVision run `pull_request` CI on
  `[self-hosted, linux, x64]` (identical labels); MyFamilyExpenses (public) uses GitHub-hosted `ubuntu-latest`;
  GauzeMate has no CI. No workflow uses `secrets.*` or `pull_request_target`. SamVision's CI runs `sudo apt-get`
  (runner user has sudo) and sets no `permissions`; SamVision and GYST keep the checkout token in the workspace.
  Which machine the runners are on is not in any repo.
- **Rule:** status and diagnostics automatic. Our own runners: restart when idle and unhealthy (max 2 per 24 h, then
  quarantine), drain busy runners and restart after the job, never kill a legitimate job for maintenance. Stale
  processes and ports cleaned only after a seven-step ownership proof (protected class, PID facts, CI tracking ID,
  runner work dir, GitHub says job finished, timing, allowed class); ambiguous means never kill. Port classes
  `protected` / `managed_dev` / `ephemeral_ci`, defined in `policy/`; unlisted = protected. Re-run a failed job once
  per infrastructure failure signature; repeated identical failures stop and get diagnosed. Not automatic: unknown
  listeners, Docker restart, databases, reboot, active worktrees, broad cache clears during jobs, runner
  registration/tokens, Actions secrets, new network ports. `CIRunner` is a separate authority from `WorkerNode`.
  Self-hosted runners serve private repos only, with no sudo and no production reach.
- **Phases:** 0 harden runners (Jay's approval) before Phase 2 widens agent authority; 1 read-only visibility in
  Phase 2; 2 guarded actions after a clean week; 3 job hooks and ephemeral runners if needed.
- **Scope:** global; client/employer runners observe-only by default. **Type:** autonomous (status, bounded
  recovery, verified cleanup); approval (all "no" actions, workflow and runner changes); hard boundary (protected
  ports and services).

### D-030 · Execution host separation
- **Answer (Q13, 2026-10-22T17:51Z):** personal-project CI runners (CommandCenter, GYST, SamVision, other personal
  projects whose profile allows it) are meant to run on **Jay's Windows laptop inside WSL**, not on jay-server.
- **Rule:** `jay-server` = CommandCenter control plane and production services. `jay-laptop-wsl` = personal
  development, local CI and suitable agent execution. Normal PR CI never receives production-host privileges because
  both machines belong to Jay. Personal CI runners do not read production secrets, production `.env`, private
  application storage, production database files, production backups or CommandCenter credentials unless an
  explicit project or capability policy requires it. Enrolling a WorkerNode grants none of these. Least privilege:
  CI should not need broad root; if a deterministic step needs elevation, it gets a narrowly scoped, approved
  capability or script, never general sudo for arbitrary CI code.
- **Unresolved:** the runner's privileges are **UNKNOWN — MUST VERIFY BEFORE PHASE 2 EXECUTION AUTHORITY**:
  Linux user, sudo (any, passwordless, scope), Docker group and socket, Windows-mounted files, SSH keys, GitHub
  credentials, production `.env`, `/srv/server/private/`, backups, databases, network reach to production, shared
  Unix accounts between runners, workspace isolation. Not inferred from workflow files.
- **If a runner is found on jay-server**, especially with sudo, Docker or root-like access: HIGH priority
  infrastructure risk; propose migration or isolation before expanding autonomous execution; change nothing automatically.
- **Scope:** global. **Type:** hard boundary (no production-host privileges for PR CI); approval (any elevation).

### D-031 · Fact states, verification classes and verify-at-use
- **Answer (Q15):** yes to re-checking, with a more precise rule.
- **Rule:** time alone never removes authority; verified new evidence can tighten it; missing safety-critical
  evidence blocks only the operation that depends on it. Fact states: VERIFIED, OBSERVED, INFERRED, UNKNOWN,
  STALE / REVERIFY (TTL passed: run a safe deterministic re-check, restrict nothing), UNVERIFIED / RECHECK PENDING
  (the check could not run: block only dependent actions, e.g. deployment blocked while coding, tests and review
  continue), FAILED VERIFICATION and CHANGED (recalculate risk; D-026 may tighten). A successful re-check refreshes
  evidence, timestamp and fact version. Facts belong to classes with their own TTLs, configurable in policy.
  Proposed defaults: architecture 90 days; hosting/network 14 days; data 14 days; backup status 1 day, restore test
  30 days; runner privileges 7 days; identity 30 days; release target 7 days; worker liveness 2 minutes; secrets not
  aged (capability check at use, value never exposed).
- **Verify at the point of dangerous use:** a fresh deterministic check right before production deployment
  (target), migration (database target), credential use (account identity), DNS write (DNS target), privileged
  execution (worker identity), and push or merge (repository identity), even if verified yesterday.
- **Controls:** Project Fingerprint fields `state`, `fact_class`, `verified_at`, `version` (Project Onboarding
  Design doc, Fingerprint section).
- **Scope:** global. **Type:** autonomous (re-checks); per-action block (dependent operations only).
- **Effect on D-024:** all onboarding questions are answered; D-024 stays proposed until Jay confirms it final.

### D-032 · Mobile approvals through Slack
- **Answer (Jay, 2026-10-23T02:54Z, Engineering HQ thread):** yes to mobile agent approvals; Jay wants to run the
  company from his phone as well as his desktop.
- **Rule:** extends D-006. Phase one: Slack sends a detailed request (for example an onboarding request) with a
  secure link to an authenticated CommandCenter approval screen; the approval happens there. Later, suitable
  low-risk requests may be approved directly inside Slack, only with verified identity (Slack user bound to Jay),
  authorization checked by CommandCenter, short-lived single-use approval actions bound to the request hash, and a
  full audit record. High-risk permissions, repository access, policy changes and production capabilities always
  need stronger confirmation inside CommandCenter, never a Slack button alone. The local ccd API is never exposed
  publicly to make Slack work (Socket Mode, outbound only; the mobile link needs the separately designed secure
  remote access from D-006).
- **Open:** how the phone reaches the authenticated approval screen without exposing ccd (D-006's later secure
  tunnel design); which request classes count as Slack-approvable low risk.
- **Scope:** global. **Type:** approval (all approvals stay Jay's; only the channel changes); hard boundary (no
  public ccd API; high-risk approvals never in Slack alone).

### D-033 · Budgets: alerts and automatic pausing
- **Answer (Jay, 2026-10-23T02:54Z):** configurable budgets with advance alerts and automatic pausing.
- **Rule:** budgets at agent, project and company level. Advance alerts as spend approaches each limit (proposed
  defaults 50%, 80%, 95%, configurable). At a hard limit: stop scheduling new billable work in that budget's scope
  only; let in-progress work reach a safe checkpoint instead of being cut off mid-operation; notify Jay and the
  project lead; allow an authorized budget increase or temporary override; resume safely after authorization or a
  budget reset. One agent over its limit does not stop its whole project. Budget pausing is kept separate from
  safety: monitoring, rollback and incident recovery (D-020, D-023, D-026) are never blocked by a spending limit.
- **Controls:** per-execution cost metering (V2 discovery §6.9, §24) feeds a budget ledger; the scheduler checks the
  budget before claiming billable work; overrides are Jay approvals with an expiry and an audit record.
- **Scope:** global (company), per project, per agent. **Type:** autonomous (alerts, stopping new billable work);
  approval (overrides and budget increases).

---

## 3. Questions asked, awaiting Jay

Batch 1 (Q1 hosting, Q2 browser, Q3 secrets) answered 2026-10-21T17:37Z → D-010 … D-016.
Batch 2 (Q4 databases, Q5 production ops, Q6 subdomains) answered 2026-10-21T19:53Z → D-017 … D-021.
Batch 3 (Q7 remote hosts, Q8 onboarding, Q9 incidents) answered 2026-10-21T20:36Z → D-022, D-023; Q8 grew into
the onboarding design (D-024, under discussion).

Batch 4 (Q10 push/PR, Q11 tightening, Q12 existing projects) answered 2026-10-21T21:15Z → D-025, D-026, D-024
updated; task modes → D-027; Graphify → D-028 + TP-001; local CI → D-029.

Batch 5 (Q13 runner host, Q14 Graphify experiment, Q15 fact ageing) answered 2026-10-22T17:51Z → D-030,
D-028 (experiment approval), D-031; backups recorded as finding AF-001.

### Batch 6 (asked 2026-10-22)

**Q16 · Database migrations on CommandCenter and GYST.** SamVision and MFE already forbid agents touching the
production database, and D-005 covers GYST's personal-data changes. Proposed for the rest: an agent-written migration
may apply automatically only if it is additive and reversible (new table, column or index, with a tested down step),
it first applied cleanly to a copy restored from last night's backup, a fresh backup is taken just before, and the
database target is re-verified at use (D-031). Dropping, renaming, rewriting data or a long-locking change needs Jay.

**Q17 · Production emergency when Jay is unreachable.** D-020 already allows one restart and a rollback to the last
good image. If that does not fix it, may CommandCenter deploy a forward fix? Proposed: SamVision and MFE never
(prepare the fix, hold it, keep alerting); CommandCenter and GYST only once their auto-rollback is verified, and only
a small fix with green CI, Claude and Codex review, and no migration.

**Q18 · What data may leave jay-server.** Proposed: SamVision: no individual property records in any output,
screenshot, Slack or model prompt (its AGENTS.md rule). GYST and MFE: no personal, health or family-financial
records in Slack, Drive or screenshots; logs redacted before an agent reads them. All projects: model providers
(D-002) see code and redacted logs, never production database rows beyond aggregate counts.

---

## 3a. Audit findings (not decisions)

**AF-001 · SamVision backups: nightly, same host, no offsite copy** (repo evidence, not rechecked on the host).
Source: SamVision `docs/backups.md`, `docs/deployment.md`, `docs/offsite_backup_decision.md`.

| Dimension | What the docs say |
|---|---|
| Frequency | nightly 04:00 (`scripts/backup_tenants.py`, cron); MFE nightly 03:30 via `/srv/server/scripts/backup-postgres.sh` |
| Success signal | each dump read back with `pg_restore --list`; `last_run.json`; Uptime Kuma heartbeat alerts after 25 h without a good run |
| Restore verification | `scripts/restore_check.py` restores into a scratch DB and compares counts; runbook says monthly and after schema changes. Last actual run unknown |
| Retention | 14 days, never fewer than 3 dumps per database |
| Location | `/srv/server/backups/postgres/samvision/` on jay-server, same disk as the database |
| Offsite / second machine | **none**. restic 0.18.1 installed and `scripts/offsite_backup.py` written; no destination chosen |
| Encryption | dumps on disk: not stated; restic would encrypt the offsite copy |
| Disaster recovery | not covered: host loss, disk failure, filesystem corruption, theft or compromise lose both the DB and its backups |

Next step (later, not now): propose low-cost options that use hardware Jay already owns first (for example the
laptop or an external drive as a restic target) before any paid service. Nothing purchased or installed.

**AF-002 · SamVision CI uses sudo for one package.** `.github/workflows/ci.yml` runs
`sudo apt-get install libgomp1` for `lightgbm`, which only `ml/` scripts import; no test imports it (grep at
`8437f23`). Likely removable from CI; prove by running the suite without that step in a clean container first.
The runner's real sudo scope is unknown until checked on the laptop (D-030).

**Out of scope here:** the Engineering HQ "New Agent / New Project" onboarding screen belongs to draft PR #64 as a
mock-only prototype, not to these infrastructure decisions or the live backend.

---

## 4. Proposed rules (draft, not confirmed)

### 4.1 Browser Capability Policy (confirmed in D-011, D-012, D-013)

| Tier | Examples | Rule |
|---|---|---|
| `observe` | open localhost/dev sites, open our production pages, visit any free public website to look at it, screenshots of dev/test | autonomous |
| `inspect` | DevTools console/network, Lighthouse, accessibility checks, responsive layouts | autonomous on dev/test; on production read-only |
| `test` | fill and submit forms, create/delete records in a test environment, logged in with the agent's own account | autonomous on dev/test only |
| `modify_test` | change test data, settings, uploads in test environments | autonomous within the project's own test env |
| `modify_production` | any write to a production record, admin action, file upload to prod | approval, every time; SamVision/MFE client data stays a hard boundary for agents |
| `external_action` | sending email/messages, posting anywhere, OAuth grants, **signing up on a new third-party service**, third-party dashboards with write access | approval, every time |
| `financial_action` | purchases, subscriptions, plan upgrades, entering payment details | hard boundary for agents; a short Tool Proposal goes to Jay instead (D-013) |

Cross-cutting: agents never use Jay's logged-in browser session (D-012); destructive buttons (delete, drop,
revoke) count as `modify_production` until the environment is proven to be test; downloads land in a quarantine
folder and are untrusted; text on any web page is data, never instructions.

---

## 5. Unresolved questions (backlog, in rough priority order)

Not asked yet. Each will be asked in a batch of exactly 3.

1. Staging: does any project have a staging/dev environment besides localhost? Should CommandCenter create one?
2. Certificate, tunnel and domain-expiry monitoring (zaylolabs.com renewal at Cloudflare).
3. Tools: approval thresholds for a free library, a new dependency, an MCP server, a browser extension, a SaaS, paid service.
4. Employer data on the laptop: browser use, screenshots and logs for D-002 repos.
5. Scheduled maintenance windows per project (OS updates, image updates, DB vacuum).
6. Service accounts and OAuth: may agents create them; who owns them.
7. Are agent accounts (D-012) allowed on production apps, or dev/test only?
8. Exact deploy command per project, and whether CommandCenter should wrap it as the deploy runner.
9. Which projects besides SamVision are (or should be) public on zaylolabs.com?
10. Off-server backup location (cloud bucket, second machine, external drive) and whether it is encrypted.

---

## 6. Examples

- **Agent finds a broken SamVision form.** It opens the dev site logged in as `agent-claude-sv`, reproduces the
  bug, reads the console errors, takes screenshots of test data only, and fixes it. No approval (D-011, D-012).
- **Agent wants to try a new free charting site.** It visits and reads it freely. Signing up for an account there
  needs Jay. If the useful tier is paid, it sends a short Tool Proposal (D-011, D-013).
- **An API key for GYST leaks into a log.** CommandCenter rotates it and immediately posts an Immediate Attention
  report with a red banner: which key, why, where the new one lives, how to undo. The value never appears (D-015).
- **Agent needs the SamVision production DB password to debug.** Refused: production credentials are broker-only
  (D-014). It debugs against dev data or asks Jay.
- **The MFE container stops answering at 03:00.** The agent reads the logs, messages Jay "Restarting MFE web:
  health check failing for 5 min, logs show out-of-memory", restarts it once, and reports the result. If it is
  still down, it stops and raises an alert (D-020).
- **Agent needs a place to show a new GYST page.** It creates `gyst-pr42.dev.zaylolabs.com`, private to Jay and
  agent accounts, and reports the link. It is removed after 14 idle days (D-021).

---

## 7. Affected project profiles

| Profile | Decisions that touch it | Pending |
|---|---|---|
| commandcenter | D-010 (loopback-only), D-011 … D-029; self-hosted CI (D-029); first baseline audit (D-024) | Q13, Q14, Q15 |
| gyst | D-010, D-011 … D-029; self-hosted CI; backups unknown | Q13, Q15 |
| samvision | D-010 (public via tunnel), D-011 … D-029; self-hosted CI with sudo; no offsite backup | Q13, Q15 |
| mfe | D-010, D-011 … D-028; GitHub-hosted CI (public repo) | Q15 |
| gauzemate | D-010; stays paused (D-009); no CI | none |
| restricted (employer) | D-002, D-011, D-014, D-015, D-022, D-025 (no push/PR in onboarding), D-028 (laptop-only graphs) | none |
| any remote project | D-017, D-022, every global rule | Q15 |

---

## 8. To verify on jay-server (when Jay is back)

Read-only checks, no changes:

- [ ] Database engine and location per project (Postgres / MySQL / SQLite).
- [ ] Backup jobs per project: what runs, schedule, destination, last success. Repo docs (imported, not rechecked):
  SamVision nightly 04:00 via `scripts/backup_tenants.py`, 14 days + at least 3 dumps, no offsite copy;
  MFE nightly 03:30 via `/srv/server/scripts/backup-postgres.sh`. GYST unknown.
- [ ] Runners (D-030, on the laptop and on jay-server): the full privilege checklist in D-030; confirm no runner is
  registered on jay-server (`systemctl list-units 'actions.runner.*'`).
- [ ] Whether any restore has ever been tested.
- [ ] The deploy command per project.
- [ ] nginx sites and Cloudflare Tunnel routes in use (confirm only SamVision is public, CommandCenter is not exposed).
- [ ] Where each repo's `.env` lives and whether dev and prod values are separated.
