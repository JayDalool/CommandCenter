// Characters and the Professional / Childish style (hq/persona): 30 faces drawn in code, a face of their own for the
// CTO and each project's lead, the same face for the same lead on every page, and none of it in the DOM unless this
// browser's Style is Childish. A face or an emoji is decoration: every status it sits beside is still in words.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { parsePrefs, prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { CAST, Face } from "../src/hq/persona/characters";
import { castFor, castLeads, hash, leadKeys } from "../src/hq/persona/assign";
import type { ChatConversation, ChatOverview } from "../src/api/types";
import { fixture, state, tasks } from "./helpers";

const SNAPSHOT = fixture.state.sources.herdr.lastSnapshotAt! * 1000;
const lead = (name: string): ChatConversation["lead"] => ({ name, state: "ready", status: "idle", running: true, idle: true, paused: false });
const conv = (id: string, name: string, kind: "cto" | "project" = "project"): ChatConversation =>
  ({ id, name, kind, lead: lead(id), unread: 0, waiting: 0, last: null, nudges: { count: 0, lastAt: null } });
const OVERVIEW: ChatOverview = { canStart: true, unread: 0, limits: { text: 16000, fileBytes: 20 << 20, filesPerMessage: 10 },
  conversations: [conv("cto", "CTO", "cto"), conv("samvision", "SamVision"), conv("gauzemate", "GauzeMate")] };

