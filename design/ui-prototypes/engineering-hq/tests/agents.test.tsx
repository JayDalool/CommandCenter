// Agent identity and colour consistency (Jay's design decisions, 2026-10-22).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "../src/App";
import { owners } from "../src/windows/manager";
import { chat, feed, setOutage, viewState } from "../src/data/live";
import { AGENTS, INITIAL_AGENT_STATE, PROJECTS, SEED_CHAT, modelLabel, project } from "../src/data/seed";

const go = (h: string) => act(() => { location.hash = h; window.dispatchEvent(new HashChangeEvent("hashchange")); });

beforeEach(() => {
  owners.set({}); viewState.set({}); chat.set(SEED_CHAT); sessionStorage.clear();
  feed.set({ agents: INITIAL_AGENT_STATE, beat: Date.now(), outage: false, source: "demo" });
  vi.stubGlobal("open", vi.fn(() => ({ closed: false, focus: vi.fn(), close: vi.fn() })));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("agent identity", () => {
  it("every team member shows role, model, status, task ID, project and last activity", () => {
    go("#/teams/samvision");
    render(<App />);
    for (const a of AGENTS) {
      const s = INITIAL_AGENT_STATE[a.id];
      const node = screen.getByRole("button", { name: new RegExp(`^${a.name}, `) });
      expect(node).toHaveTextContent(a.role);
      expect(node).toHaveTextContent(modelLabel(s.model));
      expect(node).toHaveTextContent(s.task!);
      expect(node).toHaveTextContent(project(s.project!).name);
      expect(node.querySelector(".am-time")!.textContent).toMatch(/ago|just now/);
      expect(node.querySelector(".pres")).not.toBeNull();
    }
  });

  it("marks every demo status so it never reads as real activity", () => {
    go("#/office");
    render(<App />);
    const statuses = document.querySelectorAll(".agent-card .pres");
    expect(statuses.length).toBe(AGENTS.length);
    statuses.forEach((p) => { expect(p.classList.contains("is-sim")).toBe(true); expect(p.querySelector("abbr.sim")).not.toBeNull(); });
  });

  it("a stale feed shows Unknown with the last-seen time, never Working", () => {
    go("#/teams/samvision");
    render(<App />);
    act(() => setOutage(true));
    const nova = screen.getByRole("button", { name: /^Nova, / });
    expect(nova).toHaveTextContent("Unknown");
    expect(nova).toHaveTextContent(/last seen/);
    expect(nova).not.toHaveTextContent("Working");
  });

  it("a paused project's team shows Paused", () => {
    go("#/teams/gauzemate");
    render(<App />);
    expect(screen.getByRole("button", { name: /^Nova, / })).toHaveTextContent("Paused");
    expect(screen.getByRole("button", { name: /^Nova, / })).not.toHaveTextContent("Working");
  });

  it("clicking an agent opens its inspector with model ID, session and earlier sessions", () => {
    go("#/teams/samvision");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /^Atlas, / }));
    const d = screen.getByRole("dialog", { name: "Agent details" });
    expect(d).toHaveTextContent("Independent Code Reviewer");
    expect(d).toHaveTextContent("gpt-5-codex");
    expect(d).toHaveTextContent("rev-sv-c470");
    expect(d).toHaveTextContent("SV-029");
    fireEvent.click(within(d).getByRole("button", { name: /Earlier sessions/ }));
    expect(d).toHaveTextContent("rev-mf-d3e8");
    fireEvent.click(within(d).getByRole("tab", { name: "Pixel" }));
    expect(d).toHaveTextContent("Blocked");
    expect(d).toHaveTextContent("MFE-014");
    fireEvent.click(within(d).getByRole("button", { name: "Close agent details" }));
    expect(screen.queryByRole("dialog", { name: "Agent details" })).toBeNull();
  });

  it("the conversation header shows the lead's status and model", () => {
    go("#/messages/sv-lead");
    render(<App />);
    const head = document.querySelector(".thread-head")!;
    expect(head).toHaveTextContent("Project Lead");
    expect(head).toHaveTextContent("Claude Opus 5.5");
    expect(head).toHaveTextContent("SV-025");
  });
});

describe("project colours", () => {
  it("each project colour is defined once, in seed.ts, and nowhere else in the source", () => {
    const src = import.meta.glob<string>("../src/**/*.{ts,tsx,css}", { query: "?raw", import: "default", eager: true });
    expect(Object.keys(src).length).toBeGreaterThan(20);
    for (const p of PROJECTS) {
      const hits = Object.entries(src).filter(([, text]) => text.toLowerCase().includes(p.color.toLowerCase())).map(([f]) => f);
      expect(hits, `${p.name} ${p.color}`).toEqual(["../src/data/seed.ts"]);
    }
  });

  it("the app publishes the colours as CSS variables", () => {
    go("#/office");
    render(<App />);
    for (const p of PROJECTS) expect(document.documentElement.style.getPropertyValue(`--pj-${p.key}`)).toBe(p.color);
  });
});
