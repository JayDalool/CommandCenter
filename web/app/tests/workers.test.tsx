/** Settings → Workers: the server node and enrolled nodes; approve/revoke need Developer Mode. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { Workers } from "../src/components/Workers";
import { setDevSession } from "../src/api/developer";
import type { WorkersState } from "../src/api/types";

const now = Date.now() / 1000;
const data: WorkersState = {
  available: true, onlineFor: 120, events: [{ node: "laptop", at: now - 60, kind: "enrolled", actor: "jay", data: {} }],
  nodes: [
    { id: "server", kind: "server", owner: "jay", status: "online", state: "active", capabilities: { tools: ["git", "gh", "claude"], repos: ["commandcenter"] },
      version: "0.4.0", enrolledAt: now - 999, enrolledBy: "system:ccd", approvedAt: now - 999, approvedBy: "jay", lastHeartbeat: now - 5, revokedAt: null, fingerprint: null },
    { id: "laptop", kind: "laptop", owner: "jay", status: "pending", state: "pending", capabilities: { tools: ["git"], repos: ["employer-java"] },
      version: "1.0", enrolledAt: now - 60, enrolledBy: "jay", approvedAt: null, approvedBy: null, lastHeartbeat: null, revokedAt: null, fingerprint: "ab12-cd34" },
  ],
};

describe("Workers", () => {
  it("shows the server online and the laptop waiting; approving without Developer Mode asks to unlock", async () => {
    vi.spyOn(app.api, "workers").mockResolvedValue(data);
    const act = vi.spyOn(app.api, "workerAct");
    render(<Workers />);
    expect(await screen.findByText("waiting for you")).toBeInTheDocument();
    expect(screen.getByText("online")).toBeInTheDocument();
    expect(screen.getByText("employer-java")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);       // never the server
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(act).not.toHaveBeenCalled();
    expect(screen.getByText(/needs Developer Mode/)).toBeInTheDocument();
  });

  afterEach(() => { vi.restoreAllMocks(); setDevSession(null); });

  it("shows the fingerprint and who enrolled; with Developer Mode, approves and revokes with a reason (cancel does nothing)", async () => {
    setDevSession("s".repeat(43), 3600);
    vi.spyOn(app.api, "workers").mockResolvedValue(data);
    const act = vi.spyOn(app.api, "workerAct").mockResolvedValue(data.nodes[1]);
    render(<Workers />);
    expect(await screen.findByText("ab12-cd34")).toBeInTheDocument();
    expect(screen.getByText(/jay · /)).toBeInTheDocument();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(act).not.toHaveBeenCalled();                                          // fingerprint not confirmed
    expect(confirm.mock.calls[0][0]).toContain("ab12-cd34");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith("approve", "laptop", ""));
    const prompt = vi.spyOn(window, "prompt").mockReturnValueOnce(null).mockReturnValueOnce("lost it");
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(act).toHaveBeenCalledTimes(1);                                        // cancelled
    await waitFor(() => expect(screen.getByRole("button", { name: "Revoke" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith("revoke", "laptop", "lost it"));
    expect(prompt).toHaveBeenCalledTimes(2);
  });

  it("a failed refresh keeps the table and says so", async () => {
    const get = vi.spyOn(app.api, "workers").mockResolvedValueOnce(data).mockRejectedValueOnce(new Error("ccd is down"));
    setDevSession("s".repeat(43), 3600);
    vi.spyOn(app.api, "workerAct").mockResolvedValue(data.nodes[1]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Workers />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/Could not refresh: ccd is down/)).toBeInTheDocument();
    expect(screen.getByText("ab12-cd34")).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });
});
