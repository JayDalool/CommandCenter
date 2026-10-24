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
- **Closed by D-039:** agents get no logins on production; agent accounts are for dev and test only.

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

### D-015 · Credentials: lifecycle is authority (amended 2026-10-24)
- **Amendment (Q38, Jay, 2026-10-24T06:57Z), replaces the autonomous permission below:** agents may read approved
  service configuration and status where policy permits. Agents do **not** generically create or rotate API keys,
  OAuth applications, OAuth grants, service accounts, deploy keys or long-lived credentials, and an Immediate
  Attention report does not make that allowed. A specific credential may later be enrolled in an explicitly approved
  deterministic capability such as `credential.rotate(<specific-credential>)` with a fixed service, fixed scope,
  verification, rollback/recovery, audit and a permitted caller; once approved, that runbook runs under its own
  policy. No generic credential-management authority. New OAuth apps and grants always need Jay unless a later
  explicit rule changes this. Leaks: D-055. The Immediate Attention report below still applies to every credential
  change an approved capability makes. **Type now:** approval (lifecycle), autonomous only through an enrolled
  capability.
- *Original answer, kept for history (superseded where it conflicts with the amendment):*
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
- **Restore drill schedule (accepted, recorded 2026-10-24T21:03Z), configurable defaults:** CommandCenter weekly,
  SamVision weekly, MyFamilyExpenses monthly, GYST monthly, GauzeMate none while Paused. Any change to a backup system
  triggers an extra restore test. A successful backup is not proven recovery until a restore has been verified.
  Replaces the single "weekly for all" line above.

### D-019 · Operations page: backups, restores, health checks, schedule
- **Answer (Q4):** "We also need an indicator page for our backups and restores, health check and schedule."
- **Rule:** CommandCenter gets one page that shows, per project and host: last backup (time, size, age warning),
  last restore test (pass/fail), current health check result, and the schedule of upcoming backups, restore tests,
  release windows and maintenance. Stale or failed items show red and raise a Needs You item.
- **Controls:** a read-only page and API; no buttons that change production in its first version.
- **Amendment (Q37, Jay, 2026-10-24T06:57Z), monitoring sources:** use both. Uptime Kuma stays one availability
  input; CommandCenter also runs its own deterministic, project-aware `health.check` (HTTP health, readiness,
  expected services, database reachability where policy permits, deployed version, required internal components).
  CommandCenter does not replace Uptime Kuma; independent signals are kept on purpose.
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

