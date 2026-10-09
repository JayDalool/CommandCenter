Applies to: samvision
## Careful mode — this project asks for a lot of research and great care

On top of everything above:
- Research before any change. Every task gets a full planning pass by the repo's planner agent first: read the code
  paths it touches, the git history of those files, the decisions/ADRs and task files for that area, PRODUCT.md and
  the existing tests. The plan records its evidence (files, functions, commits), the base main SHA, the change
  surface, what could break, and how it will be tested. No evidence, no plan.
- At night, implement only tasks whose plan is LOW risk with a small, precise change surface. Anything MEDIUM or
  HIGH risk — or touching the repo's "do not touch" list, valuation/CMA/scoring math, migrations, auth, tenant
  isolation, uploads, licensed data or deployment — stops at a recorded plan for Jay.
- One implementation at a time, never two.
- A reviewer that finds anything material means rework and a new review; never argue a finding away.
- Jay merges every PR. Never deploy, never run docker compose up/down/build/restart, never touch the production
  database or its containers.
- No screenshots and no individual property records in any output; text snapshots only.
