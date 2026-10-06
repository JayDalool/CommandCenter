import { render, screen, waitFor, act, within, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { Projects, resetRegistryCache } from "../src/screens/Projects";
import { AppShell } from "../src/components/Shell";
import { prefs } from "../src/lib/prefs";
import { state, tasks } from "./helpers";

const reg = [{ key: "commandcenter", name: "Command Center", prefix: "CC", root: "/srv/cc", exists: true, branch: "main",
  github: { owner: "JayDalool", repo: "CommandCenter", slug: "JayDalool/CommandCenter", url: "https://github.com/JayDalool/CommandCenter" },
  coordinator: { id: "p1", name: "cc-coord", status: "idle", cwd: "/srv/cc" } }];

beforeEach(() => {
  resetRegistryCache();
  const t = tasks();
  const s = state();
  app.store.set({ ...initial, auth: "ok", state: s, stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: [...t.projects, { key: "commandcenter", name: "Command Center" } as never], meta: t.meta });
  vi.spyOn(app.api, "workspaceProjects").mockResolvedValue({ projects: reg });
});

const hrefOf = (name: string) => screen.getByRole("link", { name }).getAttribute("href");

it("polled project: action bar routes, safe GitHub link, no herdr workspaces link", () => {
  const s = state(); s.projects[0].repoUrl = "https://github.com/JayDalool/SamVision";
  app.store.set({ ...app.store.get(), state: s });
  const p = s.projects[0];
  location.hash = `#/projects/${p.key}`;
  const { container } = render(<Projects />);
  expect(screen.getByRole("region", { name: "Project actions" })).toBeTruthy();
  // Primary: Open Workspace, Tasks, Development, GitHub. Everything else is under ⋯.
  expect(hrefOf("Open Workspace")).toBe(`#/workspace?project=${p.key}`);
  expect(hrefOf("Tasks")).toBe(`#/tasks?project=${p.key}`);
  expect(hrefOf("Development")).toBe(`#/development?project=${p.key}`);
  const bar = screen.getByRole("region", { name: "Project actions" });
  expect(within(bar).getAllByRole("link").map((a) => a.textContent)).toEqual(["Open Workspace", "Tasks", "Development", "GitHub ↗"]);
  fireEvent.click(screen.getByRole("button", { name: "More project actions" }));
  expect(screen.getByRole("menuitem", { name: "Open Claude" }).getAttribute("href")).toBe(`#/workspace?project=${p.key}&tab=claude`);
  expect(screen.getByRole("menuitem", { name: "Open Project terminal" }).getAttribute("href")).toBe(`#/workspace?project=${p.key}&tab=repo`);
  expect(p.repoUrl).toBeTruthy();
  const gh = screen.getByRole("link", { name: "GitHub ↗" });
  expect(gh.getAttribute("href")).toMatch(/^https:\/\/github\.com\//);
  expect(gh.getAttribute("rel")).toBe("noopener noreferrer");
  expect(gh.getAttribute("target")).toBe("_blank");
  expect(screen.getByRole("menuitem", { name: "New ticket" })).toBeTruthy();
  expect(container.querySelector('a[href^="#/workspaces"]')).toBeNull();
  expect(screen.queryByText("Workspace access")).toBeNull();
});

it("commandcenter: same bar from the registry, fetched once", async () => {
  location.hash = "#/projects/commandcenter";
  const { container } = render(<Projects />);
  expect(hrefOf("Open Workspace")).toBe("#/workspace?project=commandcenter");
  expect(hrefOf("Tasks")).toBe("#/tasks?project=commandcenter");
  expect(hrefOf("Development")).toBe("#/development?project=commandcenter");
  const gh = await screen.findByRole("link", { name: "GitHub ↗" });
  expect(gh.getAttribute("href")).toBe("https://github.com/JayDalool/CommandCenter");
  expect(gh.getAttribute("rel")).toBe("noopener noreferrer");
  await waitFor(() => expect(screen.getByText("cc-coord")).toBeTruthy());
  expect(container.querySelector('a[href^="#/workspaces"]')).toBeNull();
  expect(app.api.workspaceProjects).toHaveBeenCalledTimes(1);
});

it("New ticket preselects the project; a plain cc:new-task falls back; a second detail retargets", async () => {
  location.hash = "#/tasks";
  render(<AppShell><div /></AppShell>);
  const select = () => within(screen.getByRole("dialog")).getByLabelText("Project") as HTMLSelectElement;
  act(() => { window.dispatchEvent(new CustomEvent("cc:new-task", { detail: { project: "commandcenter" } })); });
  await screen.findByRole("dialog");
  expect(select().value).toBe("commandcenter");
  const other = app.store.get().taskProjects.find((p) => p.key !== "commandcenter")!.key;
  act(() => { window.dispatchEvent(new CustomEvent("cc:new-task", { detail: { project: other } })); });
  expect(select().value).toBe(other);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  prefs.patch({ lastProject: null } as never);
  act(() => { window.dispatchEvent(new Event("cc:new-task")); });
  await screen.findByRole("dialog");
  expect(select().value).toBe(app.store.get().taskProjects[0].key);
});

it("commandcenter: live coordinator status comes from /api/state, not the registry; registry failure shows an error", async () => {
  vi.mocked(app.api.workspaceProjects).mockRejectedValue(new Error("boom"));
  const s = state();
  s.coordinators.commandcenter = { name: "cc-live", status: "working", paneId: "w:9" } as never;
  app.store.set({ ...app.store.get(), state: s });
  location.hash = "#/projects/commandcenter";
  render(<Projects />);
  expect(screen.getByText("cc-live")).toBeTruthy();
  expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  expect(screen.queryByRole("link", { name: "GitHub ↗" })).toBeNull();
});
