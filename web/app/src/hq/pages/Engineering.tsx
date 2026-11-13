// Engineering (roadmap P3.3): every open task by stage, on live data from hq/data/engineering.ts, with the release
// gate and the task detail. The detail is Classic's TicketDetailPane, unchanged, so its actions, gates and Developer
// Unlock checks are exactly Classic's. The release gate only lists what waits for Jay's merge; nothing here merges.
// Classic's Tasks screen stays one link away (?view=board), and its own addresses with ?view or ?status still open it.
import { useEffect, useMemo, useState } from "react";
import "./office.css";
import "./engineering.css";
import { href } from "../../lib/router";
import { usePageNav, type PageNav } from "./route";
import { ago } from "../../lib/time";
import { PRIORITY_META } from "../../tickets/model";
import { TicketDetailPane } from "../../screens/TicketDetail";
import { VISIBLE_STAGES, type VisibleStage } from "../../api/types";
import { buildEngineering, PRESENCE_LABEL, type EngTask } from "../data";
import { useHqData } from "./live";
import { Pill, PRESENCE_TONE, cx, plural } from "./ui";

const STAGES = VISIBLE_STAGES.filter((s) => s !== "Closed");
const STAGE_TONE: Record<VisibleStage, string> = {
  Planning: "idle", Implementing: "violet", Reviewing: "info", "UI Testing": "info", Verifying: "info",
  "Ready to Merge": "ok", Deploying: "violet", "Needs Jay": "jay", Blocked: "bad", Closed: "idle",
};