function load() {
  const t = tasks(), now = SNAPSHOT + 10_000;
  vi.useFakeTimers({ toFake: ["Date"], now });
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: now, tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta, conn: { status: "live", lastMessageAt: now, attempt: 0 } });
}
async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  for (let i = 0; i < 4; i++) await act(async () => {});
  return document.querySelector<HTMLElement>("#main")!;
}
const faces = (el: ParentNode) => [...el.querySelectorAll<SVGElement>(".hq-face")];
const who = (el: ParentNode) => el.querySelector<SVGElement>(".hq-face")?.dataset.character;

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  vi.spyOn(app.api, "chat").mockResolvedValue(OVERVIEW);
  prefs.patch({ ui: "hq", style: "professional" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional" }); });

describe("the cast", () => {
  it("has 30 characters, each with its own id, name and look", () => {
    expect(CAST).toHaveLength(30);
    expect(new Set(CAST.map((c) => c.id)).size).toBe(30);
    expect(new Set(CAST.map((c) => c.name)).size).toBe(30);
    expect(new Set(CAST.map((c) => [c.hue, c.head, c.top, c.eyes, c.mouth].join())).size).toBe(30);
  });

  it("draws every character as a picture screen readers skip, with a tooltip when it is given one", () => {
    for (const c of CAST) {
      const { container, unmount } = render(<Face who={c} size={40} title={`${c.name}, the face of the CTO`} />);
      const svg = container.querySelector("svg.hq-face")!;
      expect(svg, c.id).toHaveAttribute("aria-hidden", "true");
      expect(svg.hasAttribute("role") || svg.hasAttribute("aria-label"), c.id).toBe(false);
      expect(svg.querySelector("title")?.textContent, c.id).toBe(`${c.name}, the face of the CTO`);
      expect(svg.getAttribute("width"), c.id).toBe("40");
      expect(svg.children.length, c.id).toBeGreaterThan(3);
      unmount();
    }
    const { container } = render(<Face who={CAST[0]} />);
    expect(container.querySelector("title")).toBeNull();
  });
});

describe("who gets which character", () => {
  it("gives the CTO and every lead a face of their own, whatever order the projects come in", () => {
    const keys = ["samvision", "gauzemate", "gyst", "mfe", "commandcenter"];
    const a = castLeads(keys), b = castLeads([...keys].reverse());
    expect([...a.keys()].sort()).toEqual(["cto", ...keys].sort());
    expect(new Set([...a.values()].map((c) => c.id)).size).toBe(6);
    for (const k of a.keys()) expect(b.get(k)!.id, k).toBe(a.get(k)!.id);
  });

  it("keeps leads apart while there are faces left, and still answers when there are not", () => {
    const many = Array.from({ length: 29 }, (_, i) => `project-${i}`);
    expect(new Set([...castLeads(many).values()].map((c) => c.id)).size).toBe(30);
    const more = castLeads(Array.from({ length: 45 }, (_, i) => `project-${i}`));
    expect(more.size).toBe(46);
    expect([...more.values()].every((c) => CAST.includes(c))).toBe(true);
  });

  it("casts leads from every project list the server sends, each key once", () => {
    const keys = leadKeys({ taskProjects: [{ key: "samvision" }, { key: "commandcenter" }],
      state: { projectsConfig: [{ key: "samvision" }, { key: "gyst" }], projects: [{ key: "gyst" }, { key: "mfe" }] } });
    expect(keys).toEqual(["samvision", "commandcenter", "samvision", "gyst", "gyst", "mfe"]);
    expect([...castLeads(keys).keys()].sort()).toEqual(["commandcenter", "cto", "gyst", "mfe", "samvision"]);
    expect(leadKeys({ taskProjects: [], state: null })).toEqual([]);
  });

  it("gives any other session the same face every time, by its name", () => {
    expect(castFor("sv-071")).toBe(castFor("SV-071"));
    expect(castFor("sv-071")).toBe(CAST[hash("agent:sv-071") % CAST.length]);
    expect(hash("")).toBe(0x811c9dc5);
  });
});

describe("the Style preference", () => {
  it("is Professional unless the stored value is exactly \"childish\"", () => {
    expect(parsePrefs(null).style).toBe("professional");
    for (const bad of ['"Childish"', "1", "true", "null", '"fun"', '["childish"]']) expect(parsePrefs(`{"style":${bad}}`).style, bad).toBe("professional");
    expect(parsePrefs('{"style":"childish"}').style).toBe("childish");
  });

  it("Settings › Appearance switches it and shows the cast", async () => {
    load();
    const page = await show("#/settings?tab=appearance");
    const group = within(page).getByRole("group", { name: "Style" });
    expect(within(group).getByRole("button", { name: "Professional" })).toHaveAttribute("aria-pressed", "true");
    expect(faces(page)).toHaveLength(0);
    fireEvent.click(within(group).getByRole("button", { name: "Childish" }));
    expect(prefs.get().style).toBe("childish");
    expect(faces(page).map((f) => f.dataset.character)).toEqual(CAST.map((c) => c.id));
    fireEvent.click(within(group).getByRole("button", { name: "Professional" }));
    expect(prefs.get().style).toBe("professional");
    expect(faces(page)).toHaveLength(0);
  });
});

describe("faces on the pages", () => {
  it("Professional shows no face and no emoji anywhere", async () => {
    load();
    for (const h of ["#/dashboard", "#/agents", "#/messages"]) {
      const main = await show(h);
      expect(main.querySelector(".hq-page"), h).not.toBeNull();
      expect(main.querySelectorAll(".hq-face, .hq-fun"), h).toHaveLength(0);
      cleanup();
    }
  });

  it("Teams gives every session a face, and keeps each status in words", async () => {
    load();
    prefs.patch({ style: "childish" });
    const main = await show("#/agents");
    const cards = [...main.querySelectorAll<HTMLElement>("a.hq-sess")];
    expect(cards).toHaveLength(app.store.get().state!.agents.length);
    for (const c of cards) {
      expect(faces(c), c.textContent ?? "").toHaveLength(1);
      expect(c.querySelector(".hq-pill")!.textContent).toMatch(/Working|Waiting for Jay|Idle|Offline|Unknown/);
      expect(c.querySelector(".hq-fun")).toHaveAttribute("aria-hidden", "true");
    }
    const leads = cards.filter((c) => c.classList.contains("is-lead")).map(who);
    expect(leads.length).toBeGreaterThan(1);
    expect(new Set(leads).size).toBe(leads.length);
  });

  it("a lead has the same face in My Office, Teams and Messages", async () => {
    load();
    prefs.patch({ style: "childish" });
    const expected = castLeads(leadKeys(app.store.get()));
    let main = await show("#/agents");
    const team = who(main.querySelector(".hq-sess.is-lead")!);
    const key = [...expected].find(([, c]) => c.id === team)![0];
    expect(["samvision", "gauzemate"]).toContain(key);
    cleanup();

    main = await show("#/dashboard");
    const card = [...main.querySelectorAll<HTMLElement>(".hq-proj")].find((p) => who(p) === team);
    expect(card?.querySelector(".hq-proj-lead")).toHaveTextContent(`Lead: ${key}`);
    expect(faces(main.querySelector(".hq-sess-grid")!).map((f) => f.dataset.character)).toContain(team);
    cleanup();

    main = await show("#/messages");
    const rows = within(within(main).getByRole("navigation", { name: "Conversations" })).getAllByRole("button");
    expect(rows.map(who)).toEqual(["cto", "samvision", "gauzemate"].map((k) => expected.get(k)!.id));
    expect(who(rows[["cto", "samvision", "gauzemate"].indexOf(key)])).toBe(team);
    expect(main.querySelector(".hq-chat-av")).toBeNull();
    // a face adds nothing to the name a screen reader gives the row
    expect(within(main).getByRole("button", { name: /^SamVision lead/ })).toBe(rows[1]);
    expect(rows.some((r) => /face of/.test(r.getAttribute("aria-label") ?? ""))).toBe(false);
  });

  it("a lead keeps its own face when it is only in the polled list, not the task registry", async () => {
    load();
    prefs.patch({ style: "childish" });
    app.store.set((d) => ({ ...d, taskProjects: d.taskProjects.filter((p) => p.key !== "samvision") }));
    expect(app.store.get().state!.projects.some((p) => p.key === "samvision")).toBe(true);
    const main = await show("#/agents");
    const expected = castLeads(leadKeys(app.store.get())).get("samvision")!.id;
    const card = [...main.querySelectorAll<HTMLElement>(".hq-sess.is-lead")].find((c) => c.querySelector("b")?.textContent === "samvision")!;
    expect(who(card)).toBe(expected);
  });
});
