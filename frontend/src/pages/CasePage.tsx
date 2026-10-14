import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type CaseDetail } from "../api";
import { ActionError, LoadState, Notice, Pill } from "../components/ui";
import { useAction, useActiveTimer, useLoad } from "../hooks";
import { CATEGORY_LABELS, DRAFT_LABELS, FLAG_LABELS, money, sourcePath, STATE_LABELS, stateTone, when } from "../labels";
import { useSession } from "../session";

const STEP_TEXT: Record<string, string> = {
  done: "Done", current: "In progress", waiting_human: "Waiting for a person", blocked: "Stopped here",
  pending: "Not started", skipped: "Not needed", not_reached: "Not reached",
};

export default function CasePage() {
  const { caseId = "" } = useParams();
  const { data, setData, loading, error } = useLoad(() => api.case(caseId), [caseId]);
  if (!data) return <LoadState loading={loading} error={error} />;
  return <CaseView c={data} onChange={setData} />;
}

const HUMAN_STATES = ["AWAITING_CLASSIFICATION_REVIEW", "AWAITING_DRAFT_APPROVAL", "DRAFT_REJECTED", "ROUTED", "SUBMITTED_BY_STAFF", "ESCALATED"];

function CaseView({ c, onChange }: { c: CaseDetail; onChange: (c: CaseDetail) => void }) {
  const { user } = useSession();
  // Active time on this case while it needs a person: feeds the handling-time measurement (AI-18).
  const timer = useActiveTimer(HUMAN_STATES.includes(c.state));
  const take = timer.take;
  const canReview = user.role === "biller" || user.role === "billing_approver";
  const canApprove = user.role === "billing_approver";
  const canWork = canReview;

  return (
    <section>
      <p className="crumb"><Link to="/billing">Billing work</Link></p>
      <header className="page-head case-head">
        <div>
          <h1>Claim {c.claim_id}</h1>
          <p className="lede">{c.payer}, service on {c.date_of_service}, {money(c.billed_amount)}</p>
        </div>
        <Pill tone={stateTone(c.state)}>{STATE_LABELS[c.state] ?? c.state}</Pill>
      </header>

      <div className="case-grid">
        <ol className="steps" aria-label="Workflow steps">
          {c.steps.map((s) => (
            <li key={s.step} className={`step step-${s.status}`}>
              <span className="step-n">{s.step}</span>
              <span className="step-label">{s.label}<small>{STEP_TEXT[s.status]}</small></span>
            </li>
          ))}
        </ol>

        <div className="case-main">
          {c.state === "ESCALATED" && (
            <Notice tone="critical" title="Stopped and handed to a person">
              {c.escalation_reason}
              {c.owner && <> Owner: {c.owner}.</>} See the exception queue.
            </Notice>
          )}
          {c.flags.includes("suspicious_content") && (
            <Notice tone="critical" title="The payer's message contains text that looks like instructions">
              It was treated as data only and had no effect on the agent. Check the remittance before acting.
            </Notice>
          )}

          <Classification c={c} canReview={canReview} onChange={onChange} take={take} />
          {(c.retrieved_records.length > 0 || c.gaps.length > 0 || c.meditab_patient_id) && <Records c={c} />}
          {c.draft && <Draft c={c} canApprove={canApprove} onChange={onChange} take={take} />}
          {c.state === "DRAFT_REJECTED" && canWork && <Redraft c={c} onChange={onChange} />}
          {["ROUTED", "SUBMITTED_BY_STAFF", "ESCALATED"].includes(c.state) && canWork && <Tracking c={c} onChange={onChange} take={take} />}
          <ClaimFacts c={c} />
          <Events c={c} />
        </div>
      </div>
    </section>
  );
}

