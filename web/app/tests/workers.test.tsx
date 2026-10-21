/** Settings → Workers: the server node and enrolled nodes; approve/revoke need Developer Mode. */
import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { app } from "../src/store/app";
import { Workers } from "../src/components/Workers";
import type { WorkersState } from "../src/api/types";

const now = Date.now() / 1000;
const data: WorkersState = {
  available: true, onlineFor: 120, events: [{ node: "laptop", at: now - 60, kind: "enrolled", actor: "jay", data: {} }],
  nodes: [
    { id: "server", kind: "server", owner: "jay", status: "online", state: "active", capabilities: { tools: ["git", "gh", "claude"], repos: ["commandcenter"] },
      version: "0.4.0", enrolledAt: now - 999, enrolledBy: "system:ccd", approvedAt: now - 999, approvedBy: "jay", lastHeartbeat: now - 5, revokedAt: null },
    { id: "laptop", kind: "laptop", owner: "jay", status: "pending", state: "pending", capabilities: { tools: ["git"], repos: ["employer-java"] },
      version: "1.0", enrolledAt: now - 60, enrolledBy: "jay", approvedAt: null, approvedBy: null, lastHeartbeat: null, revokedAt: null },
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
});
