import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ChronicPainView, type ClinicalRecord, type RecordItem, type SummaryResult } from "../api";
import DocAuditTab from "../components/DocAuditTab";
import SourcePanel, { type SourceSelection } from "../components/SourcePanel";
import Sparkline from "../components/Sparkline";
import { ActionError, LoadState, Notice } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import { SECTION_LABELS, sourcePath, when } from "../labels";

const TABS = ["summary", "chronic", "audit", "medications", "allergies", "problems", "labs", "encounters", "documents"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABELS: Record<Tab, string> = {
  summary: "Pre-visit summary", chronic: "Chronic pain", audit: "Documentation audit", medications: "Medications", allergies: "Allergies",
  problems: "Problems", labs: "Labs", encounters: "Encounters", documents: "Documents",
};

export default function PatientPage() {
  const { patientId = "" } = useParams();
  const { data: record, loading, error } = useLoad(() => api.record(patientId), [patientId]);
  const [tab, setTab] = useState<Tab>("summary");
  const [selection, setSelection] = useState<SourceSelection | null>(null);
  const close = useCallback(() => setSelection(null), []);

  if (!record) return <LoadState loading={loading} error={error} />;
  const p = record.patient;
  const unavailable = record.statuses.filter((s) => s.status === "unavailable");

  return (
    <div className={`with-panel${selection ? " panel-open" : ""}`}>
      <section>
        <p className="crumb"><Link to="/patients">Patients</Link></p>
        <header className="page-head patient-head">
          <h1>{p.last_name}, {p.first_name}</h1>
          <dl className="facts">
            <div><dt>MRN</dt><dd>{p.mrn}</dd></div>
            <div><dt>Date of birth</dt><dd>{p.dob}</dd></div>
            <div><dt>Sex</dt><dd>{p.sex}</dd></div>
            <div><dt>Read from Meditab</dt><dd>{when(record.retrieved_at)}</dd></div>
          </dl>
        </header>

        {unavailable.length > 0 && (
          <Notice tone="human" title={`${unavailable.map((s) => SECTION_LABELS[s.section]).join(", ")} could not be loaded from Meditab`}>
            Those sections are shown as unavailable, not empty. Anything generated from this record leaves them out.
          </Notice>
        )}
        {record.quarantined.map((q) => (
          <Notice key={q.document_id} tone="critical" title={`Withheld: ${q.title}`}>
            The identifiers printed in this document don't match this patient, so it isn't shown or used. It's in the exception queue for review.
          </Notice>
        ))}

        <div className="tabs" role="tablist" aria-label="Record sections">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={`tab${tab === t ? " active" : ""}`} onClick={() => setTab(t)}>
              {TAB_LABELS[t]}
              {t !== "summary" && t !== "chronic" && t !== "audit" && <SectionCount record={record} section={t} />}
            </button>
          ))}
        </div>

        {tab === "summary" && <SummaryTab patientId={patientId} onCite={setSelection} />}
        {tab === "chronic" && <ChronicTab patientId={patientId} onCite={setSelection} />}
        {tab === "audit" && <DocAuditTab patientId={patientId} onCite={setSelection} />}
        {tab !== "summary" && tab !== "chronic" && tab !== "audit" && <SectionTable record={record} section={tab} onCite={setSelection} />}
      </section>
      <SourcePanel selection={selection} onClose={close} />
    </div>
  );
}

function SectionCount({ record, section }: { record: ClinicalRecord; section: string }) {
  const status = record.statuses.find((s) => s.section === section);
  if (!status) return null;
  return <span className="count">{status.status === "unavailable" ? "!" : status.item_count}</span>;
}

function SectionTable({ record, section, onCite }: { record: ClinicalRecord; section: string; onCite: (s: SourceSelection) => void }) {
  const status = record.statuses.find((s) => s.section === section);
  const items = record.items[section] ?? [];
  if (status?.status === "unavailable")
    return <Notice tone="human" title={`${SECTION_LABELS[section]} are unavailable`}>{status.message ?? "Meditab did not respond."} Try again later; don't assume there are none.</Notice>;
  if (items.length === 0) return <p className="empty">No {SECTION_LABELS[section].toLowerCase()} are recorded in Meditab for this patient.</p>;
  return (
    <ul className="record-list">
      {items.map((i) => (
        <li key={i.item_id}>
          <span className="record-date num">{i.date}</span>
          <span className="record-text">{i.display}</span>
          <button className="link source-link" onClick={() => onCite({ label: SECTION_LABELS[section], display: i.display, source: i.source })}>
            {sourcePath(i.source)}
          </button>
        </li>
      ))}
    </ul>
  );
}