function Classification({ c, canReview, onChange, take }: { c: CaseDetail; canReview: boolean; onChange: (c: CaseDetail) => void; take: () => number }) {
  const k = c.classification;
  const action = useAction();
  const [changeTo, setChangeTo] = useState("");
  const [note, setNote] = useState("");
  const awaiting = c.state === "AWAITING_CLASSIFICATION_REVIEW";
  const label = (cat: string | null) => (cat ? CATEGORY_LABELS[cat] ?? cat : "None");

  return (
    <div className="panel">
      <h2>Classification</h2>
      {!k.model_category && c.state !== "NO_ACTION" && <p className="empty small">Not classified yet.</p>}
      {c.state === "NO_ACTION" && <p className="empty small">Nothing wrong with this claim. No action needed.</p>}
      {k.model_category && (
        <dl className="kv">
          <dt>Rule result</dt><dd>{k.rule_category ? label(k.rule_category) : "No rule applies"}</dd>
          <dt>Model suggestion</dt>
          <dd>{label(k.model_category)} {k.model_confidence !== null && <span className="fine">confidence {Math.round(k.model_confidence * 100)}%</span>}</dd>
          <dt>Model's reasoning</dt><dd>{k.model_rationale}</dd>
          <dt>Suggested next step</dt><dd>{k.recommended_action}</dd>
          <dt>{k.confirmed_category ? "Confirmed" : "Proposed"}</dt>
          <dd><strong>{label(k.confirmed_category ?? k.proposed_category)}</strong>{k.reviewed_by && <span className="fine"> by {k.reviewed_by}</span>}</dd>
        </dl>
      )}
      {c.flags.filter((f) => f !== "suspicious_content").map((f) => <p key={f} className="flag">{FLAG_LABELS[f] ?? f}</p>)}
      {awaiting && canReview && (
        <div className="decide">
          <label>Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <div className="row">
            <button className="primary" disabled={action.busy}
                    onClick={() => action.run(async () => onChange(await api.reviewClassification(c.id, { decision: "confirm", note: note || undefined, handling_seconds: take() })))}>
              Confirm {label(k.proposed_category)}
            </button>
            <select aria-label="Change category to" value={changeTo} onChange={(e) => setChangeTo(e.target.value)}>
              <option value="">Change to…</option>
              {c.categories.map((cat) => <option key={cat} value={cat}>{label(cat)}</option>)}
            </select>
            <button disabled={!changeTo || action.busy}
                    onClick={() => action.run(async () => onChange(await api.reviewClassification(c.id, { decision: "change", category: changeTo, note: note || undefined, handling_seconds: take() })))}>
              Use this category
            </button>
          </div>
          {action.busy && <p className="fine">The agent is retrieving records and drafting…</p>}
        </div>
      )}
      {awaiting && !canReview && <p className="fine">Billing staff confirm classifications. Switch user to continue.</p>}
      <ActionError message={action.error} />
    </div>
  );
}

