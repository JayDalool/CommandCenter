# Command Center

@AGENTS.md

Claude-specific notes; everything else is in AGENTS.md and [docs/flow/FLOW.md](docs/flow/FLOW.md).

- Start from the ticket (`python -m ccd.pipeline_cli work KEY`, run from `server/`), not from an earlier chat. Record
  yourself in your seat with `pipeline_cli role` before working, and write every stage result back through
  `pipeline_cli`; a result said only in a session does not count.
- Read only your seat's page in `docs/flow/seats/`. If you are the project's lead (coordinator), `lead.md` is yours.
- A subagent you start inherits these rules; give it the ticket key and its seat page, never your own notes.
- Work in the worktree `pipeline_cli start` recorded for the ticket. `.claude/worktrees/` and `.claude/settings.local.json` are machine-local and git-ignored.
