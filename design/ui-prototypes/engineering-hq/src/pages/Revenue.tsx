// REVENUE — paid subscriptions and earnings (reference 07). No provider is connected, so the page says
// so. A clearly fictional demo can be switched on to review the layout; it is watermarked everywhere.
import { useViewState } from "../data/live";
import { Icon } from "../components/Icon";
import { Demo, Panel, Pill, Spark, cx } from "../components/ui";
import { PopButton } from "../windows/Detachable";

const V = "page:revenue";
const TREND = [9.2, 11.4, 14.8, 15.6, 19.9, 25.3, 27.1, 28.4, 32.5, 33.9, 38.7, 39.6];
const MONTHS = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"];

function Line({ data, range }: { data: number[]; range: string }) {
  const n = range === "3M" ? 3 : range === "6M" ? 6 : 12;
  const d = data.slice(-n), labels = MONTHS.slice(-n);
  const W = 640, H = 230, max = 45, px = (i: number) => 46 + (i / Math.max(1, d.length - 1)) * (W - 70), py = (v: number) => H - 30 - (v / max) * (H - 50);
  const line = d.map((v, i) => `${px(i)},${py(v)}`).join(" ");
  return <svg className="line-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Fictional MRR trend">
    <defs><linearGradient id="rev-a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5b6cff" stopOpacity=".45" /><stop offset="1" stopColor="#5b6cff" stopOpacity="0" /></linearGradient>
      <linearGradient id="rev-l" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#3f8bff" /><stop offset="1" stopColor="#9d6bff" /></linearGradient></defs>
    {[0, 10, 20, 30, 40].map((v) => <g key={v}><line x1="46" x2={W - 20} y1={py(v)} y2={py(v)} className="gridline" /><text x="38" y={py(v) + 4} textAnchor="end">${v}K</text></g>)}
    <polygon points={`${px(0)},${py(0)} ${line} ${px(d.length - 1)},${py(0)}`} fill="url(#rev-a)" />
    <polyline points={line} fill="none" stroke="url(#rev-l)" strokeWidth="3" strokeLinejoin="round" />
    {d.map((v, i) => <circle key={i} cx={px(i)} cy={py(v)} r={i === d.length - 1 ? 6 : 3.6} fill={i === d.length - 1 ? "#fff" : "#7c8cff"} stroke="#7c8cff" strokeWidth="2" />)}
    {labels.map((l, i) => <text key={l} x={px(i)} y={H - 8} textAnchor="middle">{l}</text>)}
  </svg>;
}

function Donut({ parts, total, label }: { parts: [string, number, string][]; total: number; label: string }) {
  let acc = 0; const r = 52, c = 2 * Math.PI * r;
  return <div className="donut-wrap"><svg viewBox="0 0 140 140" className="donut" role="img" aria-label={`${label}: fictional`}>
    {parts.map(([n, v, col]) => { const len = (v / total) * c; const el = <circle key={n} cx="70" cy="70" r={r} fill="none" stroke={col} strokeWidth="16" strokeDasharray={`${len - 2} ${c - len + 2}`} strokeDashoffset={-acc} transform="rotate(-90 70 70)" />; acc += len; return el; })}
    <text x="70" y="68" textAnchor="middle" className="donut-n">{total}</text><text x="70" y="88" textAnchor="middle" className="donut-l">{label}</text></svg>
    <ul className="donut-legend">{parts.map(([n, v, col]) => <li key={n}><i style={{ background: col }} />{n}<span className="sp" /><b>{v}</b><small>({((v / total) * 100).toFixed(1)}%)</small></li>)}</ul></div>;
}

