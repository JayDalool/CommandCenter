// How Command Center reaches a workspace. One interface, two modes.
//
//   BROWSER MODE (now)  monitoring, safe ccd actions (focus agent/workspace/tab),
//                       read-only tails, and the exact SSH command that opens the
//                       real interactive herdr terminal. No PTY in the page.
//   TAURI MODE (later)  the same calls, plus `openTerminal()` backed by a local
//                       PTY running `ssh -t <host> herdr agent attach <name>`,
//                       rendered with a terminal widget. ccd is unchanged: the
//                       interactive byte stream never passes through it.
import { app } from "../store/app";
import { prefs, commands } from "../lib/prefs";

export interface WorkspaceTransport {
  readonly mode: "browser" | "tauri";
  /** Can this mode host an interactive terminal inside Command Center? */
  readonly interactive: boolean;
  focusAgent(agentId: string): Promise<void>;
  focusWorkspace(workspaceId: string): Promise<void>;
  focusTab(tabId: string): Promise<void>;
  attachCommand(agentName?: string | null): string;
  openTerminal?(agentName: string): Promise<void>;
}

export class BrowserTransport implements WorkspaceTransport {
  readonly mode = "browser" as const;
  readonly interactive = false;
  async focusAgent(agentId: string) {
    await app.action(() => app.api.focusAgent(agentId), "Focused in herdr — switch to your herdr window");
  }
  async focusWorkspace(workspaceId: string) {
    await app.action(() => app.api.focusWorkspace(workspaceId), "Workspace brought forward in herdr");
  }
  async focusTab(tabId: string) {
    await app.action(() => app.api.focusTab(tabId), "Tab brought forward in herdr");
  }
  attachCommand(agentName?: string | null) {
    const h = prefs.get().sshHost;
    return agentName ? commands.attachAgent(h, agentName) : commands.attach(h);
  }
}

export const workspace: WorkspaceTransport = new BrowserTransport();
