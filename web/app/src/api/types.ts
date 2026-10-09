// Shapes served by ccd (docs/API.md). Times from ccd are epoch SECONDS.

export type AgentStatus = "idle" | "working" | "blocked" | "done" | "unknown";
export type AgentRole = "coordinator" | "lane" | "command-center" | "other";

export interface Agent {
  id: string;
  pane_id: string;
  agent_name: string;
  agent: string;
  label: string;
  project: string | null;
  role: AgentRole;
  status: AgentStatus;
  live: boolean;
  cwd: string;
  workspace: string;
  workspace_id: string;
  tab_id: string;
  session_id: string;
  blockedSinceMs: number | null;
  blockedForMin: number | null;
  context: null;
}

export type CiMark = "✓" | "✗" | "…" | "–";

export interface PrRow {
  number: number;
  ref: string;
  title: string;
  ci: CiMark;
  ready: boolean;
  draft: boolean | null;
  url: string | null;
  sha: string;
  age_h: number;
  review?: string | null;
  mergeable?: string | null;
  branch?: string | null;
  updatedAt?: string | null;
}

export interface Checklist { exists: boolean; open: number; done: number; items: string[] }

export interface ProjectView {
  key: string;
  name: string;
  repo: string;
  /** https://github.com/<owner>/<repo>, built by ccd from the registry; null when unknown. */
  repoUrl?: string | null;
  path: string;
  source: string;
  tasks: { ref: string; title: string; stage: string; url: string | null; flags: string[] }[];
  prs: PrRow[];
  recent: { ref: string; title: string; url: string | null }[];
  team: { name: string; model: string; status: string; pane_id: string | null; stuck_min: number | null }[];
  panes: Agent[];
  tests: { ui: Checklist; actions: Checklist };
  main_ci: CiMark;
  counts: Record<string, number>;
  errors: string[];
  handoff: string[];
  coordinator: Agent | null;
  summary: string;
  github: { asOf: number | null; error: string | null };
}

export interface Need {
  project: string;
  ref: string;
  text: string;
  kind: "merge" | "task" | "actions" | "ci" | "ticket" | string;
  url: string | null;
  sha?: string;
  number?: number;
  flags?: string[];
  status?: string;
  since?: number;
}

export interface Blocked { project: string; pane_id: string; name: string; question: string; stuck_min: number }

export interface Alert {
  id: string;
  severity: "warn" | "action" | "info" | string;
  source: string;
  project: string | null;
  text: string;
  since: number;
  lastSeen: number;
  ack: boolean;
  ackAt: number | null;
  active: boolean;
}

export interface Host {
  asOf: number | null;
  disk?: number;
  containers_up?: number;
  containers_total?: number;
  down?: string[];
  containers?: { name: string; state: string }[];
  procs?: { pid: number; name: string; rssMB: number }[];
  claudeCount?: number;
  memTotal?: number;
  memAvailable?: number;
  memUsed?: number;
  swapTotal?: number;
  swapUsed?: number;
  swapPct?: number;
  load?: number[];
  cpuPct?: number | null;
  cpus?: number;
  uptimeS?: number | null;
  oomKills24h?: number | null;
  backup_age_h?: number;
}

export interface SourceState { asOf: number | null; error: string | null }

export interface Sources {
  herdr: { ok: boolean; connected: boolean; error: string | null; protocol: number | null;
    lastSnapshotAt: number | null; lastEventAt: number | null; warning: string | null };
  github: Record<string, SourceState>;
  git: SourceState;
  host: SourceState;
  tasks?: { ok: boolean; asOf: number | null; error: string | null };
}

export interface WorkspacePaneCell {
  id: string;
  rect: { x: number; y: number; w: number; h: number };
  focused: boolean;
  live: boolean;
  agentName: string | null;
  agent: string | null;
  label: string | null;
  status: AgentStatus | null;
  role: AgentRole | null;
  project: string | null;
  cwd: string | null;
}

export interface WorkspaceTab {
  id: string;
  label: string;
  number: number | null;
  focused: boolean;
  zoomed: boolean;
  focusedPaneId: string | null;
  area: { w: number; h: number };
  panes: WorkspacePaneCell[];
}

