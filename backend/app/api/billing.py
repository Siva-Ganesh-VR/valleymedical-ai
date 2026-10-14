from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.billing_agent import BillingAgent, proposed_category, step_progress
from app.api.deps import get_container, get_session, require
from app.container import Container
from app.models import BillingCase
from app.security import Actor, Permission
from app.services.billing_rules import Category

router = APIRouter(prefix="/api/billing", tags=["billing"])


class ClassificationReview(BaseModel):
    decision: Literal["confirm", "change"]
    category: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    handling_seconds: int | None = Field(default=None, ge=0, le=86400)


class DraftReview(BaseModel):
    decision: Literal["approve", "reject"]
    edited_text: str | None = Field(default=None, max_length=20000)
    note: str | None = Field(default=None, max_length=2000)
    handling_seconds: int | None = Field(default=None, ge=0, le=86400)
    edit_level: Literal["none", "minor", "major"] | None = None


class TrackingUpdate(BaseModel):
    status: Literal["submitted_by_staff", "resolved"]
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    handling_seconds: int | None = Field(default=None, ge=0, le=86400)


def _summary(case: BillingCase, agent: BillingAgent) -> dict:
    item = agent.work_item(case)
    return {
        "id": case.id, "claim_id": case.claim_id, "queue": case.queue, "state": case.state,
        "problem_type": case.problem_type, "category": case.confirmed_category or proposed_category(case),
        "category_confirmed": case.confirmed_category is not None, "flags": case.flags, "owner": case.owner,
        "payer": item.payer, "date_of_service": str(item.date_of_service), "billed_amount": item.billed_amount,
        "denial_code": item.denial.carc_code if item.denial else None, "updated_at": case.updated_at,
    }


def _detail(case: BillingCase, agent: BillingAgent) -> dict:
    item = agent.work_item(case)
    events = agent.events(case.id)
    return _summary(case, agent) | {
        "claim": item.model_dump(mode="json"),
        "steps": step_progress(case, events),
        "classification": {
            "rule_category": case.rule_category, "model_category": case.model_category,
            "model_confidence": case.model_confidence, "model_rationale": case.model_rationale,
            "recommended_action": case.recommended_action, "proposed_category": proposed_category(case),
            "confirmed_category": case.confirmed_category, "reviewed_by": case.classification_reviewed_by,
        },
        "meditab_patient_id": case.meditab_patient_id,
        "retrieved_records": case.retrieved_records,
        "gaps": case.gaps,
        "draft": None if case.draft_text is None else {
            "type": case.draft_type, "text": case.draft_text, "evidence": case.draft_evidence,
            "warnings": case.draft_warnings, "version": case.draft_version, "source": case.draft_source,
            "model": case.draft_model, "prompt_version": case.draft_prompt_version,
            "reviewed_by": case.draft_reviewed_by, "review_note": case.review_note,
        },
        "external_status": case.external_status, "external_reference": case.external_reference,
        "escalation_reason": case.escalation_reason,
        "events": [{"ts": e.ts, "step": e.step, "from_state": e.from_state, "to_state": e.to_state,
                    "actor": e.actor, "summary": e.summary} for e in events],
        "categories": [c.value for c in Category],
    }


@router.get("/queues")
def queues(actor: Actor = Depends(require(Permission.BILLING_READ)), container: Container = Depends(get_container)):
    return container.billing.list_queues()


@router.post("/queues/{queue}/sync")
def sync_queue(queue: str, actor: Actor = Depends(require(Permission.BILLING_WORK)),
               container: Container = Depends(get_container), session: Session = Depends(get_session)):
    result = container.billing_agent(session).sync_queue(queue, actor)
    session.commit()
    return result


@router.get("/cases")
def list_cases(queue: str | None = None, actor: Actor = Depends(require(Permission.BILLING_READ)),
               container: Container = Depends(get_container), session: Session = Depends(get_session)):
    agent = container.billing_agent(session)
    return [_summary(c, agent) for c in agent.list_cases(queue)]


@router.get("/cases/{case_id}")
def get_case(case_id: str, actor: Actor = Depends(require(Permission.BILLING_READ)),
             container: Container = Depends(get_container), session: Session = Depends(get_session)):
    agent = container.billing_agent(session)
    return _detail(agent.get_case(case_id), agent)


@router.post("/cases/{case_id}/advance")
def advance(case_id: str, actor: Actor = Depends(require(Permission.BILLING_WORK)),
            container: Container = Depends(get_container), session: Session = Depends(get_session)):
    agent = container.billing_agent(session)
    case = agent.advance(case_id)
    session.commit()
    return _detail(case, agent)


@router.post("/cases/{case_id}/classification-review")
def review_classification(case_id: str, body: ClassificationReview,
                          actor: Actor = Depends(require(Permission.BILLING_CLASSIFY_REVIEW)),
                          container: Container = Depends(get_container), session: Session = Depends(get_session)):
    agent = container.billing_agent(session)
    case = agent.review_classification(case_id, actor, decision=body.decision, category=body.category, note=body.note,
                                       handling_seconds=body.handling_seconds)
    session.commit()
    return _detail(case, agent)


@router.post("/cases/{case_id}/draft-review")
def review_draft(case_id: str, body: DraftReview, actor: Actor = Depends(require(Permission.BILLING_APPROVE)),
                 container: Container = Depends(get_container), session: Session = Depends(get_session)):
    agent = container.billing_agent(session)
    case = agent.review_draft(case_id, actor, decision=body.decision, edited_text=body.edited_text, note=body.note,
                              handling_seconds=body.handling_seconds, edit_level=body.edit_level)
    session.commit()
    return _detail(case, agent)


@router.post("/cases/{case_id}/tracking")
def tracking(case_id: str, body: TrackingUpdate, actor: Actor = Depends(require(Permission.BILLING_WORK)),
             container: Container = Depends(get_container), session: Session = Depends(get_session)):
    agent = container.billing_agent(session)
    case = agent.update_tracking(case_id, actor, status=body.status, reference=body.reference, note=body.note,
                                 handling_seconds=body.handling_seconds)
    session.commit()
    return _detail(case, agent)
