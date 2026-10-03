/* Direction C — TERMINAL+. A graphical workstation: monospace throughout,
 * 26 px rows, a status line and a command line, box-titled panes, four-letter
 * state codes. Keyboard-first; the mouse still works everywhere. */
(function () {
  const CC = window.CC;
  const H = () => CC.helpers;
  const R = () => CC.R;
  const esc = (s) => H().esc(s);

  const shell = () => `
    <div class="app">
      <header id="cc-top" class="statusline"></header>
      <aside class="rail" aria-label="Navigation">
        <nav id="cc-nav" aria-label="Screens"></nav>
        <div id="cc-railfoot" class="rail-foot"></div>
      </aside>
      <div class="main">
        <div id="cc-banner"></div>
        <main id="cc-screen" class="screen" tabindex="-1"></main>
      </div>
      <footer id="cc-cmd" class="cmdline"></footer>
    </div>`;

  const status = (state) => {
    const m = CC.STATE[state];
    return `<span class="st tone-${m.tone}" data-state="${state}" title="${m.label}"><i class="glyph" data-shape="${m.shape}" aria-hidden="true"></i><span class="st-label">${m.short}</span><span class="sr"> ${m.label}</span></span>`;
  };
  const ci = (v) => {
    const map = { pass: ["ok", "ok"], fail: ["FAIL", "bad"], pending: ["run", "run"], none: ["--", "none"] };
    const [t, tone] = map[v] || map.none;
    return `<span class="ci ci-${tone}" title="${H().CI[v] ? H().CI[v].label : "no checks"}">${t}</span>`;
  };
  const needTag = (kind) => `<span class="need need-${kind.toLowerCase()}">${kind}</span>`;

  const section = (title, o = {}) => `
    <div class="sec-head">
      <h2 class="sec-title">${esc(title.toUpperCase())}</h2>${o.count != null ? `<span class="sec-count num">${o.count}</span>` : ""}
      <span class="sec-rule" aria-hidden="true"></span>
      ${o.meta ? `<div class="sec-meta">${o.meta}</div>` : ""}
      ${o.tools ? `<div class="sec-tools">${o.tools}</div>` : ""}
    </div>`;

  const goto = (screen, label) => {
    const i = CC.NAV.findIndex(([k]) => k === screen) + 1;
    return `<a class="goto" href="#${screen}" data-act="nav" data-screen="${screen}"><kbd>${i}</kbd> ${esc(label.toLowerCase())}</a>`;
  };

  // The five questions as the output of a status command.
  const answersStrip = () => {
    const xs = R().answers();
    const key = { Server: "server", Working: "working", Blocked: "blocked", "Needs Jay": "needs_jay", "Last change": "last" };
    return `<div class="prompt-out">
      <div class="po-cmd"><span class="po-ps">cc@jay-server:~$</span> <span>status</span></div>
      <ul class="po-kv">${xs.map((x) => `<li class="tone-${x.tone}"><a href="#${x.key}" data-act="nav" data-screen="${x.key}">
        <span class="po-k">${key[x.q]}</span><span class="po-eq">=</span><span class="po-v">${x.q === "Last change" ? `"${esc(x.a)}"` : esc(x.a.toLowerCase())}</span></a></li>`).join("")}</ul>
    </div>`;
  };

  const nav = () => {
    const c = H().counts(), S = CC.S;
    const n = { overview: c.needs, agents: c.agents, tasks: c.tasks, prs: c.prs, alerts: c.alerts };
    return `<div class="nav-title">screens</div><ul class="nav-list">${CC.NAV.map(([k, label], i) => `
      <li><a class="nav-item${S.screen === k ? " is-on" : ""}" href="#${k}" data-act="nav" data-screen="${k}" ${S.screen === k ? 'aria-current="page"' : ""}>
        <span class="nav-key">${i + 1}</span><span class="nav-label">${label.toLowerCase()}</span>
        ${n[k] ? `<span class="nav-n num${k === "overview" ? " is-jay" : k === "alerts" ? " is-alert" : ""}">${n[k]}</span>` : ""}</a></li>`).join("")}</ul>`;
  };

  const top = () => {
    const c = H().counts(), S = CC.S;
    const conn = S.loading ? `<span class="sl-seg conn is-connecting">◌ CONNECTING</span>`
      : S.offline ? `<span class="sl-seg conn is-off">○ OFFLINE <span class="conn-sub">last update ${H().hms(S.offlineAt)}</span></span>`
        : `<span class="sl-seg conn is-live">● LIVE</span>`;
    return `<div class="sl">
      <span class="sl-seg sl-brand">COMMAND CENTER</span>
      <span class="sl-seg sl-host">jay@jay-server</span>
      ${conn}
      <time class="sl-seg sl-clock num" id="cc-clock">${H().hms(H().vnow())}</time>
      <a class="sl-seg sl-stat is-jay" href="#overview" data-act="nav" data-screen="overview">JAY <b class="num">${c.needs}</b></a>
      <a class="sl-seg sl-stat" href="#agents" data-act="nav" data-screen="agents">WORK <b class="num">${c.working}</b></a>
      <a class="sl-seg sl-stat${c.blocked ? " is-blk" : ""}" href="#agents" data-act="nav" data-screen="agents">BLKD <b class="num">${c.blocked}</b></a>
      <a class="sl-seg sl-stat" href="#prs" data-act="nav" data-screen="prs">PR <b class="num">${c.prs}</b></a>
      <span class="sl-fill"></span>
      <button class="sl-seg sl-btn" data-act="theme" title="Toggle light/dark">${S.theme === "dark" ? "light" : "dark"} <kbd>D</kbd></button>
      <button class="sl-seg sl-btn" data-act="palette" title="Command palette">palette <kbd>^K</kbd></button>
    </div>`;
  };

  const cmdline = () => {
    const S = CC.S, D = CC.data(), H_ = H();
    const src = D.sources, now = H_.vnow();
    const fresh = (ms) => (S.offline ? "stale" : H_.ago(ms, now));
    return `<div class="cl">
      <button class="cl-prompt" data-act="palette" aria-label="Open command palette"><span class="cl-ps">:</span><span class="cl-hint">type ^K to search or run</span></button>
      <span class="cl-keys"><kbd>1-9</kbd> screen <kbd>j</kbd><kbd>k</kbd> row <kbd>⏎</kbd> expand <kbd>f</kbd> focus <kbd>a</kbd> answer <kbd>t</kbd> view <kbd>[ ]</kbd> filter <kbd>?</kbd> keys</span>
      <span class="cl-right num">seq ${D.seq} │ herdr ${fresh(src.herdr.lastEventAt)} │ gh ${fresh(src.github.asOf)} │ host ${fresh(src.host.asOf)}</span>
    </div>`;
  };

  const variant = {
    id: "terminal-plus", shell, top, nav, cmdline,
    renderers: { status, ci, needTag, section, goto, answersStrip },
    screens: {},
  };

  if (CC && CC.start && typeof document !== "undefined" && document.getElementById("cc-app")) {
    CC.start(variant);
    // The command line shows source freshness; refresh it with the clock.
    setInterval(() => { const el = document.getElementById("cc-cmd"); if (el) el.innerHTML = cmdline(); }, 5000);
  }
  window.CC_VARIANTS = Object.assign(window.CC_VARIANTS || {}, { "terminal-plus": variant });
})();
