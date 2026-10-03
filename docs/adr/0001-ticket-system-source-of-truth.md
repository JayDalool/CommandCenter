# 0001 — Command Center's database is the source of truth for tickets

Date: 2026-10-03 · Status: accepted (P4B), migration pending Jay's approval

## Context

Work was tracked in four places: `docs/tasks/INDEX.md` tables (SamVision), one
file per task (GYST), GitHub issues with `status:*`/`needs:*` labels (GauzeMate),
and `docs/jay/MY_ACTIONS.md`. The legacy board re-derived stages from labels and
markdown on every poll. Agents could not ask "what is CC-012?" in one call, and
paid project features (GitHub Projects, Linear) were the only way to get a board.

## Decision

A durable ticket store inside ccd, in its own SQLite file (`tasks.db`, separate
from the prunable operational `ccd.db`). Keys are `<PREFIX>-<NNN>` per project,
allocated from a forward-only counter and never reused. Every mutation writes an
audit row in the same transaction. GitHub is an integration: PRs are
`ticket_links` rows, never a foreign key on the ticket.

## Alternatives considered

- **GitHub Issues + Projects as the store.** Rejected: couples the workflow to one
  forge and a paid feature, rate limits, no audit of who changed what, labels as
  a type system.
- **Markdown files in each repo.** Rejected: merge conflicts between agents,
  no relations, no cross-project Needs-Jay query, history only via git.
- **Postgres.** Rejected for now: one user, one host, low write rate; SQLite with
  WAL and `synchronous=FULL` is enough and needs no service.
- **Same file as ccd.db.** Rejected: the event log is pruned and disposable;
  product data must not share its lifecycle or backup policy.

## Why

Small, local, auditable, forge-independent, and it lets agents and the UI share
one model.

## Consequences

- tasks.db must be backed up as data (`~/command-center/data/tasks.db`).
- Ticket writes go through ccd's API; agents writing as themselves set
  `X-CCD-Actor` (self-asserted, not authentication).
- Until the import runs, existing sources stay authoritative for their projects.

## Future considerations

Cycles (`cycle_id` is reserved), saved views, estimates/analytics, a second
forge provider, per-agent tokens if attribution must be enforced.