### D-024 · New project onboarding (final)
- **Final (Jay, 2026-10-24T06:51Z); text of record `docs/decisions/D-024.md`** (with `policy/decisions/D-024.toml`,
  written in the Engineering HQ thread, PR #66). Final as policy and design only: it does not authorize production
  enforcement, agent activation, credential issuance, Broker grants, budget holds, Slack approval buttons, autonomous
  onboarding authority, Phase 2 enforcement or production deployment. Production activation stays NO-GO until Phase
  2 actor-token enforcement, shadow-mode validation, D-030/D-045 laptop runner verification and the private
  authenticated approval path exist; each enforcement switch is a separate explicit approval. The history below is
  kept for context.
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

### D-028 · Derived code intelligence is evidence, not authority (accepted 2026-10-24)
- **Accepted (Jay, 2026-10-24T21:03Z):** Git remains source-code truth; CommandCenter SQLite remains operational,
  policy and audit truth; graph or index data is derived evidence only; graph intelligence may raise risk but never
  lower deterministic risk; it never authorizes merge or deploy and never bypasses approval; CommandCenter must work
  without it. The local Graphify sandbox experiment is approved under the constraints below. **Still undecided:**
  Graphify adoption after the experiment (ADOPT LOCAL, WATCH or REJECT). Experiment approval is not adoption approval.
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
  Multi-repo option D. Restricted repos laptop-only, never in a shared or cloud graph. Not installed; Q14 answered
  below.
- **Experiment approved (Q14, 2026-10-22T17:51Z):** the local sandbox experiment may run **after Phase 1 is
  deployed and verified**, not before. Throwaway copy of CommandCenter; local, CLI only; no Graphify Cloud, no source
  upload, no paid services, no AI backend unless separately approved; no `graphify install`; no change to CLAUDE.md,
  AGENTS.md, Claude hooks, git hooks or agent settings; no production repo mutation; no effect on ccd or CI; no
  secrets. Measures indexing time, CPU, RAM, disk, graph size, stack coverage, accuracy, stale-graph behaviour
  (including whether Claude notices staleness with the SHA check off), architecture and change-impact answer
  quality, context/token use vs ordinary inspection, fallback, and clean uninstall. Approval of the experiment is
  not approval to adopt: Jay decides ADOPT LOCAL, WATCH or REJECT from the evidence. No automatic promotion.
- **Scope:** global. **Type:** hard boundary (graph never lowers risk or authorizes).

### D-029 · Local CI runner operations (accepted 2026-10-24)
- **Accepted (Q42, Jay, 2026-10-24T06:57Z)** with the later refinements: personal CI runs on Jay's laptop/WSL
  (D-030); runner privileges still need physical verification; idle unhealthy runners may restart automatically;
  verified CI orphan processes may be killed automatically; unknown processes are never killed; port cleanup needs
  deterministic ownership; systemd, process scopes and cgroups where practical; runner operations are deterministic
  capabilities and runbooks, with no arbitrary remote shell as the normal mechanism; WorkerNode trust and capability
  permission stay separate; personal CI is isolated from employer code and credentials (D-045). Implementation waits
  for the Phase 2 work and its approval.
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
  Approved starting defaults (Jay, 2026-10-24T06:51Z), configurable, not hardcoded: architecture/framework about
  90 days unless code changes invalidate them sooner; hosting/DNS/deployment configuration about 30 days; backup
  success/state verified every backup cycle; restore capability by periodic drill (schedule in D-018); worker online
  state live/short TTL; secrets not aged (capability check at use, value never exposed). Classes Jay did not name
  (data, runner privileges, identity, release target) keep the earlier proposed values until tuned.
- **Verify at the point of dangerous use:** a fresh deterministic check right before production deployment
  (target), migration (database target), credential use (account identity), DNS write (DNS target), privileged
  execution (worker identity), and push or merge (repository identity), even if verified yesterday. Approved
  (2026-10-24): dangerous actions always run their point-of-use check even when the stored fact is not stale.
- **Controls:** Project Fingerprint fields `state`, `fact_class`, `verified_at`, `version` (Project Onboarding
  Design doc, Fingerprint section).
- **Scope:** global. **Type:** autonomous (re-checks); per-action block (dependent operations only).
- **Effect on D-024:** D-024 is final (2026-10-24).

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
- **Initial design approved (Jay, 2026-10-24T06:51Z):** Slack is a notification, approval-request and secure-link
  surface only; CommandCenter stays the approval authority. A private CommandCenter Slack integration posts to a
  private channel or DM with the risk tier, agent ID, project, a concise request and an opaque link back to
  CommandCenter. The link is not an approval credential. Standard and High-risk approvals happen inside
  authenticated CommandCenter; High-risk also needs Developer Unlock and the existing stronger confirmation. Direct
  Low-risk Slack buttons are a later, separately approved capability and stay disabled.
- **Amendment (Q32, Jay, 2026-10-24T06:57Z), Slack-button scope once activated:** only low-risk, reversible,
  non-production actions: acknowledge an alert, re-run an already-approved CI job, pause an agent, pause a project,
  extend an approved preview, acknowledge a budget warning, or another explicitly classified Low-tier reversible
  action. Slack alone never authorizes a production deploy, production database operation, migration, repository
  access, widening permissions, credentials or secrets, policy changes, project-mode promotion, agent activation with
  meaningful grants, DNS or hosting changes, purchases, new paid spend, or a destructive action; those open the
  authenticated approval page, and High-risk stays CommandCenter plus Developer Unlock. Still not enabled.
- **Amendment (Q30, Jay, 2026-10-24T06:57Z), phone path:** preferred long-term path is Jay's phone → private
  Tailscale network → authenticated CommandCenter approval UI. ccd and its API are never publicly reachable.
  Cloudflare Access may be evaluated later as a fallback. Adding or configuring Tailscale is a tool/infrastructure
  change under D-040 and its own approval; nothing is installed from this answer.
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
- **Approved defaults (Jay, 2026-10-24T06:51Z), configurable per scope later:** alerts at 50% informational, 80%
  warning, 95% urgent, 100% hard hold. Up to 5% past the hard limit only for work already running to reach a safe
  checkpoint; no new work starts on it; deploy, migration, rollback and push already executing follow their own
  atomic safety rules. Per-step cap: the lower of 25% of the agent's daily budget or $10; a step reaching it
  checkpoints instead of continuing. Estimated cost over $10 needs Project Lead approval (D-046), over $25 needs Jay.
  Burn-rate breaker: more than 25% of a scope's daily allocation in one hour stops new billable steps in that scope,
  lets running work checkpoint, alerts Jay and starts a runaway investigation. **No permanent dollar budgets yet:**
  the evaluator runs in shadow/soft-warning mode first; agent, project and company limits are proposed later from
  real usage evidence.
- **Controls:** per-execution cost metering (V2 discovery §6.9, §24) feeds a budget ledger; the scheduler checks the
  budget before claiming billable work; overrides are Jay approvals with an expiry and an audit record.
- **Scope:** global (company), per project, per agent. **Type:** autonomous (alerts, stopping new billable work);
  approval (overrides and budget increases).

### D-034 · Expand-only automatic production migrations
- **Answer (Q16, 2026-10-23T16:43Z):** yes, with an expand-only policy; CommandCenter and GYST differ.
- **Rule (CommandCenter):** a production migration applies automatically only when all hold: deterministically LOW
  risk; expand-only and backward-compatible; no existing rows rewritten; nothing dropped or renamed; no type narrowed
  or changed incompatibly; no destructive cleanup; no change to secrets, auth, policy or autonomy-permission
  semantics; nothing irreversible; expected locking and runtime within the project's tested safe threshold;
  production DB identity freshly verified (D-031); current application and schema version verified; migration
  checksum and version known; applied successfully to a recent restored copy of production; post-migration
  validation passes on that copy; a fresh production backup taken and verified immediately before; recovery
  procedure proven; and **the old application version still works against the new schema**. Expand → deploy →
  contract: the contract (removal) phase always needs Jay. Example: add a nullable column = candidate; rename a
  column = not automatic.
- **Recovery, not a fake DOWN:** require a tested recovery strategy (code rollback onto the compatible expanded
  schema, and a verified restore when truly needed), not a down-migration written to satisfy a checklist.
- **Indexes are not assumed harmless:** before automatic execution verify locking behaviour, table and database
  size, runtime, disk needs and production impact. If impact cannot be bounded: Jay.
- **Thresholds:** no universal duration; each project and database gets a tested safe-operation threshold. Cannot
  bound lock time or runtime confidently: Jay.
- **GYST:** same policy only for operational/internal schema that does not change handling of Jay's personal
  information. Never automatic (even if additive): personal-data schema, health data, retention, deletion,
  encryption, privacy boundaries, authentication/authorization, sensitive-data storage, data sharing/export (D-005).
  Example: an internal job-status table may be automatic; a column storing health measurements needs Jay.
- **SamVision and MFE:** existing restrictions stay (`never = prod_database`); no automatic production migrations.
- **On failure:** stop; preserve logs and evidence; no alternative schema attempts; run the approved recovery path
  where deterministic; block deployment; D-023 incident report. No autonomous migration improvisation.
- **Pushback, D-007 conflict:** CommandCenter's own schema migrations live in `server/ccd/tasks.py` (`MIGRATIONS`,
  `PRAGMA user_version`), which is a D-007 self-protection path. As things stand every ccd migration needs Jay
  anyway. **Resolved by D-037:** D-034 does not override D-007; ccd's own production migrations need Jay.
- **Scope:** CommandCenter and GYST (internal schema only); SamVision and MFE excluded. **Type:** autonomous only
  inside all conditions; approval (contract phase, anything unbounded, GYST personal-data schema); hard boundary
  (no improvisation after a failure).

### D-035 · Emergency Forward Repair (designed, not active)
- **Answer (Q17):** yes for CommandCenter and GYST as a narrow capability; no for SamVision and MFE.
- **SamVision / MFE:** when production is down and Jay cannot be reached, CommandCenter may diagnose, restart by
  approved runbooks, execute an already-approved rollback, collect evidence, prepare a fix, run CI, get reviews,
  prepare a release-ready PR or commit, and keep notifying Jay. It never deploys newly generated repair code.
- **CommandCenter / GYST, all must hold:** production genuinely unhealthy or unavailable; Jay cannot be reached;
  approved restart and recovery failed; approved rollback failed, was impossible, or did not restore service. The
  repair is very small, directly tied to the incident, with no migration, data rewrite, new dependency, new
  external service, provisioning, DNS change, credential or secret change, auth or permission expansion, policy or
  autonomy expansion, or redesign. CommandCenter's repair never touches its self-protection core (autonomy
  authority, Broker boundaries, approval enforcement, agent permissions, policy enforcement, identity and
  authentication, secret handling). GYST's never changes sensitive personal-data handling.
- **Evidence before deploy:** reproducible failure; identified or strongly evidenced direct cause; a targeted test
  showing the failure and one showing the repair; full applicable CI green; Claude review and independent Codex
  review, both bound to the exact final commit; risk classifier still within the emergency-fix class.
- **Deploy:** the existing deterministic deployment capability only, never improvised shell commands: fix → CI and
  reviews → deploy → immediate health check → bounded observation.