function NotConnected({ onDemo }: { onDemo: () => void }) {
  return <section className="panel rev-empty">
    <span className="rev-ico"><Icon name="plug" size={34} /></span>
    <h2>Revenue is not connected</h2>
    <p>No billing provider is connected, so there are no revenue numbers to show. CommandCenter will never estimate or invent them.</p>
    <div className="rev-steps">
      <div><b>1 · Choose the provider</b><small>Stripe, Paddle or another. You decide; nothing is assumed.</small></div>
      <div><b>2 · Read-only access</b><small>A restricted, read-only key stored server-side (never in the browser), behind a provider-neutral adapter.</small></div>
      <div><b>3 · Security review</b><small>Scopes, storage, retention and audit reviewed before anything is fetched.</small></div>
      <div><b>4 · Your approval</b><small>Turned on only after you approve it explicitly.</small></div>
    </div>
    <p className="muted small">When connected, this page separates gross sales, refunds, tax, fees and net receipts from subscription metrics (MRR, ARR, renewals, churn, failed payments), per product, currency and time zone. AI model spend lives on Engineering, not here.</p>
    <div className="row-gap"><button type="button" className="btn" disabled>Connect provider (needs your approval)</button><button type="button" className="btn btn-outline" onClick={onDemo}><Icon name="eye" size={16} /> Preview with fictional demo data</button></div>
  </section>;
}

