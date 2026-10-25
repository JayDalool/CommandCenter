# Engineering HQ page map

Every screen in the prototype, how to reach it, and the states the gallery captures. Addresses are hash routes
(`http://127.0.0.1:5181/#/office`). Add `?nofeed` to freeze the demo feed, `?slow` to show loading skeletons.

## Sidebar

| Page | Address | What it shows | Main states |
|---|---|---|---|
| My Office | `#/office` | Executive dashboard: KPIs, company topology, Needs You, updates from Project Leads, active agents | Feed outage (Unknown / Stale), agent filters, agent drawer |
| Messages | `#/messages/<conversation>` | Private Project Lead conversations, agent DMs, team channels, Slack (not connected), with the task context beside them | New Message menu, Attach menu, archived conversations, context panel popped out |
| Decisions | `#/decisions` | **Needs My Attention**: decisions, questions, reviews and approvals waiting for Jay | Kind filters (tabs and KPI tiles), done items |
| Decision room | `#/decisions/sv-025` | One decision with options, evidence, people, plan, questions and technical detail | Evidence tabs (Logs, Screenshots, UI Findings, Files), Record decision confirm, decided state |
| Teams | `#/teams/<project>` | Engineering hierarchy per project: Jay → Project Lead → specialist leads → agents | Paused project (GauzeMate), onboarding project, agent drawer |
| Agents | `#/agents` | Agent Directory and Agent Management | Lifecycle filters, inspector, context menu, pause, reassign, offboard |
| Company | `#/topology` | Full-screen Operations Topology: Jay, projects, pipeline stages, agents, hosts | Full-screen graph, stage selected, project selected, Table and Timeline views, filters |
| Engineering | `#/engineering` | Workbench of active tasks, release gate, model usage, task detail | Detail tabs (Details, Plan, Checks, Activity), filters, selection bar |
| Task Room | `#/task/<KEY>` | One task: conversation, plan, terminal, evidence | Terminal popped out |
| Revenue | `#/revenue` | Subscription analytics. Not connected by default | Fictional demo, clearly watermarked |
| Approvals | `#/approvals/<request>` | D-032 approval queue, approval screen, Slack phone preview | High risk (Developer Unlock + typed ID), expired, approved |
| Budgets | `#/budgets` | D-033 company, project and agent budgets (shadow) | Normal, agent over limit, project over limit, company over limit, override request |
| Settings | `#/settings/<section>` | macOS-style settings in 11 sections | See below |

## Settings sections

`general` · `appearance` · `notifications` · `windows` (monitors and pop-outs) · `security` (Developer Unlock, read-only) ·
`connections` · `projects` (operating profiles) · `workers` · `demo` (feed outage, slow loading, reset) · `more`
(Releases, Fleet, Activity, AI Usage and other destinations) · `help` (shortcuts and where things are).

## Flows

| Flow | Start | Steps |
|---|---|---|
| New Agent | `#/onboard`, or New Agent on My Office, Teams or Agents | Template, Identity, Intelligence, Organisation, Skills and tools, Repositories and machines, Permissions, Instructions, Budget, Review and activate |
| New Project | `#/newproject`, or New Project on Teams or Topology | Identity, Repository, Environments, Workers, Team, Operating profile, Budget, Deploy rules, Review |

Both end in a mock approval. Nothing is created anywhere.

## Other places

| Place | Address |
|---|---|
| Design System | `#/design` |
| Older "Settings & more" list | `#/more` (still works) |

## Shell

Search (Ctrl+K), notifications bell, Jay's menu, tab strip with right-click menu, sidebar with right-click menu,
toasts, tooltips, popovers, modals, loading skeletons.

## Pop-out windows

Any view can open in its own window at `#/pop/<view id>`. The address carries no credential and no parameters.

| View id | Window |
|---|---|
| `page:<page>` | Any page above (1440 × 900) |
| `dm:<conversation>` | One conversation (980 × 820) |
| `task:<KEY>` | A Task Room (1200 × 800) |
| `term:<KEY>` | A Task Room's terminal (960 × 600) |
| `panel:topology-inspector`, `panel:task-context`, `panel:evidence`, `panel:task-detail`, `panel:agent` | Inspectors and side panels (520 × 860) |

The original tab stays, shaded with ↗, and offers Focus window and Return here.
