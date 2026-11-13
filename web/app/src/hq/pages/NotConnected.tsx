// Revenue (P5.2) has no backend yet, so its page says Not connected, what it will need, and where to go today. No
// sample figures stand in for the real thing (roadmap: "never with mock data"). Messages has its own page (Messages.tsx).
import type { ReactNode } from "react";
import "./office.css";
import "./governance.css";
import { href } from "../../lib/router";
import { Icon } from "../frame/icons";
import { Pill } from "./ui";

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