- **One attempt:** a single reviewed forward-fix deployment. If it does not restore service: stop autonomous repair,
  put the project in Paused / Incident, preserve evidence, keep safe diagnostics and alerting.
- **Afterwards:** mandatory incident review for Jay (outage, restarts, rollback, forward fix, exact commit, reviews,
  tests, production result, costs, remaining risks). Jay explicitly accepts, replaces or reverts the repair.
- **Activation:** designed now; the authority is **off** until a later explicit readiness approval after automatic
  deployment and rollback are proven in production or shadow exercises.
- **Quiet hours (D-049, 2026-10-24):** the unreachable timer below does not run during 23:00–07:00 Winnipeg time
  unless the incident was severe enough to break through quiet hours.
- **"Jay cannot be reached" (approved by Jay, 2026-10-23T17:27Z):** Jay is `UNREACHABLE_FOR_INCIDENT_POLICY` only
  when all hold: (1) production outage confirmed; (2) approved automated restart/recovery and rollback failed or
  cannot restore service; (3) urgent alerts sent on at least Slack and ntfy; (4) neither acknowledged for 30
  minutes; (5) health checks still confirm the incident at the end of the window. Never inferred from Slack
  presence, phone status, time of day, calendar, an AI guess, or whether Jay answered an unrelated message. Any
  explicit incident acknowledgement from Jay ("I'm here", "Do not deploy", "Hold", "Proceed") cancels the state
  immediately. While D-035 is disabled, reaching the threshold authorizes nothing.
- **Scope:** CommandCenter and GYST (capability), SamVision and MFE (prepare-only). **Type:** approval (activation;
  acceptance afterwards); autonomous only inside every condition once active; hard boundary (one attempt, no
  self-protection or personal-data changes).

### D-036 · Data egress and information classification
- **Answer (Q18):** no universal rule; classification plus project-specific destination allowlists.
- **Classes:** PUBLIC (may leave under normal tool policy) · SOURCE / INTERNAL ENGINEERING (code, architecture,
  non-sensitive build/test output: to an AI provider only if that project's profile permits that provider;
  permission never transfers between projects) · OPERATIONAL METADATA (task IDs, statuses, health, CI result,
  deploy version, aggregate usage, sanitized error class: to approved operational destinations such as Slack) ·
  SENSITIVE PERSONAL / CLIENT DATA (GYST personal and health data, family finance, private user or client data,
  individual production records: external egress denied by default) · SECRETS (passwords, API keys, OAuth tokens,
  cookies, auth headers, private keys, production `.env` values: never to AI prompts, Slack, Drive, screenshots,
  Graphify Cloud or external logging; redacted before an agent receives logs whenever practical).
- **Per project:** SamVision: individual property or client records never reach CommandCenter telemetry, AI
  prompts, Slack, diagnostic screenshots or unrelated artifacts; this does not limit the product showing records to
  its authorized user; debug with synthetic, redacted, aggregate or schema data. GYST: personal, health and life
  data stays on approved local/private infrastructure; logs scrubbed before external AI analysis; prefer local
  deterministic analysis, then a later-approved local model, then synthetic reproduction; a one-time Jay approval
  for specific sanitized data must be deliberate and audited. MFE: no transaction records, account information,
  financial details or family identifiers to Slack, Drive, screenshots or external AI. CommandCenter: operational
  metadata may leave via approved integrations; its secrets, actor tokens, Developer Unlock information,
  credentials, private audit contents and sensitive cross-project data stay protected; CommandCenter must not
  become a path for one project's restricted data to leak through its own logs or conversations. Employer repos:
  own profile and employer rules; laptop-only where required; never mixed into another project's graph or context;
  no Graphify Cloud without an explicit employer-project policy; only the AI providers permitted for that repo.
- **AI providers:** for personal repos, the minimum source and context the task needs, when the profile permits the
  provider. Production data limit by default: schema, row counts, aggregate metrics, sanitized logs, synthetic
  examples; not real rows.
- **Screenshots are data exports:** classify what is visible before sending one externally; never with secrets,
  personal data, family finance, client data or private production records unless a policy allows it. Local
  screenshots kept on an approved machine are a separate case.
- **Logs:** deterministic scrubbing of known patterns (tokens, auth headers, cookies, passwords, connection
  strings, API keys, project-defined sensitive identifiers) before an external agent sees them; not an AI doing it
  by hand each time.
- **Egress audit:** record project, actor, destination, data class, purpose, policy decision, timestamp, amount and
  type of material; never a second copy of the sensitive payload.
- **Local AI:** a truly local model with verified no external calls may later get broader access through its own
  capability decision; "local" labels are verified, not trusted.
- **Principle:** minimum necessary data + project-specific destination allowlists. A tool being available does not
  mean a project may send data to it.
- **Pushback 1, an agent's own reads are egress:** whatever an agent reads (a query result, a log tail, a page in a
  browser) goes into its prompt at the provider. So "no real rows to AI providers" has to be enforced at the tool
  level: agents get query and log tools that return schema, counts, aggregates and scrubbed lines, not raw
  production rows or raw logs. This also limits agent accounts on production apps (Q21).
- **Pushback 2, free text in metadata:** task titles, PR titles, commit messages and error messages are free text and
  can carry an address, a name or an amount. They count as OPERATIONAL METADATA only after the project's scrubber
  runs; SamVision already limits GitHub issues to task title, IDs and the task-file link.
- **Scope:** global, with per-project profiles. **Type:** hard boundary (secrets; sensitive data default-deny);
  approval (one-time sensitive transfers, new destinations, local model access); autonomous (allowed classes to
  allowlisted destinations).

### D-037 · CommandCenter's own database: protection follows the effect
- **Answer (Q19, 2026-10-23T17:27Z):** every production migration to CommandCenter's `tasks.db` needs Jay, for now.
- **Rule:** D-034 does not override D-007. Protection follows what a change affects, not where the file lives. A
  change to CommandCenter's operational database that can affect approvals, decisions, audit history, autonomy
  state, WorkerNodes, actor identity, capabilities, policies, usage or budget records, or execution authority is
  inside the self-protection boundary. SQL is not moved to another folder to make it eligible for automatic
  execution; moving migrations into a dedicated folder for maintainability is fine, but **location never grants
  authority**.
- **Future:** a narrower class such as `CCD_SAFE_EXPAND_MIGRATION` may be considered only after Capability Broker
  enforcement, actor identity enforcement, a migration sandbox, backup/restore reliability, schema compatibility
  checks, deterministic risk classification, rollback/recovery and audit integrity are all proven, and only through a
  separate decision. Not created now.
- **Controls:** the engine classifies a change by the tables and semantics it touches, not only by path globs; the
  D-007 path list stays as a second line.
- **Scope:** CommandCenter. **Type:** approval (every ccd production migration).

