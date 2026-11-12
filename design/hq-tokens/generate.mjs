// Generates HQ's design tokens for Classic (web/app/src/hq/tokens.css and palette.ts) from the approved Engineering HQ
// prototype, read straight from git at the approved commit, so the output always says exactly which design it is.
//
//   node design/hq-tokens/generate.mjs           write both files
//   node design/hq-tokens/generate.mjs --check   exit 1 if either file differs from what the approved commit gives
//
// To adopt a newly approved design (for example V11 and V12), change APPROVED to the commit Jay approved and run it.
// The commit must be in this clone's history (the prototype lives in design/ui-prototypes/engineering-hq).
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** The design Jay picked (2026-11-12): Workbench, "Engineering HQ prototype: Workbench direction (V13)". Before it:
 *  4b72f3f, "Engineering HQ: final design refinements", signed off 2026-10-25. */
export const APPROVED = "d55aab08055fceda80ab08e5f105257a4bf13543";
const PROTO = "design/ui-prototypes/engineering-hq/src";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const OUT_CSS = path.join(ROOT, "web/app/src/hq/tokens.css");
const OUT_TS = path.join(ROOT, "web/app/src/hq/palette.ts");
const HQ = ':root[data-ui="hq"]';

/** The approved commit is on the prototype's branch (PR #64), not on main: a clone may not have it yet. */
export const MISSING = 3;
function haveApproved() {
  try { execFileSync("git", ["cat-file", "-e", `${APPROVED}^{commit}`], { cwd: ROOT, stdio: "ignore" }); return true; }
  catch { return false; }
}
const show = (file) => execFileSync("git", ["show", `${APPROVED}:${PROTO}/${file}`], { cwd: ROOT, encoding: "utf8" });

/** sha256 of a generated file with its own hash left out. tests/hq-tokens.test.ts recomputes it, so a hand edit fails
 *  there even in a clone without the approved commit; --check compares with the commit itself. */
export const SEAL = /values sha256 [0-9a-f]{64}/;
export const seal = (text) => createHash("sha256").update(text.replace(SEAL, "values sha256 ")).digest("hex");
const sealed = (text) => text.replace(SEAL, `values sha256 ${seal(text)}`);
const uncomment = (css) => css.replace(/\/\*[\s\S]*?\*\//g, "");

/** The custom properties of the rule that starts with `selector {` (other declarations, like color-scheme, are not tokens). */
function block(css, selector) {
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`prototype has no "${selector} {" rule`);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return declarations(body);
}
function declarations(body) {
  return body.split(";").map((d) => d.trim()).filter((d) => d.startsWith("--")).map((d) => {
    const i = d.indexOf(":");
    return [d.slice(0, i).trim(), d.slice(i + 1).trim().replace(/\s+/g, " ")];
  });
}

/** --name -> --hq-name, in names and in var() references. */
const hq = (s) => s.replace(/--([a-z0-9-]+)/g, "--hq-$1");

/** Declarations packed several to a line, in source order, the way the prototype writes them. */
function rule(selector, decls, indent = "") {
  const lines = [];
  let line = "";
  for (const [k, v] of decls) {
    const d = `${hq(k)}: ${hq(v)};`;
    if (line && line.length + d.length + 1 > 116 - indent.length) { lines.push(line); line = ""; }
    line = line ? `${line} ${d}` : d;
  }
  if (line) lines.push(line);
  return `${indent}${selector} {\n${lines.map((l) => `${indent}  ${l}`).join("\n")}\n${indent}}\n`;
}

