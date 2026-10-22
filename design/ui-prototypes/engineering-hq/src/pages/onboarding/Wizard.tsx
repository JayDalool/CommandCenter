// The shared wizard frame for New Agent and New Project: stepper, step card, live preview, footer.
// The draft lives in shared view state (data/live.ts), so a wizard moved to another window keeps it.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/form";
import { Demo, cx, plural } from "../../components/ui";
import { PopButton } from "../../windows/Detachable";
import { focusWindow, owners, returnHere } from "../../windows/manager";
import { viewState } from "../../data/live";
import { go } from "../../lib/router";
import type { Issue, Result } from "../../data/validate";

export interface StepDef { id: string; label: string; icon: string; hint: string }

/** Read / write one key of a view's shared state outside React (entry points, actions). */
export const peekView = <T,>(view: string, key: string): T | undefined => viewState.get()[view]?.[key] as T | undefined;
export const putView = (view: string, key: string, v: unknown) => viewState.set((s) => ({ ...s, [view]: { ...(s[view] ?? {}), [key]: v } }));
/** Show a page: focus its window if it is popped out, else go there in this window. */
/** A wizard finished in a pop-out: the result opens in the main window and the pop-out returns there, instead of
 *  staying behind as an empty wizard. */
export function leavePopout(viewId: string) { if (location.hash.startsWith("#/pop/")) returnHere(viewId); }
export function showPage(screen: string) { const id = `page:${screen}`; if (owners.get()[id]) focusWindow(id); else go(screen); }

export function Wizard({ viewId, title, sub, steps, step, setStep, result, preview, children, onSave, onCancelConfirmed, dirty, approve, banner, mode }: {
  viewId: string; title: ReactNode; sub: ReactNode; steps: StepDef[]; step: number; setStep: (i: number) => void; result: Result;
  preview: ReactNode; children: ReactNode; onSave?: () => void; onCancelConfirmed: () => void; dirty: boolean;
  approve: { label: string; run: () => void; icon?: string }; banner?: ReactNode; mode?: string;
}) {
  const [confirm, setConfirm] = useState(false);
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => { top.current?.scrollIntoView?.({ block: "start" }); }, [step]);
  const cur = steps[step] ?? steps[0];
  const last = step === steps.length - 1;
  const errs = (id: string) => result.errors.filter((e) => e.step === id).length;
  const here = result.errors.filter((e) => e.step === cur.id);
  const hereW = result.warnings.filter((e) => e.step === cur.id);
  const cancel = () => (dirty ? setConfirm(true) : onCancelConfirmed());
  return <div className="page page-wizard" data-mode={mode} ref={top}>
    <header className="wz-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <span className="sp" />
      <span className="wz-mock" title="Approving changes only this prototype's local mock data"><Icon name="shield" size={15} /> Mock only · nothing leaves this prototype</span>
      <Demo label="Prototype" />
      <PopButton id={viewId} label="Pop out" />
    </header>
    {banner}
    <div className="wz-grid">
      <nav className="wz-steps" aria-label="Steps">
        <ol>{steps.map((s, i) => { const n = errs(s.id); const showErr = n > 0 && (i < step || last);
          return <li key={s.id}><button type="button" className={cx("wz-step", i === step && "is-cur", i < step && !showErr && "is-done", showErr && "is-err")}
            aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)}>
            <span className="wz-num">{showErr ? "!" : i < step ? <Icon name="tick" size={13} stroke={2.6} /> : i + 1}</span>
            <span className="wz-lbl"><b>{s.label}</b>{showErr && <small className="t-bad">{plural(n, "issue")}</small>}</span></button></li>; })}</ol>
      </nav>
      <section className="wz-main" aria-labelledby="wz-step-title">
        <header className="wz-step-h"><span className="wz-step-ico"><Icon name={cur.icon} size={20} /></span>
          <div><small className="muted">Step {step + 1} of {steps.length}</small><h2 id="wz-step-title">{cur.label}</h2><p>{cur.hint}</p></div></header>
        <div className="wz-body" key={cur.id}>{children}</div>
        {!last && (here.length > 0 || hereW.length > 0) && <IssueList errors={here} warnings={hereW} compact />}
        <footer className="wz-foot">
          <button type="button" className="btn" onClick={cancel}>Cancel</button>
          {onSave && <button type="button" className="btn" onClick={onSave}><Icon name="doc" size={15} /> Save Draft</button>}
          <span className="sp" />
          {step > 0 && <button type="button" className="btn" onClick={() => setStep(step - 1)}><Icon name="arrowl" size={15} /> Back</button>}
          {!last ? <button type="button" className="btn btn-primary" onClick={() => setStep(step + 1)}>Next: {steps[step + 1].label} <Icon name="arrowr" size={15} /></button>
            : <button type="button" className="btn btn-primary" disabled={result.errors.length > 0} onClick={approve.run}
              title={result.errors.length ? "Fix the issues above first" : undefined}><Icon name={approve.icon ?? "shield"} size={16} /> {approve.label}</button>}
        </footer>
      </section>
      <aside className="wz-preview" aria-label="Preview">{preview}</aside>
    </div>
    {confirm && <Modal title="Discard your changes?" tone="warn" onClose={() => setConfirm(false)}
      footer={<><button type="button" className="btn" data-autofocus onClick={() => setConfirm(false)}>Keep editing</button>
        {onSave && <button type="button" className="btn" onClick={() => { setConfirm(false); onSave(); onCancelConfirmed(); }}>Save draft and close</button>}
        <button type="button" className="btn btn-danger" onClick={() => { setConfirm(false); onCancelConfirmed(); }}>Discard</button></>}>
      <p>You have changes that aren't saved. Discarding them adds nothing to the organisation. Saved drafts stay in Agents → Drafts.</p>
    </Modal>}
  </div>;
}

