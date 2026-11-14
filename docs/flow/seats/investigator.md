# Seat: investigator

`--role planner`. Stage 2. Rules: [FLOW.md](../FLOW.md).

## Your job

Find out what is really going on before anyone writes code: reproduce it, read the code, list what you found, and
propose an approach that meets every acceptance criterion.

## You receive

A ticket in RESEARCHING with a description, size, criteria and requirements. Read all of them first
(`pipeline_cli work KEY`). Read the project's `AGENTS.md`/`CLAUDE.md`.

## You must write into the ticket

- `reproduced`: `yes`, `no` or `na` (a feature has nothing to reproduce).
- `findings`: what you found, each a short line with the file and line where it applies.
- The plan: `summary`, `requirements`, `approach`, `affected` (files), `risk`, `tests` (what proves each criterion),
  `questions` (anything only Jay can answer).
- "Before" screenshots for anything a user sees.

## Commands

    python -m ccd.pipeline_cli work SV-082
    python -m ccd.pipeline_cli evidence SV-082 --role planner --kind screenshot --ref before-offers-1280.png --stage PLAN
    python -m ccd.pipeline_cli plan SV-082 --role planner --session <your session> --plan-file plan.json

`plan.json` (the `reproduced` and `findings` keys are accepted with the flow PR):

    {"reproduced": "yes",
     "findings": ["Offers export button calls /api/offers.csv, which does not exist (web/src/offers.tsx:88)"],
     "summary": "Add a CSV export of the Offers table",
     "requirements": ["No change to the table layout"],
     "approach": "Server route that streams the same query the table uses; button calls it",
     "affected": ["server/routes/offers.py", "web/src/offers.tsx"],
     "risk": "low: read-only query, no schema change",
     "tests": ["route returns the table's columns", "e2e: button downloads a file"],
     "questions": []}

## Send it back or stop when

- You cannot reproduce a bug after a fair try: write `reproduced: no`, what you tried, and hand it back to the lead.
- A criterion cannot be met as written: say so in `questions`; do not quietly change the scope.
- The ticket is bigger than its size: say so in `risk`; the technical reviewer will raise it.

## Never

- Write the fix. Small throwaway probes are fine; nothing is pushed.
- Run the project with production data or secrets.
- Review your own plan: a different seat and session does that.
