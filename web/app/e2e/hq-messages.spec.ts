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
