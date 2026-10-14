export const STATE_LABELS: Record<string, string> = {
  IDENTIFIED: "Classifying",
  NO_ACTION: "No action needed",
  AWAITING_CLASSIFICATION_REVIEW: "Needs classification review",
  CLASSIFICATION_CONFIRMED: "Retrieving records",
  RECORDS_RETRIEVED: "Drafting",
  AWAITING_DRAFT_APPROVAL: "Needs draft approval",
  DRAFT_REJECTED: "Draft rejected",
  APPROVED: "Approved",
  ROUTED: "With owner",
  SUBMITTED_BY_STAFF: "Submitted by staff",
  COMPLETED: "Completed",
  ESCALATED: "Escalated to a person",
};

export type Tone = "neutral" | "human" | "critical" | "done";

export function stateTone(state: string): Tone {
  if (state === "AWAITING_CLASSIFICATION_REVIEW" || state === "AWAITING_DRAFT_APPROVAL" || state === "DRAFT_REJECTED")
    return "human";
  if (state === "ESCALATED") return "critical";
  if (state === "COMPLETED" || state === "NO_ACTION") return "done";
  return "neutral";
}

export const CATEGORY_LABELS: Record<string, string> = {
  MEDICAL_NECESSITY: "Medical necessity",
  MISSING_PRIOR_AUTH: "Missing prior authorization",
  MISSING_DOCUMENTATION: "Missing documentation",
  CODING_ERROR: "Coding error",
  ELIGIBILITY: "Eligibility",
  TIMELY_FILING: "Timely filing",
  DUPLICATE: "Duplicate claim",
  NO_PAYER_RESPONSE: "No payer response",
  OTHER: "Other",
};

export const FLAG_LABELS: Record<string, string> = {
  suspicious_content: "Instruction-like text in payer message",
  rule_overrides_model: "Rule overrode the model",
  low_confidence: "Low model confidence",
  invalid_model_output: "Model output was invalid",
};

export const DRAFT_LABELS: Record<string, string> = {
  appeal_letter: "Appeal letter",
  provider_query: "Provider query",
  payer_follow_up: "Payer follow-up",
  coding_review: "Coding review note",
};

export const SECTION_LABELS: Record<string, string> = {
  encounters: "Encounters",
  medications: "Medications",
  allergies: "Allergies",
  problems: "Problems",
  labs: "Labs",
  observations: "Scores",
  procedures: "Procedures",
  documents: "Documents",
};

export function sourcePath(s: { record_type: string; record_id: string; page: number | null }) {
  return `Meditab / ${s.record_type.replace("_", " ")} / ${s.record_id}${s.page ? `, page ${s.page}` : ""}`;
}

export function money(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

// US format (MM/DD/YYYY). Always explicit, so the display never depends on the machine's locale
// (toLocaleString() printed 10/8/2026 vs 8/10/2026 depending on the region).
export function usDate(iso: string | null | undefined) {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (m) return `${m[2]}/${m[3]}/${m[1]}`;
  return iso;
}

// Timestamp as MM/DD/YYYY hh:mm AM/PM in the viewer's time zone.
export function when(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  const h = d.getHours() % 12 || 12;
  return `${p(d.getMonth() + 1)}/${p(d.getDate())}/${d.getFullYear()} ${p(h)}:${p(d.getMinutes())} ${d.getHours() < 12 ? "AM" : "PM"}`;
}

// Rewrites ISO dates and timestamps inside free text (record lines, findings, drafts) for display.
// Display only: never pass the result back to the API or into an editable field.
export function usText(text: string | null | undefined) {
  if (!text) return text ?? "";
  return text.replace(
    /\b(\d{4})-(\d{2})-(\d{2})(T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?(?!\d)/g,
    (m, y, mo, d, time) => (time ? when(m) : `${mo}/${d}/${y}`),
  );
}

// "2026-10" -> "10/2026"
export function usMonth(ym: string) {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  return m ? `${m[2]}/${m[1]}` : ym;
}
