import { useEffect, useState } from "react";
import { features, type AcceptanceResult, type AcceptanceRunView, type CriterionStatus } from "../api";
import { ActionError, LoadState, Notice, Pill } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import type { Tone } from "../labels";
import { when } from "../labels";
import { useSession } from "../session";

const STATUS: Record<CriterionStatus, { label: string; tone: Tone }> = {
  pass: { label: "Pass", tone: "done" },
  fail: { label: "Fail", tone: "critical" },
  measured: { label: "Measured", tone: "neutral" },
  pending: { label: "Pending pilot", tone: "human" },
  not_testable: { label: "Not testable yet", tone: "neutral" },
};

export default function AcceptancePage() {
  const { user } = useSession();
  const runs = useLoad(() => features.acceptanceRuns(), []);
  const [selected, setSelected] = useState<AcceptanceRunView | null>(null);
  const action = useAction();
  useEffect(() => {
    if (runs.data?.length && !selected) setSelected(runs.data[0]);
  }, [runs.data, selected]);

  const run = () => action.run(async () => {
    const r = await features.runAcceptance();
    setSelected(r);
    await runs.reload();
  });

  if (runs.error) return <LoadState loading={false} error={runs.error} />;
  return (
    <section>
      <header className="page-head row spread">
        <div>
          <h1>Acceptance scorecard</h1>
          <p className="lede">Runs the platform against a labelled test set in an isolated sandbox and scores every acceptance criterion from Valley Medical's feasibility document. Live data isn't touched.</p>
        </div>
        {user.role === "admin" && (
          <button className="primary" disabled={action.busy} onClick={run}>{action.busy ? "Running tests…" : "Run acceptance tests"}</button>
        )}
      </header>
      {action.busy && <p className="fine">Running the real pipelines with the configured model. With a live model this takes a minute or two.</p>}
      <ActionError message={action.error} />
      {!selected && !runs.loading && <p className="empty">No runs yet.{user.role === "admin" ? " Run the tests to see the scorecard." : " An administrator can run the tests."}</p>}
      {selected && <Scorecard run={selected} />}
      {runs.data && runs.data.length > 1 && (
        <details className="panel">
          <summary>Previous runs</summary>
          <ul className="plain">
            {runs.data.map((r) => (
              <li key={r.id}>
                <button className="link" onClick={() => setSelected(r)}>{when(r.created_at)}</button>{" "}
                {r.summary.pass} pass, {r.summary.fail} fail, model {r.model}{r.id === selected?.id && " (showing)"}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function Scorecard({ run }: { run: AcceptanceRunView }) {
  const s = run.summary;
  const groups = ["Meditab", "Billing", "Both"];
  return (
    <>
      {s.hard_gate_failures.length === 0 ? (
        <Notice tone="info" title="No hard-gate failures">
          Patient matching, clinical integrity, human approval, auditability and exception handling all passed on this test set.
          {s.hard_gates_pending.length > 0 && <> Still pending: {s.hard_gates_pending.join(", ")} (needs deployment controls).</>}
        </Notice>
      ) : (
        <Notice tone="critical" title={`Hard gate failed: ${s.hard_gate_failures.join(", ")}`}>Safety-critical criteria are never averaged with performance. Fix before anything else.</Notice>
      )}
      {s.mock_model && (
        <Notice tone="human" title="Run with the offline mock model">This proves the controls and plumbing. Accuracy figures only mean something with a live model (set GEMINI_API_KEY or ANTHROPIC_API_KEY).</Notice>
      )}
      <div className="score-row">
        {(["pass", "fail", "measured", "pending", "not_testable"] as const).map((k) => (
          <div key={k} className={`score-tile tile-${STATUS[k].tone}`}><span className="score-big">{s[k]}</span><span className="fine">{STATUS[k].label}</span></div>
        ))}
        <div className="score-meta fine">
          {when(run.created_at)} by {run.actor}<br />
          Model {run.model}, {s.model_calls} calls, {s.tokens.toLocaleString()} tokens, {s.seconds}s<br />
          Test set {run.testset_version}
        </div>
      </div>
      {groups.map((g) => (
        <div key={g} className="panel">
          <h2>{g === "Meditab" ? "Core Proof 1: Meditab integration" : g === "Billing" ? "Core Proof 2: Billing agent" : "Both proofs"}</h2>
          <ul className="criteria">
            {run.results.filter((r) => r.proof === g).map((r) => <Criterion key={r.id} r={r} />)}
          </ul>
        </div>
      ))}
      <p className="fine">An automated pre-check on synthetic data, not the formal acceptance test. The formal test set is agreed with Valley Medical, who keep final authority over it, the scoring and written acceptance.</p>
    </>
  );
}

function Criterion({ r }: { r: AcceptanceResult }) {
  const st = STATUS[r.status];
  return (
    <li className={`criterion criterion-${r.status}`}>
      <details>
        <summary>
          <span className="crit-id">{r.id}</span>
          <span className="crit-main">
            <strong>{r.area}</strong>{r.hard_gate && <span className="hard">Hard gate</span>}
            <span className="fine">{r.requirement}. Target: {r.threshold}</span>
          </span>
          <span className="crit-value">{r.value}{r.n !== null && r.n > 0 && <span className="fine"> n={r.n}</span>}</span>
          <Pill tone={st.tone}>{st.label}</Pill>
        </summary>
        <div className="crit-body">
          <ul>{r.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
          {r.failures.length > 0 && (<><strong>Problems found</strong><ul className="fails">{r.failures.map((f, i) => <li key={i}>{f}</li>)}</ul></>)}
        </div>
      </details>
    </li>
  );
}
