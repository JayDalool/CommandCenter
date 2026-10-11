/**
 * Source control asks in the app's own dialog, never window.confirm: Discard (danger) and Create branch.
 * Cancel and Esc run nothing; confirming runs the git action once.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { ScmSidebar } from "../src/workspace/SourceControl";
import { app } from "../src/store/app";
import { setDevSession } from "../src/api/developer";
import type { ScmStatus } from "../src/api/types";

const scm = (clean: boolean): ScmStatus => ({ project: "samvision", clean,
  branch: { head: "main", upstream: null, ahead: 0, behind: 0, oid: "abc" },
  staged: [], unstaged: clean ? [] : [{ path: "a.py", orig: null, code: "M", status: ".M", protected: false }],
  untracked: [], conflicts: [] }) as unknown as ScmStatus;

let native: ReturnType<typeof vi.spyOn>;
let git: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  native = vi.spyOn(window, "confirm");
  git = vi.spyOn(app.api, "scm").mockResolvedValue({} as never);
  vi.spyOn(app, "action").mockImplementation(async (fn: () => Promise<unknown>) => { await fn(); return true; });
  setDevSession("s".repeat(43), 3600);   // git actions need Developer Unlock, as in the app
});
afterEach(() => { vi.restoreAllMocks(); setDevSession(null); });

const sidebar = (ticket: { key: string; title: string; branch: string | null } | null = null) =>
  render(<ScmSidebar project="samvision" ticket={ticket} githubUrl={null} prUrl={null} onOpenFile={() => {}} onOpenDiff={() => {}} selected={null} />);

it("Discard asks in a danger dialog; Cancel and Esc keep the file, confirm discards once", async () => {
  vi.spyOn(app.api, "scmStatus").mockResolvedValue(scm(false));
  sidebar();
  const discard = await screen.findByRole("button", { name: "Discard" });
  fireEvent.click(discard);
  expect(screen.getByRole("dialog", { name: "Discard changes?" })).toHaveTextContent("Discard your changes to a.py? This cannot be undone.");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(discard);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(git).not.toHaveBeenCalled();
  fireEvent.click(discard);
  const dlg = screen.getByRole("dialog", { name: "Discard changes?" });
  fireEvent.click(dlg.querySelector<HTMLButtonElement>("button.is-danger")!);
  await waitFor(() => expect(git).toHaveBeenCalledTimes(1));
  expect(git).toHaveBeenCalledWith("discard", { project: "samvision", path: "a.py", confirm: true });
  expect(native).not.toHaveBeenCalled();
});

it("Create branch asks in the dialog (and says uncommitted changes come along); confirm creates it once", async () => {
  vi.spyOn(app.api, "scmStatus").mockResolvedValue(scm(false));
  vi.spyOn(app.api, "scmTicketBranch").mockResolvedValue({ suggested: "SV-071-fix" } as never);
  sidebar({ key: "SV-071", title: "Fix", branch: null });
  const create = await screen.findByRole("button", { name: "Create branch" });
  fireEvent.click(create);
  const dlg = screen.getByRole("dialog", { name: "Create branch?" });
  expect(dlg).toHaveTextContent("Create branch SV-071-fix from main and switch to it? Your uncommitted changes come along; nothing is lost.");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(git).not.toHaveBeenCalled();
  fireEvent.click(create);
  fireEvent.click(screen.getByRole("dialog", { name: "Create branch?" }).querySelector<HTMLButtonElement>("button.is-jay")!);
  await waitFor(() => expect(git).toHaveBeenCalledWith("branch", { project: "samvision", name: "SV-071-fix", ticket: "SV-071" }));
  expect(git).toHaveBeenCalledTimes(1);
  expect(native).not.toHaveBeenCalled();
});