export interface Workspace {
  id: string;
  label: string;
  number: number | null;
  focused: boolean;
  activeTabId: string | null;
  project: string | null;
  tabs: WorkspaceTab[];
}

export interface PublicProject {
  key: string; name: string; repo: string; path: string; branch: string;
  github?: GithubIdentity | null;
  model?: string; effort?: string; index?: string; prefix?: string;
  /** Prefixes this project has retired. Their keys still resolve; new keys never use them. */
  legacy_prefixes?: string[];
}

export interface Coordinator {
  name: string; paneId: string | null; status: string; canonical: boolean;
  /** The one resolver's verdict (ccd/coordid.py); absent from an older ccd. */
  state?: CoordinatorState["state"]; how?: string | null; candidates?: CoordinatorCandidate[];
}

export interface HealthShort {
  ok: boolean;
  herdr: Sources["herdr"] & { reconnects?: number };
  gh: { ok: boolean; projects: Record<string, SourceState> };
  seq: number;
  uptimeS: number;
  version: string;
  tasks?: { enabled: boolean; schemaVersion: number | null };
}

export interface State {
  seq: number;
  latestSeq: number;
  version: string;
  at: number;
  agents: Agent[];
  coordinators: Record<string, Coordinator>;
  projects: ProjectView[];
  projectsConfig: PublicProject[];
  needs: Need[];
  blocked: Blocked[];
  stale: { project: string; text: string }[];
  alerts: Alert[];
  host: Host;
  sources: Sources;
  totals: Record<string, number> & { tickets?: Record<string, number> };
  herdr_error: string | null;
  brief: string;
  workspaces?: Workspace[];
  worktrees?: Record<string, string[]>;
  health: HealthShort;
}

export interface CcdEvent {
  seq: number;
  at: number;
  source: string;
  kind: string;
  severity: string;
  project: string | null;
  agentId: string | null;
  ref: string | null;
  text: string;
  data: Record<string, unknown>;
}

export type WsMessage =
  | { type: "hello"; seq: number }
  | { type: "replay_done"; seq: number }
  | { type: "events_lost"; seq: number; reason?: string }
  | { type: "ping"; seq: number }
  | { type: "event"; event: CcdEvent };

// ---------- tickets ----------

export const STATUSES = ["INBOX", "PROPOSED", "RESEARCHING", "READY_TO_IMPLEMENT", "IN_PROGRESS", "IN_REVIEW",
  "READY_TO_MERGE", "VERIFYING", "DONE"] as const;
export const OFF_PIPELINE = ["BLOCKED", "DENIED", "CANCELLED"] as const;
export type TicketStatus = (typeof STATUSES)[number] | (typeof OFF_PIPELINE)[number];
export const PRIORITIES = ["URGENT", "HIGH", "MEDIUM", "LOW", "NO_PRIORITY"] as const;
export type Priority = (typeof PRIORITIES)[number];
export const ROLES = ["COORDINATOR", "PLANNER", "IMPLEMENTER", "REVIEWER", "VERIFIER"] as const;
export const FLAGS = ["needs_jay", "needs_legal", "needs_ui_review", "needs_deploy"] as const;
export type Flag = (typeof FLAGS)[number];

export interface TicketLink {
  provider: string; kind: string; ref: string; url: string | null; title: string | null;
  number: number | null; createdAt: number; createdBy: string;
}

export interface Ticket {
  id: number;
  key: string;
  project: string;
  number: number;
  title: string;
  description?: string;
  status: TicketStatus;
  priority: Priority;
  type: string | null;
  creator: string;
  assignee: string | null;
  agentRole: string | null;
  agentPaneId: string | null;
  agentSessionId: string | null;
  parent: string | null;
  branch: string | null;
  createdAt: number;
  updatedAt: number;
  startedAt: number | null;
  completedAt: number | null;
  dueAt: number | null;
  estimate: number | null;
  flags: Flag[];
  archived: boolean;
  labels: string[];
  links: TicketLink[];
  prNumber: number | null;
  prUrl: string | null;
  blockedBy: string[];
  blocks: string[];
  subtasks: { total: number; done: number };
  // Control room (ccd ≥ schema 4): the work facts lists need. Absent from an older ccd.
  gate?: PipelineGate | null;
  gateReason?: string | null;
  openQuestions?: number;
  deploy?: { env: string; requestedAt: number | null; approvedAt: number | null; result: string | null } | null;
  visibleStage?: VisibleStage;
}

