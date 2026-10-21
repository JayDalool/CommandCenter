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
- **Open:** SamVision weekly is below the proposed daily; confirm whether to raise it once verified.

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

### D-024 · New project onboarding (under discussion)
- Not final. The full design is in the Project Onboarding Design doc
  (https://claude.ai/artifact/AR9b53F8irK2VB3d8fzAmu). This entry is written once Jay answers Q10 to Q12.

---

## 3. Questions asked, awaiting Jay

Batch 1 (Q1 hosting, Q2 browser, Q3 secrets) answered 2026-10-21T17:37Z → D-010 … D-016.
Batch 2 (Q4 databases, Q5 production ops, Q6 subdomains) answered 2026-10-21T19:53Z → D-017 … D-021.
Batch 3 (Q7 remote hosts, Q8 onboarding, Q9 incidents) answered 2026-10-21T20:36Z → D-022, D-023; Q8 grew into
the onboarding design (D-024, under discussion).

### Batch 4 (asked 2026-10-21, to finalize D-024)

**Q10 · Proposal PR safety.** On Jay's own repos, draft PRs only after the pre-push check (no deploy-on-push, no
workflow/deploy/auth/migration files, max 5 open). On client and employer repos, no PRs during onboarding, patches
only. May a CI workflow ever be opened as a PR without asking?

**Q11 · Ratchet.** After graduation, may CommandCenter automatically tighten a project (down to Restricted or
Paused) when the weekly re-fingerprint finds new production risk, with a full report (D-023 style)?

**Q12 · Existing projects.** Run baseline audits with current permissions unchanged, in the order GYST, SamVision,
MFE, CommandCenter, and skip GauzeMate until it is resumed?

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

1. Migrations: may a reversible migration ship on CommandCenter/GYST without Jay (D-005 covers GYST's personal data)?
2. Staging: does any project have a staging/dev environment besides localhost? Should CommandCenter create one?
3. Certificate, tunnel and domain-expiry monitoring (zaylolabs.com renewal at Cloudflare).
4. Tools: approval thresholds for a free library, a new dependency, an MCP server, a browser extension, a SaaS, paid service.
5. Screenshots and logs: what may leave jay-server (Slack, Drive, model providers) for each project?
6. Employer data on the laptop: browser use, screenshots and logs for D-002 repos.
7. Emergency fixes: what counts as an emergency, and may one bypass a release window?
8. Scheduled maintenance windows per project (OS updates, image updates, DB vacuum).
9. Service accounts and OAuth: may agents create them; who owns them.
10. Are agent accounts (D-012) allowed on production apps, or dev/test only?
11. Exact deploy command per project, and whether CommandCenter should wrap it as the deploy runner.
12. Which projects besides SamVision are (or should be) public on zaylolabs.com?
13. Off-server backup location (cloud bucket, second machine, external drive) and whether it is encrypted.

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
| commandcenter | D-010 (loopback-only, not on the tunnel), D-011 … D-021 | Q8, Q9 |
| samvision | D-010 (public via tunnel), D-011 … D-021; backups weekly (D-018) | Q9 |
| mfe | D-010, D-011 … D-021; backups daily (D-018) | Q9 |
| gyst | D-010, D-011 … D-021; backups unknown | Q9 |
| gauzemate | D-010 (inventory only; stays paused per D-009) | none |
| restricted (employer) | D-011, D-014, D-015 (laptop-only per D-002) | none |
| any remote project | D-017, D-022 (directed style for client servers), every global rule | Q10, Q12 |

---

## 8. To verify on jay-server (when Jay is back)

Read-only checks, no changes:

- [ ] Database engine and location per project (Postgres / MySQL / SQLite).
- [ ] Backup jobs per project: what runs, schedule, destination, last success. MFE expected daily, SamVision about weekly.
- [ ] Whether any restore has ever been tested.
- [ ] The deploy command per project.
- [ ] nginx sites and Cloudflare Tunnel routes in use (confirm only SamVision is public, CommandCenter is not exposed).
- [ ] Where each repo's `.env` lives and whether dev and prod values are separated.
