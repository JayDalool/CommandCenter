# policy/: Project Operating Profiles and Jay's decisions

These files say how much autonomy each project has. They are versioned, read at ccd start-up, validated by
`server/ccd/profiles.py` and shown read-only in **Settings → Policies** and at `GET /api/profiles`.

```
policy/projects/<key>.toml    one Project Operating Profile per registered project
policy/decisions/D-NNN.toml   Jay's policy decisions; profiles cite them by id
policy/examples/*.toml        validated examples that are not loaded as projects (example-restricted: a laptop-only repo)
```

## Two halves of every profile

| Section | Meaning | Enforced? |
|---|---|---|
| `[enforced]` | What Command Center does **today**: merge policy, night-shift mode, pause, lanes, UI-test fix mode. It must equal `ccd/registry.py`; a test and a runtime drift check keep them equal. | Yes (through the registry, unchanged) |
| `[target]` | The agreed policy Jay decided (D-001 … D-006): merge, deploy, plan approval, reviews, release windows, personal-data triggers, execution nodes. | **No.** The Autonomy Engine evaluates it in SHADOW MODE only and records disagreements. |
| `[capabilities]` | Facts a target rule depends on (for example `auto_rollback`). They start `false`; a capability turns `true` only after it has been built and rehearsed. | Read by the engine |

No autonomous merge or deploy is enabled by these files. Moving a project from `[enforced]` to `[target]` is a
later, separate change that Jay approves.

## Who may change these files

Only Jay. "No agent may expand its own authority": `policy/**` is in the auto-merge denylist
(`ccd/merge_policy.py`), every load records each file's SHA-256 so a change is visible, and a change to a profile
or decision is a self-protection item that needs Jay's approval (D-001 follow-up, 2026-10-21).

A decision is never edited to mean something else: write a new `D-NNN` with `supersedes = "D-OLD"`.

## Format

TOML (read with Python's standard `tomllib`, so ccd gains no dependency). Unknown sections and keys are errors,
so a typo never silently means "no rule". The exact schema is `ccd/profiles.py` (`SCHEMA`).
