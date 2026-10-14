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

// Unambiguous year-month-day in every locale. toLocaleString() printed 8/10/2026 on an
// Indian-locale machine, which a US reader takes as 10 August.
export function when(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