function Records({ c }: { c: CaseDetail }) {
  const groups = Array.from(new Set(c.retrieved_records.map((r) => r.requirement)));
  return (
    <div className="panel">
      <h2>Supporting records from Meditab</h2>
      <p className="fine">Only the records this category needs were read (minimum necessary). Patient {c.meditab_patient_id ?? "not matched"}.</p>
      {groups.map((g) => (
        <div key={g} className="req">
          <h3>{g.replace(/_/g, " ")}</h3>
          <ul className="record-list compact">
            {c.retrieved_records.filter((r) => r.requirement === g).map((r) => (
              <li key={r.item_id}>
                <span className="record-text">{r.display}</span>
                <span className="fine">{sourcePath(r.source)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {c.gaps.length > 0 && (
        <Notice tone="human" title="Missing items">
          <ul>{c.gaps.map((g) => <li key={g.key}><strong>{g.label}.</strong> {g.reason}.</li>)}</ul>
        </Notice>
      )}
      {c.gaps.length === 0 && c.retrieved_records.length > 0 && <p className="fine">No missing items found.</p>}
    </div>
  );
}

function Draft({ c, canApprove, onChange, take }: { c: CaseDetail; canApprove: boolean; onChange: (c: CaseDetail) => void; take: () => number }) {
  const d = c.draft!;
  const awaiting = c.state === "AWAITING_DRAFT_APPROVAL";
  const [text, setText] = useState(d.text);
  const [note, setNote] = useState("");
  const [rating, setRating] = useState<"none" | "minor" | "major" | "">("");
  const action = useAction();
  useEffect(() => setText(d.text), [d.text, d.version]);
  const edited = text !== d.text;
  useEffect(() => { if (!edited) setRating(""); }, [edited]);
  const level = edited ? rating : "none";

  return (
    <div className="panel">
      <h2>{DRAFT_LABELS[d.type] ?? d.type} <span className="fine">version {d.version}</span></h2>
      {d.warnings.map((w) => <Notice key={w} tone="human" title="Check before approving">{w}</Notice>)}
      {awaiting && canApprove ? (
        <textarea className="draft-text" value={text} onChange={(e) => setText(e.target.value)} rows={Math.min(24, text.split("\n").length + 2)} aria-label="Draft text" />
      ) : (
        <pre className="draft-text">{d.text}</pre>
      )}
      {d.evidence.length > 0 && (
        <details>
          <summary>{d.evidence.length} cited record{d.evidence.length > 1 ? "s" : ""}</summary>
          <ul className="plain">{d.evidence.map((e) => <li key={e.id}><strong>[{e.id}]</strong> {e.text}</li>)}</ul>
        </details>
      )}
      <p className="fine">
        {d.source === "human_edited" ? "Edited by a person. " : `Drafted by ${d.model ?? "model"} using prompt ${d.prompt_version}. `}
        {d.reviewed_by && `Reviewed by ${d.reviewed_by}.`} {d.review_note && `Note: ${d.review_note}`}
      </p>
      {awaiting && canApprove && (
        <div className="decide">
          {edited && (
            <fieldset className="rating">
              <legend>How much did you change? (measures draft usability)</legend>
              {(["minor", "major"] as const).map((r) => (
                <label key={r} className="radio">
                  <input type="radio" name={`rating-${c.id}`} checked={rating === r} onChange={() => setRating(r)} />
                  {r === "minor" ? "Minor edits (wording, small fixes)" : "Major rewrite (facts, structure or argument)"}
                </label>
              ))}
            </fieldset>
          )}
          <label>Note {edited ? "(optional)" : "(required to reject)"}<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <div className="row">
            <button className="primary" disabled={action.busy || (edited && !rating)}
                    onClick={() => action.run(async () => onChange(await api.reviewDraft(c.id, { decision: "approve", edited_text: edited ? text : undefined, note: note || undefined, handling_seconds: take(), edit_level: level || undefined })))}>
              {edited ? "Approve with my edits" : "Approve and route"}
            </button>
            <button disabled={action.busy || !note.trim()}
                    onClick={() => action.run(async () => onChange(await api.reviewDraft(c.id, { decision: "reject", note, handling_seconds: take() })))}>
              Reject draft
            </button>
          </div>
          <p className="fine">Approving routes the item to its owner. It does not send anything to the payer.</p>
        </div>
      )}
      {awaiting && !canApprove && <p className="fine">Only a billing approver can approve drafts. Switch user to continue.</p>}
      <ActionError message={action.error} />
    </div>
  );
}

function Redraft({ c, onChange }: { c: CaseDetail; onChange: (c: CaseDetail) => void }) {
  const action = useAction();
  return (
    <div className="panel">
      <p>The draft was rejected{c.draft?.review_note ? `: "${c.draft.review_note}"` : ""}. The agent will use that note.</p>
      <button className="primary" disabled={action.busy} onClick={() => action.run(async () => onChange(await api.advance(c.id)))}>
        {action.busy ? "Redrafting…" : "Write a new draft"}
      </button>
      <ActionError message={action.error} />
    </div>
  );
}

function Tracking({ c, onChange, take }: { c: CaseDetail; onChange: (c: CaseDetail) => void; take: () => number }) {
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const action = useAction();
  return (
    <div className="panel">
      <h2>Tracking</h2>
      {c.owner && <p>Owner: <strong>{c.owner}</strong></p>}
      {c.external_reference && <p>Submitted by staff, reference {c.external_reference}.</p>}
      {c.state === "ROUTED" && (
        <div className="decide">
          <label>Reference from the payer portal or clearinghouse<input value={reference} onChange={(e) => setReference(e.target.value)} /></label>
          <button className="primary" disabled={action.busy || !reference.trim()}
                  onClick={() => action.run(async () => onChange(await api.tracking(c.id, { status: "submitted_by_staff", reference, handling_seconds: take() })))}>
            Record staff submission
          </button>
          <p className="fine">Staff submit outside this platform, then record it here.</p>
        </div>
      )}
      {(c.state === "SUBMITTED_BY_STAFF" || c.state === "ESCALATED" || c.state === "ROUTED") && (
        <div className="decide">
          <label>
            Resolution note {c.state === "ESCALATED" ? "(required)" : "(optional)"}
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={c.state === "ESCALATED" ? "What was done to resolve it?" : ""} />
          </label>
          <button disabled={action.busy || (c.state === "ESCALATED" && note.trim().length < 3)}
                  onClick={() => action.run(async () => onChange(await api.tracking(c.id, { status: "resolved", note: note || undefined, handling_seconds: take() })))}>
            Mark resolved
          </button>
          <p className="fine">Resolving the case also closes its open exceptions.</p>
        </div>
      )}
      <ActionError message={action.error} />
    </div>
  );
}

function ClaimFacts({ c }: { c: CaseDetail }) {
  const k = c.claim;
  return (
    <details className="panel">
      <summary>Claim details from the billing system</summary>
      <dl className="kv">
        <dt>Patient on claim</dt><dd>{k.patient_last_name}, MRN {k.patient_mrn}</dd>
        <dt>Procedure codes</dt><dd>{k.cpt_codes.join(", ")}</dd>
        <dt>Diagnosis codes</dt><dd>{k.icd10_codes.join(", ") || "None"}</dd>
        <dt>Submitted</dt><dd>{k.submitted_on ?? "Unknown"}</dd>
        <dt>Authorization</dt><dd>{k.authorization_number ?? "None on claim"}</dd>
        {k.denial && (<>
          <dt>Denial</dt><dd>Code {k.denial.carc_code}: {k.denial.description} ({k.denial.denial_date})</dd>
          {k.denial.payer_remark && (<><dt>Payer remark</dt><dd className="untrusted">{k.denial.payer_remark}</dd></>)}
        </>)}
      </dl>
    </details>
  );
}

function Events({ c }: { c: CaseDetail }) {
  return (
    <details className="panel" open>
      <summary>Activity ({c.events.length})</summary>
      <ol className="events">
        {c.events.map((e, i) => (
          <li key={i}>
            <span className="num fine">{when(e.ts)}</span>
            <span>Step {e.step}: {e.summary}</span>
            <span className="fine">{e.actor}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
