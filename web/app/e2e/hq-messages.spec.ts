// An open conversation in Messages, in a real browser: who it is with at the top, a line for each new day, and in
// Childish mode the lead's face beside its messages. Everything fits a desktop and a phone, and reading sends nothing
// (every message here is already read).
import { test, expect, open, problems, NOW } from "./fixture";

test.use({ ui: "hq" });

const S = Math.floor(NOW / 1000), DAY = 86400;
const wide = () => document.documentElement.scrollWidth <= window.innerWidth;
const lead = { name: "samvision", state: "ready", status: "idle", running: true, idle: true, paused: false };
const conv = (id: string, name: string, kind: "cto" | "project") => ({ id, name, kind, lead: { ...lead, name: id }, unread: 0, waiting: 0, last: null, nudges: { count: 0, lastAt: null } });
const msg = (id: number, side: "jay" | "lead", at: number, text: string) => ({ id, conversation: "samvision", side, author: side === "jay" ? "jay" : "agent:lead-samvision",
  text, via: side === "jay" ? "app" : "cli", ref: null, replyTo: null, at, seenAt: at + 60, files: [] });
const MSGS = [
  msg(1, "jay", S - 2 * DAY, "Where are we on the valuation layout?"),
  msg(2, "lead", S - 2 * DAY + 240, "The desktop layout is merged. The phone version is in review, with two small findings left, and it will be ready for your check tomorrow."),
  msg(3, "lead", S - 2 * DAY + 300, "Nothing is blocked."),
  msg(4, "jay", S - DAY, "Good. Also set up the staging back end."),
  msg(5, "lead", S - 600, "Staging is up. The checks pass on main."),
];

test("an open conversation: who it is with, a line per day, the lead's face beside its messages, at desktop and phone width", async ({ page, watch }) => {
  await page.route("**/api/chat", (r) => r.fulfill({ json: { canStart: false, unread: 0, limits: { text: 16000, fileBytes: 20971520, filesPerMessage: 10 },
    conversations: [conv("cto", "CTO", "cto"), conv("samvision", "SamVision", "project")] } }));
  await page.route("**/api/chat/samvision", (r) => r.fulfill({ json: { conversation: "samvision", messages: MSGS, lead } }));
  await page.addInitScript(() => {
    const p = JSON.parse(localStorage.getItem("cc.prefs") ?? "{}");
    localStorage.setItem("cc.prefs", JSON.stringify({ ...p, ui: "hq", style: "childish" }));
  });

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await open(page, "messages?c=samvision");
    const thread = page.getByRole("region", { name: "Conversation with the SamVision lead" });
    const log = thread.getByRole("log");
    await expect(log.locator(".hq-msg")).toHaveCount(5);
    await expect(log.locator(".hq-chat-day")).toHaveText([/^\w{3}, \w{3} \d+$/, "Yesterday", "Today"]);

    // the face at the top is beside the name, and both are inside the header
    const head = await thread.locator(".hq-chat-head").evaluate((h) => {
      const f = h.querySelector(".hq-face")!.getBoundingClientRect(), t = h.querySelector("h3")!.getBoundingClientRect(), b = h.getBoundingClientRect();
      return f.width === 36 && f.height === 36 && f.right <= t.left && f.left >= b.left && t.right <= b.right;
    });
    expect(head, `header at ${width}`).toBe(true);

    // a face beside the first message of each run of the lead's; every one of its bubbles starts right of the gutter
    await expect(log.locator(".hq-msg-face .hq-face")).toHaveCount(2);
    const fit = await log.evaluate((l) => {
      const box = l.getBoundingClientRect();
      return [...l.querySelectorAll(".hq-msg.is-lead")].every((m) => {
        const g = m.querySelector(".hq-msg-face")!.getBoundingClientRect(), b = m.querySelector(".hq-msg-bubble")!.getBoundingClientRect(), f = m.querySelector("footer")!.getBoundingClientRect();
        return g.left >= box.left && g.right <= b.left && f.left === b.left && b.right <= box.right + 0.5;
      }) && [...l.querySelectorAll(".hq-msg.is-me")].every((m) => !m.querySelector(".hq-msg-face") && m.getBoundingClientRect().right <= box.right + 0.5);
    });
    expect(fit, `messages at ${width}`).toBe(true);
    expect(await page.evaluate(wide), `${width}`).toBe(true);
  }
  expect(await problems(page, watch)).toEqual([]);
});

