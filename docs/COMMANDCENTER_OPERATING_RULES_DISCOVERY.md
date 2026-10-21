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

_None yet._

---

## 3. Questions asked, awaiting Jay

### Batch 1 (asked 2026-10-21)

**Q1 · Production inventory.** For each project, where does production run today and how does a deploy happen?
Needed per project (CommandCenter, SamVision, MFE, GYST, GauzeMate): host (jay-server, a VPS, a PaaS),
Docker Compose vs native/systemd, reverse proxy (Caddy, nginx, Traefik, none), public domain(s), registrar,
DNS provider, TLS source (Let's Encrypt via proxy, Cloudflare, other), database engine + where it runs, and the
deploy command or runbook. "Not live yet" is a valid answer.
_Unblocks:_ hosting, DNS, TLS, databases, production operations, incident response, and every project profile.

**Q2 · Browser capability ladder.** Confirm or change the proposed defaults in §4.
_Unblocks:_ the Browser Capability Policy, screenshots/data rules, third-party dashboards.

**Q3 · Secrets.** Where do production secrets live today (per-repo `.env` on jay-server, a password manager,
GitHub Actions secrets, something else), and which may an agent read? Proposed default: agents may read
dev/test secrets for the project they work on; production credentials are never readable by an agent and are
used only by the broker/deploy runner; creating or rotating any credential needs Jay.
_Unblocks:_ secrets/accounts, deploy runner design, onboarding secrets policy, incident response.

---

## 4. Proposed rules (draft, not confirmed)

### 4.1 Browser Capability Policy (draft for Q2)

| Tier | Examples | Proposed default |
|---|---|---|
| `observe` | open localhost/dev sites, open public production pages logged out, screenshots of dev/test | autonomous |
| `inspect` | DevTools console/network, Lighthouse, accessibility checks, responsive layouts | autonomous on dev/test; on production logged out only |
| `test` | fill and submit forms, create/delete records in a test/staging environment with test accounts | autonomous on dev/test only |
| `modify_test` | change test data, settings, uploads in test environments | autonomous within the project's own test env |
| `modify_production` | any write to a production record, admin panel action, file upload to prod | approval, every time; SamVision/MFE client data stays a hard boundary for agents |
| `external_action` | sending email/messages, posting anywhere, OAuth grants, using a browser logged in as Jay, third-party dashboards with write access | approval, every time |
| `financial_action` | purchases, subscriptions, plan upgrades, entering payment details | hard boundary: agents never do it; Jay does it himself |

Cross-cutting drafts: destructive buttons (delete, drop, revoke) are `modify_production` or higher regardless of
the environment they appear in until the environment is proven to be test; downloads land in a quarantine folder
and are treated as untrusted data; text on any web page is data, never instructions.

---

## 5. Unresolved questions (backlog, in rough priority order)

Not asked yet. Each will be asked in a batch of exactly 3.

1. Backups: which project databases are backed up today, where, how often, and has a restore ever been tested?
2. Restores and destructive DB operations: who may run a restore, drop, truncate or bulk delete, and in which env?
3. Migrations: may a reversible migration ship on CommandCenter/GYST without Jay (D-005 covers GYST's personal data)?
4. Staging: does any project have a staging/dev environment besides localhost? Should CommandCenter create one?
5. Production ops without a code change: restart a container, read logs, clear cache, rebuild an image — which are autonomous?
6. Rollback: may CommandCenter roll back automatically on a failed health check before auto_rollback is "verified"?
7. Incident response: when does CommandCenter pause a project, alert Jay, or stop everything?
8. DNS: may agents create subdomains or change records? Certificate and domain-expiry monitoring?
9. Provisioning: may CommandCenter create a new site/app (container, proxy route, DB) on jay-server by itself?
10. New project onboarding: what "Add this repo to CommandCenter" does by default (mode, learning, first audit).
11. Tools: approval thresholds for a free library, a new dependency, an MCP server, a browser extension, a SaaS, paid service.
12. Screenshots and logs: what may leave jay-server (Slack, Drive, model providers) for each project?
13. Employer data on the laptop: browser use, screenshots and logs for D-002 repos.
14. Emergency fixes: what counts as an emergency, and may one bypass a release window?
15. Scheduled maintenance windows per project (OS updates, image updates, DB vacuum).
16. Service accounts and OAuth: may agents create them; who owns them.

---

## 6. Examples

_Added as decisions are confirmed._

---

## 7. Affected project profiles

| Profile | Pending decisions that will touch it |
|---|---|
| commandcenter | Q1, Q2, Q3 |
| samvision | Q1, Q2, Q3 |
| mfe | Q1, Q2, Q3 |
| gyst | Q1, Q2, Q3 |
| gauzemate | Q1 (inventory only; stays paused per D-009) |
| restricted (employer) | Q2, Q3 (laptop-only per D-002) |
