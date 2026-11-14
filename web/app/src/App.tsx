import { useEffect } from "react";
import { app } from "./store/app";
import { useSelector } from "./lib/store";
import { href, useRoute } from "./lib/router";
import { TITLES } from "./lib/titles";
import { AppShell } from "./components/Shell";
import { Connect } from "./screens/Connect";
import { Dashboard } from "./screens/Dashboard";
import { Projects } from "./screens/Projects";
import { Agents } from "./screens/Agents";
import { Tasks } from "./screens/Tasks";
import { Development } from "./screens/Development";
import { Workspace } from "./screens/Workspace";
import { Files } from "./screens/Files";
import { PaneWindow, PopWindow, RoomWindow } from "./screens/Popout";
import { restoreToken } from "./api/auth";
import { checkRemembered, restoreDevSession } from "./api/developer";
import { redeemSignin } from "./api/signin";
import { PullRequests } from "./screens/PullRequests";
import { Workspaces } from "./screens/Workspaces";
import { Server } from "./screens/Server";
import { Activity } from "./screens/Activity";
import { Alerts } from "./screens/Alerts";
import { Settings } from "./screens/Settings";
import { NeedsYou } from "./screens/NeedsYou";
import { EmptyState } from "./components/ui";

const SCREENS: Record<string, () => React.JSX.Element> = { dashboard: Dashboard, overview: Dashboard, projects: Projects,
  agents: Agents, tasks: Tasks, development: Development, workspace: Workspace, files: Files, console: Files, prs: PullRequests,
  workspaces: Workspaces, server: Server, activity: Activity, alerts: Alerts, settings: Settings, needs: NeedsYou,
  approvals: HqOnly, budgets: HqOnly, messages: HqOnly, revenue: HqOnly };
const FLUSH = new Set(["tasks", "workspaces", "console", "workspace", "files"]);
/** Pop-out windows: one room, one terminal or one HQ page, no navigation around them. */
const BARE: Record<string, () => React.JSX.Element> = { room: RoomWindow, pane: PaneWindow, pop: PopWindow };

/** Approvals, Budgets, Messages and Revenue are HQ pages only (hq/pages): Classic says where they are. */
function HqOnly() {
  const route = useRoute();
  return <EmptyState title={`${TITLES[route.screen] ?? "This page"} is in the HQ preview`}
    hint="Turn it on in Settings › General › Interface."><a href={href("dashboard")}>Back to the Dashboard</a></EmptyState>;
}

/** A pop-out or second window gets the token and the Developer session from the open windows. */
export async function start() {
  const signinError = await redeemSignin();   // CommandCenter.exe's SSH sign-in, when the address carries one
  if (signinError) app.toast(`SSH sign-in: ${signinError}`, "bad");
  await restoreToken();
  await restoreDevSession();
  // A remembered device's session comes from localStorage: ask ccd whether it still stands, without holding the page up.
  void checkRemembered(() => app.api.developerStatus());
  await app.boot();
}

export function App() {
  const auth = useSelector(app.store, (d) => d.auth);
  const hasState = useSelector(app.store, (d) => d.state !== null);
  const route = useRoute();
  useEffect(() => { void start(); return () => app.live.stop(); }, []);
  // A sign-in link opened in a tab that is already open (only the address changes): redeem it too.
  useEffect(() => {
    const on = () => {
      if (!/[?&]signin=/.test(location.hash)) return;
      void redeemSignin().then((err) => {
        if (err) app.toast(`SSH sign-in: ${err}`, "bad");
        else { app.toast("Signed in over SSH — Developer Mode on"); void app.boot(); }
      });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { document.getElementById("main")?.focus({ preventScroll: true }); }, [route.screen]);
  if (auth === "needed" || (auth === "checking" && !hasState)) return auth === "needed" ? <Connect /> : <div className="connect"><EmptyState title="Connecting to ccd…" /></div>;
  const Bare = BARE[route.screen];
  if (Bare) return <AppShell bare flush><Bare /></AppShell>;
  const Screen = SCREENS[route.screen] ?? Dashboard;
  return <AppShell flush={FLUSH.has(route.screen)} chrome={route.screen === "dashboard" || route.screen === "overview" ? "dash" : "full"}>
    <Screen /></AppShell>;
}
