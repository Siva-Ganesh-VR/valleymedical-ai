import { api } from "../api";
import { LoadState, Notice } from "../components/ui";
import { useLoad } from "../hooks";
import { when } from "../labels";

export default function AuditPage() {
  const rows = useLoad(() => api.audit(), []);
  const check = useLoad(() => api.verifyAudit(), []);

  return (
    <section>
      <header className="page-head">
        <h1>Audit log</h1>
        <p className="lede">Every record read, model call, decision and approval. Each entry is chained to the one before it, so edits are detectable.</p>
      </header>
      {check.data && (check.data.ok
        ? <Notice tone="info" title={`Chain intact: ${check.data.checked} entries verified`} />
        : <Notice tone="critical" title="Audit chain broken">Entry {check.data.first_invalid_id} doesn't match its recorded hash.</Notice>)}
      <LoadState loading={rows.loading && !rows.data} error={rows.error} />
      {rows.data && (
        <div className="table-wrap">
          <table className="table dense">
            <thead><tr><th>Time</th><th>Who</th><th>Action</th><th>About</th><th>Purpose</th><th>Model and prompt</th></tr></thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.id}>
                  <td className="num">{when(r.ts)}</td>
                  <td>{r.actor}<div className="fine">{r.actor_role}</div></td>
                  <td>{r.action}</td>
                  <td>{r.entity_type} {r.entity_id.length > 14 ? r.entity_id.slice(0, 8) : r.entity_id}{r.patient_ref && <div className="fine">patient {r.patient_ref}</div>}</td>
                  <td>{r.purpose ?? ""}</td>
                  <td>{r.model ? <>{r.model}<div className="fine">{r.prompt_version}</div></> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
