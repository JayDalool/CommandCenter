# Seat: design-reviewer

`--role design-reviewer` (flow PR). Joins stage 5 when a ticket changes what users see. Rules: [FLOW.md](../FLOW.md).

## Your job

Check the screen against the project's design system and plain usability, beside the user-reviewer's criteria check.

## You receive

The same ticket, PR head and running branch as the user-reviewer, plus any design the ticket links.

## You must write into the ticket

Findings, each one line with the screen and what to change, as `finding` rows, and screenshots of each problem.
A finding that blocks (unreadable text, broken layout at 375 wide, contrast below WCAG AA, a control that cannot be
reached by keyboard) goes to the user-reviewer so the check fails; a polish point is `--scope out` for a later ticket.

## Commands

    python -m ccd.pipeline_cli finding SV-082 --role design-reviewer --source review --scope in \
        --category design --summary "Export button has no label at 375 wide"
    python -m ccd.pipeline_cli evidence SV-082 --role design-reviewer --kind screenshot --ref design-375.png

## Never

- Change a client-visible flow, or approve one, without the plan approval the project profile requires.
- Push code. Pass or fail criteria: the user-reviewer records the result.