export function generate() {
  const hqCss = uncomment(show("styles/hq.css"));
  const lightCss = uncomment(show("styles/theme-light.css"));
  const seed = show("data/seed.ts");

  // The prototype re-applies the dark tokens to two "dark islands", .term and .slack-phone, so the terminal and the Slack
  // phone preview stay dark in Light. Only the values are taken here; whoever ports those screens adds the island rule
  // (scoped under :root[data-ui="hq"], repeating every dark token, because var() resolves where it is declared).
  const dark = block(hqCss, ":root, .term, .slack-phone");
  const light = block(lightCss, ':root[data-hq-theme="light"]');
  // Every other rule in theme-light.css styles components. One that declared a token would be lost here: refuse it.
  const lightRest = lightCss.replace(/:root\[data-hq-theme="light"\] \{[^}]*\}/, "");
  const stray = lightRest.match(/--[a-z0-9-]+\s*:/g);
  if (stray) throw new Error(`theme-light.css declares tokens outside its :root rule (${stray.join(" ")}); this generator would drop them`);
  const names = new Set(dark.map(([k]) => k));
  for (const [k] of light) if (!names.has(k)) throw new Error(`light theme sets ${k}, which dark does not define`);

  // Layout tokens that change with the window: `@media (...) { :root { --x: … } }` in hq.css.
  const media = [...hqCss.matchAll(/@media\s*(\([^{]*\))\s*\{\s*:root\s*\{([^}]*)\}/g)].map((m) => [m[1].trim(), declarations(m[2])]);
  const roots = (hqCss.match(/:root\b/g) ?? []).length;
  if (roots !== 1 + media.length) throw new Error(`hq.css has ${roots} :root rules; this generator understands ${1 + media.length}`);

  // Project and agent colours (src/data/seed.ts).
  const projects = [...seed.matchAll(/\{ key: "([a-z]+)", name: "([^"]+)", prefix: "[^"]+", color: "(#[0-9a-f]{6})"/g)]
    .map((m) => ({ key: m[1], name: m[2], color: m[3] }));
  const agentList = seed.slice(seed.indexOf("export const AGENTS"), seed.indexOf("];", seed.indexOf("export const AGENTS")));
  const agents = [...agentList.matchAll(/\{ id: "([a-z]+)", name: "([^"]+)",[^\n]*?color: "(#[0-9a-f]{6})"/g)]
    .map((m) => ({ key: m[1], name: m[2], color: m[3] }));
  if (projects.length !== 5 || agents.length !== 6) throw new Error(`expected 5 projects and 6 agents, found ${projects.length} and ${agents.length}`);

  const durations = dark.filter(([k]) => k.startsWith("--dur-")).map(([k]) => [k, "0ms"]);
  const pj = projects.map((p) => [`--pj-${p.key}`, p.color]);
  const short = APPROVED.slice(0, 7);

  const css = sealed(`/* HQ design tokens. GENERATED by design/hq-tokens/generate.mjs from the approved Engineering HQ prototype
 * (design/ui-prototypes/engineering-hq at ${short}). Do not edit by hand: change the prototype, have it approved,
 * set APPROVED in the generator and run it again.
 * values sha256 0000000000000000000000000000000000000000000000000000000000000000 (tests/hq-tokens.test.ts checks it)
 *
 * Inert unless <html data-ui="hq">. Every rule is scoped to ${HQ} and every declaration is an --hq-* custom
 * property, so nothing here can match Classic or change one of Classic's own variables. HQ follows Classic's theme
 * (data-theme dark, light or system) and adds no theme setting of its own. Fonts are names only here: src/hq/fonts/fonts.css loads Geist and Geist Mono.
 * tests/hq-tokens.test.ts and e2e/hq-tokens.spec.ts hold these rules.
 *
 * Not here yet: the prototype's dark islands (.term and .slack-phone keep the dark tokens in Light), for the screens
 * that port them. Added here, not in the prototype: the reduced-motion rule at the end. The production build
 * minifies values (120ms becomes .12s, #ffffff becomes #fff): read them in code as CSS strings, never parse them. */

/* Dark, the default: ${dark.length} tokens from hq.css, then the ${pj.length} project colours from data/seed.ts. */
${rule(HQ, [...dark, ...pj])}
/* Light: ${light.length} values from theme-light.css. */
${rule(`${HQ}[data-theme="light"]`, light)}
/* System: the same light values when the computer is in light mode. */
@media (prefers-color-scheme: light) {
${rule(`${HQ}[data-theme="system"]`, light, "  ")}}
${media.map(([q, d]) => `\n/* Narrow windows (hq.css). */\n@media ${q} {\n${rule(HQ, d, "  ")}}\n`).join("")}
/* Reduced motion (a Classic-side addition): HQ's own durations become instant. Classic's rule already stops every
 * animation; the prototype does it per element instead. */
@media (prefers-reduced-motion: reduce) {
${rule(HQ, durations, "  ")}}
`);

  const entry = (x) => `  ${x.key}: "${x.color}", // ${x.name}`;
  const ts = sealed(`// GENERATED by design/hq-tokens/generate.mjs from the approved Engineering HQ prototype (design/ui-prototypes/
// engineering-hq/src/data/seed.ts at ${short}). Do not edit by hand.
// values sha256 0000000000000000000000000000000000000000000000000000000000000000 (tests/hq-tokens.test.ts checks it)
//
// HQ's project and agent colours as values, for code that cannot use CSS (charts, canvas). CSS uses
// var(--hq-pj-<key>) from tokens.css. Classic's own project colours (--pj-* in styles/tokens.css) are separate.

export const HQ_PROJECT_COLORS = {
${projects.map(entry).join("\n")}
} as const;

export const HQ_AGENT_COLORS = {
${agents.map(entry).join("\n")}
} as const;

export type HqProjectKey = keyof typeof HQ_PROJECT_COLORS;
export type HqAgentId = keyof typeof HQ_AGENT_COLORS;
`);
  return { css, ts };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  if (!haveApproved()) {
    console.error(`The approved design commit ${APPROVED.slice(0, 7)} is not in this clone. It is on the prototype's branch:\n` +
      `  git fetch origin claude/project-thread-gs2u2h`);
    process.exit(MISSING);
  }
  const { css, ts } = generate();
  if (process.argv.includes("--check")) {
    const stale = [[OUT_CSS, css], [OUT_TS, ts]].filter(([f, want]) => !fs.existsSync(f) || fs.readFileSync(f, "utf8") !== want);
    for (const [f] of stale) console.error(`${path.relative(ROOT, f)} does not match ${APPROVED.slice(0, 7)}: run node design/hq-tokens/generate.mjs`);
    process.exit(stale.length ? 1 : 0);
  }
  fs.mkdirSync(path.dirname(OUT_CSS), { recursive: true });
  fs.writeFileSync(OUT_CSS, css);
  fs.writeFileSync(OUT_TS, ts);
  console.log(`wrote ${path.relative(ROOT, OUT_CSS)} and ${path.relative(ROOT, OUT_TS)} from ${APPROVED.slice(0, 7)}`);
}
