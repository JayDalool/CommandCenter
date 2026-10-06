/** Agents shows what matters (project, agent, state, task, model, last activity); herdr detail is one click away. */
import { render, screen, within, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { Agents } from "../src/screens/Agents";
import { buildItems } from "../src/components/CommandPalette";
import { state, tasks } from "./helpers";

beforeEach(() => {
  vi.restoreAllMocks();
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true, taskProjects: t.projects, meta: t.meta });
  location.hash = "#/agents";
});

it("columns are Project · Agent · State · Task · Model · Last activity; pane and session only when expanded", () => {
  render(<Agents />);
  const table = screen.getByRole("table", { name: "Agents" });
  expect(within(table).getAllByRole("columnheader").map((h) => h.textContent))
    .toEqual(["Project", "Agent", "State", "Task", "Model", "Last activity"]);
  expect(within(table).queryByText("wE:p2")).toBeNull();
});

it("a coordinator opens in the Workspace Claude terminal; Focus goes to herdr", () => {
  const focus = vi.spyOn(app.api, "focusAgent").mockResolvedValue({ ok: true });
  location.hash = "#/agents/wE:p2";
  render(<Agents />);
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(location.hash).toBe("#/workspace?project=samvision&tab=claude");
  fireEvent.click(screen.getByRole("button", { name: "Focus" }));
  expect(focus).toHaveBeenCalledWith("wE:p2");
  for (const gone of ["Read tail", "Answer…"]) expect(screen.queryByRole("button", { name: gone })).toBeNull();
});

it("the palette opens a project's Workspace by name and has one label per action", () => {
  const items = buildItems(() => {});
  const labels = items.filter((i) => i.kind === "ACTION").map((i) => i.label);
  expect(labels).toContain("Open SamVision");
  for (const l of ["Open Claude", "Open Project terminal", "Open Server terminal", "Go to file", "Search", "Source Control", "New ticket"])
    expect(labels.filter((x) => x === l), l).toHaveLength(1);
  for (const gone of ["Toggle quick console", "Repo shell", "Server shell", "Claude", "New task"]) expect(labels).not.toContain(gone);
});