export const VISIBLE_STAGES = ["Planning", "Implementing", "Reviewing", "UI Testing", "Verifying", "Ready to Merge",
  "Deploying", "Needs Jay", "Blocked", "Closed"] as const;
export type VisibleStage = (typeof VISIBLE_STAGES)[number];

export interface Question {
  id: number; batch: number; position: number; text: string; kind: "text" | "choice" | "yesno"; options: string[];
  askedAt: number; askedBy: string; answer: string | null; answeredAt: number | null; answeredBy: string | null;
  /** "stale": the task check — Claude thinks this task is no longer needed; Jay answers Cancel it / Keep it. */
  purpose?: "stale" | null;
}
export interface Evidence { id: number; at: number; actor: string; stage: string | null; kind: string; ref: string; note: string | null }
export interface Checkpoint {
  reason: string; branch: string; worktree: string; commit: string; dirty: string; changed: string[]; tests: string;
  decisions: string; blocker: string; remaining: string; at: number; by: string; frm: string | null; to: string;
}
export interface DeployState {
  env: "live" | "preview" | "dev"; what: string; verification: string; requestedAt: number; requestedBy: string;
  approvedAt: number | null; approvedBy?: string; result: "pass" | "fail" | null; evidence?: string; deployedAt?: number;
}
export interface TaskSession { state: "ready" | "multiple" | "none"; paneId: string | null; sessionId: string | null; status: string }
export interface AnswersResult { work: TicketWork; complete: boolean; delivered: boolean; reason: string | null; replanned?: boolean;
  /** A task-check answer: true when "Cancel it" cancelled the ticket, false when Jay kept it. */
  cancelled?: boolean }
export interface TaskCheckResult { ok: boolean; project: string; coordinator: string | null; openTasks?: number;
  /** With copy: the message itself, nothing sent (a project without a coordinator Claude). */
  text?: string }
export interface TaskRecord { key: string; taskMd: string; workflowMd: string; dir: string | null }

export interface TicketRef { key: string; title: string; status: TicketStatus }

export type PipelineStage = "PLAN" | "BUILD" | "REVIEW" | "MERGE" | "VERIFY" | "DONE";
export type PipelineGate = "plan" | "merge" | "ui" | "deploy" | "failure";
/** GET /api/tasks/{key}/work — the ticket's durable pipeline state (plans/TICKET-PIPELINE-V1.md). */
export interface TicketWork {
  key: string; status: TicketStatus; stage: PipelineStage | null;
  stages: { stage: PipelineStage; state: "done" | "active" | "blocked" | "todo" }[];
  plan: { summary?: string; requirements?: string[]; approach?: string; affected?: string[]; risk?: string; tests?: string[]; questions?: string[] };
  planState: "none" | "proposed" | "accepted";
  policy: { plan: "auto" | "owner"; planReasons: string[]; merge: string; ui: boolean; deploy: boolean };
  gate: PipelineGate | null; gateReason: string | null; confirmed: string[];
  branch: string | null; worktree: string | null; prs: string[];
  roles: Record<string, { model: string | null; session: string | null; at: number }>;
  review: { verdict: "APPROVE" | "REQUEST_CHANGES" | null; head: string | null; cycles: number; pr?: string | null };
  verification: { result: "pass" | "fail"; evidence: string; at: number; by: string } | null;
  merge: { pr: string; sha: string | null; at: number } | null;
  handoff: { done: string; decisions: string; next: string; blockers: string; at: number; by: string } | null;
  blocked: { stage: PipelineStage; reason: string; at: number; what?: string; why?: string; action?: string;
    impact?: string; technical?: string } | null;
  findings: { at: number; source: string; scope: "in" | "out"; category: string; summary: string; head: string | null }[];
  // Control room (schema 4); optional so an older ccd still renders.
  questions?: Question[];
  openQuestions?: number;
  evidence?: Evidence[];
  writer?: string | null;
  checkpoint?: Checkpoint | null;
  deploy?: DeployState | null;
  released?: { ptys: string[]; claude: string | null; at: number } | null;
  visibleStage?: VisibleStage;
  session?: TaskSession;
  project?: string;
  nudge?: { delivered: boolean; reason: string | null };
}
export interface TimelineEvent {
  id: number; at: number; actor: string; kind: string; field: string | null;
  from: string | null; to: string | null; trigger: string | null; data: Record<string, unknown>;
}

