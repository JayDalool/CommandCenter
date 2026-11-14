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
  /** Messages (ccd/leadchat.py): lead messages Jay has not read. Absent when Messages is not configured. */
  chat?: { unread: number };
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
  /** A choice question: the index into options Claude recommends, and why (ccd pipeline.ask). */
  recommended?: number | null;
  why?: string | null;
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
  cancelled?: boolean;
  /** Who got the answers: the task's own session, the project's lead through Messages, or nobody. */
  deliveredTo?: "task" | "lead" | null }
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
/** Merge (ccd /api/jay/merge): per project, what Jay can merge now — reviewed head, PR open and green — in order. */
export interface MergeItem { key: string; title: string; pr: string; head: string; gate: string | null }
export interface MergeReady {
  projects: Record<string, { ready: MergeItem[]; skipped: { key: string; reason: string }[]; paused: string | null }>;
}
export interface MergeResult {
  ok: boolean; project: string; coordinator: string; merging: { key: string; pr: string; head: string }[];
  skipped: { key: string; reason: string }[]; errors?: { key: string; error: string }[];
}

/** UI test runs (ccd uitests.py): the latest run per project and Jay's decision on each finding. */
export interface UiFinding {
  id: string; severity: "showstopper" | "major" | "minor"; title: string; feature: string; steps: string[];
  expected: string; actual: string; evidence: string;
  decision: { decision: "fix" | "skip"; ticket: string | null; at: number } | null;
}
export interface UiRun {
  run: string; status: "working" | "complete" | null; report: string;
  summary: { features?: number; passed?: number; failed?: number }; findings: UiFinding[];
}
export interface UiTestsState {
  projects: Record<string, { paused: string | null; fixMode: "ask" | "auto"; runs: string[]; latest: UiRun | null }>;
}

/** Project Operating Profiles (ccd GET /api/profiles). `enforced` is what Command Center does today; `target` is
 *  Jay's agreed policy, NOT enforced (the Autonomy Engine reads it in shadow mode only). */
export type PolicyValue = string | number | boolean | string[] | { [k: string]: PolicyValue };
export interface PolicyProject {
  name: string; file: string; sha256: string | null; valid: boolean; errors: string[];
  drift: { field: string; profile: PolicyValue; registry: PolicyValue }[];
  mode: string | null; decisions: string[]; learning: string | null;
  enforced: Record<string, PolicyValue>; target: Record<string, Record<string, PolicyValue>>; capabilities: Record<string, boolean>;
}
export interface PolicyDecision {
  id: string; date: string; decided_by: string; projects: string[]; question: string; decision: string; rationale: string;
  rules: string[]; reconsider: string | null; supersedes: string | null; valid: boolean;
}
export interface PolicyState {
  fingerprint: string; problems: string[]; projects: Record<string, PolicyProject>; decisions: Record<string, PolicyDecision>;
}

/** The Autonomy Engine's shadow record (ccd GET /api/autonomy, decision D-008). The engine decides nothing: it records
 *  what the agreed target policy would have done next to what Command Center did. */
export type AutonomyOutcome = "auto" | "jay" | "refuse";
export interface AutonomyDisagreement {
  id: number; at: number; key: string | null; project: string; action: "plan" | "merge" | "deploy";
  observed: AutonomyOutcome; engine: AutonomyOutcome; rule: string; reasons: string[]; missing: string[];
}
export interface AutonomyState {
  mode: "shadow"; engine: number; available: boolean; policy?: string; total: number; agree: number; disagree: number;
  counts: Record<string, Record<string, { total: number; agree: number; pairs: Record<string, number> }>>;
  missing: Record<string, number>; disagreements: AutonomyDisagreement[];
}

/** Decision and Approval records (ccd GET /api/decisions, v2 Phase 1). A mirror of today's gates and answers. */
export interface DecisionRecord {
  id: number; ref: string | null; project: string; key: string | null; question: string; options: string[];
  decision: string; rationale: string; decidedBy: string; via: string | null; reconsider: string | null;
  decidedAt: number | null; supersedes: number | null; source: "policy" | "question"; sourceRef: string; sha256: string;
  current: boolean;
}
export type ApprovalState = "pending" | "approved" | "rejected" | "consumed" | "void";
export interface ApprovalRecord {
  id: number; project: string; key: string | null; subject: "plan" | "merge" | "ui" | "deploy" | "failure";
  subjectHash: string; action: string; state: ApprovalState; reason: string | null; requestedAt: number;
  requestedBy: string; expiresAt: number | null; overdue: boolean; decidedAt: number | null; decidedBy: string | null;
  via: string | null; consumedAt: number | null; voidedAt: number | null; voidReason: string | null;
}
export interface LedgerState {
  available: boolean; decisions: DecisionRecord[]; approvals: ApprovalRecord[]; counts: Partial<Record<ApprovalState, number>>;
}