### D-038 · Restored production data
- **Answer (Q20):** yes to temporary restored copies, under a broader rule.
- **Rule:** production-derived database copies stay inside the same approved private data boundary as production:
  no cloud sandbox, no developer SaaS, no external AI service, no preview environment with real production data.
  For databases on jay-server, prefer a temporary isolated environment on jay-server: migration-check job →
  encrypted local backup → temporary isolated DB/container/namespace → restore → run migration → structural
  validation → destroy.
- **Isolation:** no public listener; no inbound access except the migration checker; no outbound Internet unless
  technically unavoidable and explicitly allowed; unique temporary credentials; production credentials not reused
  unnecessarily; no production app or preview site connected; no normal agent browsing or query access; strict
  lifetime; creation and deletion audited.
- **What the checker returns to an agent:** restore success or failure, schema before and after, migration duration,
  row, table and index counts, constraint failures, lock and runtime measurements, the migration error with scrubbed
  context, compatibility test result. No sample rows.
- **Sensitivity:** a restored copy of GYST, MFE or any sensitive project is exactly as sensitive as production; it
  is not test data because it is temporary.
- **Deletion:** destroy the DB, container and volume; verify deletion; remove temporary credentials; keep only
  non-sensitive test evidence. No long-lived production-derived sandboxes.
- **Capacity guard:** before restoring, check free disk, backup size, estimated restored size, temporary overhead
  and the production safety margin. Not enough safe capacity: do not restore; Needs You, or another approved private
  machine later. Never risk filling the production disk.
- **Preview and staging:** synthetic data, seeded fixtures, or sanitized fixtures where explicitly approved; never
  full production clones.
