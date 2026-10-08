// Typed API client. POC identity is sent as demo headers; production uses SSO tokens.

export type Role = "provider" | "biller" | "billing_approver" | "admin";

export interface DemoUser {
  username: string;
  role: Role;
  label: string;
}

export const DEMO_USERS: DemoUser[] = [
  { username: "dr.test", role: "provider", label: "Dr. Test (provider)" },
  { username: "biller.test", role: "biller", label: "Biller Test (billing staff)" },
  { username: "approver.test", role: "billing_approver", label: "Approver Test (billing approver)" },
  { username: "admin.test", role: "admin", label: "Admin Test (administrator)" },
];

let currentUser: DemoUser = DEMO_USERS[0];
export function setApiUser(user: DemoUser) {
  currentUser = user;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-Demo-User": currentUser.username,
        "X-Demo-Role": currentUser.role,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the platform API. Check that the backend is running on port 8000.");
  }
  if (!res.ok) {
    let code = "error";
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.message === "string") message = data.message;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
      if (typeof data.error === "string") code = data.error;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message);
  }
  return res.json() as Promise<T>;
}

// ------------------------------------------------------------------ types
export interface Patient {
  patient_id: string;
  mrn: string;
  first_name: string;
  last_name: string;
  dob: string;
  sex: string;
}

export interface SourceRef {
  system: string;
  record_type: string;
  record_id: string;
  encounter_id: string | null;
  recorded_on: string | null;
  page: number | null;
}

export interface RecordItem {
  item_id: string;
  section: string;
  display: string;
  date: string | null;
  data: Record<string, unknown>;
  source: SourceRef;
}

export interface SectionStatus {
  section: string;
  status: "ok" | "unavailable";
  item_count: number;
  message: string | null;
}

export interface ClinicalRecord {
  patient: Patient;
  items: Record<string, RecordItem[]>;
  statuses: SectionStatus[];
  quarantined: { document_id: string; title: string; reasons: string[] }[];
  retrieved_at: string;
}

export interface Citation {
  evidence_id: string;
  item_id: string;
  display: string;
  source: SourceRef;
}

export interface SummaryResult {
  patient_id: string;
  status: "ok" | "failed";
  statements: { section: string; text: string; citations: Citation[] }[];
  removed: { section: string; text: string; reasons: string[] }[];
  data_gaps: string[];
  verified_medications: RecordItem[];
  verified_allergies: RecordItem[];
  model: string | null;
  prompt_version: string;
  generated_at: string;
  message: string | null;
}

export interface TrendPoint {
  date: string;
  value: number;
  display_value: string;
  instrument: string;
  item_id: string;
  source: SourceRef;
}

export interface ChronicPainView {
  patient_id: string;
  dimensions: { dimension: string; label: string; status: "data" | "no_data" | "unavailable"; points: TrendPoint[] }[];
  medications: RecordItem[];
  treatment_responses: { procedure: RecordItem; pain_before: TrendPoint | null; pain_after: TrendPoint | null }[];
  imaging: RecordItem[];
  statuses: SectionStatus[];
  withheld_documents: number;
}

export interface CaseSummary {
  id: string;
  claim_id: string;
  queue: string;
  state: string;
  problem_type: string | null;
  category: string | null;
  category_confirmed: boolean;
  flags: string[];
  owner: string | null;
  payer: string;
  date_of_service: string;
  billed_amount: number;
  denial_code: string | null;
  updated_at: string;
}

export interface RetrievedRecord {
  requirement: string;
  item_id: string;
  section: string;
  display: string;
  source: SourceRef;
}

