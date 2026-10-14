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
  reused: boolean;
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
  escalation_kind: string | null;
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
  steps: { step: number; label: string; status: "done" | "current" | "waiting_human" | "blocked" | "pending" | "skipped" | "not_reached" }[];
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
  summary: (id: string, force = false) =>
    request<SummaryResult>("POST", `/patients/${enc(id)}/previsit-summary${force ? "?force=true" : ""}`),

  queues: () => request<string[]>("GET", "/billing/queues"),
  sync: (queue: string) =>
    request<{ created: number; already_open: number; no_action: number }>("POST", `/billing/queues/${enc(queue)}/sync`),
  cases: (queue?: string) => request<CaseSummary[]>("GET", `/billing/cases${queue ? `?queue=${enc(queue)}` : ""}`),
  case: (id: string) => request<CaseDetail>("GET", `/billing/cases/${enc(id)}`),
  advance: (id: string) => request<CaseDetail>("POST", `/billing/cases/${enc(id)}/advance`),
  retryAi: (id: string) => request<CaseDetail>("POST", `/billing/cases/${enc(id)}/retry-ai`),
  retryQueueAi: (queue: string) =>
    request<{ retried: string[]; recovered: string[]; still_failing: string[] }>("POST", `/billing/queues/${enc(queue)}/retry-ai`),
  reviewClassification: (id: string, body: { decision: "confirm" | "change"; category?: string; note?: string; handling_seconds?: number }) =>
    request<CaseDetail>("POST", `/billing/cases/${enc(id)}/classification-review`, body),
  reviewDraft: (id: string, body: { decision: "approve" | "reject"; edited_text?: string; note?: string; handling_seconds?: number; edit_level?: "none" | "minor" | "major" }) =>
    request<CaseDetail>("POST", `/billing/cases/${enc(id)}/draft-review`, body),
  tracking: (id: string, body: { status: "submitted_by_staff" | "resolved"; reference?: string; note?: string; handling_seconds?: number }) =>
    request<CaseDetail>("POST", `/billing/cases/${enc(id)}/tracking`, body),

  exceptions: (status?: string) => request<ExceptionRow[]>("GET", `/exceptions${status ? `?status=${enc(status)}` : ""}`),
  resolveException: (id: number, note: string) => request<{ id: number }>("POST", `/exceptions/${id}/resolve`, { note }),
  audit: () => request<AuditRow[]>("GET", "/audit?limit=300"),
  verifyAudit: () => request<{ ok: boolean; checked: number; first_invalid_id: number | null }>("GET", "/audit/verify"),
};

// ------------------------------------------------------------------ feature pack types
export interface AuditEvidence {
  item_id: string;
  display: string;
  source: SourceRef;
}

export interface DocAuditView {
  run_id: number;
  patient_id: string;
  created_at: string;
  actor: string;
  ruleset_version: string;
  model: string | null;
  prompt_version: string | null;
  checks_total: number;
  checks_passed: number;
  score: number | null;
  rules: { rule_id: string; title: string; description: string; method: "rule" | "ai"; severity: string }[];
  passed: { rule_id: string; target: string; note: string; evidence: AuditEvidence[] }[];
  not_checked: string[];
  findings: {
    id: number;
    rule_id: string;
    rule_title: string;
    target: string;
    severity: string;
    method: "rule" | "ai";
    message: string;
    evidence: AuditEvidence[];
    status: "open" | "confirmed" | "dismissed";
    reviewed_by: string | null;
    review_note: string | null;
  }[];
}

export interface Baseline {
  category: string;
  minutes_per_case: number;
  sample_size: number;
  source: string;
  synthetic: boolean;
  created_by: string;
  created_at: string;
}

