# Engineering HQ — audit and migration plan

Status: **Stage A + B + C (prototype)**. Branch `claude/project-thread-gs2u2h`. No production file,
service, database, policy or deploy was touched. Everything new lives in `design/ui-prototypes/engineering-hq/`.

## 1. What exists today (audit of `main` @ 693a556)

| Area | Today | Notes for the redesign |
|---|---|---|
| Frontend | React 19 + TS + Vite 8 at `web/app`, hash router (`lib/router.ts`), tiny external store | Prototype uses the same stack and versions; no new libraries. |
| Shell | 7 destinations: Dashboard, Needs You, Workspace, Task Manager, Activity/Logs, Files, Settings; old routes kept | New IA: My Office, Messages, Decisions, Teams, Company (Topology), Engineering, Revenue, + "Settings & more". All old routes must keep working. |
| Pop-outs | `screens/Popout.tsx` (RoomWindow, PaneWindow) + `workspace/rooms.ts`: localStorage layout, `storage` event, attach-by-session-name, `pagehide` → detach | Proven model for terminals/rooms. The prototype generalises it to any view (§3). |
| Auth | ccd token in memory/sessionStorage; handed to pop-outs over same-origin BroadcastChannel `cc-token`; never in a URL | Reused as-is in migration. The prototype carries no credentials at all. |
| Developer Unlock | Session id (never the token) shared over `cc-dev`; 2 h idle / 8 h max; LOCK in any window locks all | Pop-out windows must keep revalidating it for privileged writes. Unchanged. |
| Data | `/api/state`, tickets, live WS, usage meter, workers, audit, policies, autonomy shadow | Map to pages in §4. No chat store, no revenue source exist. |
| Policy truth | `server/ccd/registry.py`, `policy/projects/*.toml` | Used for prototype labels: GauzeMate **paused**; merge = owner (CC: low-risk docs/tests only); autonomy targets are **shadow only**; SamVision release windows Thu/Sat 01:00 America/Winnipeg. |

## 2. Where the concept art and the repo disagree (decisions for Jay)

1. **Project colours.** Repo tokens: SamVision red, GauzeMate green, CommandCenter blue, GYST orange, MFE purple. Concept art: SamVision mint, GYST purple, MFE orange, GauzeMate pink, CommandCenter blue. The prototype follows the **concept art**; one token change switches back. → *Jay to pick.*
2. **SamVision** is shown as real-estate/realtor tooling (art said computer vision).
3. **GauzeMate** is shown **Paused** (art said "Degraded / 2 agents working").
4. **Deploy buttons** in the art are shown as **Gated** / disabled: releases only through existing gates.
5. **Agent persona names** (Iris, Nova, Atlas, Pixel, Orion) are placeholders over real pipeline roles (plan, implement, independent review, UI test, release). Real names/models come from ccd sessions. → *Keep personas or show role + model only?*
6. **Revenue** has no data source. Default is *Not connected*; a fictional demo is opt-in and watermarked.
7. **Model usage/cost** on Engineering shows `$—` + Demo; live numbers come from ccd's meter (AI spend, kept separate from revenue).

## 3. Cross-window architecture (prototype, proposed for production)

- **Stable view ids**: `page:<page>`, `dm:<conversation>`, `task:<KEY>`, `term:<KEY>`, `panel:<name>`; validated by a strict regex. The pop-out URL is `#/pop/<id>` — no credentials, no parameters.
- **One owner** per view in a small shared record (`owners`): BroadcastChannel for live sync + localStorage for late joiners, shape-checked on receipt. Non-owners render a shaded placeholder (Focus window / Return here), so there are never two interactive copies or duplicate subscriptions.
- **Liveness**: each pop-out holds a Web Lock `hq-view:<id>` for its life (released by the browser on close/reload/crash, immune to background timer throttling); heartbeat fallback where Web Locks are missing. `pagehide` marks *closing*; a reload re-claims within the grace period; otherwise the view returns home with a notice. A pending pop that never loads is reclaimed after 8 s.
- **Re-pop** of a popped view focuses its window (named windows also make a duplicate impossible).
- **Main window gone**: pop-outs detect no `hq-main:*` lock, keep working, and can become the main window.
- **Shared UI state** (selected sub-tab, filters, drafts, inspector selection) is synced per view id, so a view keeps its context when it moves; chat sends are idempotent by client id.
- **Production rule kept**: closing any window only detaches. In the real app a Task Room / terminal view attaches to the same ccd/herdr session by name (`rooms.ts`); End Session stays a separate confirmed action.
- **Migration**: `rooms.ts` room/pane pop-outs become two view kinds of this manager; its `storage`-event layout stays the source for wall slots. Token and Developer Unlock handoff stay in `api/auth.ts` / `api/developer.ts` unchanged.
- **Limits**: browsers cannot place a window on a chosen monitor, and may refuse `focus()` — the UI then says where to find the window. Exact monitor placement would need a native (Tauri) proposal.

## 4. Pages → data (for the live build; all read-only first)

| Page | Live source | New backend needed? |
|---|---|---|
| My Office | `/api/state` (projects, needs-you queue, alerts), tickets, sessions | No (read-only). "Updates from leads" needs a lead-summary feed → proposal. |
| Messages | — | **Yes**: conversation store, indexing, retention, access rules. Separate security review; never in ccd operational metadata without it. |
| Decisions | tickets questions/gates, policy files, evidence/attachments | Recording an answer reuses existing question/gate endpoints and session routing. |
| Teams | registry, tickets by stage/owner, session presence | Presence must report Disconnected/Unknown on stale streams (prototype already does). |
| Topology | projects, tickets→stages, workers, release readiness | No for read-only. Layout is custom SVG + HTML (no graph library). |
| Engineering | tickets, PRs/CI, release gates, usage meter, workers | No. New Task stays disabled until an approved create API. |
| Revenue | — | **Yes**: provider-neutral read-only adapter; provider chosen by Jay; server-side restricted key. |

## 5. Phased migration (each step is its own gated PR; nothing auto-deploys)

1. Jay reviews the prototype; decisions in §2.
2. Tokens + shell (sidebar, top bar, tab strip) behind a `?ui=hq` flag; old UI default.
3. Window manager in `web/app`, wrapping existing Room/Pane pop-outs; regression tests that closing never calls `ptyClose`.
4. Pages one at a time on read-only data: Topology → Office → Engineering → Teams → Decisions.
5. Messages and Revenue only after their backend proposals are approved.
6. Flip the default after Jay signs off; old screens remain reachable.

## 6. Tool proposals

None needed so far. Possible later: `@playwright/test` as a dev dependency for CI (tests currently use the globally installed Playwright). Not added without Jay's approval.
