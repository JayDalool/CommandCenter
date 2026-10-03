/* Direction B — STUDIO. Professional desktop software: a page title, quiet
 * panels, sentence-case typography, and a rail that also summarises each
 * project. Same data and behaviour as the other directions. */
(function () {
  const CC = window.CC;
  const H = () => CC.helpers;
  const R = () => CC.R;
  const esc = (s) => H().esc(s);

  const shell = () => `
    <div class="app">
      <aside class="rail" aria-label="Navigation">
        <div class="brand"><span class="brand-mark" aria-hidden="true"><i></i><i></i></span>
          <span class="brand-text"><span class="brand-name">Command Center</span><span class="brand-sub">jay-server</span></span></div>
        <nav id="cc-nav" aria-label="Screens"></nav>
        <div id="cc-railprojects" class="rail-projects"></div>
        <div id="cc-railfoot" class="rail-foot"></div>
      </aside>
      <div class="main">
        <header id="cc-top" class="top"></header>
        <div id="cc-banner"></div>
        <main id="cc-screen" class="screen" tabindex="-1"></main>
      </div>
    </div>`;

  // Sentence-case states: "Working", not "WORKING". Same glyph shapes.
  const status = (state) => {
    const m = CC.STATE[state];
    return `<span class="st tone-${m.tone}" data-state="${state}"><i class="glyph" data-shape="${m.shape}" aria-hidden="true"></i><span class="st-label">${m.label}</span></span>`;
  };

  const panel = (cls, head, body) => `<section class="panel ${cls}">${head}<div class="panel-body">${body}</div></section>`;
  const section = (title, o = {}) => `
    <div class="sec-head">
      <h2 class="sec-title">${esc(title)}</h2>
      ${o.count != null ? `<span class="sec-count num">${o.count}</span>` : ""}
      ${o.meta ? `<div class="sec-meta">${o.meta}</div>` : ""}
      ${o.tools ? `<div class="sec-tools">${o.tools}</div>` : ""}
    </div>`;

  const titles = Object.fromEntries(CC.NAV);

  const top = () => {
    const c = H().counts(), S = CC.S;
    return `<div class="top-inner">
      <div class="top-heading">
        <div class="crumb">COMMAND CENTER</div>
        <h1 class="page-title">${titles[S.screen]}</h1>
      </div>
      <div class="top-right">
        ${R().conn()}
        <time class="top-clock mono num" id="cc-clock">${H().hms(H().vnow())}</time>
        <span class="divider" aria-hidden="true"></span>
        <a class="chip chip-jay" href="#overview" data-act="nav" data-screen="overview"><span class="num">${c.needs}</span> needs Jay</a>
        <a class="chip" href="#agents" data-act="nav" data-screen="agents"><span class="num">${c.working}</span> working</a>
        <a class="chip" href="#prs" data-act="nav" data-screen="prs"><span class="num">${c.prs}</span> open PRs</a>
        <span class="divider" aria-hidden="true"></span>
        <button class="btn btn-quiet btn-sm" data-act="theme" title="Toggle light/dark (D)">${S.theme === "dark" ? "Light" : "Dark"}</button>
        <button class="kbd-btn" data-act="palette" title="Command palette">Ctrl K</button>
      </div>
    </div>`;
  };

  const railProjects = () => {
    const D = CC.data();
    return `<div class="rp-head">Projects</div><ul class="rp-list">${D.projects.map((p) => {
      const ags = D.agents.filter((a) => a.project === p.key);
      const blocked = ags.filter((a) => a.state === "BLOCKED" || a.state === "FAILED").length;
      const active = ags.filter((a) => H().ACTIVE.has(a.state)).length;
      const needs = D.needs.filter((n) => n.project === p.key).length;
      const line = blocked ? `<span class="rp-attn">${blocked} need${blocked === 1 ? "s" : ""} you</span>`
        : active ? `<span>${active} active</span>` : `<span class="muted">quiet</span>`;
      return `<li><a class="rp-item" href="#projects" data-act="goto" data-screen="projects" data-target="proj:${p.key}">
        ${R().proj(p.key)}<span class="rp-state">${line}</span>${needs ? `<span class="rp-n num">${needs}</span>` : ""}</a></li>`;
    }).join("")}</ul>`;
  };

  const overview = () => {
    const D = CC.data(), h = D.host, c = H().counts();
    const cpu = h.samples.map((s) => s.cpu);
    const oldest = Math.min(...D.needs.map((n) => n.since));
    return `<div class="ovb">
      <section class="ovb-glance" aria-label="At a glance">${R().answersStrip()}</section>
      <div class="ovb-cols">
        <div class="ovb-main">
          ${panel("p-needs", section("Needs you", { count: D.needs.length, meta: `oldest waiting ${R().agoCell(oldest)}` }), R().needsList({ headless: true }))}
          ${panel("p-agents", section("Agents", { count: D.agents.length, meta: `${c.working} working · ${c.blocked} blocked`, tools: R().goto("agents", "All agents") }), R().agentsCompact())}
          ${panel("p-pipe", section("Pipeline", { count: D.tasks.length, tools: R().goto("tasks", "Tasks") }), R().pipelineStrip())}
        </div>
        <aside class="ovb-side">
          ${panel("p-server", section("Server", { meta: `<span class="mono">jay-server</span> · ${R().agoMeta(h.asOf)}`, tools: R().goto("server", "Details") }),
            `${R().serverCompact()}<div class="p-trend"><div class="trend-head"><span>CPU · 60 min</span><span class="mono num">max ${Math.max(...cpu).toFixed(1)}%</span></div>${R().spark(cpu, { h: 34, label: "CPU, last hour", max: Math.max(20, Math.max(...cpu) * 1.2) })}</div>`)}
          ${panel("p-activity", section("Recent activity", { tools: R().goto("activity", "All") }), R().activityList({ limit: 10 }))}
        </aside>
      </div>
    </div>`;
  };

  const variant = {
    id: "studio", shell, top,
    renderers: { status, section },
    screens: { overview },
  };

  // The rail's project list is extra to the shared shell: refresh it with the nav.
  const navWithProjects = () => {
    const host = typeof document !== "undefined" && document.getElementById("cc-railprojects");
    if (host) host.innerHTML = railProjects();
    return R().nav();
  };
  variant.nav = navWithProjects;
  variant.railProjects = railProjects;

  if (CC && CC.start && typeof document !== "undefined" && document.getElementById("cc-app")) CC.start(variant);
  window.CC_VARIANTS = Object.assign(window.CC_VARIANTS || {}, { studio: variant });
})();