export function Revenue() {
  const [demo, setDemo] = useViewState(V, "demo", false);
  const [range, setRange] = useViewState(V, "range", "12M");
  return <div className={cx("page page-revenue", demo && "is-demo")}>
    <div className="page-head"><div><h1>Revenue</h1><p>Track subscription revenue, growth and customer success across your products.</p></div>
      <div className="row-gap">{demo ? <span className="sync-pill t-warn"><i /><b>FICTIONAL DEMO DATA</b><small>Not connected to any billing provider</small></span>
        : <span className="sync-pill t-idle"><i /><b>Not connected</b><small>No billing provider</small></span>}
        <label className="switch"><input type="checkbox" checked={demo} onChange={() => setDemo(!demo)} /><span>Fictional demo</span></label><PopButton id={V} /></div></div>
    {!demo ? <>
      <div className="rev-kpis is-empty" aria-label="Revenue metrics, not connected">{["Monthly Recurring Revenue", "Annual Recurring Revenue", "Active Subscriptions", "Net Receipts (MTD)", "Churn Rate", "Trial → Paid"].map((l) =>
        <div key={l} className="rkpi"><span className="kpi-ico"><Icon name="plug" size={20} /></span><div><small>{l}</small><b>—</b><em className="muted">Not connected</em></div></div>)}</div>
      <NotConnected onDemo={() => setDemo(true)} /></> : <>
      <div className="demo-ribbon" role="note"><Icon name="info" size={16} /> Every number on this page is FICTIONAL sample data for reviewing the layout. None of it is your revenue.</div>
      <div className="rev-kpis">{[["Monthly Recurring Revenue", "$39,600", "↑ 12%", "#2fe0a0", "card"], ["Annual Recurring Revenue", "$475,200", "↑ 16%", "#9d6bff", "calendar"], ["Active Subscriptions", "87", "↑ 8%", "#4f8bff", "users"],
        ["Net Receipts (MTD)", "$41,020", "↑ 24%", "#ff9f43", "receipt"], ["Churn Rate", "2.3%", "↓ 0.8%", "#ff4f6d", "pulse"], ["Trial → Paid", "18.4%", "↑ 3.1%", "#5b7cff", "target"]].map(([l, v, d, col, ic]) =>
        <div key={l} className="rkpi"><span className="kpi-ico" style={{ color: col, background: `${col}22` }}><Icon name={ic} size={22} /></span><div><small>{l}</small><b>{v}</b><em className={d.startsWith("↓") && l !== "Churn Rate" ? "t-bad" : "t-ok"}>{d} <span className="muted">vs last month</span></em></div><Spark data={[4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11]} color={col} w={92} h={34} /></div>)}</div>
      <div className="rev-grid">
        <Panel className="rev-trend" icon="chart" title="Revenue Trend" sub="Monthly recurring revenue (fictional)" action={<div className="seg seg-boxed">{["3M", "6M", "12M"].map((r) => <button key={r} type="button" aria-selected={range === r} onClick={() => setRange(r)}>{r}</button>)}</div>}>
          <Line data={TREND} range={range} />
          <div className="rev-split">{[["Gross sales", "$44,310"], ["Refunds", "−$1,120"], ["Tax collected", "−$1,410"], ["Processor fees", "−$760"], ["Net receipts", "$41,020"]].map(([l, v]) => <div key={l}><small>{l}</small><b>{v}</b></div>)}</div>
        </Panel>
        <Panel icon="users" title="Subscriptions by Plan" sub="Active subscription distribution"><Donut total={87} label="Subscriptions" parts={[["Starter", 28, "#2fe0a0"], ["Team", 24, "#9d6bff"], ["Business", 20, "#4f8bff"], ["Enterprise", 11, "#ff9f43"], ["Other", 4, "#8892a8"]]} /></Panel>
        <Panel icon="card" title="Payment Status" sub="Current subscription payment status"><Donut total={87} label="Total" parts={[["Paid", 78, "#2fe0a0"], ["Past due", 4, "#ffb020"], ["Failed", 2, "#ff4f6d"], ["Upcoming", 3, "#8892a8"]]} /></Panel>
        <Panel icon="box" title="Revenue by Product" sub="MRR by product (fictional)">
          <ul className="bars-h">{[["samvision", "SamVision", 38, "$15,050"], ["gyst", "GYST / LifeOps", 26, "$10,300"], ["mfe", "MyFamilyExpenses", 20, "$7,920"], ["commandcenter", "Consulting", 12, "$4,750"], ["", "Other", 4, "$1,580"]].map(([k, n, pct, v]) =>
            <li key={n as string}><span>{n}</span><small>{pct}%</small><span className="bar"><i style={{ width: `${pct as number * 2.2}%`, background: k ? `var(--pj-${k})` : "#8892a8" }} /></span><b>{v}</b></li>)}</ul></Panel>
        <Panel icon="bulb" title="Insights" sub="Key revenue signals (fictional)">
          <ul className="insights">{[["$41,020", "Net receipts this month", "↑ 24%"], ["12", "Renewals in the next 30 days", ""], ["7", "Trial to paid conversions", "↑ 40%"], ["4", "Overdue invoices", ""]].map(([v, l, d]) => <li key={l}><b>{v}</b><small>{l}</small>{d && <em className="t-ok">{d}</em>}<Icon name="chevron" size={15} /></li>)}</ul></Panel>
      </div>
      <Panel icon="doc" title="Recent Subscriptions" sub="Latest subscriptions, invoices and customer accounts (fictional companies)">
        <table className="grid"><thead><tr><th>Customer</th><th>Plan</th><th>Product</th><th>Seats</th><th>MRR</th><th>Status</th><th>Renewal</th></tr></thead>
          <tbody>{[["Example Realty Co.", "Enterprise", "SamVision", 50, "$5,000", "Active", "in 30 days"], ["Sample Homes LLC", "Business", "SamVision", 20, "$2,400", "Active", "in 14 days"], ["Demo Family Plan", "Team", "MyFamilyExpenses", 8, "$960", "Active", "in 34 days"],
            ["Placeholder Partners", "Starter", "SamVision", 3, "$297", "Past due", "5 days ago"], ["Fictional Agency", "Business", "Consulting", 15, "$1,800", "Active", "in 22 days"]].map((r) =>
            <tr key={r[0] as string}><td>{r[0]}</td><td><Pill tone={r[1] === "Enterprise" ? "warn" : r[1] === "Business" ? "info" : r[1] === "Team" ? "violet" : "ok"}>{r[1]}</Pill></td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td>
              <td><Pill tone={r[5] === "Active" ? "ok" : "warn"}>{r[5]}</Pill></td><td className={r[5] === "Active" ? "muted" : "t-bad"}>{r[6]}</td></tr>)}</tbody></table>
      </Panel>
      <p className="muted small"><Demo label="Fictional" /> Currency USD · time zone America/Winnipeg · period: last 12 months.</p>
    </>}
  </div>;
}
