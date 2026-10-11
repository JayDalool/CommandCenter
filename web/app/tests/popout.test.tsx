/**
 * A popped-out terminal window: End Session asks in the app's own dialog (never window.confirm),
 * Cancel / Esc keep the session, confirming ends it once.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("../src/lib/router", async (orig) => ({
  ...(await orig<typeof import("../src/lib/router")>()),
  useRoute: () => ({ screen: "pane", id: "t:SV-071/project", query: {} }),
}));
vi.mock("../src/workspace/Room", async (orig) => ({
  ...(await orig<typeof import("../src/workspace/Room")>()),
  PaneBody: () => <div>terminal</div>,
  useWsProjects: () => ({ rows: [{ key: "samvision", name: "SamVision", prefix: "SV", root: "/srv/x", exists: true, branch: "main",
    github: null, coordinator: null }], err: null }),
}));

import { PaneWindow } from "../src/screens/Popout";
import { app } from "../src/store/app";
import { openRoom, popPaneState } from "../src/workspace/rooms";

beforeEach(() => {
  openRoom("1", { kind: "task", project: "samvision", key: "SV-071", tools: ["claude", "project"] });
  popPaneState("t:SV-071", "project");
});
afterEach(() => vi.restoreAllMocks());

it("End Session asks in the app's dialog; Cancel and Esc keep the session, confirm ends it once", async () => {
  const native = vi.spyOn(window, "confirm");
  const close = vi.spyOn(app.api, "ptyClose").mockResolvedValue({ ok: true } as never);
  render(<PaneWindow />);
  const end = screen.getByRole("button", { name: "End Session" });

  fireEvent.click(end);
  expect(screen.getByRole("dialog", { name: "End the Project session?" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();

  fireEvent.click(end);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(close).not.toHaveBeenCalled();

  fireEvent.click(end);
  fireEvent.click(screen.getByRole("button", { name: "End session" }));
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  expect(close.mock.calls[0][0]).toMatch(/SV-071/);
  await waitFor(() => expect(screen.getByRole("button", { name: "End Session" })).toBeDisabled());
  expect(native).not.toHaveBeenCalled();
});