export interface BillingInsights {
  generated_at: string;
  thresholds: Record<string, number>;
  volume: { cases: number; worked: number; by_state: Record<string, number>; waiting_for_person: number; escalated: number; completed: number; by_category: Record<string, number> };
  classification: { reviewed: number; proposal_agreed: number; proposal_accuracy: number | null; model_agreed: number; model_accuracy: number | null };
  supporting_records: { cases: number; complete: number; rate: number | null };
  drafts: { rated: number; usable: number; usable_rate: number | null; ratings: Record<string, number> };
  handling_time: {
    by_category: { category: string; cases: number; avg_minutes_with_agent: number | null; baseline_minutes: number | null; baseline_sample: number | null; baseline_synthetic: boolean | null; reduction: number | null }[];
    overall_reduction: number | null;
    baseline_captured: boolean;
    baseline_synthetic: boolean;
  };
  money: { at_risk_open: number; open_cases: number; appeals_with_owner: number; appeal_cases: number; worked_to_completion: number; completed_cases: number };
  escalations: Record<string, number>;
  demo_seeded_cases: number;
  baselines: Baseline[];
}

export type CriterionStatus = "pass" | "fail" | "measured" | "pending" | "not_testable";

export interface AcceptanceResult {
  id: string;
  proof: string;
  area: string;
  requirement: string;
  threshold: string;
  hard_gate: boolean;
  status: CriterionStatus;
  value: string;
  n: number | null;
  evidence: string[];
  failures: string[];
}

export interface AcceptanceRunView {
  id: number;
  created_at: string;
  actor: string;
  model: string;
  testset_version: string;
  hard_gates_passed: boolean;
  summary: {
    pass: number; fail: number; measured: number; pending: number; not_testable: number;
    hard_gate_failures: string[]; hard_gates_pending: string[];
    model_calls: number; tokens: number; seconds: number; mock_model: boolean;
  };
  results: AcceptanceResult[];
}

export interface AiUsage {
  provider: string;
  model: string;
  month: string;
  tokens_this_month: number;
  monthly_budget: number | null;
  budget_used: number | null;
  prices_configured: boolean;
  pause: { paused: boolean; reason?: string | null; updated_by?: string; updated_at?: string };
  by_task: { task: string; calls: number; errors: number; blocked: number; reused: number; input_tokens: number; output_tokens: number; avg_latency_ms: number | null; est_cost_usd: number | null }[];
  by_day: { day: string; tokens: number; calls: number }[];
  recent: { ts: string; task: string; status: string; model: string | null; prompt_version: string | null; tokens: number; latency_ms: number; note: string | null }[];
}

export const features = {
  runDocAudit: (pid: string) => request<DocAuditView>("POST", `/patients/${enc(pid)}/documentation-audit`),
  latestDocAudit: (pid: string) => request<DocAuditView | null>("GET", `/patients/${enc(pid)}/documentation-audit`),
  reviewFinding: (id: number, decision: "confirmed" | "dismissed", note?: string) =>
    request<DocAuditView>("POST", `/documentation-audit/findings/${id}/review`, { decision, note }),

  insights: () => request<BillingInsights>("GET", "/billing/insights"),
  addBaseline: (b: { category: string; minutes_per_case: number; sample_size: number; source: string }) =>
    request<{ category: string }>("POST", "/billing/baselines", b),
  demoBaselines: () => request<{ loaded: number }>("POST", "/billing/baselines/demo"),
  demoWorkload: (queue: string) =>
    request<{ moved: string[]; skipped: string[]; problems: string[] }>("POST", `/billing/queues/${enc(queue)}/demo-workload`),
  insightsCsv: () => requestText("/billing/insights.csv"),

  acceptanceRuns: () => request<AcceptanceRunView[]>("GET", "/acceptance/runs"),
  runAcceptance: () => request<AcceptanceRunView>("POST", "/acceptance/run"),

  aiUsage: () => request<AiUsage>("GET", "/ai/usage"),
  setPaused: (paused: boolean, reason?: string) => request<AiUsage["pause"]>("POST", "/ai/pause", { paused, reason }),
};

async function requestText(path: string): Promise<string> {
  const res = await fetch(`/api${path}`, { headers: { "X-Demo-User": currentUser.username, "X-Demo-Role": currentUser.role } });
  if (!res.ok) throw new ApiError(res.status, "error", `Download failed (${res.status})`);
  return res.text();
}
