import { useState } from "react";
import { features, type BillingInsights } from "../api";
import { ActionError, LoadState, Notice, Pill } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import { CATEGORY_LABELS, STATE_LABELS, money, when } from "../labels";
import { useSession } from "../session";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);

function Kpi({ label, value, target, n, unit, note }: { label: string; value: number | null; target: number; n: number; unit: string; note: string }) {
  const tone = value === null ? "neutral" : value >= target ? "done" : "human";
  return (
    <div className={`kpi kpi-${tone}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{pct(value)}</span>
      <span className="fine">Target {pct(target)} · {n} {unit}</span>
      <span className="fine">{value === null ? note : value >= target ? "Meets target" : "Below target"}</span>
    </div>
  );
}

export default function InsightsPage() {
  const { user } = useSession();
  const { data, loading, error, reload } = useLoad(() => features.insights(), []);
  const canEdit = user.role === "billing_approver" || user.role === "admin";
  const download = useAction();

  const exportCsv = () => download.run(async () => {
    const text = await features.insightsCsv();
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `billing-cases-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  });

  if (!data) return <LoadState loading={loading} error={error} />;
  const m = data;
  return (
    <section>
      <header className="page-head row spread">
        <div>
          <h1>Billing insights</h1>
          <p className="lede">How the billing agent is performing against the feasibility targets, from real decisions in this workspace. Every figure shows how many cases it is based on.</p>
        </div>
        <button disabled={download.busy} onClick={exportCsv}>Export cases (CSV)</button>
      </header>
      <ActionError message={download.error} />

      <div className="kpis">
        <Kpi label="Classification accuracy" value={m.classification.proposal_accuracy} target={m.thresholds.classification}
             n={m.classification.reviewed} unit="reviewed" note="No classifications reviewed yet" />
        <Kpi label="Supporting records complete" value={m.supporting_records.rate} target={m.thresholds.supporting_records}
             n={m.supporting_records.cases} unit="cases" note="No records retrieved yet" />
        <Kpi label="Drafts usable as written or with minor edits" value={m.drafts.usable_rate} target={m.thresholds.draft_usable}
             n={m.drafts.rated} unit="rated" note="No drafts rated yet" />
        <Kpi label="Handling-time reduction" value={m.handling_time.overall_reduction} target={m.thresholds.handling_reduction}
             n={m.handling_time.by_category.reduce((a, r) => a + r.cases, 0)} unit="timed cases"
             note={m.handling_time.baseline_captured ? "No timed cases yet" : "Needs a time-study baseline"} />
      </div>
      {m.demo_seeded_cases > 0 && (
        <Notice tone="info" title={`${m.demo_seeded_cases} cases were moved by the demo workload loader`}>
          Their classification and draft decisions are left out of the accuracy and usability figures. Volume and money still include them.
        </Notice>
      )}
      {m.handling_time.baseline_synthetic && (
        <Notice tone="human" title="The handling-time baseline includes synthetic demo figures">Replace them with the real pre-agent time study before quoting any reduction.</Notice>
      )}
      {m.classification.reviewed > 0 && (
        <p className="fine">Model alone agreed with reviewers on {pct(m.classification.model_accuracy)} ({m.classification.model_agreed}/{m.classification.reviewed}); deterministic rules lift the proposal to {pct(m.classification.proposal_accuracy)}.</p>
      )}

      <div className="money">
        <div><span className="kpi-label">Open, not yet resolved</span><span className="money-value">{money(m.money.at_risk_open)}</span><span className="fine">{m.money.open_cases} cases</span></div>
        <div><span className="kpi-label">Appeals approved and with an owner</span><span className="money-value">{money(m.money.appeals_with_owner)}</span><span className="fine">{m.money.appeal_cases} cases</span></div>
        <div><span className="kpi-label">Worked to completion</span><span className="money-value">{money(m.money.worked_to_completion)}</span><span className="fine">{m.money.completed_cases} cases. Not the same as money recovered: payer outcomes aren't visible yet.</span></div>
      </div>

      <div className="two-col">
        <div className="panel">
          <h2>Where cases are</h2>
          <Bars data={m.volume.by_state} label={(k) => STATE_LABELS[k] ?? k} />
        </div>
        <div className="panel">
          <h2>By category</h2>
          <Bars data={m.volume.by_category} label={(k) => CATEGORY_LABELS[k] ?? k} />
          {Object.keys(m.escalations).length > 0 && (
            <>
              <h3>Escalations</h3>
              <Bars data={m.escalations} label={(k) => k.replace(/_/g, " ")} />
            </>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>Handling time</h2>
        <p className="fine">Active time a person spent on each case (the screen counts only while it's open and in focus), compared with the time-study baseline.</p>
        {m.handling_time.by_category.length === 0 ? <p className="empty">No timed cases or baselines yet.</p> : (
          <table className="table">
            <thead><tr><th>Category</th><th className="num">Timed cases</th><th className="num">With agent (min)</th><th className="num">Baseline (min)</th><th className="num">Reduction</th></tr></thead>
            <tbody>
              {m.handling_time.by_category.map((r) => (
                <tr key={r.category}>
                  <td>{CATEGORY_LABELS[r.category] ?? r.category}</td>
                  <td className="num">{r.cases}</td>
                  <td className="num">{r.avg_minutes_with_agent ?? "–"}</td>
                  <td className="num">{r.baseline_minutes ?? "–"} {r.baseline_synthetic && <Pill tone="human">synthetic</Pill>}</td>
                  <td className="num">{pct(r.reduction)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Baselines data={data} canEdit={canEdit} onSaved={reload} />
      <p className="fine">Updated {when(m.generated_at)}.</p>
    </section>
  );
}

function Bars({ data, label }: { data: Record<string, number>; label: (k: string) => string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <p className="empty small">Nothing yet.</p>;
  return (
    <ul className="bars">
      {entries.map(([k, v]) => (
        <li key={k}>
          <span className="bar-label">{label(k)}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></span>
          <span className="num">{v}</span>
        </li>
      ))}
    </ul>
  );
}

function Baselines({ data, canEdit, onSaved }: { data: BillingInsights; canEdit: boolean; onSaved: () => void }) {
  const [form, setForm] = useState({ category: "MEDICAL_NECESSITY", minutes: "", sample: "", source: "" });
  const action = useAction();
  const save = () => action.run(async () => {
    await features.addBaseline({ category: form.category, minutes_per_case: Number(form.minutes), sample_size: Number(form.sample), source: form.source });
    setForm({ ...form, minutes: "", sample: "", source: "" });
    onSaved();
  });
  return (
    <div className="panel">
      <h2>Time-study baseline</h2>
      <p className="fine">Minutes per case before the agent, measured by billing staff in Months 1 to 2. The reduction is calculated against the latest entry per category.</p>
      {data.baselines.length > 0 && (
        <table className="table dense">
          <thead><tr><th>Category</th><th className="num">Minutes per case</th><th className="num">Sample</th><th>Source</th><th>Entered</th></tr></thead>
          <tbody>
            {data.baselines.map((b) => (
              <tr key={b.category}>
                <td>{CATEGORY_LABELS[b.category] ?? b.category}</td>
                <td className="num">{b.minutes_per_case}</td>
                <td className="num">{b.sample_size}</td>
                <td>{b.source} {b.synthetic && <Pill tone="human">synthetic</Pill>}</td>
                <td className="fine">{b.created_by}, {when(b.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <div className="baseline-form">
          <label>Category
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>Minutes per case<input type="number" min="0.1" step="0.1" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} /></label>
          <label>Cases timed<input type="number" min="1" value={form.sample} onChange={(e) => setForm({ ...form, sample: e.target.value })} /></label>
          <label className="grow">Source<input placeholder="e.g. Time study, 2 billers, 14-25 Oct" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></label>
          <button className="primary" disabled={action.busy || !form.minutes || !form.sample || form.source.trim().length < 3} onClick={save}>Save baseline</button>
          <button disabled={action.busy} onClick={() => action.run(async () => { await features.demoBaselines(); onSaved(); })}>Load synthetic demo baseline</button>
        </div>
      )}
      <ActionError message={action.error} />
    </div>
  );
}
