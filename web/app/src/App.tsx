import { useEffect } from "react";
import { app } from "./store/app";
import { useSelector } from "./lib/store";
import { useRoute } from "./lib/router";
import { AppShell } from "./components/Shell";
import { Connect } from "./screens/Connect";
import { Dashboard } from "./screens/Dashboard";
import { Projects } from "./screens/Projects";
import { Agents } from "./screens/Agents";
import { Tasks } from "./screens/Tasks";
import { Development } from "./screens/Development";
import { Workspace } from "./screens/Workspace";
import { Files } from "./screens/Files";
import { PaneWindow, RoomWindow } from "./screens/Popout";
import { restoreToken } from "./api/auth";
import { restoreDevSession } from "./api/developer";
import { PullRequests } from "./screens/PullRequests";
import { Workspaces } from "./screens/Workspaces";
import { Server } from "./screens/Server";
import { Activity } from "./screens/Activity";
import { Alerts } from "./screens/Alerts";
import { Settings } from "./screens/Settings";
import { EmptyState } from "./components/ui";

const SCREENS: Record<string, () => React.JSX.Element> = { dashboard: Dashboard, overview: Dashboard, projects: Projects,
  agents: Agents, tasks: Tasks, development: Development, workspace: Workspace, files: Files, console: Files, prs: PullRequests,
  workspaces: Workspaces, server: Server, activity: Activity, alerts: Alerts, settings: Settings };
const FLUSH = new Set(["tasks", "workspaces", "console", "workspace", "files"]);
/** Pop-out windows: one room or one terminal, no navigation around them. */
const BARE: Record<string, () => React.JSX.Element> = { room: RoomWindow, pane: PaneWindow };

/** A pop-out or second window gets the token and the Developer session from the open windows. */
export async function start() {
  await restoreToken();
  await restoreDevSession();
  await app.boot();
}

export function App() {
  const auth = useSelector(app.store, (d) => d.auth);
  const hasState = useSelector(app.store, (d) => d.state !== null);
  const route = useRoute();
  useEffect(() => { void start(); return () => app.live.stop(); }, []);
  useEffect(() => { document.getElementById("main")?.focus({ preventScroll: true }); }, [route.screen]);
  if (auth === "needed" || (auth === "checking" && !hasState)) return auth === "needed" ? <Connect /> : <div className="connect"><EmptyState title="Connecting to ccd…" /></div>;
  const Bare = BARE[route.screen];
  if (Bare) return <AppShell bare flush><Bare /></AppShell>;
  const Screen = SCREENS[route.screen] ?? Dashboard;
  return <AppShell flush={FLUSH.has(route.screen)} chrome={route.screen === "dashboard" || route.screen === "overview" ? "dash" : "full"}>
    <Screen /></AppShell>;
}
