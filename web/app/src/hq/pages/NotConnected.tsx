// Messages (roadmap P5.1) and Revenue (P5.2): neither has a backend yet, so each page says Not connected, what it
// will need, and where to go today. No sample conversations or figures stand in for the real thing (roadmap: "never
// with mock data").
import type { ReactNode } from "react";
import "./office.css";
import "./governance.css";
import { app } from "../../store/app";
import { useSelector } from "../../lib/store";
import { href } from "../../lib/router";
import { jayQueue } from "../../tickets/model";
import { Icon } from "../frame/icons";
import { Pill, plural } from "./ui";

function NotConnected({ icon, title, lead, steps, children }: {
  icon: string; title: string; lead: string; steps: [string, string][]; children?: ReactNode;
}) {
  return <section className="hq-panel hq-nc" aria-labelledby="hq-nc-title">
    <header><span className="hq-nc-ico"><Icon name={icon} size={22} /></span><h3 id="hq-nc-title">{title}</h3>
      <Pill tone="idle">Not connected</Pill></header>
    <p className="hq-nc-lead">{lead}</p>
    <ol className="hq-nc-steps">{steps.map(([b, s]) => <li key={b}><b>{b}</b><span>{s}</span></li>)}</ol>
    {children}
  </section>;
}

export function Messages() {
  const asks = useSelector(app.store, (d) => jayQueue(d.state, undefined, d.tickets).filter((j) => j.kind === "answer" || j.kind === "questions").length);
  return <div className="hq-page hq-messages">
    <header className="hq-hero"><div><h2>Messages</h2>
      <p>Conversations with each project's lead.</p></div></header>
    <NotConnected icon="message" title="Messages is not connected"
      lead="Conversations need a message store on the server, and it has not been built. There is nothing to show here yet, and no sample conversations stand in for it."
      steps={[
        ["Your answers", "Who you message, how a message reaches a lead, and how long history is kept."],
        ["A message store on the server", "With its own security review. A message is never typed into a running session."],
        ["Conversations here", "One thread per project lead, which can also open in its own window."],
      ]}>
      <p className="hq-note">Until then, questions agents ask you are in <a className="hq-link" href={href("needs")}>Decisions
        {asks ? ` (${plural(asks, "question")} waiting)` : ""}</a>, where you answer them as today. Slack stays off.</p>
    </NotConnected>
  </div>;
}

export function Revenue() {
  return <div className="hq-page hq-revenue">
    <header className="hq-hero"><div><h2>Revenue</h2>
      <p>Sales, subscriptions and payouts from your billing provider.</p></div></header>
    <NotConnected icon="plug" title="Revenue is not connected"
      lead="No billing provider is connected, so there are no revenue figures. Command Center never estimates them or fills in sample numbers."
      steps={[
        ["Choose the provider", "Stripe, Paddle or another. Nothing is assumed."],
        ["Read-only access", "A restricted, read-only key held by the server, never in the browser."],
        ["Security review, then your approval", "Scopes, storage and audit are reviewed before anything is read, and it turns on only when you say so."],
      ]}>
      <p className="hq-note">Model spend is on <a className="hq-link" href={href("budgets")}>Budgets</a>, not here.</p>
    </NotConnected>
  </div>;
}
