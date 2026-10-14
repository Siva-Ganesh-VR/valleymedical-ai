import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ActionError, LoadState, Notice, Pill } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import { CATEGORY_LABELS, FLAG_LABELS, money, STATE_LABELS, stateTone, usDate } from "../labels";
import { useSession } from "../session";

export default function BillingPage() {
  const navigate = useNavigate();
  const { user } = useSession();
  const queues = useLoad(() => api.queues(), []);
  const [queue, setQueue] = useState<string>("");
  useEffect(() => {
    if (!queue && queues.data?.length) setQueue(queues.data[0]);
  }, [queues.data, queue]);
  const cases = useLoad(() => (queue ? api.cases(queue) : Promise.resolve([])), [queue]);
  const sync = useAction();
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const canWork = user.role === "biller" || user.role === "billing_approver";

  const pull = () =>
    sync.run(async () => {
      const r = await api.sync(queue);
      setSyncNote(`${r.created} new case${r.created === 1 ? "" : "s"}, ${r.already_open} already open, ${r.no_action} need no action.`);
      await cases.reload();
    });

  if (queues.error || !queues.data) return <LoadState loading={queues.loading} error={queues.error} />;

  const waiting = (cases.data ?? []).filter((c) => stateTone(c.state) === "human").length;

  return (
    <section>
      <header className="page-head">
        <h1>Billing work</h1>
        <p className="lede">The agent classifies claims, gathers records and drafts letters. People confirm every classification and approve every draft. Nothing is sent from here.</p>
      </header>
      <div className="toolbar">
        <label>
          Work queue{" "}
          <select value={queue} onChange={(e) => setQueue(e.target.value)}>
            {queues.data.map((q) => <option key={q} value={q}>{q}</option>)}
          </select>
        </label>
        {canWork && (
          <button className="primary" disabled={!queue || sync.busy} onClick={pull}>
            {sync.busy ? "Reading queue…" : "Read work queue"}
          </button>
        )}
        {syncNote && <span className="fine">{syncNote}</span>}
      </div>
      <ActionError message={sync.error} />
      {waiting > 0 && <Notice tone="human" title={`${waiting} case${waiting > 1 ? "s" : ""} waiting for a person`} />}
      <LoadState loading={cases.loading && !cases.data} error={cases.error} />
      {cases.data && cases.data.length === 0 && (
        <p className="empty">No cases yet. {canWork ? "Read the work queue to start." : "Ask billing staff to read the work queue."}</p>
      )}
      {cases.data && cases.data.length > 0 && (
        <table className="table clickable">
          <thead>
            <tr><th>Claim</th><th>Payer</th><th>Service date</th><th className="num">Billed</th><th>Category</th><th>Status</th><th>Owner</th></tr>
          </thead>
          <tbody>
            {cases.data.map((c) => (
              <tr key={c.id} onClick={() => navigate(`/billing/cases/${c.id}`)} tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/billing/cases/${c.id}`)}>
                <td><strong>{c.claim_id}</strong>{c.denial_code && <span className="fine"> code {c.denial_code}</span>}</td>
                <td>{c.payer}</td>
                <td className="num">{usDate(c.date_of_service)}</td>
                <td className="num">{money(c.billed_amount)}</td>
                <td>
                  {c.category ? CATEGORY_LABELS[c.category] ?? c.category : "None"}
                  {c.category && !c.category_confirmed && <span className="fine"> (proposed)</span>}
                  {c.flags.map((f) => <div key={f} className="flag">{FLAG_LABELS[f] ?? f}</div>)}
                </td>
                <td><Pill tone={stateTone(c.state)}>{STATE_LABELS[c.state] ?? c.state}</Pill></td>
                <td>{c.owner ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