function SummaryTab({ patientId, onCite }: { patientId: string; onCite: (s: SourceSelection) => void }) {
  const [result, setResult] = useState<SummaryResult | null>(null);
  const action = useAction();
  const generate = (force = false) => action.run(async () => setResult(await api.summary(patientId, force)));
  const label = (n: number) => `${n}`;

  return (
    <div className="summary">
      <div className="summary-bar">
        <button className="primary" disabled={action.busy} onClick={() => generate()}>
          {action.busy ? "Writing summary…" : result ? "Write a new summary" : "Write pre-visit summary"}
        </button>
        <p className="fine">Every statement links to its Meditab source. Statements the system can't trace to a source are removed and listed below.</p>
      </div>
      <ActionError message={action.error} />
      {result && (
        <>
          {result.reused && (
            <Notice tone="info" title="Nothing in the chart has changed, so the earlier summary was reused">
              No AI call was needed. <button className="link" disabled={action.busy} onClick={() => generate(true)}>Write a fresh one anyway</button>
            </Notice>
          )}
          {result.message && <Notice tone={result.status === "failed" ? "human" : "info"} title={result.message} />}
          {result.data_gaps.length > 0 && (
            <Notice tone="human" title="Not included in this summary">
              <ul>{result.data_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
            </Notice>
          )}
          <div className="verified">
            <div>
              <h3>Active medications, from Meditab</h3>
              <VerifiedList items={result.verified_medications} empty="None recorded" onCite={onCite} label="Medication" />
            </div>
            <div>
              <h3>Allergies, from Meditab</h3>
              <VerifiedList items={result.verified_allergies} empty="None recorded. Confirm with the patient." onCite={onCite} label="Allergy" />
            </div>
          </div>
          {result.statements.length > 0 && (
            <article className="narrative">
              {result.statements.map((s, idx) => (
                <p key={idx}>
                  {s.text}
                  {s.citations.map((c, ci) => (
                    <button key={c.evidence_id} className="cite" title={sourcePath(c.source)}
                            onClick={() => onCite({ label: `Source ${idx + 1}.${ci + 1}`, display: c.display, source: c.source })}>
                      {label(idx + 1)}{s.citations.length > 1 ? `.${ci + 1}` : ""}
                    </button>
                  ))}
                </p>
              ))}
            </article>
          )}
          {result.removed.length > 0 && (
            <details className="removed">
              <summary>{result.removed.length} statement{result.removed.length > 1 ? "s" : ""} removed because they couldn't be traced to a source</summary>
              <ul>{result.removed.map((r, i) => <li key={i}><s>{r.text}</s> <span className="fine">{r.reasons.join("; ")}</span></li>)}</ul>
            </details>
          )}
          <p className="fine">Draft for clinician review. Written {when(result.generated_at)} by {result.model ?? "no model"} using prompt {result.prompt_version}.</p>
        </>
      )}
    </div>
  );
}

function VerifiedList({ items, empty, onCite, label }: { items: RecordItem[]; empty: string; onCite: (s: SourceSelection) => void; label: string }) {
  if (items.length === 0) return <p className="empty small">{empty}</p>;
  return (
    <ul className="plain">
      {items.map((i) => (
        <li key={i.item_id}>
          <button className="link" onClick={() => onCite({ label, display: i.display, source: i.source })}>{i.display}</button>
        </li>
      ))}
    </ul>
  );
}

function ChronicTab({ patientId, onCite }: { patientId: string; onCite: (s: SourceSelection) => void }) {
  const { data, loading, error } = useLoad<ChronicPainView>(() => api.chronicPain(patientId), [patientId]);
  if (!data) return <LoadState loading={loading} error={error} />;
  return (
    <div className="chronic">
      <div className="dims">
        {data.dimensions.map((d) => (
          <div key={d.dimension} className="dim">
            <h3>{d.label}</h3>
            {d.status === "unavailable" && <p className="empty small">Couldn't load scores from Meditab.</p>}
            {d.status === "no_data" && <p className="empty small">No {d.label.toLowerCase()} scores recorded.</p>}
            {d.status === "data" && (
              <>
                <Sparkline points={d.points} label={d.label} />
                <ol className="points">
                  {d.points.map((p) => (
                    <li key={p.item_id}>
                      <button className="link" onClick={() => onCite({ label: d.label, display: `${d.label} ${p.display_value} (${p.instrument}) on ${p.date}`, source: p.source })}>
                        <span className="num">{p.date}</span> <strong>{p.display_value}</strong>
                      </button>
                    </li>
                  ))}
                </ol>
                <p className="fine">{d.points[0].instrument}</p>
              </>
            )}
          </div>
        ))}
      </div>

      <h2>Response to past treatment</h2>
      {data.treatment_responses.length === 0 ? (
        <p className="empty">No procedures recorded.</p>
      ) : (
        <table className="table">
          <thead><tr><th>Procedure</th><th>Date</th><th>Pain before</th><th>Pain after</th></tr></thead>
          <tbody>
            {data.treatment_responses.map((t) => (
              <tr key={t.procedure.item_id}>
                <td><button className="link" onClick={() => onCite({ label: "Procedure", display: t.procedure.display, source: t.procedure.source })}>{String(t.procedure.data.name)}</button></td>
                <td className="num">{t.procedure.date}</td>
                <td className="num">{t.pain_before ? `${t.pain_before.display_value} (${t.pain_before.date})` : "No score within 90 days"}</td>
                <td className="num">{t.pain_after ? `${t.pain_after.display_value} (${t.pain_after.date})` : "No score within 90 days"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="two-col">
        <div>
          <h2>Medications</h2>
          <VerifiedList items={data.medications} empty="None recorded" onCite={onCite} label="Medication" />
        </div>
        <div>
          <h2>Imaging</h2>
          <VerifiedList items={data.imaging} empty="No imaging reports in Meditab" onCite={onCite} label="Imaging" />
        </div>
      </div>
      <p className="fine">Calculated directly from Meditab data. No AI model is used on this tab.</p>
    </div>
  );
}