export interface TicketDetail extends Ticket {
  description: string;
  relations: { blocks: TicketRef[]; blocked_by: TicketRef[]; related: TicketRef[]; duplicates: TicketRef[];
    duplicated_by: TicketRef[] };
  subtaskList: { key: string; title: string; status: TicketStatus; assignee: string | null }[];
  comments: { id: number; author: string; body: string; at: number }[];
  timeline: TimelineEvent[];
}

export interface TaskProject { key: string; name: string; prefix: string; nextNumber: number;
  legacyPrefixes?: string[] }

/** One ticket's development trail. Every field is evidence, never a guess. */
export interface DevBranch {
  name: string; evidence: string; exists: boolean;
  commits: number | null; head: string | null; at: number | null; countOk: boolean;
}
export interface DevPr {
  number: number | null; state: "OPEN" | "DRAFT" | "MERGED" | "UNKNOWN"; url: string | null;
  title: string | null; branch: string | null; ci: "PASS" | "FAIL" | "PENDING" | "NONE";
  review: string; mergedAt: string | null; asOf: number | null;
}
export interface DevRow {
  key: string; project: string; title: string; status: TicketStatus; priority: Priority;
  assignee: string | null; flags: Flag[]; updatedAt: number;
  branch: DevBranch | null; prs: DevPr[]; pr: DevPr | null;
  commits: number | null;
  ci: DevPr["ci"] | null; review: string | null;
  merge: "MERGED" | "WAITING FOR JAY" | "BLOCKED" | null;
  verify: "PENDING" | "DONE" | null;
  deploy: null;
  // Recorded by pipeline steps only; never inferred from the assignee or text.
  roles?: Record<string, { model: string | null; at: number }>;
  pipelineReview?: { verdict: string | null; head: string | null } | null;
}
export interface Development { rows: DevRow[]; seq: number; gitAsOf: number | null; stages: string[];
  notes: string[] }

export interface TaskMeta {
  statuses: TicketStatus[]; offPipeline: TicketStatus[]; priorities: Priority[]; types: string[];
  roles: string[]; flags: Flag[]; relationKinds: string[]; schemaVersion: number;
}

export interface TaskList { tickets: Ticket[]; projects: TaskProject[]; meta: TaskMeta; seq: number }

export interface ImportPreview {
  mode: "preview"; applied: false; generatedAt: number; tookMs: number;
  summary: { wouldCreate: number; wouldUpdate: number; ambiguous: number; duplicates: number; skipped: number };
  sources: { project: string; kind: string; ref: string | null; count: number; error: string | null }[];
  wouldCreate: { proposedKey: string; project: string; title: string; status: string; priority: string;
    type: string | null; flags: string[]; keepsId: boolean; links: { provider: string; kind: string; ref: string }[];
    blockedBy: string[]; note: string; sources: { kind: string; ref: string }[] }[];
  wouldUpdate: { key: string; project: string; changes: { field: string; from: unknown; to: unknown }[];
    sources: { kind: string; ref: string }[] }[];
  ambiguous: { project: string; source: string; ref: string; title: string; reason: string; suggestion: string }[];
  duplicates: { project: string; key: string; sources: { kind: string; ref: string }[]; resolution: string }[];
  skipped: { project: string; source: string; ref: string; reason: string }[];
  notes: string[];
}

