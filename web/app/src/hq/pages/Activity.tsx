// Activity (roadmap P3.7): the same rows as Classic's Activity screen (hq/data/activity.ts: meaningful events, newest
// first, Classic's filters, closed tasks hidden unless asked), grouped by day, with the alerts beside them. Older pages
// load through the same GET /api/activity as Classic. Acknowledging an alert stays on Classic's Alerts screen.
import { useEffect, useMemo, useState } from "react";
import "./office.css";
import "./activity.css";
import { app } from "../../store/app";
import { href, useRoute } from "../../lib/router";
import { ago, hms } from "../../lib/time";
import type { CcdEvent } from "../../api/types";
import type { FeedCat } from "../../components/Feed";
import { ACTIVITY_FILTERS, buildActivity, buildAlerts, type ActivityFilter, type ActivityRowView } from "../data";
import { useHqData } from "./live";
import { Pill, cx } from "./ui";

const FILTER_LABEL: Record<ActivityFilter, string> = { ALL: "All", AGENTS: "Agents", TASKS: "Tasks", PRS: "Pull requests", CI: "CI", JAY: "You", HOST: "Host" };
const CAT: Record<FeedCat, [string, string]> = {
  AGENT: ["Agent", "violet"], TASK: ["Task", "info"], PR: ["PR", "ok"], CI: ["CI", "ok"], JAY: ["You", "jay"], HOST: ["Host", "idle"],
  ALERT: ["Alert", "warn"], CCD: ["ccd", "idle"], ACTION: ["Action", "idle"],
};
const DIAGNOSTICS: [string, string][] = [["alerts", "Alerts"], ["server", "Server"], ["agents", "Agents"], ["development", "Development"],
  ["prs", "Pull requests"], ["workspaces", "herdr layout"]];

function dayOf(at: number) {
  return new Date(at * 1000).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

function Row({ r, project }: { r: ActivityRowView; project: string }) {
  const [label, tone] = CAT[r.cat];
  return <li className="hq-act-row">
    <time dateTime={new Date(r.at * 1000).toISOString()}>{hms(r.at).slice(0, 5)}</time>
    <Pill tone={tone}>{label}</Pill>
    <span className={cx("hq-act-text", r.severity === "warn" && "t-warn", r.severity === "action" && "t-jay")} title={r.text}>
      {r.project && <small>{project} · </small>}
      {r.ticket ? <a href={href("tasks", r.ticket)}>{r.text}</a> : r.text}
    </span>
  </li>;
}

export function Activity() {
  const route = useRoute();
  const { src, ev } = useHqData();
  const project = route.params.get("project");
  const [filter, setFilter] = useState<ActivityFilter>("ALL");
  const [withClosed, setWithClosed] = useState(false);
  const [older, setOlder] = useState<CcdEvent[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => setOlder([]), [project]);
  const names = new Map(src.taskProjects.map((p) => [p.key, p.name]));
  // One pass per filter, only when the feed or a setting changes, not on every tick.
  const byFilter = useMemo(() => new Map((Object.keys(ACTIVITY_FILTERS) as ActivityFilter[])
    .map((f) => [f, buildActivity(src.activity, src.tickets, { project, withClosed, older, filter: f })])),
  [src.activity, src.tickets, older, project, withClosed]);
  const rows = byFilter.get(filter) ?? [];
  const count = (f: ActivityFilter) => byFilter.get(f)?.length ?? 0;
  const alerts = buildAlerts(src.state?.alerts);
  // Older pages start below the oldest event loaded, filtered or not, as in Classic.
  const seqs = [...src.activity, ...older].map((e) => e.seq);
  const oldest = seqs.length ? Math.min(...seqs) : undefined;
  const more = async () => {
    setBusy(true);
    try { const r = await app.api.activity({ limit: 200, before: oldest }); setOlder((o) => [...o, ...r.events]); }
    catch { app.toast("Could not load older activity.", "bad"); }
    finally { setBusy(false); }
  };
  const days: [string, ActivityRowView[]][] = [];
  for (const r of rows) {
    const d = dayOf(r.at);
    if (days.at(-1)?.[0] === d) days.at(-1)![1].push(r); else days.push([d, [r]]);
  }

  return <div className="hq-page hq-activity">
    <header className="hq-hero"><div><h2>Activity</h2>
      <p>What happened across your projects, newest first{project ? ` · ${names.get(project) ?? project} only` : ""}.</p></div></header>

    <div className="hq-office-grid">
      <section className="hq-panel" aria-labelledby="hq-act-feed">
        <header><h3 id="hq-act-feed">Events <small>{rows.length} shown</small></h3>
          <label className="hq-check"><input type="checkbox" checked={withClosed} onChange={(e) => setWithClosed(e.target.checked)} />Closed tasks</label></header>
        <div className="hq-seg" role="group" aria-label="Filter events">
          {(Object.keys(ACTIVITY_FILTERS) as ActivityFilter[]).map((f) => <button key={f} type="button" aria-pressed={filter === f}
            onClick={() => setFilter(f)}>{FILTER_LABEL[f]} ({count(f)})</button>)}
        </div>
        {days.length ? days.map(([d, list]) => <section key={d} className="hq-act-day" aria-label={d}>
          <h4>{d}</h4><ul>{list.map((r) => <Row key={r.seq} r={r} project={r.project ? names.get(r.project) ?? r.project : ""} />)}</ul></section>)
          : <p className="hq-empty">Nothing here yet.</p>}
        <div><button type="button" className="hq-btn" onClick={more} disabled={busy}>{busy ? "Loading…" : "Load older"}</button></div>
      </section>

      <div className="hq-office-side">
        <section className="hq-panel" aria-labelledby="hq-act-alerts">
          <header><h3 id="hq-act-alerts">Alerts <small>{alerts.unacked} not acknowledged</small></h3>
            <a className="hq-link" href={href("alerts")}>{alerts.rows.length > 6 ? `Open all ${alerts.rows.length}` : "Open Alerts"}</a></header>
          {alerts.rows.length ? <ul className="hq-attn">{alerts.rows.slice(0, 6).map((a) => <li key={a.id}><a href={href("alerts")}>
            <span className="hq-attn-body"><span className="hq-ellip" title={a.text}>{a.text}</span>
              <small>{a.source}{a.project ? ` · ${names.get(a.project) ?? a.project}` : ""} · {ago(a.since, ev.now)}{a.ack ? " · acknowledged" : ""}</small></span>
            <Pill tone={a.severity === "action" ? "bad" : a.severity === "warn" ? "warn" : "info"}>
              {a.severity === "action" ? "Action" : a.severity === "warn" ? "Warning" : "Info"}</Pill></a></li>)}</ul>
            : <p className="hq-empty">No active alerts.</p>}
          <p className="hq-note">You acknowledge alerts on the Alerts screen.</p>
        </section>
        <section className="hq-panel" aria-labelledby="hq-act-diag">
          <header><h3 id="hq-act-diag">Logs and diagnostics</h3></header>
          <ul className="hq-act-links">{DIAGNOSTICS.map(([id, label]) => <li key={id}><a className="hq-btn" href={href(id)}>{label}</a></li>)}</ul>
        </section>
      </div>
    </div>
  </div>;
}