export function IssueList({ errors, warnings, compact, goTo, steps, applyFix }: { errors: Issue[]; warnings: Issue[]; compact?: boolean; goTo?: (step: string) => void; steps?: StepDef[]; applyFix?: (i: Issue) => void }) {
  if (!errors.length && !warnings.length) return compact ? null : <p className="callout t-ok"><Icon name="check" size={16} /> No issues. Everything needed is filled in.</p>;
  const label = (id: string) => steps?.find((s) => s.id === id)?.label;
  const row = (i: Issue, k: number, tone: "bad" | "warn") => <li key={tone + k} className={`iss t-${tone}`}>
    <Icon name={tone === "bad" ? "info" : "help"} size={15} /><span>{i.msg}</span>
    {i.fix && applyFix && <button type="button" className="btn btn-sm" onClick={() => applyFix(i)}>{i.fix.label}</button>}
    {goTo && label(i.step) && <button type="button" className="link" onClick={() => goTo(i.step)}>{label(i.step)} <Icon name="arrowr" size={12} /></button>}</li>;
  return <div className={cx("issues", compact && "is-compact")} role="status" aria-label="Validation">
    {errors.length > 0 && <><h4 className="t-bad">{plural(errors.length, "issue")} to fix before approval</h4><ul>{errors.map((e, k) => row(e, k, "bad"))}</ul></>}
    {warnings.length > 0 && <><h4 className="t-warn">{plural(warnings.length, "warning")}</h4><ul>{warnings.map((e, k) => row(e, k, "warn"))}</ul></>}
  </div>;
}

/** Jay → … → the new agent, and whoever it will supervise. */
export function Hierarchy({ chain, below }: { chain: { key: string; name: string; role: string; color: string; glyph: string; me?: boolean; jay?: boolean }[]; below: { key: string; name: string; color: string; glyph: string }[] }) {
  return <ol className="hier" aria-label="Reporting line">
    {chain.map((c) => <li key={c.key} className={cx(c.me && "is-me")}>
      {c.jay ? <span className="av av-jay" style={{ width: 30, height: 30, fontSize: 13 }}>J</span>
        : <span className="av" style={{ width: 30, height: 30, ["--c" as string]: c.color }}><Icon name={c.glyph} size={16} stroke={2} /></span>}
      <span><b>{c.name}</b><small>{c.role}</small></span>{c.me && <em>new</em>}</li>)}
    {below.length > 0 && <li className="hier-below">{below.map((b) => <span key={b.key} className="hier-sub"><span className="av" style={{ width: 22, height: 22, ["--c" as string]: b.color }}><Icon name={b.glyph} size={12} stroke={2} /></span>{b.name}</span>)}</li>}
  </ol>;
}
