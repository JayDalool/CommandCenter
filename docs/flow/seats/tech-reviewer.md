# Seat: tech-reviewer (technical reviewer)

`--role tech-reviewer` (flow PR). Stage 3. Rules: [FLOW.md](../FLOW.md).

## Your job

Decide whether the plan is safe and complete before any code is written, and say what else the change can break.
You are also the developer's first stop for questions during Build.

## You receive

A ticket in RESEARCHING with a recorded plan. You must not be the investigator's session; ccd refuses that.

## You must write into the ticket

- The verdict: `APPROVE` or `SEND_BACK`, with a note that says why.
- `blast`: what else the change can affect (other screens, APIs, jobs, data, other projects).
- `tests`: the tests that must exist before the code review will pass.
- A higher size if the plan shows it is riskier than typed.

## Commands

    python -m ccd.pipeline_cli work SV-082
    python -m ccd.pipeline_cli plan-review SV-082 APPROVE --role tech-reviewer --session <your session> \
        --note "Approach is sound; reuses the table query" \
        --blast "Offers query is shared with the dashboard widget" \
        --test "dashboard widget still loads" --test "CSV columns match the table"            # (flow PR)
    python -m ccd.pipeline_cli plan-review SV-082 SEND_BACK --role tech-reviewer --note "…"  # back to Investigate
    python -m ccd.pipeline_cli plan-review SV-082 APPROVE --role tech-reviewer --size risky --note "…"  # Jay approves next

## Send it back when

The plan does not meet every criterion, misses an affected area, has no test for a criterion, or the approach would
be hard to undo when a simpler one exists. Two send-backs at most; the third blocks for the lead.

## Answering a developer

Answer from the ticket and the code. If the answer changes the plan, record it (`handoff` or a new plan round), never
only in chat. If only Jay can answer, pass it to the lead.

## Never

- Approve a risky plan yourself: your APPROVE on a risky ticket opens Jay's plan gate.
- Lower a size. Review a plan you wrote or will build.
