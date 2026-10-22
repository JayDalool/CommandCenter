import { useEffect, type ReactNode } from "react";
import { useRoute } from "./lib/router";
import { Notices, Sidebar, TabStrip, TopBar, useWindowKeys } from "./components/Shell";
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

const PAGES: Record<string, () => React.JSX.Element> = { office: Office, messages: Messages, decisions: Decisions, teams: Teams, topology: Topology,
  engineering: Engineering, revenue: Revenue, more: More, task: () => <TaskRoom /> };

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
  return null;
}

function MainWindow() {
  const route = useRoute();
  useWindowKeys();
  useEffect(() => { const a = startMainWindowDuties(); const b = beatAsMain(); return () => { a(); b(); }; }, []);
  const view = viewForRoute(route.screen, route.id);
  const Page = PAGES[route.screen] ?? Office;
  useEffect(() => { document.title = `CommandCenter · ${view?.title ?? "Engineering HQ"}`; }, [view?.title]);
  return <div className="app">
    <Sidebar />
    <div className="main-col">
      <TopBar />
      <TabStrip />
      <main id="main" className="content" tabIndex={-1}>
        {view ? <Detachable id={view.id} className="page-placeholder"><Page /></Detachable> : <Page />}
      </main>
    </div>
  </div>;
}

export function App() {
  const route = useRoute();
  useFeedRunner();
  return <>{route.screen === "pop" ? <PopoutWindow render={renderView} /> : <MainWindow />}<Notices /></>;
}