export interface Tail { agentId: string; name: string | null; lines: number; text: string; redactions: number;
  truncated: boolean }

// ---------- workspace ----------
export interface GithubIdentity { owner: string; repo: string; slug: string; url: string }
export interface WorkspaceProject {
  key: string; name: string; prefix: string; root: string | null; exists: boolean; branch: string | null;
  github: GithubIdentity | null;
  coordinator: { id: string | null; name: string | null; status: string | null; cwd: string | null } | null;
  /** From ccd's one resolver: ready, found (one unnamed Claude at the root: Adopt), multiple (pick one), none. */
  coordinatorState?: CoordinatorState;
}
export interface CoordinatorCandidate { paneId: string; sessionId: string; status: string }
export interface CoordinatorState { state: "ready" | "found" | "multiple" | "none"; how: string | null; candidates: CoordinatorCandidate[] }
export interface FileEntry {
  name: string; kind: "dir" | "file" | "other" | "outside" | "broken"; size: number | null; mtime: number | null;
  protected: boolean; link: boolean; git?: string | null;
}
export interface FileList { project: string; path: string; crumbs: string[]; entries: FileEntry[]; truncated: boolean; git: boolean }
export interface FileRead {
  project: string; path: string; size: number; mtime: number; mode: string;
  kind: "text" | "binary" | "large"; text: string | null; sha: string | null;
}
export interface SaveResult { project: string; path: string; sha: string; size: number; mtime: number }
export interface UploadResult { project: string; path: string; name: string; size: number; sha: string; renamed: boolean }
export interface Attachment {
  id: string; ownerKind: "ticket" | "project"; ownerKey: string; name: string; size: number; sha256: string;
  uploadedAt: number; uploadedBy: string;
}
export interface LauncherInfo { available: boolean; version?: string; sha256?: string; commit?: string; built_at?: string; size?: number }
export interface DevCommit { sha: string; short: string; message: string; author: string; at: number | null; url: string | null }
export interface DevCommits { key: string; branch: string | null; base: string; branchUrl: string | null; commits: DevCommit[]; error?: string }

// ---------- workstation ----------
export interface SearchMatch { path: string; line: number; text: string; ranges: [number, number][] }
export interface SearchResult { project: string; query: string; matches: SearchMatch[]; files: number; truncated: boolean }
export interface ScmFile { path: string; orig: string | null; code: string; status: string; protected: boolean }
export interface ScmStatus {
  project: string; clean: boolean;
  branch: { head: string | null; upstream: string | null; ahead: number; behind: number; oid: string | null };
  staged: ScmFile[]; unstaged: ScmFile[]; untracked: ScmFile[]; conflicts: ScmFile[];
}
export interface ScmDiff { project: string; path: string; staged: boolean; diff: string; truncated: boolean; binary: boolean;
  tooLarge?: number | null }  // bytes: above the server's limit, no diff is run
export interface PtySession { name: string; cwd: string; clients: number; createdAt: number; alive: boolean }

/** The night shift (ccd nightshift.py): the newest morning report and the supervisor's state per project. */
export interface NightReport { name: string; mtime: number; status: "working" | "complete" | null; text: string }
/** One ticket in the Go Live confirm box: `reason` is set only for merged tickets Jay should look at first. */
export interface GoLiveTicket { key: string; title: string; reason?: string }
export interface NightProject {
  /** Why Jay paused the project (no agent works on it), or null. */
  paused?: string | null;
  /** careful: research first, one task at a time, risky work stops at a plan. */
  mode?: "normal" | "careful";
  active: boolean; startedAt: number | null; endedAt: number | null; endReason: string | null; nudges: number | null;
  cutoffAt?: number | null; goLiveAt: number | null; goLive?: { approves: GoLiveTicket[]; warnings: GoLiveTicket[] }; coordinator: { name: string; state: string; status: string | null }; report: NightReport | null;
}
export interface NightShiftState { projects: Record<string, NightProject> }
export interface GoLiveResult {
  ok: boolean; project: string; coordinator: string; approved: string[]; skipped?: { key: string; reason: string }[]; errors?: { key: string; error: string }[];
}
