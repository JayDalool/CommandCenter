import { render, screen, waitFor, act, within } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { Projects, resetRegistryCache } from "../src/screens/Projects";
import { AppShell } from "../src/components/Shell";
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
  expect(hrefOf("Open Workspace")).toBe(`#/workspace?project=${p.key}`);
  expect(hrefOf("Claude")).toBe(`#/workspace?project=${p.key}&tab=claude`);
  expect(hrefOf("Repo shell")).toBe(`#/workspace?project=${p.key}&tab=repo`);
  expect(hrefOf("Source control")).toBe(`#/workspace?project=${p.key}&view=scm`);
  expect(hrefOf("Development")).toBe(`#/development?project=${p.key}`);
  expect(p.repoUrl).toBeTruthy();
  const gh = screen.getByRole("link", { name: "GitHub ↗" });
  expect(gh.getAttribute("href")).toMatch(/^https:\/\/github\.com\//);
  expect(gh.getAttribute("rel")).toBe("noopener noreferrer");
  expect(gh.getAttribute("target")).toBe("_blank");
  expect(screen.getByRole("button", { name: "New ticket" })).toBeTruthy();
  expect(container.querySelector('a[href^="#/workspaces"]')).toBeNull();
  expect(screen.queryByText("Workspace access")).toBeNull();
});

it("commandcenter: same bar from the registry, fetched once", async () => {
  location.hash = "#/projects/commandcenter";
  const { container } = render(<Projects />);
  expect(hrefOf("Open Workspace")).toBe("#/workspace?project=commandcenter");
  expect(hrefOf("Claude")).toBe("#/workspace?project=commandcenter&tab=claude");
  expect(hrefOf("Repo shell")).toBe("#/workspace?project=commandcenter&tab=repo");
  expect(hrefOf("Source control")).toBe("#/workspace?project=commandcenter&view=scm");
  expect(hrefOf("Development")).toBe("#/development?project=commandcenter");
  const gh = await screen.findByRole("link", { name: "GitHub ↗" });
  expect(gh.getAttribute("href")).toBe("https://github.com/JayDalool/CommandCenter");
  expect(gh.getAttribute("rel")).toBe("noopener noreferrer");
  await waitFor(() => expect(screen.getByText("cc-coord")).toBeTruthy());
  expect(container.querySelector('a[href^="#/workspaces"]')).toBeNull();
  expect(app.api.workspaceProjects).toHaveBeenCalledTimes(1);
});

it("New ticket preselects the project; a plain cc:new-task event still works", async () => {
  location.hash = "#/tasks";
  render(<AppShell><div /></AppShell>);
  act(() => { window.dispatchEvent(new CustomEvent("cc:new-task", { detail: { project: "commandcenter" } })); });
  const dlg = await screen.findByRole("dialog");
  expect((within(dlg).getByLabelText("Project") as HTMLSelectElement).value).toBe("commandcenter");
  act(() => { window.dispatchEvent(new Event("cc:new-task")); });
  expect(screen.getAllByRole("dialog").length).toBeGreaterThan(0);
});
