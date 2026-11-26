# CTO rules (CC-089)

Template: Jay copies this file into `/home/jay/cto` next to `.claude/settings.json`.

- Follow D-058 (`docs/decisions/D-058.md`) for every cleanup.
- Never hand-delete Docker volumes, databases, backups, GauzeMate items or anything of a live app.
- Ask the project's lead, or Jay, as D-058's tiers say, before removing anything outside tier 1.
- If a deny rule blocks a Jay-tier removal, do not look for a way around it. Jay does it himself, and you record it
  with `cc-cleanup --done --yes-from jay --ref <ref>` once CC-101 ships the tool.
- Never edit your own settings, this file, the user settings or the board config.
- The cc-cleanup tool arrives with CC-101. Until then, clean up only tier-1 items, by hand, within the deny rules.