export interface CaseDetail extends CaseSummary {
  claim: {
    claim_id: string;
    patient_mrn: string;
    patient_last_name: string;
    payer: string;
    date_of_service: string;
    cpt_codes: string[];
    icd10_codes: string[];
    billed_amount: number;
    status: string;
    submitted_on: string | null;
    authorization_number: string | null;
    denial: { carc_code: string | null; description: string | null; denial_date: string | null; payer_remark: string | null } | null;
  };
  steps: { step: number; label: string; status: "done" | "current" | "waiting_human" | "blocked" | "pending" | "skipped" }[];
  classification: {
    rule_category: string | null;
    model_category: string | null;
    model_confidence: number | null;
    model_rationale: string | null;
    recommended_action: string | null;
    proposed_category: string | null;
    confirmed_category: string | null;
    reviewed_by: string | null;
  };
  meditab_patient_id: string | null;
  retrieved_records: RetrievedRecord[];
  gaps: { key: string; label: string; reason: string }[];
  draft: {
    type: string;
    text: string;
    evidence: { id: string; item_id: string; text: string }[];
    warnings: string[];
    version: number;
    source: string;
    model: string | null;
    prompt_version: string | null;
    reviewed_by: string | null;
    review_note: string | null;
  } | null;
  external_status: string | null;
  external_reference: string | null;
  escalation_reason: string | null;
  events: { ts: string; step: number; from_state: string | null; to_state: string; actor: string; summary: string }[];
  categories: string[];
}

export interface ExceptionRow {
  id: number;
  created_at: string;
  kind: string;
  severity: string;
  entity_type: string;
  entity_id: string;
  summary: string;
  status: string;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface AuditRow {
  id: number;
  ts: string;
  actor: string;
  actor_role: string;
  action: string;
  entity_type: string;
  entity_id: string;
  patient_ref: string | null;
  purpose: string | null;
  model: string | null;
  prompt_version: string | null;
  detail: Record<string, unknown>;
  hash: string;
}

// ------------------------------------------------------------------ endpoints
const enc = encodeURIComponent;

export const api = {
  health: () => request<{ status: string; llm: string; meditab: string; billing: string }>("GET", "/health"),
  patients: (q: string) => request<Patient[]>("GET", `/patients?q=${enc(q)}`),
  record: (id: string) => request<ClinicalRecord>("GET", `/patients/${enc(id)}/record`),
  chronicPain: (id: string) => request<ChronicPainView>("GET", `/patients/${enc(id)}/chronic-pain`),
  summary: (id: string) => request<SummaryResult>("POST", `/patients/${enc(id)}/previsit-summary`),

  queues: () => request<string[]>("GET", "/billing/queues"),
  sync: (queue: string) =>
    request<{ created: number; already_open: number; no_action: number }>("POST", `/billing/queues/${enc(queue)}/sync`),
  cases: (queue?: string) => request<CaseSummary[]>("GET", `/billing/cases${queue ? `?queue=${enc(queue)}` : ""}`),
  case: (id: string) => request<CaseDetail>("GET", `/billing/cases/${enc(id)}`),
  advance: (id: string) => request<CaseDetail>("POST", `/billing/cases/${enc(id)}/advance`),
  reviewClassification: (id: string, body: { decision: "confirm" | "change"; category?: string; note?: string }) =>
    request<CaseDetail>("POST", `/billing/cases/${enc(id)}/classification-review`, body),
  reviewDraft: (id: string, body: { decision: "approve" | "reject"; edited_text?: string; note?: string }) =>
    request<CaseDetail>("POST", `/billing/cases/${enc(id)}/draft-review`, body),
  tracking: (id: string, body: { status: "submitted_by_staff" | "resolved"; reference?: string; note?: string }) =>
    request<CaseDetail>("POST", `/billing/cases/${enc(id)}/tracking`, body),

  exceptions: (status?: string) => request<ExceptionRow[]>("GET", `/exceptions${status ? `?status=${enc(status)}` : ""}`),
  resolveException: (id: number, note: string) => request<{ id: number }>("POST", `/exceptions/${id}/resolve`, { note }),
  audit: () => request<AuditRow[]>("GET", "/audit?limit=300"),
  verifyAudit: () => request<{ ok: boolean; checked: number; first_invalid_id: number | null }>("GET", "/audit/verify"),
};
