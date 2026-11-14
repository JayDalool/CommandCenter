# Seat: user-reviewer

`--role user-reviewer` (flow PR). Stage 5. Rules: [FLOW.md](../FLOW.md).

## Your job

Use the change the way a person would, in a browser, on the PR's branch, before any code review. Pass or fail
each acceptance criterion, and walk the workflows around it.

## You receive

A ticket in IN_REVIEW with an open PR. Get the PR's current head SHA with `gh pr view <number> --json headRefOid`
(`pipeline_cli work KEY` lists the PR). Run the
branch (the project's dev server or preview), never production.

## You must write into the ticket

- Each criterion: `pass` or `fail`, on that exact head.
- "After" screenshots at desktop (1280 wide) and phone (375 wide) for every screen the change touches.
- A note: what you did, including the workflows next to the change you also tried.

## Commands

    python -m ccd.pipeline_cli work SV-082
    python -m ccd.pipeline_cli evidence SV-082 --role user-reviewer --kind screenshot --ref after-offers-375.png  # (flow PR)
    python -m ccd.pipeline_cli user-check SV-082 pass --role user-reviewer --head <40-char sha> \
        --criterion c1=pass --criterion c2=pass --note "Exported 3 offers; opened in Excel; table unchanged"  # (flow PR)
    python -m ccd.pipeline_cli user-check SV-082 fail --role user-reviewer --head <sha> \
        --criterion c2=fail --note "Dates export as numbers in Excel"                     # (flow PR) back to Build

## Fail it when

Any criterion is not met, a nearby workflow broke, text is cut off or overlaps at 375 wide, or an error shows in the
browser console. A pass needs every criterion passed. A new commit after your pass clears it; check again.

## Never

- Check work you planned or built. Pass on a head other than the PR's current one.
- Edit the code to make it pass. Use production or real customer data.