function matches(t: EngTask, q: string) {
  if (!q) return true;
  const s = q.trim().toLowerCase().replace(/^#/, "");
  return [t.key, t.title, ...t.labels, t.pr ? String(t.pr.number) : ""].some((x) => x.toLowerCase().includes(s));
}

const COLS = [["key", "Key"], ["title", "Title"], ["project", "Project"], ["stage", "Stage"], ["priority", "Priority"],
  ["assignee", "Assignee"], ["session", "Session"], ["pr", "PR"], ["updated", "Updated"]] as const;

function Row({ t, sel, now, name, go }: { t: EngTask; sel: boolean; now: number; name: string; go: PageNav["go"] }) {
  return <tr className={cx(sel && "is-sel")} onClick={() => go("tasks", t.key)}>
    <td className="c-key"><a href={href("tasks", t.key)} aria-current={sel ? "true" : undefined} onClick={(e) => e.stopPropagation()}><code>{t.key}</code></a></td>
    <td className="c-title"><span className="hq-eng-t"><span className="hq-ellip" title={t.title}>{t.title}</span>
      {t.blocked && <span className="hq-flag t-bad">blocked</span>}
      {t.openQuestions > 0 && <span className="hq-flag t-jay">{plural(t.openQuestions, "question")}</span>}</span></td>
    <td className="c-project">{name}</td>
    <td className="c-stage"><Pill tone={STAGE_TONE[t.stage]}>{t.stage}</Pill></td>
    <td className={cx("c-priority", t.priority === "URGENT" && "t-bad", t.priority === "HIGH" && "t-warn")}>{PRIORITY_META[t.priority].label}</td>
    <td className="c-assignee" title={t.assignee}>{t.assignee}</td>
    <td className="c-session">{t.session ? <Pill tone={PRESENCE_TONE[t.session.presence]}>{PRESENCE_LABEL[t.session.presence]}</Pill> : <span className="hq-dim">None recorded</span>}</td>
    <td className="c-pr">{t.pr ? `#${t.pr.number}` : <span className="hq-dim">—</span>}</td>
    <td className="c-updated hq-dim">{ago(t.updatedAt, now)}</td>
  </tr>;
}

export function Engineering() {
  const { route, go } = usePageNav();
  const { src, ev } = useHqData();
  const asked = route.params.get("project") ?? "";
  const [project, setProject] = useState(asked);
  // A new ?project= while the page stays mounted (the address changes, the page does not) applies too. An address with
  // none, such as a task opened from the table, keeps the filter.
  useEffect(() => { if (asked) setProject(asked); }, [asked]);
  const [stage, setStage] = useState<VisibleStage | "">("");
  const [who, setWho] = useState("");
  const [q, setQ] = useState("");
  const v = useMemo(() => buildEngineering(src, ev, { project: project || null }), [src, ev, project]);
  const all = v.columns.flatMap((c) => c.tasks);
  const people = [...new Set(all.map((t) => t.assignee))].sort();
  const rows = all.filter((t) => (!stage || t.stage === stage) && (!who || t.assignee === who) && matches(t, q));
  const names = new Map(src.taskProjects.map((p) => [p.key, p.name]));
  const filtered = !!(project || stage || who || q);
  const open = route.id;

  return <div className="hq-page hq-eng">
    <header className="hq-hero">
      <div><h2>Engineering</h2><p>Every open task across your projects, by stage, from live data.</p></div>
      <div className="hq-eng-tools">
        <a className="hq-link" href={href("tasks", null, { view: "board" })}>Classic pipeline board</a>
        <button type="button" className="hq-btn is-primary"
          onClick={() => window.dispatchEvent(new CustomEvent("cc:new-task", { detail: project ? { project } : null }))}>New task</button>
      </div>
    </header>

    <div className="hq-eng-top">
      <section className="hq-panel" aria-labelledby="hq-eng-stages">
        <header><h3 id="hq-eng-stages">By stage <small>{plural(v.total, "open task")}</small></h3></header>
        <div className="hq-stages" role="group" aria-label="Filter by stage">
          {STAGES.map((s) => <button key={s} type="button" aria-pressed={stage === s} onClick={() => setStage(stage === s ? "" : s)}
            className={`t-${STAGE_TONE[s]}`}><b>{v.counts[s]}</b><span>{s}</span></button>)}
        </div>
      </section>
      <section className="hq-panel hq-gate" aria-labelledby="hq-eng-gate">
        <header><h3 id="hq-eng-gate">Release gate <small>Ready to merge</small></h3></header>
        {v.releaseGate.length ? <ul className="hq-attn">{v.releaseGate.map((t) => <li key={t.key}><a href={href("tasks", t.key)}>
          <span className="hq-attn-body"><span className="hq-ellip" title={t.title}><code>{t.key}</code> {t.title}</span>
            <small>{t.pr ? `Pull request #${t.pr.number}` : "No pull request recorded"} · {names.get(t.project) ?? t.project}</small></span>
          <Pill tone="ok">Awaiting merge</Pill></a></li>)}</ul>
          : <p className="hq-empty">Nothing is waiting for your merge.</p>}
        <p className="hq-note">You merge. Nothing on this page merges.</p>
      </section>
    </div>

    <div className={cx("hq-eng-grid", open && "has-detail")}>
      <section className="hq-panel hq-wb" aria-labelledby="hq-eng-wb">
        <header><h3 id="hq-eng-wb">Workbench <small>{rows.length} shown</small></h3>
          <div className="hq-filters">
            <label><span className="sr">Project</span><select value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">All projects</option>{v.projects.map((k) => <option key={k} value={k}>{names.get(k) ?? k}</option>)}</select></label>
            <label><span className="sr">Assignee</span><select value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">Anyone</option>{people.map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
            <label><span className="sr">Search tasks</span><input type="search" placeholder="Key, title, label, #PR" value={q}
              onChange={(e) => setQ(e.target.value)} /></label>
            {filtered && <button type="button" className="hq-btn" onClick={() => { setProject(""); setStage(""); setWho(""); setQ(""); }}>Clear</button>}
          </div></header>
        {!src.ticketsLoaded ? <p className="hq-empty">Loading tasks…</p>
          : rows.length ? <div className="hq-table-wrap"><table className="hq-table">
            <thead><tr>{COLS.map(([c, h]) => <th key={c} scope="col" className={`c-${c}`}>{h}</th>)}</tr></thead>
            <tbody>{rows.map((t) => <Row key={t.key} t={t} sel={open === t.key} now={ev.now} name={names.get(t.project) ?? t.project} go={go} />)}</tbody></table></div>
          : <p className="hq-empty">{all.length ? "No open task matches these filters." : "No open tasks."}</p>}
      </section>
      {open && <div className="hq-eng-detail"><TicketDetailPane ticketKey={open} onClose={() => go("tasks")} /></div>}
    </div>
  </div>;
}