- **Scope:** global. **Type:** hard boundary (no production data outside the private boundary or in previews);
  autonomous (the isolated check, inside D-034's conditions).

### D-039 · No agent logins on production; purpose-built capabilities instead
- **Answer (Q21):** no general-purpose agent accounts on production applications.
- **Rule:** on production, agents use public logged-out pages, health endpoints, synthetic monitoring endpoints,
  sanitized observability, deterministic probes and aggregate metrics. No normal user or admin production accounts by
  default. SamVision: no agent login exposing real property, client or private listing/customer data; test on
  staging, synthetic accounts, public pages and health checks. GYST: no external-AI agent login that could expose
  Jay's personal, health or life information. MFE: no external-AI agent login that could expose family financial
  records. CommandCenter: no automatic exception; a scoped production-observer or operator identity needs its own
  capability and security decision. Claude or Codex do not get a production login because CommandCenter manages
  agents. Narrows D-012: agent accounts apply to dev, test and preview.
- **Service capabilities over logins:** automated production interaction uses purpose-built capabilities (for
  example `service.restart(samvision-web)`) with narrow scope, deterministic input, explicit authorization, an audit
  trail and no access to unrelated application data, rather than an agent clicking through an admin UI.
- **Browser testing on production:** only under a future separate policy for a restricted synthetic test account
  whose data is deliberately non-sensitive; never Jay's, a client's or an admin account.
- **Jay's sessions:** a browser session authenticated as Jay never becomes an agent credential automatically; it is a
  high-risk capability needing its own explicit policy (consistent with D-011, D-012).
- **Enforce before data reaches the agent (from D-036):** deterministic interfaces such as `db.schema`, `db.count`,
  `db.migration_check`, `logs.scrubbed_tail`, `logs.error_summary`, `health.check`, instead of an unrestricted SQL
  shell, raw logs or an unrestricted production browser. Ticket titles, commit messages, branch names, filenames, PR
  text and browser pages are free text and go through deterministic secret and sensitive-data scrubbing before
  external AI ingestion where the project policy requires it.
- **GYST and MFE logs (refinement accepted by Jay, 2026-10-23T17:38Z):** pattern scrubbing removes API keys, auth
  headers, connection strings, tokens and passwords, but cannot recognise every sensitive value (`Failed health
  entry for Jay: weight=...`, `Transaction rejected: amount=...`). External agents therefore get a deterministic
  structured summary by default: error type, component, count, first and last seen, affected operation, a safe
  structural location (stack/function) where allowed, "production rows: not exposed", "sensitive values:
  withheld". Raw or scrubbed lines from GYST or MFE need either Jay's approval for that incident or a future
  explicitly approved local/private AI path where the data stays inside the private boundary. Reproduce with
  synthetic data first where possible.
- **Scope:** global, per-project detail as above. **Type:** hard boundary (no production logins for SamVision, GYST,
  MFE; no use of Jay's sessions); approval (any future observer identity or production test account).

### D-040 · Tools and dependencies: five tiers
- **Answer (Q22, 2026-10-23T17:38Z):** tiered policy; a library is not treated like an MCP server.
- **Tier 1 · code dependency:** added through the normal PR process without asking Jay first when all hold: needed
  for the scoped task; licence on the approved list; source repository identifiable; version pinned through the
  project's lockfile; no known critical or high advisory at that version; not abandoned or suspicious; name checked
  for typosquatting and dependency confusion; install scripts and native binaries evaluated where relevant; no new
  external service or account; no change to agent configuration; no global or system install; no privileged access;
  no material expansion of the application's security boundary; CI green. Evaluated on maintainership, release
  activity, provenance, adoption, security history, dependency tree, package-to-repository ownership, licence and
  install behaviour, not a fixed age. Unusual or high-impact dependencies escalate: an ORM, auth framework,
  encryption library, database driver, runtime framework or build system may need Jay depending on the profile; a
  small UI utility does not.
- **Tier 2 · project-scoped dev tooling** (formatter, linter, test helper, code generator, local CLI): normal PR
  review when project-scoped, non-privileged, no agent-setting changes, no persistent daemon, no external account,
  no sensitive-data upload. If it touches git hooks, agent prompts or configuration, or machine-level settings: Tier 3.
- **Tier 3 · agent and execution tooling:** Jay approves before activation. MCP servers; Claude/Codex plugins;
  agent skills that execute code; browser extensions; agent hooks (PreToolUse/PostToolUse); tools that edit
  `CLAUDE.md` or `AGENTS.md`; git hooks installed by an agent tool; code-indexing systems that shape agent context;
  persistent local daemons used by agents; tools that gain repository or system credentials, execute arbitrary
  commands, or can modify external systems. Graphify integration is Tier 3; its CLI sandbox experiment is approved
  separately under D-028.
- **Tier 4 · hosted or system service:** Jay approves before first deployment, even if free: a new service or
  persistent container on jay-server, Redis, a database server, a queue, a monitoring platform, a reverse-proxy
  component, a background daemon, a cloud service, a SaaS integration. Free still adds attack surface, maintenance,
  backups, ports, resource use, upgrades and an operational dependency.
- **Tier 5 · paid:** D-013 stays authoritative.
- **Approval is reusable:** once Jay approves a tool for a scope, routine use within that scope needs no new
  approval (for example Playwright for UI testing in approved projects). A major version upgrade, privilege
  expansion, cloud enablement or new data access triggers a fresh review.
- **Tool Proposal needed for:** Tier 3, Tier 4, paid tools, major architectural dependencies, and dependencies with
  meaningful data, security or lock-in implications. Normal low-risk libraries need none.
- **Controls:** a deterministic dependency checker on lockfile diffs (licence, advisories, typosquat distance,
  install scripts); an approved-tools register with scope and version range.
- **Scope:** global. **Type:** autonomous (Tier 1 and 2 within conditions); approval (Tier 3, 4, 5, and escalations).

### D-041 · Production deploys are deterministic named capabilities
- **Answer (Q23):** yes.
- **Rule:** each project gets a reviewed capability (`deploy.samvision`, `deploy.gyst`, `deploy.mfe`,
  `deploy.commandcenter`) wrapping its approved procedure; CommandCenter's wraps the existing `scripts/go-live.sh`
  rather than having Claude rediscover commands. Before every production deploy: (1) verify project identity, (2)
  target host and environment, (3) repository and exact commit SHA, (4) approved release or decision state, (5) CI and
  reviews the profile requires, (6) database target where relevant, (7) take or verify the required backup, (8)
  check host health and resources, (9) run the deterministic deploy, (10) health checks, (11) smoke checks, (12)
  record result and audit, (13) approved rollback automatically if health criteria fail.
- **Identity:** a dedicated deploy user or service identity per project with only the permissions that deploy needs.
  Agent or Jay → Capability Broker → `deploy.samvision(commit=abc123)` → reviewed script → deploy identity. Never
  agent → unrestricted SSH → arbitrary sudo.
- **No production shell:** agents do not get a general interactive production shell. Diagnostics go through
  read-only capabilities (`service.status`, `logs.summary`, `logs.scrubbed_tail` subject to D-039, `disk.status`,
  `container.status`, `health.check`, `deploy.status`). A future emergency diagnostic shell would be a separate
  high-risk capability.
- **Trigger authority:** only Jay until a project's profile grants auto-deploy; then CommandCenter calls the same
  capability. Manual and autonomous deploys use the same reviewed runbook.
- **No AI shell scripting at deploy time:** a deploy change goes through the version-controlled runbook → review and
  test → approval → use.
- **Pushback, Docker makes "least permission" hard:** our apps run in Docker, and membership of the Docker group is
  root-equivalent, so a deploy user that can run `docker compose` can do anything on the host. Proposed: the deploy
  user is not in the Docker group; a root-owned wrapper per project is the only thing it may run (one sudoers line
  each, e.g. `deploy-samvision`), and the wrapper accepts only a validated commit SHA, no free-form arguments.
- **Scope:** global. **Type:** approval (Jay triggers until a profile allows more; runbook changes); hard boundary (no
  general production shell; no improvised deploy commands).

### D-042 · Backups: second machine first, offsite later
- **Answer (Q24):** use Jay's laptop as a second-machine target; do not call it offsite.
- **Rule:** production on jay-server → local primary backup on jay-server → encrypted second copy on Jay's laptop.
  Protects against server disk failure, accidental deletion on the server, some server-level corruption and server
  hardware failure. Does not protect against theft of both devices, fire or flood affecting both, ransomware with
  access to both, or other same-location disasters. The laptop copy is classified `SECOND_MACHINE`, not `OFFSITE`,
  until physical separation is actually true.
- **Isolation on the laptop:** the copy lives in a Windows or dedicated backup storage area, or under a separate
  restricted Linux/WSL user, with ACLs so the GitHub runner and agent execution users have no read, write, delete
  or decryption access (D-030).
- **Encryption and keys:** encrypted before or during transfer. The only recovery key is never kept solely on the
  laptop, nor solely on jay-server. Recovery material needs a user-controlled path independent of the backed-up
  machine; keys are never exposed to agents. Key policy: D-043.
- **Runbook, no LLM in routine execution:** `backup.create` → `backup.verify` → `backup.encrypt` →
  `backup.replicate(laptop)` → `backup.verify_remote`; laptop copies are deleted only laptop-side (D-044). CommandCenter receives structured status only
  (result, source, created, local verification, second-machine copy, encrypted, age, last restore test).
- **Laptop offline:** the production backup does not fail; record local PASS and second-machine PENDING; run the
  pending replication when the laptop reconnects; alert Jay only when the second copy is older than the configured
  tolerance.
- **External drive:** evaluate later only if Jay already owns a suitable one; never buy one automatically; a drive
  permanently attached to jay-server is still not geographic offsite.
- **Later:** a geographically separate encrypted target (another location or machine, trusted remote storage,
  low-cost object storage, another user-owned device) as a separate Tool or Infrastructure Proposal if it adds cost
  or a third party.
- **AF-001 stays open** until a backup exists, verification exists, a second-machine copy exists, and the restore
  process is tested, all with evidence. A configured copy command does not close it.
- **Scope:** global; SamVision and MFE first (they have backups today), GYST and CommandCenter once their backups are
  known. **Type:** autonomous (the runbook once approved and installed); approval (installing it, any new tool or
  service); hard boundary (CI and agents never reach backups or keys).

### D-043 · Backup classes and encryption keys
- **Answer (Q25, Jay, 2026-10-24T06:51Z, Engineering HQ thread):** "APPROVED: HYBRID MODEL."
- **Rule:** two backup classes. (1) **Operational backup:** short-term, inside the approved production/private
  environment; CommandCenter may use it automatically for rollback, migration verification, automated restore tests
  and recovery from routine mistakes. (2) **SECOND_MACHINE disaster copy:** a separate copy on Jay's laptop,
  encrypted with `age` public-key encryption. jay-server may hold the public key only. The private key never exists
  on jay-server, Jay's laptop, CI runners, WorkerNodes, Claude or Codex; Jay holds it separately with an independent
  recovery copy.
- **Not yet:** installing `age` is a system-tool change and goes through the Tool/Infrastructure process (D-040).
  Not installed.
- **Scope:** global. **Type:** autonomous (operational backup use); hard boundary (private key location);
  approval (installing `age`).

### D-044 · Laptop copies are append-only from the server
- **Answer (Q26, Jay, 2026-10-24T06:51Z, Engineering HQ thread):** "APPROVED: APPEND-ONLY FROM THE SERVER."
- **Rule:** jay-server may create a new encrypted backup object on the laptop and verify the upload succeeded. It may
  not delete or overwrite earlier laptop copies, change laptop retention, or decrypt laptop copies. Retention and
  deletion run from a separate laptop-side backup identity and runbook, so a compromised jay-server cannot erase the
  second-machine history.
- **Runbooks (deterministic scripts, not recurring LLM tasks):** server side `backup.create` → `backup.verify` →
  `backup.encrypt` → `backup.replicate` → `backup.verify_remote`; laptop side `backup.retention`, which deletes only
  copies expired under the approved retention policy. Replaces the server-side `backup.prune` step in D-042.
- **Controls (proposed):** an SSH key limited to a forced command that only writes new files.
- **Scope:** global. **Type:** hard boundary (server cannot delete, overwrite or decrypt); autonomous (the approved
  runbooks once installed).

### D-045 · Personal CI is isolated from employer code on the laptop
- **Answer (Q27, Jay, 2026-10-24T06:51Z, Engineering HQ thread):** "APPROVED: STRICT OS/FILESYSTEM/CREDENTIAL
  SEPARATION."
- **Rule:** personal CI on the laptop runs under a dedicated locked-down identity that cannot read employer
  repository directories, employer credentials, SSH keys, tokens or environment files, Jay's general Windows profile,
  production backups, or unrelated personal secrets. Employer work uses a separate Linux/WSL user or environment.
- **Verification:** checked on the actual laptop before Phase 2 execution authority is enabled, with recorded
  evidence; isolation is never assumed. If it cannot be proven, personal CI and autonomous execution stay restricted
  until it is fixed. Extends D-030.
- **Scope:** global (laptop). **Type:** hard boundary; prerequisite for Phase 2 authority.

### D-046 · Initial Project Leads
- **Answer (Jay, 2026-10-24T06:51Z, Engineering HQ thread):** approved initial structure.
- **Rule:** CommandCenter, GYST, SamVision and MyFamilyExpenses each have a Claude Project Lead; GauzeMate has no
  active lead while it is Paused. "Claude Project Lead" is a stable agent role, not tied to one model version: the
  backing model may change while the agent identity and work history stay intact. Each project's assignment and
  history stay separate even when the same lead persona is used. Dedicated leads may be onboarded later.
- **Relation:** the Project Lead approves estimated costs over $10 (D-033); Jay above $25. Naming the leads
  activates nothing.
- **Scope:** per project. **Type:** structure (grants no authority by itself).

### D-047 · Domain, certificate and tunnel expiry monitoring
- **Answer (Q28, Jay, 2026-10-24T06:57Z):** approved.
- **Rule:** CommandCenter will check daily: domain registration expiry, TLS certificate expiry on public hostnames,
  and Cloudflare Tunnel connector health where a tunnel is used. Alerts at 30, 14 and 3 days. Agents may diagnose
  and remind. Renewal and payment stay Jay's (D-013): agents never purchase renewals, change payment methods or
  change automatic-renewal settings.
- **Scope:** global. **Type:** autonomous (checks, reminders); hard boundary (renewal, payment, auto-renew settings).

### D-048 · Public exposure by project
- **Answer (Q29, Jay, 2026-10-24T06:57Z):** approved default.
- **Rule:** SamVision may be public under its own project and hosting policy. CommandCenter, GYST and
  MyFamilyExpenses are private by default; CommandCenter itself always stays private. GauzeMate follows its Paused
  state. Making any new hostname or application publicly reachable needs Jay (extends D-021). A future, deliberately
  designed public endpoint for GYST or MFE can be approved on its own; that does not make the whole application
  public.
- **Scope:** per project. **Type:** hard boundary (CommandCenter never public); approval (any new public exposure).

### D-049 · Quiet hours
- **Answer (Q31, Jay, 2026-10-24T06:57Z):** approved.
- **Rule:** quiet hours 23:00–07:00 America/Winnipeg. CI failures, ordinary questions, budget warnings, low-priority
  maintenance and non-critical project notifications wait until quiet hours end. Only a confirmed production
  outage, data at immediate risk, or a confirmed or suspected security incident needing attention may break
  through. D-035's "Jay unreachable" timer does not run during quiet hours unless the incident broke through.
- **Scope:** global. **Type:** notification policy (amends D-035's unreachable test).

### D-050 · Jay is the only approver
- **Answer (Q33, Jay, 2026-10-24T06:57Z):** approved.
- **Rule:** Jay is the only approver for now. Identities and roles are designed so multi-user approval could be added
  later, without weakening today's security model for hypothetical users. Letting a collaborator, client, family
  member or another administrator view or approve CommandCenter decisions needs a separate policy and security
  decision.
- **Scope:** global. **Type:** hard boundary (single approver until a new decision).

### D-051 · OS and container updates on jay-server
- **Answer (Q34, Jay, 2026-10-24T06:57Z):** approved.
- **Rule:** security-only OS updates may later install automatically through Ubuntu's normal security-update
  mechanism. No automatic reboot: if an update needs one, Jay gets a request explaining why. Application, container
  and base-image updates go PR → CI and review → approved deploy capability (D-041); application stacks are never
  silently upgraded because an upstream image changed.
- **Scope:** jay-server. **Type:** autonomous (security-only OS updates, once set up); approval (reboot, stack updates
  via the normal deploy path).

### D-052 · Dependency updates by risk class
- **Answer (Q35, Jay, 2026-10-24T06:57Z):** approved with risk classes.
- **Rule:** on CommandCenter and GYST, patch and minor updates may proceed under the project's autonomy policy when the
  dependency is allowed under D-040, CI passes, an independent review passes and no high-risk subsystem is affected.
  SamVision and MFE keep their stricter project gates. Always escalated to Jay: major versions, authentication
  libraries, cryptography, database drivers and ORM foundations, core frameworks and runtimes, build and deployment
  system changes, and any dependency change with meaningful security or architecture impact. A known, actively
  exploited serious vulnerability is Immediate Attention, but being security-related never bypasses project safety
  rules.
- **Scope:** per project. **Type:** autonomous (low-risk updates on CC and GYST); approval (escalated classes).

### D-053 · Disk cleanup on jay-server
- **Answer (Q36, Jay, 2026-10-24T06:57Z):** approved for deterministically safe categories.
- **Rule:** may later be cleaned automatically: dangling Docker images, known build cache, expired temporary files of
  managed jobs, logs older than approved retention, verified stale CI and work artifacts. Never deleted
  automatically unless a separate narrow capability allows it: Docker volumes, databases, production application
  data, backups, uploads, unknown directories, files in protected backup or storage locations. Alert below about 15%
  free disk. Low disk is never solved by guessing what is safe to delete.
- **Scope:** jay-server. **Type:** autonomous (listed categories); hard boundary (everything else).

### D-054 · GitHub settings are read-only for agents
- **Answer (Q39, Jay, 2026-10-24T06:57Z):** approved.
- **Rule:** agents may read GitHub settings where available. Without a future narrow capability they may not create,
  delete, archive or rename repositories, change branch protection or rulesets, modify Actions secrets or
  environments, change runner registration, change webhooks, add deploy keys, or alter collaborators and access.
  They propose the exact change to Jay.
- **Scope:** global. **Type:** autonomous (read); approval (every listed change).

### D-055 · Leaked secret: deterministic revoke first
- **Answer (Q40, Jay, 2026-10-24T06:57Z):** approved with deterministic safeguards.
- **Rule:** when CommandCenter deterministically confirms a specific credential has leaked, an already-approved
  revoke capability may revoke first and report immediately after, even if that briefly breaks a running service.
  Requires: exact credential identity known, exact service known, an approved revoke capability exists, an audit
  event, an Immediate Attention alert, and a dependent-service health check afterwards. The LLM never guesses which
  credential to revoke; if identity is ambiguous, nothing is revoked and Jay is alerted at once. Git history is never
  rewritten automatically. Replacement follows the credential policy (D-015 as amended).
- **Scope:** global. **Type:** autonomous (deterministic revoke through an approved capability); hard boundary (no
  guessing, no history rewrite).

### D-056 · Record retention
- **Answer (Q41, Jay, 2026-10-24T06:57Z):** approved starting defaults.
- **Rule:** kept long-term: audit records, approval records, durable Decisions, incident reports, durable policy and
  configuration history (subject to future storage or privacy requirements). 90 days: ordinary AI transcripts,
  command and tool output, routine agent-session details, unless turned into structured decisions or evidence. 30
  days: production diagnostic material that may contain or come from sensitive or scrubbed production context.
  Sensitive projects may set shorter retention. Durable knowledge is extracted into structured records instead of
  keeping raw transcripts forever.
- **Scope:** global, with per-project shorter limits allowed. **Type:** retention policy.

### D-057 · Temporary remote laptop access (proposed, 2026-10-24)
- **Source:** Jay's brief (2026-10-24T21:03Z). Full design: D-057 Temporary Remote Laptop Access doc
  (https://claude.ai/artifact/9La3jFrBBtLhyooBrJUEXm).
- **Proposed rule:** Jay may grant one named agent (Claude Code or Codex) a signed, time-limited lease on one approved
  personal worktree on `jay-laptop-wsl`, in Inspect, Assisted or Interactive mode. The lease only narrows authority
  (agent grant ∩ profile ∩ task mode ∩ WorkerNode ∩ lease ∩ egress ∩ safety state) and never grants production,
  secrets, deploy, DNS, GitHub settings, credential management, Jay's browser profile or employer repositories. The
  boundary is the outbound WorkerNode connection, the lease, the Capability Broker and OS isolation (a separate
  `cc-agent` WSL distribution with interop and Windows mounts off), never a vendor remote-control feature or a
  prompt. Agents work in their own clone, not Jay's checkout. Leases expire at an absolute time with an idle timeout;
  the worker freezes the session after 5 minutes without ccd; REVOKE ALL is always available.
- **Open (asked 2026-10-24):** Q44 isolation shape (separate distribution recommended), Q45 provider credential
  (dedicated capped API keys recommended), Q46 package downloads in Assisted (lockfile install before the session
  recommended).
- **Prerequisites:** Phase 2 actor tokens, the private network path (D-032, which also changes D-010's loopback rule
  for the worker endpoint), D-045 laptop evidence, an approved `jay-laptop-wsl` WorkerNode. Phases: shadow leases →
  Inspect (no AI process on the laptop) → Assisted → Interactive, each separately approved.
- **Scope:** global (laptop). **Type:** approval (every lease); hard boundary (no production, no employer repos in v1).
  Nothing implemented, enabled, installed or exposed.

---

## 3. Questions asked and answered

Batch 1 (Q1 hosting, Q2 browser, Q3 secrets) answered 2026-10-21T17:37Z → D-010 … D-016.
Batch 2 (Q4 databases, Q5 production ops, Q6 subdomains) answered 2026-10-21T19:53Z → D-017 … D-021.
Batch 3 (Q7 remote hosts, Q8 onboarding, Q9 incidents) answered 2026-10-21T20:36Z → D-022, D-023; Q8 grew into
the onboarding design (D-024, final 2026-10-24).

Batch 4 (Q10 push/PR, Q11 tightening, Q12 existing projects) answered 2026-10-21T21:15Z → D-025, D-026, D-024
updated; task modes → D-027; Graphify → D-028 + TP-001; local CI → D-029.

Batch 5 (Q13 runner host, Q14 Graphify experiment, Q15 fact ageing) answered 2026-10-22T17:51Z → D-030,
D-028 (experiment approval), D-031; backups recorded as finding AF-001.

Batch 6 (Q16 migrations, Q17 emergency repair, Q18 data egress) answered 2026-10-23T16:43Z → D-034, D-035, D-036.
Also recorded from the Engineering HQ thread: D-032 (Slack mobile approvals), D-033 (budgets).

Batch 7 (Q19 ccd migrations, Q20 restored copies, Q21 production logins) answered 2026-10-23T17:27Z → D-037,
D-038, D-039; D-035 gains the deterministic unreachable test.

Batch 8 (Q22 tools, Q23 deploy runner, Q24 backup target) answered 2026-10-23T17:38Z → D-040, D-041, D-042;
GYST/MFE log refinement folded into D-039.

Batch 9 (Q25 encryption, Q26 laptop deletion, Q27 employer isolation) answered 2026-10-24T06:51Z in the
Engineering HQ thread → D-043, D-044, D-045; also D-046 (Project Leads), D-024 final, and updates to D-031, D-032,
D-033.

Full list (Q28 to Q43, sent 2026-10-24T06:53Z) answered 2026-10-24T06:57Z → D-047 to D-056 new; D-015, D-019,
D-032, D-035 amended; D-029 accepted; AF-002 experiment approved. Mapping in section 5. No question is open.

D-057 (2026-10-24): Q44 to Q46 asked about temporary remote laptop access; see D-057.

### Batch 9 (answered, kept for reference)

**Q25 · Backup encryption and the recovery key.** restic needs its password on the machine that writes the backup,
so jay-server would hold a key that can also read every old backup. Alternative: encrypt each dump with a public key
(`age`); jay-server holds only the public key and cannot decrypt, and the private key stays with Jay (password
manager from D-016 once it exists, plus a paper or USB copy he keeps). Proposed: public-key encryption, private key
never on jay-server or the laptop. Installing `age` is a system tool, so it needs Jay's approval (D-040 Tier 4 /
system install).

**Q26 · Who may delete the laptop copy.** If jay-server can delete or overwrite the laptop copy, ransomware or a
compromise on jay-server can destroy both. Proposed: jay-server pushes with an SSH key limited to one command that
only writes new files (append-only); pruning runs on the laptop under the backup user, never triggered from jay-server.

**Q27 · Employer code on the same laptop as personal CI.** D-002 keeps employer repos laptop-only, and D-030 puts
personal-project CI runners on the same laptop. A personal PR's code then runs on the machine holding employer code.
Proposed: the runner user cannot read employer repo folders, their credentials or the Windows user profile
(`/mnt/c/Users/...`); employer work runs under a different Unix user; verified on the laptop before Phase 2.

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
**Experiment approved (Q43, Jay, 2026-10-24T06:57Z):** an agent may use a clean, disposable container or environment
to prove whether SamVision CI and tests work without `sudo apt-get install libgomp1`, and whether the dependency can
instead be present in the controlled runner or container image so CI code needs no sudo. The proof never touches
production. If it works, the exact CI patch and result go to Jay under the existing CI approval rule; the workflow
change is not pushed, opened or merged on the strength of the experiment. Goal: remove root-equivalent capability
from PR-executed code. Not started.

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

## 5. Open questions: all answered (Q25 to Q43 closed 2026-10-24)

Jay asked for every remaining question at once (2026-10-24T06:51Z) and answered them all at 2026-10-24T06:57Z
(Q25 to Q27 also in the Engineering HQ thread at 06:51Z). No discovery question is open. Answering a question
decides policy only; nothing below is implemented, installed or enabled.

| Q | Topic | Recorded as | Final rule, short |
|---|---|---|---|
| Q25 | Backup encryption | D-043 (new) | Operational backups stay private and usable automatically; laptop copy `age`-encrypted, private key only with Jay |
| Q26 | Deleting laptop copies | D-044 (new) | jay-server appends and verifies only; retention runs laptop-side |
| Q27 | Employer code vs personal CI | D-045 (new) | Separate locked-down CI identity; employer work under its own user; proven on the laptop before Phase 2 |
| Q28 | Domain, cert, tunnel expiry | D-047 (new) | Daily checks, alerts at 30/14/3 days; renewal and payment stay Jay's |
| Q29 | Public projects | D-048 (new) | SamVision may be public; CommandCenter, GYST, MFE private; new public exposure needs Jay |
| Q30 | Phone access to approvals | D-032 (amended) | Tailscale private network preferred; ccd never public; Cloudflare Access only as a later fallback |
| Q31 | Quiet hours | D-049 (new), D-035 (amended) | 23:00–07:00 Winnipeg; only outage, data at risk, security incident break through; unreachable timer paused |
| Q32 | Slack-only approvals | D-032 (amended) | Later, only low-risk reversible non-production actions; everything else opens CommandCenter |
| Q33 | Other approvers | D-050 (new) | Jay is the only approver; any other viewer or approver needs a new decision |
| Q34 | OS and container updates | D-051 (new) | Security-only OS updates may be automatic; no automatic reboot; stacks update via PR and deploy |
| Q35 | Dependency updates | D-052 (new) | Low-risk patch/minor on CC and GYST under conditions; listed risk classes go to Jay |
| Q36 | Disk cleanup | D-053 (new) | Only listed safe categories automatic; volumes, data, backups, uploads, unknown dirs never; alert at ~15% free |
| Q37 | Monitoring source | D-019 (amended) | Both Uptime Kuma and CommandCenter `health.check` |
| Q38 | Service accounts, keys, OAuth | D-015 (amended, tightened) | No generic create/rotate; only enrolled deterministic capabilities; new OAuth always Jay |
| Q39 | GitHub settings | D-054 (new) | Read only; every listed change is a proposal to Jay |
| Q40 | Leaked secret | D-055 (new) | Deterministic revoke first through an approved capability; ambiguous means escalate, never guess |
| Q41 | Record retention | D-056 (new) | Audit, approvals, decisions, incidents long-term; transcripts and output 90 days; production diagnostics 30 days |
| Q42 | Local CI runner ops | D-029 (accepted) | Accepted with refinements; implementation waits for Phase 2 |
| Q43 | SamVision sudo step | AF-002 (experiment approved) | Disposable-container proof allowed; CI patch goes to Jay, not pushed |

Still undecided, not discovery questions: D-016 password manager (intent only; which product, and the migration
plan); a geographically separate offsite target (D-042 later, AF-001 open); the Graphify adoption verdict (D-028,
after the experiment); actual budget amounts (D-033, after shadow-mode usage); which specific credentials get a `credential.rotate` or revoke capability
(D-015, D-055).

---

## 6. Examples

- **Agent finds a broken SamVision form.** It opens the dev site logged in as `agent-claude-sv`, reproduces the
  bug, reads the console errors, takes screenshots of test data only, and fixes it. No approval (D-011, D-012).
- **Agent wants to try a new free charting site.** It visits and reads it freely. Signing up for an account there
  needs Jay. If the useful tier is paid, it sends a short Tool Proposal (D-011, D-013).
- **An API key for GYST leaks into a log.** If CommandCenter deterministically identifies the exact key and service
  and an approved revoke capability exists, it revokes the key, posts an Immediate Attention report, and checks the
  dependent service. If the key's identity is ambiguous, it revokes nothing and alerts Jay. Creating the replacement
  follows the amended D-015. The value never appears (D-055, D-015).
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
| commandcenter | D-010 (loopback-only), D-011 … D-056; self-hosted CI (D-029); first baseline audit (D-024); private (D-048) | machine verification (section 8) |
| gyst | D-010, D-011 … D-056; self-hosted CI; backups unknown; private (D-048); low-risk dependency updates (D-052) | machine verification |
| samvision | D-010 (public via tunnel), D-011 … D-056; self-hosted CI with sudo (AF-002); no offsite backup (AF-001); stricter gates (D-052) | machine verification |
| mfe | D-010, D-011 … D-056; GitHub-hosted CI (public repo); private (D-048); stricter gates (D-052) | machine verification |
| gauzemate | D-010; stays paused (D-009); no CI; no Project Lead (D-046) | none |
| restricted (employer) | D-002, D-011, D-014, D-015, D-022, D-025 (no push/PR in onboarding), D-028 (laptop-only graphs), D-045 (isolated from personal CI) | laptop isolation evidence |
| any remote project | D-017, D-022, every global rule | none |

---

## 8. To verify on jay-server and the laptop (when Jay is back)

Policy decisions are not evidence of machine state. None of these is verified; each needs read-only evidence
recorded with its date. No changes during these checks.

- [ ] Database engine and location per project (Postgres / MySQL / SQLite).
- [ ] Backup jobs per project: what runs, schedule, destination, last success. Repo docs (imported, not rechecked):
  SamVision nightly 04:00 via `scripts/backup_tenants.py`, 14 days + at least 3 dumps, no offsite copy;
  MFE nightly 03:30 via `/srv/server/scripts/backup-postgres.sh`. GYST unknown.
- [ ] Production restore history: whether any restore has ever been tested, and when.
- [ ] Runner users and privileges on the laptop (D-030 checklist, D-045 employer isolation).
- [ ] Docker-group membership and sudo access for runner, deploy and agent users (D-041, D-029).
- [ ] No unintended runner on jay-server (`systemctl list-units 'actions.runner.*'`).
- [ ] The actual deploy command per project.
- [ ] nginx sites in use.
- [ ] Cloudflare Tunnel routes in use (confirm only SamVision is public and CommandCenter is not exposed, D-048).
- [ ] Where each repo's `.env` lives and whether dev and prod values are separated.
