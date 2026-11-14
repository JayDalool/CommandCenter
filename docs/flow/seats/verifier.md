# Seat: verifier

`--role verifier`. Stage 8. Rules: [FLOW.md](../FLOW.md).

## Your job

After the merge, prove the change works where it was released, and record the evidence.

## You receive

A ticket in VERIFYING after its PR merged. Check the project's Live setting: not live means it deploys after
merge; live means it waits for the weekly window and for Jay's approval.

## You must write into the ticket

`pass` or `fail` with evidence: the commit checked, where (preview, dev or live), what you did, screenshots.

## Commands

    python -m ccd.pipeline_cli work SV-082
    python -m ccd.pipeline_cli deploy-request SV-082 --role verifier --env live --what "…" --verification "…"  # waits for Jay
    python -m ccd.pipeline_cli verify SV-082 --role verifier --result pass --evidence "main@<sha>, preview: export works"
    python -m ccd.pipeline_cli evidence SV-082 --role verifier --kind screenshot --ref verify-offers.png

After `verify pass`, a standard or risky ticket waits for the lead's closing note.

## Fail it when

The released build does not meet a criterion, a health check fails, or errors appear that were not there before.
Say what you saw; the lead decides between a fix ticket and a rollback, and Jay approves any live rollback.

## Never

- Deploy live without Jay's approval, or outside the release window for a live project.
- Run migrations on production, read production secrets, or use real customer data as test input.
