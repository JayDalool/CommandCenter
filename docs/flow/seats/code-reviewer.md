# Seat: code-reviewer

`--role reviewer`. Stage 6. Rules: [FLOW.md](../FLOW.md).

## Your job

An independent review of the diff on its exact head: correct, tested, consistent, efficient, and not hurting anything
outside the plan's blast radius.

## You receive

A ticket in IN_REVIEW whose user check passed on the current head (a small ticket that is not a UI ticket skips the
user check). Start a **fresh session**: read the diff, the ticket, the plan, the blast radius and the criteria. Never
the developer's session or notes. You must have had no part in the change (D-024 clause 15).

## You must write into the ticket

`APPROVE` or `REQUEST_CHANGES` bound to the exact 40-character head, and findings: `scope in` (must fix in this PR)
or `scope out` (a later ticket).

## Commands

    python -m ccd.pipeline_cli work SV-082
    python -m ccd.pipeline_cli review SV-082 --role reviewer --session <fresh session> --verdict APPROVE --head <sha>
    python -m ccd.pipeline_cli review SV-082 --role reviewer --session <fresh session> --verdict REQUEST_CHANGES \
        --head <sha> --findings-file findings.json

`findings.json`: `[{"scope": "in", "category": "test", "summary": "No test for an empty offer list"}]`

## Check, in order

1. Every acceptance criterion and every test the technical reviewer required is covered.
2. Correctness: edge cases, errors, concurrency, time zones (use America/Winnipeg by name).
3. Blast radius: nothing outside the plan's `affected` list changed without reason.
4. Why-comments where the code is not obvious; no dead code; no secrets or customer data.
5. Protected paths (see the repository's `AGENTS.md`): flag any change for Jay.

Risky tickets and changes to protected paths also get a second review from a different model family (Codex), on
top of yours (D-024 clause 15). A small ticket that touches no protected or sensitive path gets one Sonnet reviewer per
round and no second reviewer; on a small ticket a fix after REQUEST_CHANGES gets a new fresh Sonnet session on the new head, within the
two-round limit. Model table: [FLOW.md](../FLOW.md#models-and-usage).

## Bundled review (small tickets only)

One fresh session per project per day may review that day's small tickets. It must have had no part in any of them
(not implementer, commit author, plan author or assigning lead). It reads each PR's diff on its own and records one
`review` per ticket on that PR's exact head. A new head on any ticket needs its own new review. Standard and risky
tickets keep one fresh session per review.

## Never

- Review a change you planned, built, assigned or committed to. Approve a head you did not read.
- Close a finding as the implementer would; you or Jay close findings.
- Merge. Approval puts the ticket in front of Jay (or the low-risk policy where it is on).
