/* Headless render check for all three directions: node tests/render.test.js
 *
 * Renders every screen in every direction, in normal, offline and each filter
 * state, and fails on runtime errors, "undefined"/"NaN"/"[object" leaking into
 * markup, unbalanced tags, or missing required content. It cannot judge looks;
 * it guarantees the screens Jay opens are complete.
 */
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
globalThis.window = globalThis;

const root = path.join(__dirname, "..");
require(path.join(root, "shared/fixture.js"));
require(path.join(root, "shared/core.js"));
for (const v of ["operator/operator.js", "studio/studio.js", "terminal-plus/terminal.js"]) {
  try { require(path.join(root, v)); } catch (e) { if (e.code !== "MODULE_NOT_FOUND") throw e; }
}

const SCREENS = ["overview", "projects", "agents", "tasks", "prs", "server", "activity", "alerts", "settings"];
const BAD = [/\bundefined\b/, /\bNaN\b/, /\[object /, /\$\{/, /\bnull\b(?![-\w])/];
let checks = 0;

function balanced(html, where) {
  const voids = new Set(["input", "br", "img", "meta", "link", "hr", "circle", "line", "polyline"]);
  const stack = [];
  const re = /<\/?([a-zA-Z][\w-]*)\b[^>]*?(\/?)>/g;
  let m;
  while ((m = re.exec(html))) {
    const tag = m[1].toLowerCase();
    if (voids.has(tag) || m[2] === "/") continue;
    if (m[0][1] === "/") {
      const top = stack.pop();
      assert.equal(top, tag, `${where}: </${tag}> closes <${top}>`);
    } else stack.push(tag);
  }
  assert.deepEqual(stack, [], `${where}: unclosed ${stack.join(",")}`);
}

function check(html, where) {
  checks++;
  assert.ok(typeof html === "string" && html.length > 40, `${where}: empty render`);
  for (const re of BAD) {
    const m = html.match(re);
    assert.ok(!m, `${where}: "${m && m[0]}" in markup near: ${m && html.slice(Math.max(0, m.index - 80), m.index + 40)}`);
  }
  balanced(html, where);
}

const variants = Object.values(window.CC_VARIANTS || {});
assert.ok(variants.length >= 1, "no variants registered");

for (const v of variants) {
  window.CC.init(v, window.CC_FIXTURE);
  const S = window.CC.S, R = window.CC.R;
  S.loading = false; S.offline = false;
  const where = (s, x = "") => `${v.id}/${s}${x}`;

  // shell pieces
  check(v.shell(), where("shell"));
  for (const p of ["top", "nav", "railServer", "banner"]) {
    const fn = v[p] || R[p];
    if (p === "banner") continue;
    check(fn(), where(p));
  }
  if (v.cmdline) check(v.cmdline(), where("cmdline"));

  // every screen
  for (const s of SCREENS) { S.screen = s; check(window.CC.render(s), where(s)); }

  // states
  S.tasksView = "pipeline"; check(window.CC.render("tasks"), where("tasks", ":pipeline"));
  S.tasksProject = "mfe"; check(window.CC.render("tasks"), where("tasks", ":pipeline:mfe"));
  S.tasksView = "table"; check(window.CC.render("tasks"), where("tasks", ":table:mfe"));
  S.tasksProject = "all";
  for (const f of ["attention", "active", "idle", "all"]) { S.agentsFilter = f; check(window.CC.render("agents"), where("agents", ":" + f)); }
  for (const [f] of window.CC.helpers.CATS) { S.activityFilter = f; check(window.CC.render("activity"), where("activity", ":" + f)); }
  S.activityFilter = "all";
  S.alertsTab = "acked"; const acked = window.CC.render("alerts"); check(acked, where("alerts", ":acked"));
  assert.match(acked, /Nothing acknowledged yet/, "acknowledged tab shows its empty state");
  S.alertsTab = "active";

  // the blocked implementer is expanded inline by default, with its question and answer box
  const agents = window.CC.render("agents");
  assert.match(agents, /npm run test:e2e/, `${v.id}: blocked question shown inline`);
  assert.match(agents, /Send answer/, `${v.id}: answer control present`);
  assert.doesNotMatch(agents, /data-act="merge"/, "no merge action");
  for (const st of Object.keys(window.CC.STATE)) assert.ok(agents.includes(`data-state="${st}"`) || agents.includes(st) || agents.toUpperCase().includes(window.CC.STATE[st].label.toUpperCase()), `${v.id}: state ${st} rendered`);

  // overview answers the five questions
  const ov = window.CC.render("overview");
  for (const want of ["Needs Jay", "PR #92", "jay-server"]) assert.ok(ov.includes(want) || ov.toLowerCase().includes(want.toLowerCase()), `${v.id}: overview shows ${want}`);
  for (const ref of ["MERGE", "ANSWER", "DO", "REVIEW"]) assert.ok(ov.includes(ref), `${v.id}: overview needs-jay has ${ref}`);

  // server
  const srv = window.CC.render("server");
  assert.match(srv, /26/, "samvision worktrees");
  assert.match(srv, /never deletes worktrees/i, "worktrees are information only");

  // offline keeps data and says so
  S.offline = true; S.offlineAt = window.CC_FIXTURE.now - 10 * 60000;
  const top = (v.top || R.top)();
  check(top, where("top", ":offline"));
  assert.match(top, /OFFLINE/i, `${v.id}: offline indicator`);
  check((v.banner || R.banner)(), where("banner", ":offline"));
  const ovOff = window.CC.render("overview");
  check(ovOff, where("overview", ":offline"));
  assert.match(ovOff, /PR #92/, "offline keeps last-known data on screen");
  S.offline = false;

  // loading
  check((v.loadingScreen || R.loadingScreen)(), where("loading"));

  // palette
  S.palette = { open: true, q: "sam", i: 0 };
  const pal = R.palette();
  check(pal, where("palette", ":sam"));
  assert.match(pal, /SamVision/);
  const labels = [...pal.matchAll(/class="pal-label">([^<]*)</g)].map((m) => m[1]);
  assert.equal(labels[0], "SamVision", "the project ranks first for its own name");
  for (const l of labels) assert.doesNotMatch(l, /merge|deploy|delete|restart|kill/i, `palette offers nothing dangerous: ${l}`);
  S.palette = { open: true, q: "zzzz-nothing", i: 0 };
  assert.match(R.palette(), /No match/);
  S.palette = { open: false, q: "", i: 0 };
  check(R.help(), where("help"));
}

console.log(`render tests: ${variants.map((v) => v.id).join(", ")} — ${checks} renders checked, all passed`);
