import { useState } from "react";
import { features, type DocAuditView } from "../api";
import { useAction, useLoad } from "../hooks";
import { usText, when } from "../labels";
import { useSession } from "../session";
import type { SourceSelection } from "./SourcePanel";
import { ActionError, LoadState, Notice, Pill } from "./ui";

export default function DocAuditTab({ patientId, onCite }: { patientId: string; onCite: (s: SourceSelection) => void }) {
  const { user } = useSession();
  const latest = useLoad(() => features.latestDocAudit(patientId), [patientId]);
  const run = useAction();
  const [view, setView] = useState<DocAuditView | null>(null);
  const current = view ?? latest.data;
  const canRun = user.role === "provider" || user.role === "admin";
  const canReview = user.role === "provider";

  if (latest.loading && !current) return <LoadState loading error={null} />;
  if (latest.error) return <LoadState loading={false} error={latest.error} />;

  return (
    <div className="doc-audit">
      <div className="summary-bar">
        {canRun && (
          <button className="primary" disabled={run.busy} onClick={() => run.run(async () => setView(await features.runDocAudit(patientId)))}>
            {run.busy ? "Auditing…" : current ? "Run audit again" : "Run documentation audit"}
          </button>
        )}
        <p className="fine">Checks the chart against documentation rules. Rule checks run as code; narrative checks use AI and must quote the note, or they become findings for review.</p>
      </div>
      <ActionError message={run.error} />
      {!current && <p className="empty">No audit has been run for this patient yet.</p>}
      {current && <AuditResult view={current} onCite={onCite} canReview={canReview} onReviewed={setView} />}
    </div>
  );
}

function AuditResult({ view, onCite, canReview, onReviewed }: {
  view: DocAuditView; onCite: (s: SourceSelection) => void; canReview: boolean; onReviewed: (v: DocAuditView) => void;
}) {
  const open = view.findings.filter((f) => f.status === "open").length;
  const pct = view.score === null ? "–" : `${Math.round(view.score * 100)}%`;
  return (
    <>
      <div className="score-row">
        <div className="score-tile">
          <span className="score-big">{pct}</span>
          <span className="fine">{view.checks_passed} of {view.checks_total} checks met</span>
        </div>
        <div className="score-tile">
          <span className="score-big">{view.findings.length}</span>
          <span className="fine">findings, {open} awaiting review</span>
        </div>
        <div className="score-meta fine">
          Run {when(view.created_at)} by {view.actor}<br />
          Rules {view.ruleset_version}{view.model && <><br />AI checks: {view.model}, prompt {view.prompt_version}</>}
        </div>
      </div>
      <Notice tone="info" title="Illustrative rules">
        These seven rules demonstrate the engine. Valley Medical's own documentation rules replace them once supplied.
      </Notice>
      {view.not_checked.length > 0 && (
        <Notice tone="human" title={`Not checked: ${view.not_checked.join(", ")}`}>The data these rules need couldn't be loaded from Meditab.</Notice>
      )}

      <h2>Findings</h2>
      {view.findings.length === 0 && <p className="empty">No findings. Every applicable rule was met.</p>}
      <ul className="findings">
        {view.findings.map((f) => <FindingItem key={f.id} f={f} onCite={onCite} canReview={canReview} onReviewed={onReviewed} />)}
      </ul>

      <details className="panel">
        <summary>{view.passed.length} checks met</summary>
        <ul className="plain passed">
          {view.passed.map((p, i) => (
            <li key={i}>
              <strong>{p.rule_id}</strong> {view.rules.find((r) => r.rule_id === p.rule_id)?.title}, {p.target}: {usText(p.note)}
              {p.evidence[0] && <> <button className="link" onClick={() => onCite({ label: p.rule_id, display: p.evidence[0].display, source: p.evidence[0].source })}>source</button></>}
            </li>
          ))}
        </ul>
      </details>
      <details className="panel">
        <summary>Rules used</summary>
        <ul className="plain">
          {view.rules.map((r) => <li key={r.rule_id}><strong>{r.rule_id} {r.title}</strong> ({r.method === "ai" ? "AI-assisted" : "rule"}, {r.severity}). {r.description}</li>)}
        </ul>
      </details>
    </>
  );
}

function FindingItem({ f, onCite, canReview, onReviewed }: {
  f: DocAuditView["findings"][number]; onCite: (s: SourceSelection) => void; canReview: boolean; onReviewed: (v: DocAuditView) => void;
}) {
  const [note, setNote] = useState("");
  const action = useAction();
  return (
    <li className={`finding finding-${f.status}`}>
      <div className="row spread">
        <span>
          <Pill tone={f.severity === "high" ? "critical" : "human"}>{f.severity}</Pill>{" "}
          <strong>{f.rule_id} {f.rule_title}</strong> <span className="fine">{f.method === "ai" ? "AI-assisted check" : "rule check"}</span>
        </span>
        {f.status !== "open" && <Pill tone={f.status === "confirmed" ? "done" : "neutral"}>{f.status} by {f.reviewed_by}</Pill>}
      </div>
      <p>{usText(f.message)}</p>
      {f.evidence.map((e) => (
        <button key={e.item_id} className="link source-link" onClick={() => onCite({ label: f.rule_id, display: e.display, source: e.source })}>
          Meditab / {e.source.record_type} / {e.source.record_id}
        </button>
      ))}
      {f.review_note && <p className="fine">Reviewer note: {f.review_note}</p>}
      {f.status === "open" && canReview && (
        <div className="row">
          <input aria-label="Review note" placeholder="Note (required to dismiss)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button disabled={action.busy} onClick={() => action.run(async () => onReviewed(await features.reviewFinding(f.id, "confirmed", note || undefined)))}>Confirm</button>
          <button disabled={action.busy || note.trim().length < 3} onClick={() => action.run(async () => onReviewed(await features.reviewFinding(f.id, "dismissed", note)))}>Dismiss</button>
        </div>
      )}
      <ActionError message={action.error} />
    </li>
  );
}