test("who can answer now: the counts above the list fit a desktop and a phone, and a count filters the list", async ({ page, watch }) => {
  const off = { state: "none", status: null, running: false, idle: false };
  const at = (id: string, name: string, l: Record<string, unknown>, extra: Record<string, unknown> = {}) =>
    ({ ...conv(id, name, id === "cto" ? "cto" : "project"), lead: { ...lead, name: id, ...l }, ...extra });
  await page.route("**/api/chat", (r) => r.fulfill({ json: { canStart: false, unread: 2, limits: { text: 16000, fileBytes: 20971520, filesPerMessage: 10 },
    conversations: [at("cto", "CTO", off), at("samvision", "SamVision", {}, { unread: 2 }), at("gyst", "GYST", { status: "working", idle: false }),
      at("mfe", "MFE", { status: "blocked", idle: false }), at("commandcenter", "CommandCenter", off)] } }));

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await open(page, "messages");
    const sum = page.getByRole("group", { name: "Show conversations by who can answer now" });
    await expect(sum.getByRole("button")).toHaveText(["Ready 1", "Working 1", "Needs a pane 3"]);
    const rows = page.getByRole("navigation", { name: "Conversations" }).getByRole("button");
    await expect(rows).toHaveCount(5);
    await expect(rows.locator(".hq-pill")).toHaveText(["Not running", "Ready", "Working", "Waiting on you", "Not running"]);
    expect(await page.evaluate(wide)).toBe(true);
    // The unread count stays in its row. With the sidebar as icons (up to 1440 wide) it used to jump to a corner.
    const unread = await rows.nth(1).getByLabel("2 unread").boundingBox(), row = await rows.nth(1).boundingBox();
    expect(unread!.y).toBeGreaterThanOrEqual(row!.y);
    expect(unread!.y + unread!.height).toBeLessThanOrEqual(row!.y + row!.height);
    expect(unread!.x + unread!.width).toBeLessThanOrEqual(row!.x + row!.width);

    await sum.getByRole("button", { name: /Needs a pane/ }).click();
    await expect(rows.locator("b")).toHaveText(["CTO", "MFE lead", "CommandCenter lead"]);
    await sum.getByRole("button", { name: /Needs a pane/ }).click();
    await expect(rows).toHaveCount(5);
  }
  expect(await problems(page, watch)).toEqual([]);
});

// CC-070: Jay's Fresh session press on a running, idle project lead, behind Developer Unlock.
test("Fresh session shows only on a running idle project lead with Developer Unlock, and shows the step that ran", async ({ page, watch }) => {
  const off = { state: "none", status: null, running: false, idle: false };
  const at = (id: string, name: string, kind: "cto" | "project", l: Record<string, unknown> = {}) =>
    ({ ...conv(id, name, kind), lead: { ...lead, name: id, ...l } });
  const busy = { status: "working", idle: false };
  const convs = [at("cto", "CTO", "cto"), at("samvision", "SamVision", "project"), at("gyst", "GYST", "project", off),
    at("mfe", "MFE", "project", busy), at("commandcenter", "CommandCenter", "project", { status: "blocked", idle: false })];
  await page.route("**/api/chat", (r) => r.fulfill({ json: { canStart: false, unread: 0, limits: { text: 16000, fileBytes: 20971520, filesPerMessage: 10 }, conversations: convs } }));
  await page.route(/\/api\/chat\/(samvision|cto|gyst|mfe|commandcenter)$/, (r) => r.fulfill({ json: { conversation: "x", messages: [], lead } }));
  const presses: string[] = [];
  await page.route("**/api/coordinators/fresh", (r) => {
    presses.push(r.request().postData() ?? "");
    const first = presses.length === 1;
    return r.fulfill({ json: first ? { ok: true, project: "samvision", coordinator: "samvision", step: "notes", message: "Asked the lead to write its notes; press again when it says ready." }
      : { ok: false, error: "the lead has not written its ready file yet; press again when it says ready" }, status: first ? 200 : 409 });
  });
  const fresh = (width: number) => page.setViewportSize({ width, height: 844 });
  const button = () => page.getByRole("button", { name: "Fresh session" });

  // locked: no button anywhere
  await open(page, "messages?c=samvision");
  await expect(page.getByRole("region", { name: "Conversation with the SamVision lead" })).toBeVisible();
  await expect(button()).toHaveCount(0);

  // unlocked (a session this browser already holds)
  await page.evaluate(() => sessionStorage.setItem("ccd.dev", JSON.stringify({ id: "e2e_dev_session_not_a_secret_0000000000000", expiresAt: Date.now() / 1000 + 3600 })));
  for (const width of [1440, 390]) {
    await fresh(width);
    await page.reload();
    await expect(button()).toHaveCount(1);
    await expect(button()).toBeVisible();
    expect(await page.evaluate(wide), `${width}`).toBe(true);
  }
  await button().click();
  await expect(page.getByRole("status").filter({ hasText: "press again when it says ready" })).toBeVisible();
  await button().click();
  await expect(page.getByRole("alert").filter({ hasText: "has not written its ready file yet" })).toBeVisible();
  expect(presses.map((p) => JSON.parse(p))).toEqual([{ project: "samvision" }, { project: "samvision" }]);

  // not the CTO conversation, and not a stopped lead (that one shows Start, not Fresh session)
  await open(page, "messages?c=cto");
  await expect(page.getByRole("region", { name: "Conversation with the CTO" })).toBeVisible();
  await expect(button()).toHaveCount(0);
  await open(page, "messages?c=gyst");
  await expect(page.getByRole("region", { name: "Conversation with the GYST lead" })).toBeVisible();
  await expect(button()).toHaveCount(0);
  await expect(page.getByText("is not running")).toBeVisible();
  // a running lead that is busy or waiting for Jay is never offered a clear
  for (const c of ["mfe", "commandcenter"]) {
    await open(page, `messages?c=${c}`);
    await expect(page.getByRole("region", { name: /Conversation with the .* lead/ })).toBeVisible();
    await expect(button()).toHaveCount(0);
  }
  // The browser logs the refused press (409) it was told to expect; nothing else may be wrong.
  expect((await problems(page, watch)).filter((p) => !p.includes("status of 409"))).toEqual([]);
});