/** Worker nodes (ccd GET /api/workers, v2 Phase 1). The model and enrolment only: nothing is scheduled on a node yet. */
export interface WorkerNode {
  id: string; kind: "server" | "laptop" | "gpu" | "cloud"; owner: string; status: "pending" | "online" | "offline" | "revoked";
  state: "pending" | "active" | "revoked"; capabilities: { os?: string; arch?: string; tools?: string[]; repos?: string[]; labels?: string[] };
  version: string | null; enrolledAt: number; enrolledBy: string; approvedAt: number | null; approvedBy: string | null;
  lastHeartbeat: number | null; revokedAt: number | null; fingerprint: string | null;
}
/** Needs You v2 (GET /api/inbox): what v2 knows about a queue item, keyed by `kind:project:ref`. Read-only. */
export interface InboxApproval { id: number; project: string; gate: string; subjectHash: string; requestedAt: number;
  expiresAt: number | null; overdue: boolean }
export interface InboxPrecedent { id: number; project: string; key: string | null; question: string; decision: string;
  decidedAt: number; decidedBy: string; reconsider: string | null }
export interface InboxExtra {
  approval?: InboxApproval;
  engine?: { engine: "auto" | "jay" | "refuse"; observed: "auto" | "jay" | "refuse"; rule: string; agree: boolean; at: number };
  precedents?: { questionId: number; question: string; precedents: InboxPrecedent[] }[];
}
export interface InboxState {
  available: boolean; error?: string; items: Record<string, InboxExtra>; orphans: (InboxApproval & { key: string })[];
  counts: { approvals?: number; overdue?: number; precedentHits?: number; orphans?: number };
}
export interface WorkersState {
  available: boolean; nodes: WorkerNode[]; onlineFor?: number;
  events: { id?: number; node: string; at: number; kind: string; actor: string; data: Record<string, unknown> }[];
}

export interface AuditEvent {
  id: number; at: number; actor: string; verified: boolean; via: "developer" | "token" | "none" | "system";
  tokenActor: string | null; method: string; path: string; status: number; project: string | null; ref: string | null;
  bodyKeys: string[]; summary: string; profileHash: string | null;
}
export interface AuditState {
  available: boolean; events: AuditEvent[];
  summary: { since?: number; total?: number; byVia?: Record<string, number>; unverifiedJay?: number; agentUnverified?: number;
    mismatch?: number; wouldRefuse?: number };
  chain: { ok?: boolean; checked?: number; brokenAt?: number | null; full?: boolean };
}
export interface ActorToken { id: number; actor: string; fingerprint: string; issuedAt: number; expiresAt: number;
  revokedAt: number | null; note: string; status: "active" | "expired" | "revoked" }
export interface ActorsState { available: boolean; tokens: ActorToken[]; header?: string }
export interface UsageRow { key: string; replies: number; input: number; output: number; cacheRead: number; cacheWrite: number;
  costUsd: number; unpriced: number }
export interface UsageState {
  available: boolean; days?: number; pricesAsOf?: string; note?: string;
  total?: Omit<UsageRow, "key">; byProject?: UsageRow[]; byModel?: UsageRow[]; byDay?: UsageRow[]; byTicket?: UsageRow[];
  bySource?: UsageRow[];
  budgets?: { project: string; monthlyUsd: number | null; monthlyTokens: number | null; spentUsd: number; spentTokens: number }[];
}
/** GET /api/onboarding/budgets (D-033 in shadow, ccd/budgets.py). 404 while the onboarding groundwork is off. */
export interface BudgetLine {
  scope: "company" | "project" | "agent"; key: string; period: "day" | "month";
  limitUsd: number | null; limitTokens: number | null; spentUsd: number; spentTokens: number;
  unpricedReplies: number; unpricedUsdAtFallback: number; assessedUsd: number; unattributedUsd?: number;
  alerts: number[]; source: "measured" | "reported"; state: "none" | "ok" | "alert" | "unknown" | "hold";
  holdReason: "limit" | "stale-meter" | null; pct: number | null; threshold: number | null; onCourseToHold: boolean;
}
export interface BudgetsState {
  mode: "shadow"; enforced: boolean; lines: BudgetLine[]; wouldHold: { scope: string; key: string }[];
  safetyKinds: string[]; meter: { lastReadAt: number | null; stale: boolean; staleAfterSeconds: number };
  prices: { asOf: string; ageDays: number; maxAgeDays: number }; dataAlerts: { kind: string; detail: string }[]; note?: string;
}

