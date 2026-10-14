import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type ExceptionRow } from "../api";
import { ActionError, LoadState, Pill } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import { usText, when } from "../labels";
import { useSession } from "../session";

const KIND_LABELS: Record<string, string> = {
  document_identity_mismatch: "Document doesn't match patient",
  cross_patient_item: "Another patient's data was withheld",
  billing_patient_match: "Claim patient couldn't be matched",
  suspicious_content: "Instruction-like text in payer data",
  llm_failure: "Model unavailable",
  hard_stop_rule: "Rule requires a person",
  draft_validation_failed: "Draft failed safety checks",
  source_unavailable: "Meditab unavailable",
  draft_limit: "Too many redrafts",
};

export default function ExceptionsPage() {
  const [status, setStatus] = useState("open");
  const { data, loading, error, reload } = useLoad(() => api.exceptions(status || undefined), [status]);
  const { user } = useSession();
  const canResolve = user.role !== "biller";

  return (
    <section>
      <header className="page-head">
        <h1>Exceptions</h1>
        <p className="lede">Anything the platform couldn't handle safely stops here for a person. Nothing is retried automatically.</p>
      </header>
      <div className="toolbar">
        <label>Show <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Open</option><option value="resolved">Resolved</option><option value="">All</option>
        </select></label>
      </div>
      <LoadState loading={loading && !data} error={error} />
      {data && data.length === 0 && <p className="empty">No {status || ""} exceptions.</p>}
      {data && data.length > 0 && (
        <ul className="exceptions">
          {data.map((e) => <ExceptionItem key={e.id} e={e} canResolve={canResolve} onResolved={reload} />)}
        </ul>
      )}
    </section>
  );
}

function ExceptionItem({ e, canResolve, onResolved }: { e: ExceptionRow; canResolve: boolean; onResolved: () => void }) {
  const [note, setNote] = useState("");
  const action = useAction();
  const tone = e.severity === "critical" || e.severity === "high" ? "critical" : "human";
  return (
    <li className="exception">
      <div className="row spread">
        <span><Pill tone={tone}>{e.severity}</Pill> <strong>{KIND_LABELS[e.kind] ?? e.kind}</strong></span>
        <span className="fine num">{when(e.created_at)}</span>
      </div>
      <p>{usText(e.summary)}</p>
      <p className="fine">
        {e.entity_type === "billing_case" ? <Link to={`/billing/cases/${e.entity_id}`}>Open the billing case</Link> : `${e.entity_type} ${e.entity_id}`}
      </p>
      {e.status === "open" && canResolve && (
        <div className="row">
          <input aria-label="Resolution note" placeholder="What did you do?" value={note} onChange={(ev) => setNote(ev.target.value)} />
          <button disabled={note.trim().length < 3 || action.busy}
                  onClick={() => action.run(async () => { await api.resolveException(e.id, note); onResolved(); })}>
            Resolve
          </button>
        </div>
      )}
      {e.status === "resolved" && <p className="fine">Resolved by {e.resolved_by}: {e.resolution_note}</p>}
      <ActionError message={action.error} />
    </li>
  );
}
