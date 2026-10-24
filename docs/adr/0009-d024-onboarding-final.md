# ADR 0009 — D-024 is final: onboarding projects and agents

Date: 2026-10-24 · Status: accepted (Jay, 2026-10-24T06:51Z: "I APPROVE D-024 AS FINAL with the decisions above
incorporated") · Decision: [D-024](../decisions/D-024.md), recorded as `policy/decisions/D-024.toml`

## Context

D-024 decides how a new project or agent joins CommandCenter and what CommandCenter may do while it does. Jay agreed
with the design on 2026-10-21. He allowed groundwork behind a disabled flag on 2026-10-23 and asked for four
refinements: the engineering hierarchy, independent review, repository authority during onboarding, and budgets
when data is incomplete. He also kept three gates apart: making the policy final, merging the backend, and turning
anything on in production.

The text of record went through two release candidates and an audit of clauses 14 to 18 against the recorded
decisions. The audit found no clause that loosens a recorded restriction. On 2026-10-24 Jay approved it as final and
set the amounts it had left proposed:
- budget alerts at 50%, 80% and 95%, with a hard hold at 100%;
- a 5% overrun, only for running work to reach a checkpoint;
- a per-step cap and approvals for large steps;
- a burn-rate breaker;
- no dollar limits until measured usage supports them;
- fact re-verification defaults;
- the initial Project Leads;
- the Slack request design.

The backend groundwork (#65) merged the same day with its flag off. Before that, the migration v10 drill passed 28
of 28 checks on a consistent backup of the live `tasks.db`.

## Decision

1. `docs/decisions/D-024.md` version 1.0 is the full text. `policy/decisions/D-024.toml` is the decision of record,
   and a test keeps it identical to the record block in the text.
2. The policy file is written under D-007 with Jay's explicit approval: `policy/**` changes need Jay.
3. Making D-024 final approves the policy and design only. It does not authorize any of these:
   - production enforcement;
   - agent activation;
   - credential issuance;
   - Broker grants;
   - budget holds;
   - Slack approval buttons;
   - autonomous onboarding authority;
   - Phase 2 enforcement;
   - production deployment.
4. No enforcement switch is requested before all of these hold (clause 18):
   - Phase 2 actor-token enforcement;
   - a shadow-mode validation;
   - the D-030 verification of the laptop runner's privileges and isolation (D-045);
   - the private authenticated approval path (D-006).

   Every switch is then a separate explicit approval.

## Consequences

- ccd loads the new record at its next start after a deploy, as it does D-001 to D-009, and shows it under
  Settings → Policies. No profile cites it yet, so no engine rule changes.
- The `onboarding_groundwork` flag stays off. Nothing records shadow results until Jay turns shadow mode on.
- Dollar limits come later, as a proposal with measured usage, for Jay to decide.
- The operating rules' discovery file records the same decisions that sit outside D-024: D-031 (fact
  re-verification), D-032 (Slack), D-033 (budgets) and D-043 to D-046 (backups, CI isolation, Project Leads).
