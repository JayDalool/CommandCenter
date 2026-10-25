import { useEffect, type ReactNode } from "react";
import { useRoute } from "./lib/router";
import { BottomNav, Notices, Sidebar, TabStrip, TopBar, useWindowKeys } from "./components/Shell";
import { Detachable } from "./windows/Detachable";
import { PopoutWindow } from "./windows/PopoutWindow";
import { beatAsMain, startMainWindowDuties } from "./windows/manager";
import { viewById, viewForRoute } from "./windows/views";
import { Office } from "./pages/Office";
import { Messages, TaskContext, Thread } from "./pages/Messages";
import { Decisions, Evidence } from "./pages/Decisions";
import { Teams } from "./pages/Teams";
import { Topology, TopologyInspector } from "./pages/Topology";
import { Engineering, TaskDetail } from "./pages/Engineering";
import { Revenue } from "./pages/Revenue";
import { More } from "./pages/More";
import { TaskRoom, Terminal } from "./pages/TaskRoom";
import { useFeedRunner } from "./data/runner";
import { useViewState } from "./data/live";
import { AgentDrawer, AgentInspector } from "./components/agent";
import { PROJECTS } from "./data/seed";
import { useOrg } from "./data/org";
import { Agents } from "./pages/Agents";
import { Onboard } from "./pages/onboarding/NewAgent";
import { NewProject } from "./pages/onboarding/NewProject";
import { DesignSystem } from "./pages/DesignSystem";
import { Budgets } from "./pages/Budgets";
import { Approvals } from "./pages/Approvals";
import { Settings } from "./pages/Settings";
import { MenuLayer, PageSkeleton, TipLayer, useSegThumbs, useSimulatedLoad } from "./components/overlay";

// One source for project colours: the project records (seed.ts, plus projects created in the prototype). CSS reads them as --pj-<key>.
function publishColours() { for (const p of PROJECTS) document.documentElement.style.setProperty(`--pj-${p.key}`, p.color); }
publishColours();

const PAGES: Record<string, () => React.JSX.Element> = { office: Office, messages: Messages, decisions: Decisions, teams: Teams, topology: Topology,
  engineering: Engineering, revenue: Revenue, more: More, task: () => <TaskRoom />,
  agents: Agents, onboard: Onboard, newproject: NewProject, design: DesignSystem, budgets: Budgets, approvals: Approvals, settings: Settings };

function MsgCtx() { const [conv] = useViewState("page:messages", "conv", "sv-lead"); return <TaskContext conv={conv} />; }

/** What a pop-out window renders for a view id. */
export function renderView(id: string): ReactNode {
  const def = viewById(id);
  if (!def) return null;
  const [kind, rest] = [def.kind, id.slice(id.indexOf(":") + 1)];
  if (kind === "page") { const P = PAGES[rest]; return P ? <P /> : null; }
  if (kind === "dm") return <div className="dm-pop"><Thread conv={rest} /><Detachable id="panel:task-context"><TaskContext conv={rest} /></Detachable></div>;
  if (kind === "task") return <TaskRoom k={rest} />;
  if (kind === "term") return <Terminal k={rest} />;
  if (rest === "topology-inspector") return <TopologyInspector />;
  if (rest === "task-context") return <MsgCtx />;
  if (rest === "evidence") return <Evidence />;
  if (rest === "task-detail") return <TaskDetail />;
  if (rest === "agent") return <AgentInspector />;
  return null;
}

function MainWindow() {
  const route = useRoute();
  useWindowKeys();
  useEffect(() => { const a = startMainWindowDuties(); const b = beatAsMain(); return () => { a(); b(); }; }, []);
  const view = viewForRoute(route.screen, route.id);
  const Page = PAGES[route.screen] ?? Office;
  const ready = useSimulatedLoad(`${route.screen}/${route.id ?? ""}`);
  useEffect(() => { document.title = `CommandCenter · ${view?.title ?? "Engineering HQ"}`; }, [view?.title]);
  return <div className="app">
    <Sidebar />
    <div className="main-col">
      <TopBar />
      <TabStrip />
      <main id="main" className="content" tabIndex={-1}>
        {!ready ? <PageSkeleton label={`Loading ${view?.title ?? "page"}`} /> : view ? <Detachable id={view.id} className="page-placeholder"><Page /></Detachable> : <Page />}
      </main>
    </div>
    <BottomNav />
  </div>;
}

export function App() {
  const route = useRoute();
  const o = useOrg();   // every page re-renders when the organisation changes, in every window
  useEffect(publishColours, [o.v]);
  useFeedRunner();
  useSegThumbs();
  return <>{route.screen === "pop" ? <PopoutWindow render={renderView} /> : <MainWindow />}<AgentDrawer /><Notices /><MenuLayer /><TipLayer /></>;
}
