"""Persistent platform state. Clinical source data stays in Meditab; we store only
workflow state, references, drafts and the audit trail."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditEvent(Base):
    """Append-only, hash-chained audit log. There is no update or delete path in the code."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    actor_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(200), index=True)
    patient_ref: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class ExceptionItem(Base):
    """Anything the platform could not handle safely, waiting for a human."""

    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BillingCase(Base):
    """One billing work item moving through the 8-step controlled workflow."""

    __tablename__ = "billing_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    queue: Mapped[str] = mapped_column(String(80), index=True)
    claim_id: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    problem_type: Mapped[str | None] = mapped_column(String(40), nullable=True)

    rule_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    classification_reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    flags: Mapped[list] = mapped_column(JSON, default=list)

    meditab_patient_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    retrieved_records: Mapped[list] = mapped_column(JSON, default=list)
    unavailable_requirements: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)

    draft_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_evidence: Mapped[list] = mapped_column(JSON, default=list)
    draft_warnings: Mapped[list] = mapped_column(JSON, default=list)
    draft_version: Mapped[int] = mapped_column(Integer, default=0)
    draft_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    draft_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    draft_prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    draft_reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    version_id: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version_id}


class CaseEvent(Base):
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    ts: Mapped[str] = mapped_column(String(40))
    step: Mapped[int] = mapped_column(Integer)
    from_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_state: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class ActionRecord(Base):
    """Idempotency ledger: an action with a given key can only ever happen once."""

    __tablename__ = "action_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(60))
    ts: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------------------------
# Added for the feature pack (WBS #10, #14, #18, N3, N9, N10). New tables only, so an existing
# poc.db keeps working: SQLAlchemy creates these on start-up without touching older tables.


class LLMCall(Base):
    """One row per model call through the AI gateway (WBS N3/N10)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40), index=True)
    task: Mapped[str] = mapped_column(String(60), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # ok | error | blocked | reused
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ControlFlag(Base):
    """Small key/value store for admin switches (e.g. the AI kill switch)."""

    __tablename__ = "control_flags"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[str] = mapped_column(String(40))


class SummaryCache(Base):
    """Re-use a pre-visit summary when nothing in the chart has changed (WBS N9)."""

    __tablename__ = "summary_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String(60), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSON)
    tokens: Mapped[int] = mapped_column(Integer, default=0)


class DocAuditRun(Base):
    """One documentation-audit run for one patient (AI-23, WBS #10)."""

    __tablename__ = "doc_audit_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String(60), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    ruleset_version: Mapped[str] = mapped_column(String(60))
    checks_total: Mapped[int] = mapped_column(Integer)
    checks_passed: Mapped[int] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class DocAuditFinding(Base):
    __tablename__ = "doc_audit_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    patient_id: Mapped[str] = mapped_column(String(60), index=True)
    rule_id: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(120))  # encounter/procedure id, or "patient"
    severity: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(10))  # rule | ai
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | confirmed | dismissed
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class BaselineMeasure(Base):
    """Handling-time baseline from the pre-agent time study (D1 Months 1-2)."""

    __tablename__ = "baseline_measures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    minutes_per_case: Mapped[float] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    synthetic: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[str] = mapped_column(String(40))


class AcceptanceRun(Base):
    """Result of one automated acceptance pre-check (WBS #18)."""

    __tablename__ = "acceptance_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(80))
    testset_version: Mapped[str] = mapped_column(String(60))
    hard_gates_passed: Mapped[bool] = mapped_column()
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list] = mapped_column(JSON, default=list)