/** GET /api/notify: Slack and ntfy. Never a token or the ntfy URL, only whether each is configured. */
export interface NotifySettings {
  slack: boolean; ntfy: boolean; quietStart: string; quietEnd: string; summaryAt: string; timezone: string;
  replyScope: "answers" | "answers_low_risk";
}
export interface NotifyState {
  settings: NotifySettings;
  status: { slack: string; socket: string; ntfy: string; lastError: string | null; lastSentAt: number | null };
  configured: { slackTokens: boolean; slackTokensError: string | null; jayMemberId: boolean; ntfy: boolean };
  channels: Record<string, string>; clientProjects: string[]; slackGates: string[]; quietNow: boolean; held: number;
}

/** Messages (ccd/chat.py, ccd/leadchat.py): Jay's conversations with the CTO and each project lead. */
export interface ChatFile {
  id: string; conversation: string; messageId: number | null; side: "jay" | "lead"; name: string;
  kind: "image" | "pdf" | "markdown"; mime: string; size: number; sha256: string; uploadedAt: number; uploadedBy: string;
}
export interface ChatMessage {
  id: number; conversation: string; side: "jay" | "lead"; author: string; text: string; via: "app" | "slack" | "cli";
  ref: string | null; replyTo: number | null; at: number; seenAt: number | null; files: ChatFile[];
}
export interface ChatLead {
  name: string; state: "ready" | "none" | "found" | "multiple" | "unknown"; status: string | null;
  running: boolean; idle: boolean; paused: boolean;
}
export interface ChatConversation {
  id: string; name: string; kind: "cto" | "project"; lead: ChatLead; unread: number; waiting: number;
  last: { id: number; side: "jay" | "lead"; author: string; at: number; via: string; text: string; files: number } | null;
  nudges: { count: number; lastAt: number | null };
}
export interface ChatOverview {
  conversations: ChatConversation[]; canStart: boolean; unread: number;
  limits: { text: number; fileBytes: number; filesPerMessage: number };
}
export type ChatDelivery = "nudged" | "queued" | "lead-offline" | "lead-paused";
export interface ChatSendResult { ok: true; message: ChatMessage; delivery: ChatDelivery }
export interface ChatOverBudget { scope: string; key: string; period: string; limitUsd: number | null; assessedUsd: number; pct: number | null; holdReason: string | null }
export interface ChatStartResult { ok: boolean; started?: boolean; lead?: ChatLead; delivery?: ChatDelivery; needsApproval?: boolean; overBudget?: ChatOverBudget[]; error?: string }

/** Milestones, the briefing and project logos (ccd/hq.py). Two tracks per project: technical is engineering work,
 *  business is real-life work (contact the lawyer, send the email to the client). */
export type MilestoneTrack = "technical" | "business";
export type MilestoneState = "todo" | "doing" | "done";
export interface Milestone {
  id: string; title: string; state: MilestoneState; due: string | null; note: string | null; doneAt: number | null; by: string;
}
export interface ProjectMilestones { technical: Milestone[]; business: Milestone[]; revision: number }
export interface MilestonesView { projects: Record<string, ProjectMilestones> }
export interface MilestoneResult { milestone: Milestone; revision: number }

/** What happened in a window of time. needsYou and mainChecks are now, not in the window; spendUsd is null when the
 *  meter has no data (never a guessed $0). */
export interface BriefingCounts {
  merged: number; done: number; failedChecks: number; opened: number; questionsAsked: number; questionsAnswered: number;
  deploys: number; needsYou: number;
}
export interface BriefingHighlight { at: number; kind: string; text: string; ref: string | null }
export interface BriefingProject extends BriefingCounts {
  key: string; name: string; mainChecks: "passing" | "failing" | "unknown"; spendUsd: number | null; highlights: BriefingHighlight[];
}
export interface Briefing { since: number; until: number; totals: BriefingCounts; projects: BriefingProject[]; quiet: boolean }
/** A project's logo as ccd lists it (GET /api/projects/logos). The bytes are fetched apart and shown from a blob:. */
export interface ProjectLogo { mime: string; sha256: string; updatedAt: number }
/** A device holding a Developer session (GET /api/developer/devices), in epoch seconds. ccd never sends the session
 *  id: `id` only names the row. `kind`: typed token, SSH sign-in, or a remembered device. */
export interface DevDevice {
  id: string; label: string; kind: "plain" | "ssh" | "remember"; remembered: boolean;
  createdAt: number; lastUsedAt: number; expiresAt: number; current: boolean;
}
