# Install the CTO deny rules (CC-089, D-058)

Jay does this; no agent writes these files. The rules bind only the CTO.

1. `mkdir -p /home/jay/cto/.claude`
2. `install -m 0600 scripts/cto/settings.json /home/jay/cto/.claude/settings.json` (from the merged repo), and copy the rules file next to it: `install -m 0644 scripts/cto/CLAUDE.md /home/jay/cto/CLAUDE.md`.
3. Set `chat_cto_root` to `/home/jay/cto` in `~/command-center/board/config.json` and restart the CTO there. Copy
   over any CTO memory or notes you want to keep: a new start folder starts with fresh folder memory.
4. Drill, in the CTO session: ask it to run `docker volume ls` and `rm -rf /tmp/cto-drill`. Both must be denied.
   `docker ps` must still work.
5. Delete the CC-089 line in `docs/jay/MY_ACTIONS.md`.

Roll back: delete `/home/jay/cto/.claude/settings.json` and unset `chat_cto_root`.
The rules are a guard, not a hard stop (D-058).
