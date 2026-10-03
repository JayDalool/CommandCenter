/* Command Center V2 — prototype core.
 *
 * Shared behaviour for all three design directions: data, routing, keyboard,
 * command palette, offline / loading / stale states, and default renderers.
 * A direction calls CC.start(variant) and overrides what makes it distinct
 * (shell, overview layout, status language). Renderers return HTML strings so
 * the whole UI can be exercised headlessly (see ../tests/render.test.js).
 *
 * Fixture data only. Nothing here talks to ccd, herdr or GitHub, and every
 * action ends in a "prototype — nothing sent" notice.
 */
(function () {
  "use strict";

  const TZ = "America/Chicago";
  const NAV = [
    ["overview", "Overview"], ["projects", "Projects"], ["agents", "Agents"], ["tasks", "Tasks"],
    ["prs", "Pull requests"], ["server", "Server"], ["activity", "Activity"], ["alerts", "Alerts"],
    ["settings", "Settings"],
  ];
  const STATE = {
    BLOCKED:   { short: "BLKD", label: "Blocked",   tone: "blocked",   shape: "square", rank: 0 },
    FAILED:    { short: "FAIL", label: "Failed",    tone: "failed",    shape: "cross",  rank: 1 },
    WORKING:   { short: "WORK", label: "Working",   tone: "working",   shape: "fill",   rank: 2 },
    REVIEW:    { short: "REVW", label: "Review",    tone: "review",    shape: "fill",   rank: 3 },
    VERIFYING: { short: "VRFY", label: "Verifying", tone: "verifying", shape: "fill",   rank: 4 },
    WAITING:   { short: "WAIT", label: "Waiting",   tone: "waiting",   shape: "half",   rank: 5 },
    UNKNOWN:   { short: "UNKN", label: "Unknown",   tone: "unknown",   shape: "dashed", rank: 6 },
    IDLE:      { short: "IDLE", label: "Idle",      tone: "idle",      shape: "ring",   rank: 7 },
    DONE:      { short: "DONE", label: "Done",      tone: "done",      shape: "check",  rank: 8 },
  };
  const ACTIVE = new Set(["WORKING", "REVIEW", "VERIFYING"]);
  const ATTENTION = new Set(["BLOCKED", "FAILED", "UNKNOWN"]);
  const CI = {
    pass: { sym: "✓", label: "passing", tone: "ok" }, fail: { sym: "✗", label: "failing", tone: "bad" },
    pending: { sym: "◌", label: "running", tone: "run" }, none: { sym: "—", label: "no checks", tone: "none" },
  };
  const REVIEW = { approved: "approved", changes: "changes requested", pending: "review pending", none: "—" };
  const MERGE = { clean: "clean", blocked: "blocked", conflicting: "conflicts", draft: "draft", unknown: "unknown" };
  const NEED_ORDER = { ANSWER: 0, MERGE: 1, REVIEW: 2, DO: 3 };
  const CATS = [["all", "All"], ["agents", "Agents"], ["tasks", "Tasks"], ["prs", "PRs"], ["ci", "CI"], ["jay", "Jay"], ["host", "Host"]];

  // ---------- helpers ----------

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const timeFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
  const timeSecFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const dateFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "2-digit", month: "short" });
  const hm = (ms) => timeFmt.format(ms);
  const hms = (ms) => timeSecFmt.format(ms);
  const day = (ms) => dateFmt.format(ms);
  function ago(ms, now) {
    const s = Math.max(0, Math.round((now - ms) / 1000));
    if (s < 60) return s + "s";
    const m = Math.floor(s / 60);
    if (m < 60) return m + "m";
    const h = Math.floor(m / 60);
    if (h < 48) return h + "h" + (h < 10 && m % 60 ? " " + (m % 60) + "m" : "");
    return Math.floor(h / 24) + "d";
  }
  const gib = (b) => (b / 1024 ** 3).toFixed(1);
  const gb = (b) => Math.round(b / 1e9);
  const pct = (a, b) => Math.round((a / b) * 100);
  const uptime = (s) => `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;

  // ---------- state ----------

  const CC = (window.CC = window.CC || {});
  const S = {
    screen: "overview", theme: "dark", offline: false, offlineAt: null, loading: true,
    expanded: new Set(["wE:p7"]), sel: {}, tasksView: "table", tasksProject: "all",
    agentsFilter: "all", activityFilter: "all", alertsTab: "active",
    palette: { open: false, q: "", i: 0 }, help: false, t0: Date.now(), retry: 8,
    fresh: new Set(), scriptI: 0,
  };
  let F, V, D;

  function vnow() { return S.offline ? S.offlineAt : F.now + (Date.now() - S.t0); }
  const proj = (k) => D.projects.find((p) => p.key === k) || { key: k, name: k || "—" };
  const pname = (k) => (k ? proj(k).name : "host");
  const agentBy = (id) => D.agents.find((a) => a.id === id);
  const sortAgents = (list) => list.slice().sort((a, b) =>
    STATE[a.state].rank - STATE[b.state].rank || a.project.localeCompare(b.project) || a.role.localeCompare(b.role));
  function counts() {
    return {
      needs: D.needs.length,
      working: D.agents.filter((a) => ACTIVE.has(a.state)).length,
      blocked: D.agents.filter((a) => a.state === "BLOCKED").length,
      prs: D.prs.length,
      alerts: D.alerts.filter((a) => !a.ack).length,
      agents: D.agents.length,
      tasks: D.tasks.filter((t) => t.stage !== "DONE").length,
    };
  }
  function health() {
    const h = D.host;
    const mem = pct(h.memUsed, h.memTotal), disk = pct(h.diskUsed, h.diskTotal), swap = pct(h.swapUsed, h.swapTotal);
    const issues = [];
    if (disk >= 78) issues.push(`disk ${disk}%`);
    if (swap >= 60) issues.push(`swap ${swap}%`);
    const down = h.containers.filter((c) => c.state !== "running" && !/months? ago/.test(c.status));
    if (down.length) issues.push(`${down.length} container down`);
    return { ok: !issues.length, issues, mem, disk, swap, running: h.containers.filter((c) => c.state === "running").length, total: h.containers.length };
  }

  // ---------- default renderers (a variant may replace any of these) ----------

  const R = {};

  R.status = (state) => {
    const m = STATE[state];
    return `<span class="st tone-${m.tone}" data-state="${state}"><i class="glyph" data-shape="${m.shape}" aria-hidden="true"></i><span class="st-label">${m.label.toUpperCase()}</span></span>`;
  };
  R.glyph = (state) => {
    const m = STATE[state];
    return `<span class="st st-glyph tone-${m.tone}" title="${m.label}"><i class="glyph" data-shape="${m.shape}" aria-hidden="true"></i><span class="sr">${m.label}</span></span>`;
  };
  R.ci = (ci) => {
    const c = CI[ci] || CI.none;
    return `<span class="ci ci-${c.tone}"><span class="ci-sym" aria-hidden="true">${c.sym}</span>${c.label}</span>`;
  };
  R.needTag = (kind) => `<span class="need need-${kind.toLowerCase()}">${kind}</span>`;
  R.proj = (k) => `<span class="pj pj-${esc(k || "host")}"><i class="pj-mark" aria-hidden="true"></i>${esc(pname(k))}</span>`;
  R.mono = (s, cls = "") => `<span class="mono ${cls}">${esc(s)}</span>`;
  R.agoCell = (ms) => `<span class="mono num" data-ago="${ms}">${ago(ms, vnow())}</span>`;
  R.pr = (n) => (n ? `<a class="mono link" href="#prs" data-act="goto" data-screen="prs" data-key="pr:${n}">#${n}</a>` : `<span class="nil">—</span>`);

  R.section = (title, o = {}) => `
    <div class="sec-head">
      <h2 class="sec-title">${esc(title)}${o.count != null ? ` <span class="sec-count num">${o.count}</span>` : ""}</h2>
      ${o.meta ? `<div class="sec-meta">${o.meta}</div>` : ""}
      ${o.tools ? `<div class="sec-tools">${o.tools}</div>` : ""}
    </div>`;

  R.empty = (title, body, hint) => `
    <div class="empty" role="status">
      <div class="empty-title">${esc(title)}</div>
      <div class="empty-body">${body}</div>
      ${hint ? `<div class="empty-hint">${hint}</div>` : ""}
    </div>`;

  R.skeleton = (rows = 6, cols = 6) => `
    <div class="skeleton" aria-busy="true" aria-label="Loading">
      ${Array.from({ length: rows }, (_, r) => `<div class="sk-row">${Array.from({ length: cols }, (_, c) =>
        `<span class="sk-bar" style="width:${[46, 70, 58, 82, 40, 64, 52][(r + c) % 7]}%"></span>`).join("")}</div>`).join("")}
    </div>`;

  R.seg = (name, opts, current, keyHint) => `
    <div class="seg" role="tablist" aria-label="${esc(name)}">
      ${opts.map(([v, l, n]) => `<button class="seg-btn${v === current ? " is-on" : ""}" role="tab" aria-selected="${v === current}"
        data-act="seg" data-seg="${name}" data-val="${v}">${esc(l)}${n != null ? ` <span class="num seg-n">${n}</span>` : ""}</button>`).join("")}
      ${keyHint ? `<span class="kbd-hint">${keyHint}</span>` : ""}
    </div>`;

  R.meter = (label, value, frac, sub, warn) => `
    <div class="meter${warn ? " is-warn" : ""}">
      <div class="meter-top"><span class="meter-label">${label}</span><span class="meter-val num">${value}</span></div>
      ${frac == null ? '<div class="meter-bar is-none" aria-hidden="true"></div>' : `<div class="meter-bar" role="meter" aria-label="${esc(label)}" aria-valuenow="${Math.round(frac * 100)}" aria-valuemin="0" aria-valuemax="100"><i style="width:${Math.min(100, frac * 100).toFixed(1)}%"></i></div>`}
      ${sub ? `<div class="meter-sub num">${sub}</div>` : ""}
    </div>`;

  R.spark = (vals, o = {}) => {
    const w = o.w || 240, h = o.h || 44, max = o.max || Math.max(...vals) * 1.15, min = o.min != null ? o.min : 0;
    const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - ((v - min) / (max - min)) * (h - 4) - 2).toFixed(1)}`);
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" width="100%" height="${h}" role="img" aria-label="${esc(o.label || "trend")}">
      <line class="spark-base" x1="0" y1="${h - 0.5}" x2="${w}" y2="${h - 0.5}"/>
      <polyline class="spark-line" points="${pts.join(" ")}"/>
      <circle class="spark-now" cx="${pts[pts.length - 1].split(",")[0]}" cy="${pts[pts.length - 1].split(",")[1]}" r="2.2"/>
    </svg>`;
  };

  // --- summary: the five questions, answered in one strip ---
  R.answers = () => {
    const c = counts(), h = health(), last = D.activity[0];
    return [
      { q: "Server", a: h.ok ? "Healthy" : h.issues.join(", "), tone: h.ok ? "ok" : "warn", key: "server" },
      { q: "Working", a: `${c.working} agent${c.working === 1 ? "" : "s"}`, tone: "working", key: "agents" },
      { q: "Blocked", a: c.blocked ? `${c.blocked} waiting for you` : "Nothing blocked", tone: c.blocked ? "blocked" : "ok", key: "agents" },
      { q: "Needs Jay", a: `${c.needs} item${c.needs === 1 ? "" : "s"}`, tone: c.needs ? "jay" : "ok", key: "overview" },
      { q: "Last change", a: `${hm(last.at)} ${last.text}`, tone: "plain", key: "activity" },
    ];
  };

  R.needsList = (o = {}) => {
    const list = D.needs.slice().sort((a, b) => NEED_ORDER[a.kind] - NEED_ORDER[b.kind] || b.since - a.since);
    if (!list.length) return R.empty("Nothing needs you", "No merges, answers, approvals or owner-only tasks are waiting.", "New items appear here the moment ccd sees them.");
    return `<table class="tbl tbl-needs">
      <thead class="${o.headless ? "sr" : ""}"><tr><th>Do</th><th>Project</th><th>Ref</th><th>What</th><th class="c-opt">Where</th><th class="r">Waiting</th></tr></thead>
      <tbody>${list.map((n) => {
        const key = n.target.agent ? n.target.agent : n.target.pr ? "pr:" + n.target.pr : "task:" + n.target.task;
        const screen = n.target.agent ? "agents" : n.target.pr ? "prs" : "tasks";
        return `<tr class="row is-link" tabindex="0" data-row data-key="need:${esc(n.ref)}:${n.project}" data-act="goto" data-screen="${screen}" data-target="${esc(key)}">
          <td class="c-need">${R.needTag(n.kind)}</td><td>${R.proj(n.project)}</td><td>${R.mono(n.ref)}</td>
          <td class="c-text">${esc(n.text)}</td><td class="c-opt c-where">${esc(n.where)}</td><td class="r">${R.agoCell(n.since)}</td></tr>`;
      }).join("")}</tbody></table>`;
  };

  R.agentsCompact = () => {
    const list = sortAgents(D.agents);
    return `<table class="tbl tbl-agents tbl-compact">
      <thead><tr><th class="c-st"><span class="sr">Status</span></th><th>Project</th><th>Role</th><th>State</th><th>Task</th><th class="c-opt">Last event</th><th>PR</th><th class="r">Time</th></tr></thead>
      <tbody>${list.map((a) => `<tr class="row is-link${a.state === "BLOCKED" ? " is-attn" : ""}" tabindex="0" data-row data-key="${a.id}"
          data-act="goto" data-screen="agents" data-target="${a.id}">
        <td class="c-st">${R.glyph(a.state)}</td><td>${R.proj(a.project)}</td><td class="c-role">${esc(a.role)}</td>
        <td>${R.status(a.state)}</td><td>${a.taskId ? R.mono(a.taskId) : '<span class="nil">—</span>'}</td>
        <td class="c-opt c-text muted">${esc(a.lastEvent)}</td><td>${R.pr(a.pr)}</td><td class="r">${R.agoCell(a.startedAt)}</td></tr>`).join("")}
      </tbody></table>`;
  };

  R.agentDetail = (a) => {
    const b = a.blocked;
    const events = a.events.map(([t, txt]) => `<li><span class="mono num">${hm(t)}</span><span>${esc(txt)}</span></li>`).join("");
    const answer = b ? `
      <div class="ad-block">
        <div class="ad-label">${b.kind === "permission" ? "Permission prompt" : "Question"} · waiting ${R.agoCell(b.since)}</div>
        <pre class="ad-question">${esc(b.question)}</pre>
        <div class="ad-options">${b.options.map((o) => `<button class="btn btn-quiet" data-act="fill" data-for="${a.id}" data-val="${esc(o.split(/\s{2,}/)[0].trim())}">${esc(o)}</button>`).join("")}</div>
        <div class="ad-answer">
          <label class="sr" for="ans-${a.id}">Answer</label>
          <input id="ans-${a.id}" class="input mono" data-key="ans:${a.id}" placeholder="Type an answer — Enter sends" autocomplete="off" spellcheck="false">
          <button class="btn btn-primary" data-act="answer" data-id="${a.id}">Send answer</button>
        </div>
        <div class="ad-note">Live: typed into pane ${esc(a.id)} and Enter pressed — only while the agent is blocked. Prototype: nothing is sent.</div>
      </div>` : "";
    return `<div class="ad">
      ${answer}
      <dl class="ad-grid">
        <div><dt>Pane</dt><dd class="mono">${esc(a.id)} <span class="muted">· ${esc(a.workspaceId)}</span></dd></div>
        <div><dt>Agent name</dt><dd class="mono">${esc(a.name)}</dd></div>
        <div><dt>Session</dt><dd class="mono">${esc(a.sessionId)}…</dd></div>
        <div><dt>Model</dt><dd>${esc(a.model)}</dd></div>
        <div class="ad-wide"><dt>Working directory</dt><dd class="mono">${esc(a.cwd)}</dd></div>
        <div><dt>Branch</dt><dd class="mono">${a.branch ? esc(a.branch) : "—"}</dd></div>
        <div><dt>PR</dt><dd>${R.pr(a.pr)}</dd></div>
        <div><dt>CI</dt><dd>${a.ci ? R.ci(a.ci) : "—"}</dd></div>
        <div><dt>Reviewer</dt><dd>${a.reviewer ? esc(a.reviewer) : "—"}</dd></div>
        <div><dt>Context</dt><dd class="muted" title="Token meter deferred">—</dd></div>
        <div><dt>Started</dt><dd class="mono num">${hm(a.startedAt)}</dd></div>
      </dl>
      <div class="ad-events"><div class="ad-label">Last events</div><ul>${events}</ul></div>
      <div class="ad-actions">
        <button class="btn" data-act="focus" data-id="${a.id}">Focus pane <kbd>F</kbd></button>
        ${b ? `<button class="btn" data-act="focusAnswer" data-id="${a.id}">Answer <kbd>A</kbd></button>` : ""}
        <button class="btn btn-quiet" data-act="copy" data-val="${esc(a.id)}">Copy pane id</button>
        ${a.pr ? `<button class="btn btn-quiet" data-act="goto" data-screen="prs" data-target="pr:${a.pr}">Open PR #${a.pr}</button>` : ""}
      </div>
    </div>`;
  };

  R.agentsTable = () => {
    const f = S.agentsFilter;
    let list = sortAgents(D.agents);
    if (f === "attention") list = list.filter((a) => ATTENTION.has(a.state));
    if (f === "active") list = list.filter((a) => ACTIVE.has(a.state) || a.state === "WAITING");
    if (f === "idle") list = list.filter((a) => ["IDLE", "DONE"].includes(a.state));
    if (!list.length) return R.empty("No agents match", "Nothing in this filter right now.", "Press 0 to show all agents.");
    return `<table class="tbl tbl-agents">
      <thead><tr><th class="c-st"><span class="sr">Status</span></th><th>Project</th><th>Role</th><th class="c-opt">Model</th><th>State</th>
        <th>Task</th><th class="c-opt2">Branch</th><th>PR</th><th class="r">Elapsed</th><th class="c-chev"><span class="sr">Expand</span></th></tr></thead>
      <tbody>${list.map((a) => {
        const open = S.expanded.has(a.id);
        return `<tr class="row is-expandable${open ? " is-open" : ""}${a.state === "BLOCKED" ? " is-attn" : ""}" tabindex="0" data-row
            data-key="${a.id}" data-act="toggle" data-id="${a.id}" aria-expanded="${open}">
          <td class="c-st">${R.glyph(a.state)}</td><td>${R.proj(a.project)}</td><td class="c-role">${esc(a.role)}</td>
          <td class="c-opt">${esc(a.model)}</td><td>${R.status(a.state)}</td>
          <td class="c-task">${a.taskId ? `${R.mono(a.taskId)} <span class="muted c-tasktitle">${esc(a.task)}</span>` : '<span class="nil">—</span>'}</td>
          <td class="c-opt2">${a.branch ? R.mono(a.branch, "trunc") : '<span class="nil">—</span>'}</td>
          <td>${R.pr(a.pr)}</td><td class="r">${R.agoCell(a.startedAt)}</td><td class="c-chev"><i class="chev" aria-hidden="true"></i></td></tr>
          ${open ? `<tr class="row-detail"><td colspan="10">${R.agentDetail(a)}</td></tr>` : ""}`;
      }).join("")}</tbody></table>`;
  };

  R.pipelineStrip = () => {
    const by = Object.fromEntries(F.stages.map((s) => [s, D.tasks.filter((t) => t.stage === s)]));
    return `<ol class="pipe-strip">${F.stages.map((s) => `
      <li class="pipe-cell${s === "MERGE" && by[s].length ? " is-jay" : ""}">
        <a href="#tasks" data-act="goto" data-screen="tasks" data-pipeline="1" class="pipe-link">
          <span class="pipe-stage">${s}</span><span class="pipe-n num">${by[s].length}</span>
          <span class="pipe-ids">${by[s].slice(0, 3).map((t) => `<span class="mono pj-txt pj-${t.project}">${esc(t.id)}</span>`).join("") || '<span class="nil">—</span>'}${by[s].length > 3 ? `<span class="muted">+${by[s].length - 3}</span>` : ""}</span>
        </a></li>`).join("")}</ol>`;
  };

  R.activityList = (o = {}) => {
    const f = o.filter || "all";
    let list = D.activity.filter((e) => f === "all" || e.cat === f);
    if (o.limit) list = list.slice(0, o.limit);
    if (!list.length) return R.empty("Quiet", `No ${f === "all" ? "" : f + " "}events in the retained log.`, "ccd keeps 30 days of meaningful events — no token or tool-call noise.");
    let lastDay = "";
    return `<ol class="feed">${list.map((e) => {
      const d = day(e.at);
      const sep = o.days && d !== lastDay ? `<li class="feed-day">${esc(d)}</li>` : "";
      lastDay = d;
      return `${sep}<li class="feed-row${S.fresh.has(e.seq) ? " is-new" : ""}" data-key="ev:${e.seq}">
        <span class="mono num feed-time">${hm(e.at)}</span>
        <span class="cat cat-${e.cat}">${e.cat.toUpperCase()}</span>
        <span class="feed-proj">${e.project ? R.proj(e.project) : '<span class="muted">host</span>'}</span>
        <span class="feed-text">${esc(e.text)}</span>
        <span class="mono muted feed-ref">${esc(e.ref || "")}</span></li>`;
    }).join("")}</ol>`;
  };

  R.serverCompact = () => {
    const h = D.host, hh = health();
    return `<div class="srv-compact">
      ${R.meter("CPU", `${h.cpuPct.toFixed(1)}%`, h.cpuPct / 100, `load ${h.load.map((l) => l.toFixed(2)).join(" ")}`)}
      ${R.meter("RAM", `${gib(h.memUsed)} / ${gib(h.memTotal)} GiB`, h.memUsed / h.memTotal, `${hh.mem}% used`)}
      ${R.meter("Swap", `${gib(h.swapUsed)} / ${gib(h.swapTotal)} GiB`, h.swapUsed / h.swapTotal, `${hh.swap}%`, hh.swap >= 60)}
      ${R.meter("Disk", `${gb(h.diskUsed)} / ${gb(h.diskTotal)} GB`, h.diskUsed / h.diskTotal, `${hh.disk}%`, hh.disk >= 78)}
      <div class="srv-facts">
        <div><span class="k">Uptime</span><span class="v mono num">${uptime(h.uptimeS)}</span></div>
        <div><span class="k">Containers</span><span class="v mono num">${hh.running}/${hh.total}</span></div>
        <div><span class="k">OOM 24h</span><span class="v mono num">0</span></div>
      </div>
    </div>`;
  };

  R.railServer = () => {
    const h = D.host, hh = health();
    const bar = (l, f, v) => `<div class="rs-row"><span class="rs-k">${l}</span><span class="rs-bar"><i style="width:${(f * 100).toFixed(0)}%"></i></span><span class="rs-v num">${v}</span></div>`;
    return `<div class="rail-server${S.offline ? " is-stale" : ""}">
      <div class="rs-host"><span class="rs-name mono">${esc(h.hostname)}</span>
        <span class="rs-state ${S.offline ? "is-off" : "is-on"}">${S.offline ? "○ unreachable" : "● online"}</span></div>
      ${bar("CPU", h.cpuPct / 100, h.cpuPct.toFixed(0) + "%")}
      ${bar("RAM", h.memUsed / h.memTotal, hh.mem + "%")}
      ${bar("DSK", h.diskUsed / h.diskTotal, hh.disk + "%")}
    </div>`;
  };

  R.nav = () => {
    const c = counts();
    const n = { agents: c.agents, tasks: c.tasks, prs: c.prs, alerts: c.alerts, overview: c.needs };
    return `<ul class="nav-list">${NAV.map(([k, label], i) => `
      <li><a class="nav-item${S.screen === k ? " is-on" : ""}" href="#${k}" data-act="nav" data-screen="${k}" ${S.screen === k ? 'aria-current="page"' : ""}>
        <span class="nav-key mono" aria-hidden="true">${i + 1}</span><span class="nav-label">${label}</span>
        ${n[k] ? `<span class="nav-n num${k === "overview" ? " is-jay" : k === "alerts" ? " is-alert" : ""}" title="${k === "overview" ? "needs Jay" : ""}">${n[k]}</span>` : ""}
      </a></li>`).join("")}</ul>`;
  };

  R.conn = () => S.loading
    ? `<span class="conn is-connecting"><i aria-hidden="true">◌</i>CONNECTING</span>`
    : S.offline
      ? `<span class="conn is-off"><i aria-hidden="true">○</i>OFFLINE <span class="conn-sub mono">last update ${hms(S.offlineAt)}</span></span>`
      : `<span class="conn is-live"><i aria-hidden="true">●</i>LIVE</span>`;

  R.top = () => {
    const c = counts();
    return `<div class="top-inner">
      <div class="top-title">COMMAND CENTER</div>
      ${R.conn()}
      <time class="top-clock mono num" id="cc-clock">${hms(vnow())}</time>
      <div class="top-stats">
        <a class="ts ts-jay" href="#overview" data-act="nav" data-screen="overview"><span class="ts-n num">${c.needs}</span><span class="ts-l">needs Jay</span></a>
        <a class="ts" href="#agents" data-act="nav" data-screen="agents"><span class="ts-n num">${c.working}</span><span class="ts-l">working</span></a>
        <a class="ts" href="#prs" data-act="nav" data-screen="prs"><span class="ts-n num">${c.prs}</span><span class="ts-l">open PRs</span></a>
      </div>
      <div class="top-tools">
        <button class="btn btn-quiet btn-sm" data-act="theme" title="Toggle light/dark (D)">${S.theme === "dark" ? "Light" : "Dark"}</button>
        <button class="kbd-btn" data-act="palette" title="Command palette">Ctrl K</button>
      </div>
    </div>`;
  };

  R.banner = () => S.offline ? `<div class="banner" role="status">
      <strong>Connection to ccd lost.</strong> Showing the last known state from <span class="mono num">${hms(S.offlineAt)}</span>.
      Agents keep running on jay-server. Reconnecting in <span class="mono num" id="cc-retry">${S.retry}s</span>…
      <button class="btn btn-quiet btn-sm" data-act="offline">Simulate reconnect</button></div>` : "";

  // --- screens ---

  const SCREENS = {};

  SCREENS.overview = () => `
    <div class="ov">
      <section class="ov-answers">${R.answersStrip()}</section>
      <section class="ov-needs">${R.section("Needs Jay", { count: D.needs.length })}${R.needsList()}</section>
      <section class="ov-server">${R.section("Server", { meta: `<span class="mono">jay-server</span> · ${R.agoMeta(D.host.asOf)}`, tools: R.goto("server", "Details") })}${R.serverCompact()}</section>
      <section class="ov-agents">${R.section("Agents", { count: D.agents.length, meta: `${counts().working} working · ${counts().blocked} blocked`, tools: R.goto("agents", "All agents") })}${R.agentsCompact()}</section>
      <section class="ov-pipe">${R.section("Pipeline", { count: D.tasks.length, tools: R.goto("tasks", "Tasks") })}${R.pipelineStrip()}</section>
      <section class="ov-activity">${R.section("Recent activity", { tools: R.goto("activity", "All activity") })}${R.activityList({ limit: 8 })}</section>
    </div>`;

  R.answersStrip = () => `<ul class="answers">${R.answers().map((x) => `
      <li class="ans tone-${x.tone}"><a href="#${x.key}" data-act="nav" data-screen="${x.key}">
        <span class="ans-q">${x.q}</span><span class="ans-a">${esc(x.a)}</span></a></li>`).join("")}</ul>`;
  R.goto = (screen, label) => `<a class="goto" href="#${screen}" data-act="nav" data-screen="${screen}">${label} <span aria-hidden="true">→</span></a>`;
  R.agoMeta = (ms) => `<span class="${S.offline ? "stale" : ""}">as of <span class="mono num">${hm(ms)}</span></span>`;

  SCREENS.agents = () => {
    const all = D.agents;
    const n = (fn) => all.filter(fn).length;
    return `<div class="screen-agents">
      ${R.section("Agents", { count: all.length, meta: `herdr · snapshot ${R.agoCell(D.sources.herdr.lastSnapshotAt)} ago · events live` })}
      <div class="toolbar">${R.seg("agents", [["all", "All", all.length], ["attention", "Needs attention", n((a) => ATTENTION.has(a.state))],
        ["active", "Active", n((a) => ACTIVE.has(a.state) || a.state === "WAITING")], ["idle", "Idle / done", n((a) => ["IDLE", "DONE"].includes(a.state))]],
        S.agentsFilter, "j k move · Enter expand · F focus · A answer")}</div>
      ${R.agentsTable()}
      <p class="foot-note">State joins herdr's five statuses with GitHub and the task index; nothing is guessed — <span class="mono">UNKNOWN</span> means herdr could not classify the pane.</p>
    </div>`;
  };

  R.tasksTable = (list) => {
    if (!list.length) return R.empty("No tasks for this project", "Nothing is proposed, in flight or recently done.", "New issues land in PROPOSED — capture one with <span class=\"mono\">board new &lt;project&gt; …</span>");
    return `<table class="tbl tbl-tasks">
      <thead><tr><th>Task</th><th>Project</th><th>Title</th><th>Stage</th><th class="c-opt">Flags</th><th>PR</th><th class="c-opt">Agent</th><th class="r">Updated</th></tr></thead>
      <tbody>${list.map((t) => {
        const ag = t.agent && agentBy(t.agent);
        return `<tr class="row" tabindex="0" data-row data-key="task:${esc(t.id)}">
          <td>${R.mono(t.id)}</td><td>${R.proj(t.project)}</td><td class="c-text">${esc(t.title)}</td>
          <td><span class="stage stage-${t.stage.replace(/\s/g, "-").toLowerCase()}">${t.stage}</span></td>
          <td class="c-opt">${t.flags.map((f) => `<span class="flag${f === "needs:jay" || f === "owner-only" ? " is-jay" : ""}">${esc(f)}</span>`).join(" ") || '<span class="nil">—</span>'}</td>
          <td>${R.pr(t.pr)}</td><td class="c-opt">${ag ? `${R.glyph(ag.state)} <span class="mono">${esc(ag.name)}</span>` : '<span class="nil">—</span>'}</td>
          <td class="r">${R.agoCell(t.updatedAt)}</td></tr>`;
      }).join("")}</tbody></table>`;
  };

  R.pipelineBoard = (list) => `<div class="board" role="list">${F.stages.map((s) => {
    const items = list.filter((t) => t.stage === s);
    return `<section class="col${s === "MERGE" && items.length ? " is-jay" : ""}" role="listitem" aria-label="${s}">
      <header class="col-head"><span class="col-name">${s}</span><span class="col-n num">${items.length}</span></header>
      ${items.length ? `<ul class="col-list">${items.map((t) => {
        const ag = t.agent && agentBy(t.agent);
        return `<li class="card-row" tabindex="0" data-row data-key="task:${esc(t.id)}">
          <div class="cr-top">${R.mono(t.id)}${ag ? R.glyph(ag.state) : ""}${t.pr ? `<span class="mono muted cr-pr">#${t.pr}</span>` : ""}</div>
          <div class="cr-title">${esc(t.title)}</div>
          <div class="cr-meta"><span class="pj-txt pj-${t.project}">${esc(pname(t.project))}</span>${t.flags.length ? ` · <span class="${t.flags.some((f) => f === "needs:jay" || f === "owner-only") ? "jay-txt" : ""}">${esc(t.flags[0])}</span>` : ""}</div>
        </li>`;
      }).join("")}</ul>` : `<div class="col-empty">Nothing ${s === "DONE" ? "finished in 48 h" : "in " + s.toLowerCase()}</div>`}
    </section>`;
  }).join("")}</div>`;

  SCREENS.tasks = () => {
    const list = D.tasks.filter((t) => S.tasksProject === "all" || t.project === S.tasksProject);
    const projOpts = [["all", "All"], ...D.projects.map((p) => [p.key, p.name])];
    return `<div class="screen-tasks">
      ${R.section("Tasks", { count: list.length, meta: `GitHub labels, then <span class="mono">docs/tasks/INDEX.md</span> · ${R.agoMeta(D.sources.github.asOf)}` })}
      <div class="toolbar">
        ${R.seg("tasksView", [["table", "Table"], ["pipeline", "Pipeline"]], S.tasksView, "T toggles")}
        ${R.seg("tasksProject", projOpts, S.tasksProject)}
      </div>
      ${S.tasksView === "table" ? R.tasksTable(list) : R.pipelineBoard(list)}
    </div>`;
  };

  SCREENS.prs = () => {
    const list = D.prs.slice().sort((a, b) => (b.jay ? 1 : 0) - (a.jay ? 1 : 0) || b.updatedAt - a.updatedAt);
    const src = D.sources.github;
    return `<div class="screen-prs">
      ${R.section("Pull requests", { count: list.length, meta: `GitHub · as of <span class="mono num">${hms(src.asOf)}</span>${S.offline ? ' · <span class="stale">stale</span>' : ` · next poll in <span class="mono num">${src.nextIn}s</span>`}` })}
      <table class="tbl tbl-prs">
        <thead><tr><th>PR</th><th>Project</th><th>Title</th><th class="c-opt">Head</th><th>CI</th><th>Review</th><th>Merge</th><th class="r c-opt">Age</th><th>Jay action</th></tr></thead>
        <tbody>${list.map((p) => `<tr class="row${p.jay ? " is-jayrow" : ""}" tabindex="0" data-row data-key="pr:${p.number}">
          <td>${R.mono("#" + p.number, "strong")}</td><td>${R.proj(p.project)}</td>
          <td class="c-text">${p.draft ? '<span class="flag">draft</span> ' : ""}${esc(p.title)}</td>
          <td class="c-opt">${R.mono(p.head, "trunc")} ${R.mono(p.sha, "muted")}</td>
          <td>${R.ci(p.ci)}</td><td class="rv rv-${p.review}">${REVIEW[p.review]}</td>
          <td class="mg mg-${p.mergeable}">${MERGE[p.mergeable]}</td><td class="r c-opt">${R.agoCell(p.updatedAt)}</td>
          <td class="c-jay">${p.jay ? `${R.needTag(p.jay)}<span class="jay-where">${p.jay === "MERGE" ? "in project pane" : "agent waiting"}</span>` : '<span class="nil">—</span>'}</td></tr>`).join("")}
        </tbody></table>
      <p class="foot-note">There is no merge button. A <span class="mono">MERGE</span> flag means Jay merges in the project's own pane — the API has no merge endpoint.</p>
    </div>`;
  };

  SCREENS.server = () => {
    const h = D.host, hh = health();
    const cpu = h.samples.map((s) => s.cpu), mem = h.samples.map((s) => s.mem);
    const wtWarn = D.projects.filter((p) => p.worktrees > p.worktreeLimit);
    return `<div class="screen-server">
      ${R.section("Server", { meta: `<span class="mono">${esc(h.hostname)}</span> · ${esc(h.os)} · ${h.cpus} cores · ${R.agoMeta(h.asOf)}` })}
      <div class="vitals">
        ${R.meter("CPU", `${h.cpuPct.toFixed(1)}%`, h.cpuPct / 100, `${h.cpus} cores`)}
        ${R.meter("Load", h.load.map((l) => l.toFixed(2)).join("  "), h.load[0] / h.cpus, "1 · 5 · 15 min")}
        ${R.meter("RAM", `${gib(h.memUsed)} / ${gib(h.memTotal)} GiB`, h.memUsed / h.memTotal, `${hh.mem}% used`)}
        ${R.meter("Swap", `${gib(h.swapUsed)} / ${gib(h.swapTotal)} GiB`, h.swapUsed / h.swapTotal, `${hh.swap}% · warn at 60%`, hh.swap >= 60)}
        ${R.meter("Disk /", `${gb(h.diskUsed)} / ${gb(h.diskTotal)} GB`, h.diskUsed / h.diskTotal, `${hh.disk}% · warn at 78%`, hh.disk >= 78)}
        ${R.meter("Uptime", uptime(h.uptimeS), null, "since last boot")}
      </div>
      <div class="trends">
        <div class="trend"><div class="trend-head"><span>CPU · last 60 min</span><span class="mono num">min ${Math.min(...cpu).toFixed(1)}% · max ${Math.max(...cpu).toFixed(1)}% · now ${cpu[cpu.length - 1].toFixed(1)}%</span></div>${R.spark(cpu, { label: "CPU percent, last hour", max: Math.max(20, Math.max(...cpu) * 1.2) })}</div>
        <div class="trend"><div class="trend-head"><span>RAM used · last 60 min</span><span class="mono num">min ${Math.min(...mem).toFixed(1)} · max ${Math.max(...mem).toFixed(1)} · now ${mem[mem.length - 1].toFixed(1)} GiB</span></div>${R.spark(mem, { label: "RAM GiB, last hour", min: 0, max: gib(h.memTotal) * 1 })}</div>
      </div>
      <div class="srv-grid">
        <section class="srv-containers">${R.section("Containers", { count: `${hh.running}/${hh.total}`, meta: "docker ps · 120 s" })}
          <table class="tbl tbl-dense"><thead><tr><th><span class="sr">State</span></th><th>Name</th><th>Status</th><th class="r">Memory</th></tr></thead><tbody>
          ${h.containers.map((c) => `<tr class="row${c.state !== "running" ? " is-dim" : ""}"><td class="c-st"><span class="st st-glyph tone-${c.state === "running" ? "working" : "idle"}"><i class="glyph" data-shape="${c.state === "running" ? "fill" : "ring"}"></i><span class="sr">${c.state}</span></span></td>
            <td class="mono">${esc(c.name)}</td><td class="muted">${esc(c.status)}</td><td class="r mono num">${c.mem ? c.mem.toFixed(0) + " MB" : "—"}</td></tr>`).join("")}
          </tbody></table></section>
        <section class="srv-procs">${R.section("Top processes", { meta: "by resident memory" })}
          <table class="tbl tbl-dense"><thead><tr><th class="r">RSS</th><th>PID</th><th>User</th><th>Command</th></tr></thead><tbody>
          ${h.topProcesses.map((p) => `<tr class="row"><td class="r mono num">${p.rss.toFixed(0)} MB</td><td class="mono num muted">${p.pid}</td><td class="mono">${esc(p.user)}</td><td class="mono trunc">${esc(p.cmd)}</td></tr>`).join("")}
          </tbody></table></section>
        <section class="srv-wt">${R.section("Worktrees", { meta: `${wtWarn.length} over the limit` })}
          <table class="tbl tbl-dense"><thead><tr><th>Project</th><th class="r">Worktrees</th><th class="r">Limit</th><th>Status</th></tr></thead><tbody>
          ${D.projects.map((p) => `<tr class="row"><td>${R.proj(p.key)}</td><td class="r mono num${p.worktrees > p.worktreeLimit ? " warn-txt" : ""}">${p.worktrees}</td><td class="r mono num muted">${p.worktreeLimit}</td>
            <td>${p.worktrees > p.worktreeLimit ? `<span class="warn-txt">▲ ${p.worktrees - p.worktreeLimit} over limit</span>` : '<span class="ok-txt">within limit</span>'}</td></tr>`).join("")}
          </tbody></table>
          <p class="foot-note">Information only. ccd never deletes worktrees; each project prunes through its own workflow.</p></section>
        <section class="srv-backups">${R.section("Backups", { meta: "last run" })}
          <table class="tbl tbl-dense"><thead><tr><th>Job</th><th>Schedule</th><th class="r">Last run</th><th class="r">Size</th><th>Result</th></tr></thead><tbody>
          ${h.backups.map((b) => `<tr class="row"><td>${esc(b.name)}</td><td class="mono muted">${esc(b.schedule)}</td><td class="r mono num">${R.agoCell(b.lastAt)} ago</td><td class="r mono num">${esc(b.size)}</td><td>${b.ok ? '<span class="ok-txt">✓ ok</span>' : '<span class="bad-txt">✗ failed</span>'}</td></tr>`).join("")}
          </tbody></table></section>
        <section class="srv-oom">${R.section("Recent OOM kills", { count: h.oom.length, meta: "kernel log · last 7 days" })}
          <table class="tbl tbl-dense"><thead><tr><th>When</th><th>Killed</th><th class="r">RSS</th><th>Triggered by</th></tr></thead><tbody>
          ${h.oom.map((o) => `<tr class="row"><td class="mono num">${day(o.at)} ${hms(o.at)}</td><td class="mono">${esc(o.victim)}</td><td class="r mono num">${esc(o.rss)}</td><td class="mono muted">${esc(o.trigger)}</td></tr>`).join("")}
          </tbody></table>
          <p class="foot-note">None in the last 24 h. All four victims were headless Chrome during one memory spike on Thu 01 Oct.</p></section>
      </div>
    </div>`;
  };

  SCREENS.activity = () => {
    const n = (c) => (c === "all" ? D.activity.length : D.activity.filter((e) => e.cat === c).length);
    return `<div class="screen-activity">
      ${R.section("Activity", { count: D.activity.length, meta: `meaningful events only · seq <span class="mono num">${D.seq}</span>` })}
      <div class="toolbar">${R.seg("activity", CATS.map(([k, l]) => [k, l, n(k)]), S.activityFilter, "[ ] cycle")}</div>
      ${R.activityList({ filter: S.activityFilter, days: true })}
    </div>`;
  };

  SCREENS.alerts = () => {
    const active = D.alerts.filter((a) => !a.ack), acked = D.alerts.filter((a) => a.ack);
    const list = S.alertsTab === "active" ? active : acked;
    return `<div class="screen-alerts">
      ${R.section("Alerts", { count: active.length, meta: "derived from agents, GitHub and the host · de-duplicated" })}
      <div class="toolbar">${R.seg("alerts", [["active", "Active", active.length], ["acked", "Acknowledged", acked.length]], S.alertsTab)}</div>
      ${list.length ? `<table class="tbl tbl-alerts">
        <thead><tr><th>Severity</th><th>Source</th><th>Project</th><th>Message</th><th class="r">Since</th><th class="r">${S.alertsTab === "active" ? "Acknowledge" : "Acknowledged"}</th></tr></thead>
        <tbody>${list.map((a) => `<tr class="row" tabindex="0" data-row data-key="al:${esc(a.id)}">
          <td><span class="sev sev-${a.severity}">${a.severity === "action" ? "ACTION" : a.severity === "warn" ? "WARN" : "INFO"}</span></td>
          <td class="mono">${esc(a.source)}</td><td>${a.project ? R.proj(a.project) : '<span class="muted">host</span>'}</td>
          <td class="c-text">${esc(a.text)}</td><td class="r">${R.agoCell(a.since)}</td>
          <td class="r">${a.ack ? `<span class="mono num muted">${hm(a.ackAt)}</span>` : `<button class="btn btn-quiet btn-sm" data-act="ack" data-id="${esc(a.id)}">Ack</button>`}</td></tr>`).join("")}
        </tbody></table>`
        : S.alertsTab === "active"
          ? R.empty("No active alerts", "Agents, GitHub and the host are all inside their thresholds.", "")
          : R.empty("Nothing acknowledged yet", "Acknowledging an alert keeps it visible here until its cause clears. An alert that clears and comes back starts unacknowledged again.", "Acknowledge from the Active tab — it changes nothing on the server.")}
    </div>`;
  };

  SCREENS.projects = () => `<div class="screen-projects">
    ${R.section("Projects", { count: D.projects.length })}
    <table class="tbl tbl-projects">
      <thead><tr><th>Project</th><th class="c-opt">Repository</th><th>Coordinator</th><th class="r">Agents</th><th class="r">In flight</th><th class="r">PRs</th><th class="r">Needs Jay</th><th>Main CI</th><th class="r">Worktrees</th><th class="r">Last activity</th></tr></thead>
      <tbody>${D.projects.map((p) => {
        const ags = D.agents.filter((a) => a.project === p.key);
        const coord = ags.find((a) => a.role === "coordinator");
        const flight = D.tasks.filter((t) => t.project === p.key && ["IN PROGRESS", "REVIEW", "MERGE", "VERIFY"].includes(t.stage)).length;
        const needs = D.needs.filter((n) => n.project === p.key).length;
        return `<tr class="row" tabindex="0" data-row data-key="proj:${p.key}">
          <td>${R.proj(p.key)}</td><td class="c-opt">${R.mono(p.repo, "muted")} ${R.mono(p.branch, "muted")}</td>
          <td>${coord ? `${R.status(coord.state)} <span class="mono muted">${esc(coord.name)}</span>` : '<span class="muted">none — tasks go to lanes</span>'}</td>
          <td class="r mono num">${ags.filter((a) => ACTIVE.has(a.state)).length}/${ags.length}</td><td class="r mono num">${flight}</td>
          <td class="r mono num">${D.prs.filter((x) => x.project === p.key).length}</td>
          <td class="r mono num${needs ? " jay-txt" : ""}">${needs || "—"}</td><td>${R.ci(p.mainCi)}</td>
          <td class="r mono num${p.worktrees > p.worktreeLimit ? " warn-txt" : ""}">${p.worktrees}<span class="muted">/${p.worktreeLimit}</span></td>
          <td class="r">${R.agoCell(p.lastActivityAt)}</td></tr>`;
      }).join("")}</tbody></table>
    <p class="foot-note">GYST has no coordinator by design: its tasks go straight to lanes. MFE's coordinator is detected but herdr has not classified it yet.</p>
  </div>`;

  SCREENS.settings = () => `<div class="screen-settings">
    ${R.section("Settings")}
    <div class="settings">
      <section class="set"><h3 class="set-title">Appearance</h3>
        <div class="set-row"><span class="set-k">Theme</span>${R.seg("theme", [["dark", "Dark"], ["light", "Light"]], S.theme, "D")}</div></section>
      <section class="set"><h3 class="set-title">Connection</h3>
        <div class="set-row"><span class="set-k">Daemon</span><span class="mono">ccd ${esc(F.version)} · ${esc(F.connection.endpoint)}</span></div>
        <div class="set-row"><span class="set-k">Token</span><span>Stored on this machine by the startup script. Never shown, never sent anywhere but ccd.</span></div>
        <div class="set-row"><span class="set-k">Sources</span><span class="src-list">
          ${Object.entries(D.sources).map(([k, s]) => `<span class="src"><span class="${S.offline ? "stale" : "ok-txt"}">${S.offline ? "○" : "●"}</span> ${k} <span class="mono num muted">${hm(s.asOf || s.lastSnapshotAt)}</span></span>`).join("")}</span></div></section>
      <section class="set"><h3 class="set-title">Notifications</h3>
        <div class="set-row"><span class="set-k">Desktop</span><span>Off in the prototype. The browser asks for permission when turned on.</span></div>
        <div class="set-row"><span class="set-k">Phone (ntfy)</span><span>Configured on the server. The topic is private and never displayed.</span></div></section>
      <section class="set"><h3 class="set-title">Keyboard</h3><div class="keys">${KEYS.map(([k, d]) => `<div class="key-row"><kbd>${k}</kbd><span>${d}</span></div>`).join("")}</div></section>
      <section class="set"><h3 class="set-title">Prototype controls</h3>
        <div class="set-row"><span class="set-k">States</span><span class="btn-row">
          <button class="btn" data-act="offline">${S.offline ? "Reconnect" : "Simulate offline"} <kbd>Shift O</kbd></button>
          <button class="btn" data-act="loading">Replay loading</button>
          <button class="btn" data-act="insert">Insert an event</button></span></div>
        <div class="set-row"><span class="set-k">Data</span><span>Fixture only. Nothing on this page talks to ccd, herdr or GitHub.</span></div></section>
    </div></div>`;

  const KEYS = [["1–9", "Go to a screen"], ["Ctrl K", "Command palette"], ["j / k", "Move between rows"], ["Enter", "Expand or open"],
    ["Esc", "Collapse, close"], ["F", "Focus the selected agent's pane"], ["A", "Answer the selected blocked agent"],
    ["T", "Tasks: table ↔ pipeline"], ["[  ]", "Previous / next filter"], ["D", "Dark ↔ light"], ["Shift O", "Simulate offline"], ["?", "Shortcuts"]];

  // --- overlays ---

  function paletteItems() {
    const items = [];
    NAV.forEach(([k, l], i) => items.push({ kind: "screen", label: l, sub: `screen · ${i + 1}`, run: () => go(k) }));
    D.projects.forEach((p) => items.push({ kind: "project", label: p.name, sub: "project", kw: p.key + " " + p.repo, run: () => go("projects", "proj:" + p.key) }));
    D.agents.forEach((a) => items.push({ kind: "agent", label: `${pname(a.project)} ${a.role}`, sub: `agent · ${STATE[a.state].label.toLowerCase()} · ${a.id}`, kw: a.name + " " + a.project, run: () => go("agents", a.id) }));
    D.tasks.forEach((t) => items.push({ kind: "task", label: t.id, sub: `task · ${t.title}`, kw: t.project + " " + pname(t.project), run: () => go("tasks", "task:" + t.id) }));
    D.prs.forEach((p) => items.push({ kind: "pr", label: `PR #${p.number}`, sub: `${pname(p.project)} · ${p.title}`, kw: p.project + " " + p.head, run: () => go("prs", "pr:" + p.number) }));
    D.agents.forEach((a) => items.push({ kind: "action", label: `Focus ${pname(a.project)} ${a.role}`, sub: `action · herdr agent focus ${a.id}`, kw: a.name + " " + a.project, run: () => notice(`Prototype — would focus pane ${a.id}. Nothing was sent.`) }));
    D.agents.filter((a) => a.blocked).forEach((a) => items.push({ kind: "action", label: `Answer ${pname(a.project)} ${a.role}`, sub: "action · type an answer into the blocked agent", kw: a.name + " " + a.project, run: () => { go("agents", a.id); setTimeout(() => focusAnswer(a.id), 30); } }));
    items.push({ kind: "action", label: "Toggle dark / light", sub: "action · D", run: toggleTheme });
    items.push({ kind: "action", label: S.offline ? "Simulate reconnect" : "Simulate offline", sub: "prototype · Shift O", run: toggleOffline });
    return items;
  }
  function paletteResults() {
    const q = S.palette.q.trim().toLowerCase();
    const all = paletteItems();
    if (!q) return all.filter((i) => i.kind === "screen" || (i.kind === "action" && /^Answer/.test(i.label))).slice(0, 12);
    return all.map((i) => {
      const hay = (i.label + " " + i.sub + " " + (i.kw || "")).toLowerCase();
      const at = hay.indexOf(q);
      if (at < 0) return null;
      const kindWeight = { project: 0, agent: 0.1, task: 0.2, pr: 0.3, screen: 0.4, action: 0.6 };
      return { i, score: (i.label.toLowerCase().startsWith(q) ? 0 : 1) + (at / 100) + (i.kind in kindWeight ? kindWeight[i.kind] : 1) };
    }).filter(Boolean).sort((a, b) => a.score - b.score).slice(0, 12).map((x) => x.i);
  }
  R.palette = () => {
    const res = paletteResults();
    S.palette.i = Math.min(S.palette.i, Math.max(0, res.length - 1));
    return `<div class="pal-backdrop" data-act="palClose"></div>
      <div class="pal" role="dialog" aria-modal="true" aria-label="Command palette">
        <div class="pal-in"><span class="pal-prompt mono" aria-hidden="true">›</span>
          <input id="pal-input" class="pal-input" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant="pal-opt-${S.palette.i}"
            placeholder="Search projects, agents, tasks, PRs, screens…" value="${esc(S.palette.q)}" autocomplete="off" spellcheck="false"></div>
        <ul id="pal-list" class="pal-list" role="listbox">${res.length ? res.map((r, i) => `
          <li id="pal-opt-${i}" class="pal-opt${i === S.palette.i ? " is-sel" : ""}" role="option" aria-selected="${i === S.palette.i}" data-act="palRun" data-i="${i}">
            <span class="pal-label">${esc(r.label)}</span><span class="pal-sub">${esc(r.sub)}</span><span class="pal-kind mono">${r.kind}</span></li>`).join("")
          : `<li class="pal-empty">No match for “${esc(S.palette.q)}”. Try a project, a task id like <span class="mono">SV-056</span>, or <span class="mono">#92</span>.</li>`}</ul>
        <div class="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span><span class="pal-safe">Navigate · focus · answer. No merge, deploy or delete — those don't exist.</span></div>
      </div>`;
  };
  R.help = () => `<div class="pal-backdrop" data-act="helpClose"></div>
    <div class="help" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
      <div class="help-head"><span>Keyboard</span><button class="btn btn-quiet btn-sm" data-act="helpClose">Close <kbd>Esc</kbd></button></div>
      <div class="keys">${KEYS.map(([k, d]) => `<div class="key-row"><kbd>${k}</kbd><span>${d}</span></div>`).join("")}</div></div>`;

  // ---------- DOM wiring ----------

  let $ = null;
  function el(id) { return document.getElementById(id); }

  function render(part) {
    if (!$) return;
    const active = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
    const ansVals = {};
    document.querySelectorAll("input[data-key^='ans:']").forEach((i) => { ansVals[i.dataset.key] = i.value; });
    const parts = part ? [part] : ["top", "nav", "rail", "banner", "screen", "cmd"];
    for (const p of parts) {
      if (p === "top" && el("cc-top")) el("cc-top").innerHTML = (V.top || R.top)();
      if (p === "nav" && el("cc-nav")) el("cc-nav").innerHTML = (V.nav || R.nav)();
      if (p === "rail" && el("cc-railfoot")) el("cc-railfoot").innerHTML = (V.railServer || R.railServer)();
      if (p === "banner" && el("cc-banner")) el("cc-banner").innerHTML = (V.banner || R.banner)();
      if (p === "cmd" && el("cc-cmd") && V.cmdline) el("cc-cmd").innerHTML = V.cmdline();
      if (p === "screen" && el("cc-screen")) {
        const body = S.loading ? (V.loadingScreen || R.loadingScreen)() : (V.screens[S.screen] || SCREENS[S.screen])();
        el("cc-screen").innerHTML = body;
        el("cc-screen").setAttribute("aria-busy", String(S.loading));
      }
    }
    document.documentElement.classList.toggle("is-offline", S.offline);
    document.documentElement.classList.toggle("is-loading", S.loading);
    document.documentElement.dataset.screen = S.screen;
    Object.entries(ansVals).forEach(([k, v]) => { const i = document.querySelector(`input[data-key="${k}"]`); if (i) i.value = v; });
    if (active) {
      const t = document.querySelector(`[data-key="${CSS.escape(active)}"]`);
      if (t && t !== document.activeElement) t.focus({ preventScroll: true });
    }
    markSelected();
  }
  R.loadingScreen = () => `<div class="loading-screen">${R.section("Connecting to ccd", { meta: "<span class='mono'>127.0.0.1:7777</span> · fetching state, then subscribing to events" })}${R.skeleton(8, 7)}</div>`;

  function markSelected() {
    const key = S.sel[S.screen];
    document.querySelectorAll("[data-row].is-sel").forEach((r) => r.classList.remove("is-sel"));
    if (key) { const r = document.querySelector(`#cc-screen [data-row][data-key="${CSS.escape(key)}"]`); if (r) r.classList.add("is-sel"); }
  }

  function overlay() {
    let host = el("cc-overlay");
    if (!host) { host = document.createElement("div"); host.id = "cc-overlay"; document.body.appendChild(host); }
    host.innerHTML = S.palette.open ? R.palette() : S.help ? R.help() : "";
    host.className = S.palette.open || S.help ? "is-open" : "";
    if (S.palette.open) {
      const inp = el("pal-input");
      if (inp && document.activeElement !== inp) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    }
  }

  let toastTimer = null;
  function notice(msg) {
    let t = el("cc-toast");
    if (!t) { t = document.createElement("div"); t.id = "cc-toast"; t.setAttribute("role", "status"); t.setAttribute("aria-live", "polite"); document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("is-on");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("is-on"), 2800);
  }

  function go(screen, key) {
    S.screen = screen;
    if (key) {
      S.sel[screen] = key;
      if (screen === "agents" && agentBy(key)) { S.expanded.add(key); S.agentsFilter = "all"; }
      if (screen === "tasks") S.tasksProject = "all";
    }
    if (location.hash !== "#" + screen) history.replaceState(null, "", "#" + screen);
    render();
    const target = key && document.querySelector(`#cc-screen [data-key="${CSS.escape(key)}"]`);
    if (target) { target.focus({ preventScroll: true }); target.scrollIntoView({ block: "nearest" }); }
    else el("cc-screen") && el("cc-screen").focus({ preventScroll: true });
  }
  function toggleTheme() {
    S.theme = S.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = S.theme;
    try { localStorage.setItem("cc-proto-theme", S.theme); } catch (e) { /* storage may be blocked */ }
    render();
  }
  function toggleOffline() {
    if (S.offline) {
      S.offline = false; const missed = Math.max(1, Math.round((Date.now() - S.offWall) / 20000));
      S.t0 += Date.now() - S.offWall; // frozen time resumes where it stopped
      render(); notice(`Reconnected — replayed ${missed} event${missed === 1 ? "" : "s"} since ${hms(S.offlineAt)}.`);
    } else {
      S.offlineAt = vnow(); S.offWall = Date.now(); S.offline = true; S.retry = 8; render();
    }
  }
  function focusAnswer(id) { const i = el("ans-" + id); if (i) i.focus(); }
  function insertEvent() {
    const s = F.scripted[S.scriptI % F.scripted.length]; S.scriptI++;
    const seq = D.seq + 1; D.seq = seq;
    D.activity.unshift({ seq, at: vnow(), cat: s.cat, project: s.project, text: s.text, ref: s.ref });
    if (s.agentState) { const a = agentBy(s.agentState.id); if (a) a.state = s.agentState.state; }
    S.fresh.add(seq); setTimeout(() => { S.fresh.delete(seq); const r = document.querySelector(`[data-key="ev:${seq}"]`); if (r) r.classList.remove("is-new"); }, 2400);
    render();
  }
  function rows() { return Array.from(document.querySelectorAll("#cc-screen [data-row]")); }
  function move(d) {
    const rs = rows(); if (!rs.length) return;
    const cur = rs.findIndex((r) => r.dataset.key === S.sel[S.screen]);
    const next = rs[Math.max(0, Math.min(rs.length - 1, cur < 0 ? 0 : cur + d))];
    S.sel[S.screen] = next.dataset.key; markSelected(); next.focus({ preventScroll: true }); next.scrollIntoView({ block: "nearest" });
  }
  function selectedAgent() { const k = S.sel[S.screen]; return k && agentBy(k); }
  function cycle(name, d) {
    const map = { activity: [CATS.map((c) => c[0]), "activityFilter"], agents: [["all", "attention", "active", "idle"], "agentsFilter"],
      tasks: [["all", ...D.projects.map((p) => p.key)], "tasksProject"], alerts: [["active", "acked"], "alertsTab"] };
    const m = map[name]; if (!m) return;
    const i = m[0].indexOf(S[m[1]]); S[m[1]] = m[0][(i + d + m[0].length) % m[0].length]; render("screen");
  }

  function onClick(e) {
    const t = e.target.closest("[data-act]");
    if (!t) return;
    const a = t.dataset.act;
    if (["nav", "goto"].includes(a) || t.tagName === "A") e.preventDefault();
    if (a === "nav") go(t.dataset.screen);
    else if (a === "goto") { if (t.dataset.pipeline) S.tasksView = "pipeline"; go(t.dataset.screen, t.dataset.target); }
    else if (a === "toggle") {
      if (e.target.closest("button, input, a, .ad")) return;
      const id = t.dataset.id; S.sel[S.screen] = id;
      S.expanded.has(id) ? S.expanded.delete(id) : S.expanded.add(id); render("screen");
    }
    else if (a === "seg") {
      const k = { agents: "agentsFilter", tasksView: "tasksView", tasksProject: "tasksProject", activity: "activityFilter", alerts: "alertsTab" }[t.dataset.seg];
      if (t.dataset.seg === "theme") { if (t.dataset.val !== S.theme) toggleTheme(); return; }
      S[k] = t.dataset.val; render("screen");
    }
    else if (a === "theme") toggleTheme();
    else if (a === "offline") toggleOffline();
    else if (a === "loading") { S.loading = true; render(); setTimeout(() => { S.loading = false; render(); }, 900); }
    else if (a === "insert") insertEvent();
    else if (a === "palette") { S.palette = { open: true, q: "", i: 0 }; overlay(); }
    else if (a === "palClose") { S.palette.open = false; overlay(); }
    else if (a === "palRun") { const r = paletteResults()[+t.dataset.i]; S.palette.open = false; overlay(); r && r.run(); }
    else if (a === "helpClose") { S.help = false; overlay(); }
    else if (a === "ack") {
      const al = D.alerts.find((x) => x.id === t.dataset.id);
      if (al) { al.ack = true; al.ackAt = vnow(); render(); notice("Acknowledged here only — prototype. Live: POST /api/action/ack."); }
    }
    else if (a === "fill") { const i = el("ans-" + t.dataset.for); if (i) { i.value = t.dataset.val; i.focus(); } }
    else if (a === "answer") sendAnswer(t.dataset.id);
    else if (a === "focus") notice(S.offline ? "Offline — actions are paused until ccd reconnects." : `Prototype — would focus pane ${t.dataset.id}. Nothing was sent.`);
    else if (a === "focusAnswer") focusAnswer(t.dataset.id);
    else if (a === "copy") { try { navigator.clipboard.writeText(t.dataset.val); } catch (err) { /* insecure context */ } notice(`Copied ${t.dataset.val}`); }
  }
  function sendAnswer(id) {
    const i = el("ans-" + id);
    if (S.offline) return notice("Offline — answers are paused until ccd reconnects.");
    if (!i || !i.value.trim()) { if (i) i.focus(); return notice("Type an answer first."); }
    notice(`Prototype — “${i.value.trim()}” not sent. Live: typed into ${id}, then Enter.`); i.value = "";
  }

  function onKey(e) {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea";
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); S.palette = { open: !S.palette.open, q: "", i: 0 }; S.help = false; overlay(); return; }
    if (S.palette.open) {
      const res = paletteResults();
      if (e.key === "Escape") { S.palette.open = false; overlay(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); S.palette.i = Math.min(res.length - 1, S.palette.i + 1); overlay(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); S.palette.i = Math.max(0, S.palette.i - 1); overlay(); }
      else if (e.key === "Enter") { e.preventDefault(); const r = res[S.palette.i]; S.palette.open = false; overlay(); r && r.run(); }
      return;
    }
    if (S.help && e.key === "Escape") { S.help = false; overlay(); return; }
    if (typing) {
      if (e.key === "Enter" && e.target.dataset.key && e.target.dataset.key.startsWith("ans:")) { e.preventDefault(); sendAnswer(e.target.dataset.key.slice(4)); }
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const k = e.key;
    // Buttons and links handle their own Enter/Space; don't also toggle the row behind them.
    if ((tag === "button" || tag === "a") && (k === "Enter" || k === " ")) return;
    if (/^[1-9]$/.test(k)) { go(NAV[+k - 1][0]); return; }
    if (k === "j" || k === "ArrowDown") { e.preventDefault(); move(1); }
    else if (k === "k" || k === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (k === "Enter" || k === "ArrowRight" || k === "ArrowLeft") {
      const key = S.sel[S.screen]; if (!key) return;
      if (S.screen === "agents" && agentBy(key)) {
        if (k === "ArrowLeft") S.expanded.delete(key); else if (k === "ArrowRight") S.expanded.add(key);
        else S.expanded.has(key) ? S.expanded.delete(key) : S.expanded.add(key);
        render("screen");
      } else if (k === "Enter") { const r = document.querySelector(`#cc-screen [data-key="${CSS.escape(key)}"]`); if (r && r.dataset.act) r.click(); }
    }
    else if (k === "Escape") { if (S.screen === "agents" && S.sel.agents) { S.expanded.delete(S.sel.agents); render("screen"); } }
    else if (k === "f" || k === "F") { const a = selectedAgent(); if (a) notice(S.offline ? "Offline — actions are paused." : `Prototype — would focus pane ${a.id}. Nothing was sent.`); }
    else if (k === "a" || k === "A") { const a = selectedAgent(); if (a && a.blocked) { S.expanded.add(a.id); render("screen"); setTimeout(() => focusAnswer(a.id), 20); e.preventDefault(); } }
    else if (k === "t" || k === "T") { if (S.screen === "tasks") { S.tasksView = S.tasksView === "table" ? "pipeline" : "table"; render("screen"); } }
    else if (k === "[" || k === "]") cycle(S.screen, k === "]" ? 1 : -1);
    else if (k === "0" && S.screen === "agents") { S.agentsFilter = "all"; render("screen"); }
    else if (k === "d" || k === "D") toggleTheme();
    else if (k === "O" && e.shiftKey) toggleOffline();
    else if (k === "?") { S.help = true; overlay(); }
  }

  function tick() {
    const now = vnow();
    const clock = el("cc-clock"); if (clock) clock.textContent = hms(now);
    document.querySelectorAll("[data-ago]").forEach((n) => { n.textContent = ago(+n.dataset.ago, now); });
    if (S.offline) {
      S.retry = S.retry <= 1 ? 8 : S.retry - 1;
      const r = el("cc-retry"); if (r) r.textContent = S.retry + "s";
    }
  }

  // ---------- public ----------

  CC.STATE = STATE; CC.NAV = NAV; CC.R = R; CC.SCREENS = SCREENS; CC.S = S;
  CC.helpers = { esc, hm, hms, day, ago, gib, gb, pct, uptime, vnow, proj, pname, agentBy, sortAgents, counts, health, ACTIVE, ATTENTION, CI, REVIEW, MERGE, CATS, KEYS };
  CC.data = () => D;

  CC.init = function (variant, fixture) {
    F = fixture || window.CC_FIXTURE;
    D = JSON.parse(JSON.stringify({ projects: F.projects, agents: F.agents, tasks: F.tasks, prs: F.prs, needs: F.needs,
      activity: F.activity, alerts: F.alerts, host: F.host, sources: F.sources, seq: F.seq }));
    V = variant || {}; V.screens = V.screens || {};
    // Each direction starts from the shared renderers, then applies its own.
    if (!CC._R0) CC._R0 = Object.assign({}, R);
    Object.keys(R).forEach((k) => { delete R[k]; });
    Object.assign(R, CC._R0, V.renderers || {});
    return CC;
  };
  CC.render = (screen) => (V.screens[screen] || SCREENS[screen])();

  CC.start = function (variant) {
    CC.init(variant);
    let theme = null;
    try { theme = localStorage.getItem("cc-proto-theme"); } catch (e) { /* ignore */ }
    const params = new URLSearchParams(location.search);
    S.theme = params.get("theme") || theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = S.theme;
    document.documentElement.dataset.variant = V.id;
    const fromHash = location.hash.slice(1);
    if (NAV.some(([k]) => k === fromHash)) S.screen = fromHash;
    document.getElementById("cc-app").innerHTML = V.shell();
    $ = true;
    render();
    if (params.get("state") === "offline") setTimeout(() => { S.loading = false; toggleOffline(); }, 0);
    setTimeout(() => { if (S.loading) { S.loading = false; render(); } }, params.get("state") === "loading" ? 2400 : 450);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    document.addEventListener("input", (e) => { if (e.target.id === "pal-input") { S.palette.q = e.target.value; S.palette.i = 0; overlay(); } });
    window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (NAV.some(([k]) => k === h) && h !== S.screen) go(h); });
    setInterval(tick, 1000);
    if (!params.has("still")) {
      setTimeout(function next() {
        if (S.scriptI < F.scripted.length) { if (!S.offline && !S.loading) insertEvent(); setTimeout(next, 26000); }
      }, 16000);
    }
  };
})();
