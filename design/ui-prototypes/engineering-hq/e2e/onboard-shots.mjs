// Walk through New Agent and New Project, screenshotting each major step.
// Usage: node e2e/onboard-shots.mjs [baseUrl] [outDir] [width] [height]
import fs from "node:fs";
import { loadPlaywright } from "./pw.mjs";

const { chromium } = loadPlaywright();
const base = process.argv[2] ?? "http://127.0.0.1:5181/";
const out = process.argv[3] ?? "e2e/out/onboarding";
const W = Number(process.argv[4] ?? 1920), H = Number(process.argv[5] ?? 1080);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: W, height: H } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const shot = async (name) => { await page.waitForTimeout(250); await page.screenshot({ path: `${out}/${name}.png` }); };
const next = () => page.getByRole("button", { name: /^Next:/ }).click();

await page.goto(`${base}?nofeed#/office`);
await page.evaluate(() => { Object.keys(localStorage).filter((k) => k.startsWith("hq.")).forEach((k) => localStorage.removeItem(k)); });
await page.goto(`${base}?nofeed#/agents`); await page.reload();
await page.getByRole("button", { name: "New Agent" }).first().click();
await shot("a0_template");
await page.getByRole("button", { name: "Implementation Agent template" }).click();
await next(); await page.getByLabel("Display name").fill("Mira"); await shot("a1_identity");
await next(); await shot("a2_intelligence");
await next(); await shot("a3_organisation");
await next(); await shot("a4_capabilities");
await next(); await page.getByRole("button", { name: /How effective access/ }).click(); await shot("a5_access");
await next(); await page.getByRole("button", { name: /^Repository/ }).click(); await page.getByRole("button", { name: /^Production/ }).click(); await shot("a6_permissions");
await next(); await shot("a7_instructions");
await next(); await shot("a8_budget");
await next(); await shot("a9_review");
await page.getByRole("button", { name: "Approve & Add Agent" }).click(); await shot("a10_approve_dialog");
await page.getByRole("dialog").getByRole("button", { name: "Approve & Add Agent" }).click();
await page.waitForTimeout(400); await shot("a11_teams_after");

await page.goto(`${base}?nofeed#/teams/samvision`);
await page.getByRole("button", { name: "New Project" }).click();
await page.getByLabel("Project name").fill("Listing Scraper"); await shot("p0_identity");
await next(); await page.getByLabel(/Repository \(owner/).fill("JayDalool/listing-scraper"); await shot("p1_repository");
await next(); await shot("p2_environments");
await next(); await shot("p3_workers");
await next(); await page.getByLabel("Project lead").selectOption("claude"); await shot("p4_team");
await next(); await shot("p5_profile");
await next(); await shot("p6_budget");
await next(); await page.getByRole("button", { name: /Advanced rules/ }).click(); await shot("p7_deploy");
await next(); await shot("p8_review");
await page.getByRole("button", { name: "Approve Mock Project" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Approve Mock Project" }).click();
await page.waitForTimeout(400); await shot("p9_teams_after");
await page.goto(`${base}?nofeed#/topology`); await page.waitForTimeout(600); await shot("p10_topology_after");
await page.goto(`${base}?nofeed#/office`); await page.waitForTimeout(500); await shot("p11_office_after");
await page.goto(`${base}?nofeed#/agents`); await page.waitForTimeout(300); await shot("p12_agents_after");
await page.getByRole("button", { name: /^Mira, / }).click(); await shot("a12_inspector_new");
console.log(errors.length ? `ERRORS:\n${errors.join("\n")}` : "no console errors");
await browser.close();
