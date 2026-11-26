# CTO rules (CC-089)

Template: Jay copies this file into `/home/jay/cto` next to `.claude/settings.json`.

- Follow D-058 (`docs/decisions/D-058.md`) for every cleanup.
- Never hand-delete Docker volumes, databases, backups, GauzeMate items or anything of a live app.
- Ask the project's lead, or Jay, as D-058's tiers say, before removing anything outside tier 1.
- The cc-cleanup tool arrives with CC-101. Until then, clean up only tier-1 items, by hand, within the deny rules.
