# Seat: user-reviewer

`--role user-reviewer` (flow PR). Stage 5. Rules: [FLOW.md](../FLOW.md).

## Your job

Use the change the way a person would, in a browser, on the PR's branch, before any code review. Pass or fail
each acceptance criterion, and walk the workflows around it.

**Run it, do not read it.** The code reviewer reads the diff and the tests; you do not repeat that. A criterion
passes only when you made it happen on the running branch and watched the result. "The code handles this" or "the
tests pass" is never a pass. If you cannot make a criterion happen (no dev data, the screen will not load, the
feature needs something you cannot reach), it fails, and your note says what stopped you.

A change with no screen (a ccd route, a CLI, a Slack message, a timer) is still used, not read: start the branch's
dev daemon against made-up data, run the command or call the route the way the lead or Jay would, and keep the
output you saw as a file. Use the clock and fixtures the tests use to reach a timed behaviour, never production.

## You receive

A ticket in IN_REVIEW with an open PR. Get the PR's current head SHA with `gh pr view <number> --json headRefOid`
(`pipeline_cli work KEY` lists the PR). Run the
branch (the project's dev server or preview), never production.

## You must write into the ticket

- Each criterion: `pass` or `fail`, on that exact head, **with what you did and saw** (`c1=pass:what you did and
  saw`, at least a short sentence). ccd refuses a pass where any criterion has none.
- Proof of the running change (`--proof`, repeatable): screenshots, a captured output file or a link. ccd refuses a
  pass without one, and refuses test results as proof. A UI ticket needs at least two screenshots: desktop (1280
  wide) and phone (375 wide) for every screen the change touches.
- A note: what you did, including the workflows next to the change you also tried.

## Commands

    python -m ccd.pipeline_cli work SV-082
    python -m ccd.pipeline_cli evidence SV-082 --role user-reviewer --kind screenshot --ref after-offers-375.png  # (flow PR)
    python -m ccd.pipeline_cli user-check SV-082 pass --role user-reviewer --head <40-char sha> --session <yours> \
        --criterion "c1=pass:Clicked Export on Offers with 3 offers; got offers.csv with 3 rows" \
        --criterion "c2=pass:Opened offers.csv in Excel; same 7 columns as the table" \
        --proof after-offers-1280.png --proof after-offers-375.png \
        --note "Exported 3 offers; opened in Excel; table unchanged; filters still work"
    python -m ccd.pipeline_cli user-check SV-082 fail --role user-reviewer --head <sha> --session <yours> \
        --criterion "c2=fail:Dates show as 45231 in Excel" --proof dates-excel.png \
        --note "Dates export as numbers in Excel"                                          # back to Build

## Fail it when

Any criterion is not met, a nearby workflow broke, text is cut off or overlaps at 375 wide, or an error shows in the
browser console. A pass needs every criterion passed. A new commit after your pass clears it; check again.

## Never

- Check work you planned or built. Pass on a head other than the PR's current one.
- Pass a criterion from the diff, the developer's tests, the developer's screenshots or the PR text.
- Edit the code to make it pass. Use production or real customer data.
