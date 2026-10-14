import { useState } from "react";
import { features } from "../api";
import { ActionError, LoadState, Notice, Pill } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import { when } from "../labels";
import { useSession } from "../session";

const TASK_LABELS: Record<string, string> = {
  previsit_summary: "Pre-visit summaries",
  billing_classify: "Billing classification",
  billing_draft: "Billing drafts",
  doc_audit_notes: "Documentation audit",
  acceptance_run: "Acceptance tests",
};

export default function AiUsagePage() {
  const { user } = useSession();
  const { data, loading, error, reload } = useLoad(() => features.aiUsage(), []);
  const [reason, setReason] = useState("");
  const action = useAction();
  if (!data) return <LoadState loading={loading} error={error} />;
  const u = data;
  const maxDay = Math.max(1, ...u.by_day.map((d) => d.tokens));
  const reusedTotal = u.by_task.reduce((a, t) => a + t.reused, 0);

  return (
    <section>
      <header className="page-head">
        <h1>AI usage and controls</h1>
        <p className="lede">Every model call goes through one gateway, which records it, enforces the monthly budget and can stop all AI instantly.</p>
      </header>

      {u.pause.paused && (
        <Notice tone="critical" title="AI is paused">
          {u.pause.reason ?? "No reason given"}. New AI work goes to the exception queue; people can keep working. Paused by {u.pause.updated_by}.
        </Notice>
      )}

      <div className="kpis">
        <div className="kpi"><span className="kpi-label">Provider and model</span><span className="kpi-value small">{u.provider}</span><span className="fine">{u.model}</span></div>
        <div className="kpi">
          <span className="kpi-label">Tokens this month ({u.month})</span>
          <span className="kpi-value">{u.tokens_this_month.toLocaleString()}</span>
          {u.monthly_budget ? (
            <>
              <span className="bar-track"><span className={`bar-fill${(u.budget_used ?? 0) > 0.8 ? " warn" : ""}`} style={{ width: `${Math.min(100, (u.budget_used ?? 0) * 100)}%` }} /></span>
              <span className="fine">{Math.round((u.budget_used ?? 0) * 100)}% of {u.monthly_budget.toLocaleString()} budget</span>
            </>
          ) : <span className="fine">No budget set</span>}
        </div>
        <div className="kpi"><span className="kpi-label">Calls avoided by reuse</span><span className="kpi-value">{reusedTotal}</span><span className="fine">Summaries reused when the chart hadn't changed</span></div>
      </div>
      {!u.prices_configured && <p className="fine">Set VM_LLM_PRICE_INPUT_PER_MTOK and VM_LLM_PRICE_OUTPUT_PER_MTOK from your provider's price page to see estimated cost.</p>}

      {user.role === "admin" && (
        <div className="panel">
          <h2>Kill switch</h2>
          <p className="fine">Stops every AI call immediately. Billing cases and summaries fall back safely; nothing is lost.</p>
          <div className="row">
            {!u.pause.paused && <input placeholder="Reason (shown to staff)" value={reason} onChange={(e) => setReason(e.target.value)} />}
            <button className={u.pause.paused ? "primary" : "danger"} disabled={action.busy}
                    onClick={() => action.run(async () => { await features.setPaused(!u.pause.paused, reason || undefined); setReason(""); await reload(); })}>
              {u.pause.paused ? "Resume AI" : "Pause all AI"}
            </button>
          </div>
          <ActionError message={action.error} />
        </div>
      )}

      <div className="panel">
        <h2>By workflow</h2>
        {u.by_task.length === 0 ? <p className="empty">No AI calls yet.</p> : (
          <table className="table">
            <thead><tr><th>Workflow</th><th className="num">Calls</th><th className="num">Tokens in</th><th className="num">Tokens out</th><th className="num">Avg time</th><th className="num">Reused</th><th className="num">Failed or blocked</th><th className="num">Est. cost</th></tr></thead>
            <tbody>
              {u.by_task.map((t) => (
                <tr key={t.task}>
                  <td>{TASK_LABELS[t.task] ?? t.task}</td>
                  <td className="num">{t.calls}</td>
                  <td className="num">{t.input_tokens.toLocaleString()}</td>
                  <td className="num">{t.output_tokens.toLocaleString()}</td>
                  <td className="num">{t.avg_latency_ms === null ? "–" : `${(t.avg_latency_ms / 1000).toFixed(1)}s`}</td>
                  <td className="num">{t.reused}</td>
                  <td className="num">{t.errors + t.blocked}</td>
                  <td className="num">{t.est_cost_usd === null ? "–" : `$${t.est_cost_usd.toFixed(4)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {u.by_day.length > 0 && (
        <div className="panel">
          <h2>Tokens per day</h2>
          <ul className="bars">
            {u.by_day.map((d) => (
              <li key={d.day}>
                <span className="bar-label num">{d.day}</span>
                <span className="bar-track"><span className="bar-fill" style={{ width: `${(d.tokens / maxDay) * 100}%` }} /></span>
                <span className="num">{d.tokens.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="panel">
        <summary>Recent calls ({u.recent.length})</summary>
        <table className="table dense">
          <thead><tr><th>Time</th><th>Workflow</th><th>Status</th><th>Model and prompt</th><th className="num">Tokens</th><th className="num">Time</th></tr></thead>
          <tbody>
            {u.recent.map((c, i) => (
              <tr key={i}>
                <td className="num">{when(c.ts)}</td>
                <td>{TASK_LABELS[c.task] ?? c.task}</td>
                <td><Pill tone={c.status === "ok" ? "done" : c.status === "reused" ? "neutral" : "critical"}>{c.status}</Pill>{c.note && <div className="fine">{c.note}</div>}</td>
                <td>{c.model ?? ""}<div className="fine">{c.prompt_version ?? ""}</div></td>
                <td className="num">{c.tokens.toLocaleString()}</td>
                <td className="num">{c.latency_ms ? `${(c.latency_ms / 1000).toFixed(1)}s` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
