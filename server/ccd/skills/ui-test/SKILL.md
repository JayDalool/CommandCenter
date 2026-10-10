---
name: ui-test
description: UI test run — test the UI features this repo merged since its last run with Playwright, keep the tests, and report findings to Jay in Command Center. Run only when Jay asks (/ui-test or Command Center's UI tests button).
disable-model-invocation: true
---
UI test run from Jay via command-center for <project>. Test the user-visible features merged since this project's
last UI test run, keep the tests as a regression suite, and report what you find. Jay decides what gets fixed.

Project key: <project> is this repo's Command Center project — samvision, gauzemate, commandcenter, gyst or mfe.
First: if `python -m ccd.pipeline_cli tasks <project>` prints PAUSED, do nothing; say so in one line and stop.
This repo's AGENTS.md / CLAUDE.md win over anything here (for SamVision: careful mode, licensed data rules).

## 1. What to test

- The run folder: ~/command-center/ui-tests/<project>/<YYYY-MM-DD-HHMM>/ (now). The previous folder there is the last
  run; with none, look back 14 days.
- Features merged since then that a user can see: Command Center tickets of this project that reached
  VERIFYING or DONE since then and are UI work (label ui, type DESIGN, or a visible change), plus the repo's own
  manual UI check lists (docs/jay/UI_TESTS.md, docs/tasks/UI_MANUAL_REVIEW.md or what AGENTS.md names).
- Each feature's acceptance criteria and human checks (task file / plan) are the test cases.

## 2. How to test

- Playwright, driven from the repo (its existing e2e setup, else tests/e2e/ with Playwright as a dev dependency).
- Against a local or preview instance of the app with test data — never production, never production data.
- Per feature: the acceptance criteria as tests, plus console errors, a 375 px narrow width, keyboard use, and
  state that survives reload and Back.
- SamVision: text snapshots only — no screenshots, no video, no traces with page content, no individual property
  records anywhere (licensed data). Other projects may attach screenshots in the run folder.
- Keep the tests: put them on a branch ui-tests-<YYYY-MM-DD>, open one PR, get a fresh review. The repo's merge
  rules apply (SamVision and GauzeMate: Jay merges). Tests that fail because of a real finding are marked
  expected-to-fail (test.fail) with the finding's id, so the suite stays green until the fix lands.

## 3. Findings — only what matters

Severity: showstopper (data loss, security/privacy, crash, a core flow cannot be completed), major (a feature does
not do what its acceptance criteria say), minor (works, but rough). Every finding needs reproduction steps and
what you expected vs what happened. No style nitpicks, no redesign wishes.

Fix mode: <fix_mode>
- ask: do NOT fix anything and do not create tasks for findings. Jay decides each finding in Command Center
  (Fix it → a task enters the pipeline; Skip → recorded).
- auto: create a task per showstopper/major finding (pipeline_cli add <project> --role coordinator --label
  ui-finding …) and fix it through the normal pipeline; minor findings are only reported.

## 4. The report (Command Center reads these two files)

In the run folder:
- report.md — first line exactly `Status: working` while you go, `Status: complete` when done. Then: features
  tested (ticket, feature, tests, pass/fail), the test PR, findings in plain words, what you could not test and why.
- findings.json — exactly this shape (no other keys):
  {"summary": {"features": <n>, "passed": <n>, "failed": <n>},
   "findings": [{"id": "F1", "severity": "showstopper|major|minor", "title": "…", "feature": "<KEY> <feature>",
                 "steps": ["…", "…"], "expected": "…", "actual": "…", "evidence": "<test file and test name>"}]}

Never: deploy, touch production, merge application code, change rules/CI/permissions, or copy licensed data,
records, addresses or secrets into any report, finding, test name or PR.
End with one line: <project> UI tests: <n> features, <n> passed, <n> failed, <n> findings (<n> showstopper, <n> major).
