// HQ on a phone (the prototype's BottomNav): at 760px and narrower the sidebar and the tab strip go, and
// a tab bar at the bottom holds Office, Messages, Decisions and Approvals, with everything else in a More sheet. Wider
// windows never show it (frame.css). Every entry is an address the sidebar already has, or Classic's New task.
import { useEffect, useRef, useState } from "react";
import { app } from "../../store/app";
import { useSelector, shallowEqual } from "../../lib/store";
import { href, useRoute } from "../../lib/router";
import { jayQueue } from "../../tickets/model";
import { useFocusTrap } from "../../components/Dialog";
import { buildDecisions } from "../data";
import { sectionOf } from "./nav";
import { Icon } from "./icons";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

const TABS = [
  { id: "dashboard", label: "Office", icon: "home" },
  { id: "messages", label: "Messages", icon: "message" },
  { id: "needs", label: "Decisions", icon: "shield" },
  { id: "approvals", label: "Approvals", icon: "check" },
] as const;

type Row = { label: string; sub: string; icon: string; id?: string; to?: string; run?: () => void };
const MORE: { title: string; rows: Row[] }[] = [
  { title: "Company", rows: [
    { id: "agents", label: "Teams", sub: "Each project's lead and members", icon: "users" },
    { id: "projects", label: "Company", sub: "Every project and how the work connects", icon: "cube" },
    { id: "tasks", label: "Engineering", sub: "Tasks, branches and reviews", icon: "wrench" },
    { id: "revenue", label: "Revenue", sub: "Not connected", icon: "chart" },
    { id: "budgets", label: "Budgets", sub: "Model spend against its limits", icon: "receipt" },
  ] },
  { title: "Work", rows: [
    { id: "workspace", label: "Workspace", sub: "Files, editor and terminals", icon: "terminal" },
    { id: "activity", label: "Activity", sub: "What happened, and alerts", icon: "pulse" },
    { id: "files", label: "Files", sub: "Each project's files", icon: "folder" },
  ] },
  { title: "", rows: [
    { label: "New task", sub: "In any project", icon: "plus", run: () => window.dispatchEvent(new Event("cc:new-task")) },
    { id: "settings", label: "Settings", sub: "Theme, notifications and connections", icon: "gear" },
    { label: "Help & shortcuts", sub: "Where things are", icon: "help", to: href("settings", null, { tab: "help" }) },
  ] },
];

function MoreSheet({ onClose, cur }: { onClose: () => void; cur: string }) {
  const ref = useFocusTrap(onClose);
  return <div className="hq-sheet-veil" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="hq-sheet" role="dialog" aria-modal="true" aria-labelledby="hq-sheet-t" ref={ref}>
      <span className="hq-sheet-grab" aria-hidden />
      <header className="hq-sheet-h"><b id="hq-sheet-t">More</b>
        <button type="button" className="hq-sheet-done" onClick={onClose} data-autofocus>Done</button></header>
      {MORE.map((g, i) => <section key={i} className="hq-sheet-group" aria-label={g.title || "Settings and help"}>
        {g.title && <h3>{g.title}</h3>}
        <div className="hq-sheet-rows">{g.rows.map((r) => {
          const on = !!r.id && r.id === cur;
          const body = <><Icon name={r.icon} size={18} /><span className="hq-sheet-row-t"><b>{r.label}</b><small>{r.sub}</small></span>
            <Icon name="chevron" size={14} /></>;
          return r.run
            ? <button key={r.label} type="button" className="hq-sheet-row" onClick={() => { onClose(); r.run!(); }}>{body}</button>
            : <a key={r.label} className={cx("hq-sheet-row", on && "is-current")} href={r.to ?? href(r.id!)}
              aria-current={on ? "page" : undefined} onClick={onClose}>{body}</a>;
        })}</div>
      </section>)}
    </div>
  </div>;
}

export function HqTabBar() {
  const route = useRoute();
  const cur = sectionOf(route.screen);
  const [more, setMore] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  // The same counts as the sidebar's Decisions badge and Jay's menu.
  const n = useSelector(app.store, (d) => ({ needs: jayQueue(d.state).length, approvals: buildDecisions(d).summary.approvals,
    messages: d.state?.chat?.unread ?? 0 }), shallowEqual);
  const badge: Partial<Record<string, number>> = { needs: n.needs, approvals: n.approvals, messages: n.messages };
  const inTabs = TABS.some((t) => t.id === cur);
  // A new address closes the sheet: a row was used, or Back was pressed.
  const at = location.hash;
  useEffect(() => { setMore(false); }, [at]);

  return <>
    <nav className="hq-tabbar" aria-label="Tab bar">
      {TABS.map((t) => {
        const on = cur === t.id && !more;
        const count = badge[t.id];
        return <a key={t.id} href={href(t.id)} className={cx("hq-tabbar-i", on && "is-current")} aria-current={cur === t.id ? "page" : undefined}
          aria-label={count ? `${t.label}, ${count} waiting` : undefined}>
          <span className="hq-tabbar-ico"><Icon name={t.icon} size={22} />{count ? <em aria-hidden>{count}</em> : null}</span>
          <span>{t.label}</span></a>;
      })}
      <button type="button" ref={btn} className={cx("hq-tabbar-i", (more || !inTabs) && "is-current")} aria-haspopup="dialog"
        aria-expanded={more} onClick={() => setMore((m) => !m)}>
        <span className="hq-tabbar-ico"><Icon name="grid" size={22} /></span><span>More</span></button>
    </nav>
    {more && <MoreSheet cur={cur} onClose={() => setMore(false)} />}
  </>;
}
