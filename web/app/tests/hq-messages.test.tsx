// Messages (hq/pages/Messages.tsx, server ccd/leadchat.py): conversations with the CTO and each project lead. The page
// reads and writes only through the chat API; images come in as blobs of the type the server stored; a lead that is
// not running can be started, and an over-budget start asks first.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import type { ChatConversation, ChatMessage, ChatOverview } from "../src/api/types";
import { state, tasks } from "./helpers";

const lead = (o: Partial<ChatConversation["lead"]> = {}): ChatConversation["lead"] =>
  ({ name: "samvision", state: "ready", status: "idle", running: true, idle: true, paused: false, ...o });
const conv = (o: Partial<ChatConversation>): ChatConversation => ({ id: "samvision", name: "SamVision", kind: "project",
  lead: lead(), unread: 0, waiting: 0, last: null, nudges: { count: 0, lastAt: null }, ...o });
const OVERVIEW: ChatOverview = {
  canStart: true, unread: 1, limits: { text: 16000, fileBytes: 20 << 20, filesPerMessage: 10 },
  conversations: [
    conv({ id: "cto", name: "CTO", kind: "cto", lead: lead({ name: "cto", state: "none", status: null, running: false, idle: false }), waiting: 1 }),
    conv({ unread: 1, last: { id: 2, side: "lead", author: "agent:lead-samvision", at: 1793098000, via: "cli", text: "Here is the diagram", files: 1 } }),
    conv({ id: "gauzemate", name: "GauzeMate", lead: lead({ name: "gauzemate", paused: true }) }),
  ],
};
const PNG = { id: "a".repeat(32), conversation: "samvision", messageId: 2, side: "lead" as const, name: "flow.png", kind: "image" as const,
  mime: "image/png", size: 2048, sha256: "x", uploadedAt: 0, uploadedBy: "agent:lead-samvision" };
const MSGS: ChatMessage[] = [
  { id: 1, conversation: "samvision", side: "jay", author: "jay", text: "Draw the auth flow", via: "app", ref: null, replyTo: null, at: 1793097000, seenAt: 1793097100, files: [] },
  { id: 2, conversation: "samvision", side: "lead", author: "agent:lead-samvision", text: "Here is the diagram", via: "cli", ref: null, replyTo: 1, at: 1793098000, seenAt: null, files: [PNG] },
];

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: { ...state(), chat: { unread: 1 } }, stateAt: Date.now(), tickets: t.tickets,
    ticketsLoaded: true, taskProjects: t.projects, meta: t.meta });
}

async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  const v = render(<App />);
  for (let i = 0; i < 4; i++) await act(async () => {});
  return v.container;
}

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  vi.spyOn(app.api, "chat").mockResolvedValue(OVERVIEW);
  vi.spyOn(app.api, "chatHistory").mockResolvedValue({ conversation: "samvision", messages: MSGS, lead: lead() });
  vi.spyOn(app.api, "chatSeen").mockResolvedValue({ ok: true, seen: 1 });
  vi.spyOn(app.api, "chatFileBlob").mockResolvedValue(new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" }));
  URL.createObjectURL = vi.fn(() => "blob:img-1");
  URL.revokeObjectURL = vi.fn();
  prefs.patch({ ui: "hq", theme: "dark" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", theme: "dark" }); });

describe("Messages", () => {
  it("lists the CTO and each lead, with unread counts and who is running", async () => {
    load();
    const c = await show("#/messages");
    const list = within(c).getByRole("navigation", { name: "Conversations" });
    const rows = within(list).getAllByRole("button");
    expect(rows.map((r) => r.querySelector("b")!.textContent)).toEqual(["CTO", "SamVision lead", "GauzeMate lead"]);
    expect(rows[0]).toHaveTextContent("Not running");
    expect(within(rows[1]).getByLabelText("1 unread")).toBeInTheDocument();
    expect(rows[2]).toHaveTextContent("Paused");
    const nav = within(c).getByRole("navigation", { name: "Screens" });
    expect(within(nav).getByRole("link", { name: /Messages/ })).toHaveTextContent("1");
  });

  it("shows the thread, an image from its blob, and marks the lead's reply read", async () => {
    load();
    const c = await show("#/messages?c=samvision");
    const thread = within(c).getByRole("region", { name: "Conversation with the SamVision lead" });
    expect(thread).toHaveTextContent("Draw the auth flow");
    expect(thread).toHaveTextContent("Read");
    const img = within(thread).getByRole("img", { name: "flow.png" });
    expect(img).toHaveAttribute("src", "blob:img-1");
    expect(app.api.chatFileBlob).toHaveBeenCalledWith(PNG);
    expect(app.api.chatSeen).toHaveBeenCalledWith("samvision", 2);
  });

  it("sends with Enter and says how it was delivered", async () => {
    load();
    const sent: ChatMessage = { ...MSGS[0], id: 3, text: "Thanks", seenAt: null };
    const send = vi.spyOn(app.api, "chatSend").mockResolvedValue({ ok: true, message: sent, delivery: "queued" });
    const c = await show("#/messages?c=samvision");
    const box = within(c).getByRole("textbox", { name: "Message the SamVision lead" });
    fireEvent.change(box, { target: { value: "Thanks" } });
    await act(async () => { fireEvent.keyDown(box, { key: "Enter" }); });
    expect(send).toHaveBeenCalledWith("samvision", "Thanks", []);
    const thread = within(c).getByRole("region", { name: "Conversation with the SamVision lead" });
    expect(thread.querySelector(".hq-chat-notice")).toHaveTextContent("busy and will be told when it is free");
    expect(box).toHaveValue("");
  });

  it("starts a stopped lead, asking first when that goes over budget", async () => {
    load();
    vi.spyOn(app.api, "chatHistory").mockResolvedValue({ conversation: "cto", messages: [], lead: OVERVIEW.conversations[0].lead });
    const start = vi.spyOn(app.api, "chatStart")
      .mockResolvedValueOnce({ ok: false, needsApproval: true, overBudget: [{ scope: "company", key: "*", period: "month", limitUsd: 300, assessedUsd: 320, pct: 106.7, holdReason: "limit" }] })
      .mockResolvedValueOnce({ ok: true, started: true, delivery: "nudged" });
    const c = await show("#/messages?c=cto");
    const thread = within(c).getByRole("region", { name: "Conversation with the CTO" });
    expect(thread).toHaveTextContent("The CTO is not running. 1 message waits for it.");
    await act(async () => { fireEvent.click(within(thread).getByRole("button", { name: "Start it" })); });
    const ask = within(thread).getByRole("alertdialog", { name: "Over budget" });
    expect(ask).toHaveTextContent("Company month: 106.7% of $300");
    await act(async () => { fireEvent.click(within(ask).getByRole("button", { name: "Start anyway" })); });
    expect(start.mock.calls).toEqual([["cto", false], ["cto", true]]);
    expect(thread.querySelector(".hq-chat-notice")).toHaveTextContent("The CTO is starting");
  });

  it("says when Messages is not set up on the server", async () => {
    load();
    const { ApiError } = await import("../src/api/client");
    vi.spyOn(app.api, "chat").mockRejectedValue(new ApiError(503, "Messages is not configured"));
    const c = await show("#/messages");
    expect(within(c).getByRole("alert")).toHaveTextContent("Messages is not set up on this server yet.");
  });
});
