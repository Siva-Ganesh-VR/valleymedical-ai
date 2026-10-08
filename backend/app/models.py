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
