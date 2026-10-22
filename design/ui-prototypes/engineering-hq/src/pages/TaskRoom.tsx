// TASK ROOM — one task with its lead, its terminal and its dossier. The terminal pane is its own
// detachable view (term:<KEY>). In the real app every pane attaches to the SAME ccd/herdr session by
// name (web/app/src/workspace/rooms.ts), so popping out or closing a window never starts or stops one.
import { useEffect, useState } from "react";
import { agent, project, task } from "../data/seed";
import { feed } from "../data/live";
import { useStore } from "../lib/store";
import { useRoute } from "../lib/router";
import { Icon } from "../components/Icon";
import { Avatar, Demo, PresenceDot, ProdBanner, ProjIcon, StagePill } from "../components/ui";
import { Detachable, PopButton } from "../windows/Detachable";
import { Thread } from "./Messages";

const LINES = ["$ npm test -- comparison", " ✓ pricing matches fixture 01–50 (50)", " ✓ filters keep sort order (12)", " ✓ renders at 1366 and 1920 (4)", "", "Tests  66 passed (66)",
  "$ git status --short", " M src/compare/Layout.tsx", " M src/compare/filters.ts", "$ █"];

export function Terminal({ k }: { k: string }) {
  const [n, setN] = useState(4);
  useEffect(() => { const t = setInterval(() => setN((x) => (x >= LINES.length ? x : x + 1)), 700); return () => clearInterval(t); }, []);
  return <section className="term" aria-label={`${k} terminal`}>
    <header><Icon name="terminal" size={16} /><b>Terminal</b><span className="muted mono">session repo:{k} · server</span><Demo label="Simulated output" /><span className="sp" /><PopButton id={`term:${k}`} compact /></header>
    <pre>{LINES.slice(0, n).join("\n")}</pre>
    <footer className="muted small">Closing this window detaches only. The session keeps running; End Session is a separate, confirmed action in the real app.</footer>
  </section>;
}

export function TaskRoom({ k: kp }: { k?: string }) {
  const route = useRoute();
  const k = kp ?? route.id ?? "SV-025";
  const t = task(k);
  const f = useStore(feed);
  if (!t) return <div className="empty">Unknown task.</div>;
  const a = agent(t.owner);
  return <div className="page page-room">
    <header className="room-head"><ProjIcon k={t.project} size={40} /><div><h1><span className="mono">{t.key}</span> {t.title}</h1><p>{project(t.project).name} · Task Room <Demo /></p></div>
      <StagePill s={t.stage} /><span className="sp" /><PresenceDot s={f.agents[t.owner]?.status ?? "unknown"} detail={`${a.name}: ${f.agents[t.owner]?.detail ?? ""}`} /><PopButton id={`task:${k}`} /></header>
    <ProdBanner compact />
    <div className="room-grid">
      <Detachable id={`dm:${t.project === "commandcenter" ? "cc-lead" : "sv-lead"}`}><Thread conv={t.project === "commandcenter" ? "cc-lead" : "sv-lead"} /></Detachable>
      <div className="room-right">
        <Detachable id={`term:${k}`}><Terminal k={k} /></Detachable>
        <section className="panel pad dossier"><h2>Dossier</h2><p>{t.why}</p><h3>Acceptance</h3><ul className="checks">{t.criteria.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="muted small"><Avatar id={t.owner} size={18} /> Owner: {a.name} ({a.role}). Same session identity in every window.</p></section>
      </div>
    </div>
  </div>;
}
