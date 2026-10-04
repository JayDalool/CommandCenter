import { useEffect } from "react";
import { app } from "./store/app";
import { useSelector } from "./lib/store";
import { useRoute } from "./lib/router";
import { AppShell } from "./components/Shell";
import { Connect } from "./screens/Connect";
import { Overview } from "./screens/Overview";
import { Projects } from "./screens/Projects";
import { Agents } from "./screens/Agents";
import { Tasks } from "./screens/Tasks";
import { Development } from "./screens/Development";
import { Workspace } from "./screens/Workspace";
import { PullRequests } from "./screens/PullRequests";
import { Workspaces } from "./screens/Workspaces";
import { Server } from "./screens/Server";
import { Activity } from "./screens/Activity";
import { Alerts } from "./screens/Alerts";
import { Settings } from "./screens/Settings";
import { EmptyState } from "./components/ui";

const SCREENS: Record<string, () => React.JSX.Element> = { overview: Overview, projects: Projects, agents: Agents,
  tasks: Tasks, development: Development, workspace: Workspace, console: Workspace, prs: PullRequests, workspaces: Workspaces, server: Server,
  activity: Activity, alerts: Alerts, settings: Settings };
const FLUSH = new Set(["tasks", "workspaces", "console", "workspace"]);

export function App() {
  const auth = useSelector(app.store, (d) => d.auth);
  const hasState = useSelector(app.store, (d) => d.state !== null);
  const route = useRoute();
  useEffect(() => { void app.boot(); return () => app.live.stop(); }, []);
  useEffect(() => { document.getElementById("main")?.focus({ preventScroll: true }); }, [route.screen]);
  if (auth === "needed" || (auth === "checking" && !hasState)) return auth === "needed" ? <Connect /> : <div className="connect"><EmptyState title="Connecting to ccd…" /></div>;
  const Screen = SCREENS[route.screen] ?? Overview;
  return <AppShell flush={FLUSH.has(route.screen)}><Screen /></AppShell>;
}
