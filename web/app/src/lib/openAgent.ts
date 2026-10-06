// One way to "open" an agent from anywhere (Needs Jay, a ticket, herdr workspaces):
// a project coordinator opens in the Workspace's Claude terminal, where Jay can read
// and answer it live; any other agent opens its row on the Agents page.
import { app } from "../store/app";
import { go } from "./router";

export function openAgent(agentId: string) {
  const a = app.data.state?.agents.find((x) => x.id === agentId);
  if (a?.role === "coordinator" && a.project) go("workspace", null, { project: a.project, tab: "claude" });
  else go("agents", agentId);
}
