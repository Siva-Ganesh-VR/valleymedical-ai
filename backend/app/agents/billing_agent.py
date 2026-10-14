"""Core Proof 2: controlled billing agent (D1 steps 1-8).

The agent is a state machine. The model is called only inside specific steps (classify,
draft) and its output is checked by deterministic rules. Humans confirm the classification
(step 3) and approve every draft (step 6). The agent has NO capability to submit claims,
appeals or messages: after approval, the item is routed to a named owner who acts outside
the platform and records what they did (step 8).

States:
  IDENTIFIED -> AWAITING_CLASSIFICATION_REVIEW -> CLASSIFICATION_CONFIRMED -> RECORDS_RETRIEVED
  -> AWAITING_DRAFT_APPROVAL -> APPROVED -> ROUTED -> SUBMITTED_BY_STAFF -> COMPLETED
  DRAFT_REJECTED loops back to drafting. Any step can go to ESCALATED (exception queue).
  NO_ACTION: nothing wrong with the claim.
"""
from __future__ import annotations

import uuid
from datetime import date
from enum import Enum
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.adapters.billing.base import BillingQueueAdapter, ClaimWorkItem
from app.audit import AuditLogger
from app.config import Settings
from app.errors import InvalidStateError, NotFoundError, ValidationFailedError
from app.llm import prompts
from app.llm.client import LLMClient, LLMError, LLMResult
from app.models import ActionRecord, BillingCase, CaseEvent, utcnow_iso
from app.security import BILLING_AGENT, Actor
from app.services.billing_rules import (
    HARD_STOPS, ROUTING, Category, RequiredEvidence, case_idempotency_key, claim_facts,
    detect_injection, identify_problem, requirements_for, rule_category,
)
from app.services.clinical_record import ClinicalRecordService, RecordScope
from app.services.exceptions import ExceptionService
from app.services.grounding import check_draft
from app.services.patient_matching import PatientMatcher


class CaseState(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NO_ACTION = "NO_ACTION"
    AWAITING_CLASSIFICATION_REVIEW = "AWAITING_CLASSIFICATION_REVIEW"
    CLASSIFICATION_CONFIRMED = "CLASSIFICATION_CONFIRMED"
    RECORDS_RETRIEVED = "RECORDS_RETRIEVED"
    AWAITING_DRAFT_APPROVAL = "AWAITING_DRAFT_APPROVAL"
    DRAFT_REJECTED = "DRAFT_REJECTED"
    APPROVED = "APPROVED"
    ROUTED = "ROUTED"
    SUBMITTED_BY_STAFF = "SUBMITTED_BY_STAFF"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"


TERMINAL = {CaseState.NO_ACTION, CaseState.COMPLETED}
HUMAN_GATES = {CaseState.AWAITING_CLASSIFICATION_REVIEW, CaseState.AWAITING_DRAFT_APPROVAL}

STEPS = [
    (1, "Get work queue"),
    (2, "Identify problem"),
    (3, "Classify and review"),
    (4, "Retrieve records"),
    (5, "Find missing items"),
    (6, "Draft and approve"),
    (7, "Route to owner"),
    (8, "Track to completion"),
]

# Step a transition INTO this state is recorded against (what just happened).
EVENT_STEP = {
    CaseState.AWAITING_CLASSIFICATION_REVIEW: 3, CaseState.CLASSIFICATION_CONFIRMED: 3,
    CaseState.RECORDS_RETRIEVED: 4, CaseState.AWAITING_DRAFT_APPROVAL: 6, CaseState.DRAFT_REJECTED: 6,
    CaseState.APPROVED: 6, CaseState.ROUTED: 7, CaseState.SUBMITTED_BY_STAFF: 8, CaseState.COMPLETED: 8,
}

# Step a case in this state is currently on (what happens next).
STATE_STEP = {
    CaseState.IDENTIFIED: 3, CaseState.NO_ACTION: 2, CaseState.AWAITING_CLASSIFICATION_REVIEW: 3,
    CaseState.CLASSIFICATION_CONFIRMED: 4, CaseState.RECORDS_RETRIEVED: 5,
    CaseState.AWAITING_DRAFT_APPROVAL: 6, CaseState.DRAFT_REJECTED: 6, CaseState.APPROVED: 7,
    CaseState.ROUTED: 8, CaseState.SUBMITTED_BY_STAFF: 8, CaseState.COMPLETED: 8, CaseState.ESCALATED: 0,
}


class BillingAgent:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        billing: BillingQueueAdapter,
        records: ClinicalRecordService,
        matcher: PatientMatcher,
        llm: LLMClient,
        audit: AuditLogger,
        exceptions: ExceptionService,
        clock: Callable[[], date],
    ):
        self._s = session
        self._settings = settings
        self._billing = billing
        self._records = records
        self._matcher = matcher
        self._llm = llm
        self._audit = audit
        self._exceptions = exceptions
        self._clock = clock

    # ------------------------------------------------------------------ steps 1 and 2
    def sync_queue(self, queue: str, actor: Actor, *, auto_classify: bool = True) -> dict:
        """Read the assigned queue and open one case per problem. Idempotent: re-running it
        never creates duplicate cases for the same claim and denial."""
        items = self._billing.list_work_items(queue)
        self._audit.record(actor=actor, action="billing.queue.read", entity_type="queue", entity_id=queue,
                           detail={"items": len(items)})
        created, existing, no_action = [], [], []
        for item in items:
            key = case_idempotency_key(item)
            case = self._s.scalars(select(BillingCase).where(BillingCase.idempotency_key == key)).first()
            if case:
                existing.append(case.id)
                continue
            problem = identify_problem(item, self._clock(), self._settings.unworked_after_days)
            now = utcnow_iso()
            case = BillingCase(
                id=str(uuid.uuid4()), idempotency_key=key, queue=queue, claim_id=item.claim_id,
                state=(CaseState.IDENTIFIED if problem else CaseState.NO_ACTION).value,
                problem_type=problem.value if problem else None, flags=[], retrieved_records=[],
                unavailable_requirements=[], gaps=[], draft_evidence=[], draft_warnings=[],
                created_at=now, updated_at=now,
            )
            self._s.add(case)
            self._s.flush()
            self._event(case, 1, None, "Read from work queue", actor, {"queue": queue})
            self._event(case, 2, None, f"Problem identified: {problem.value}" if problem else "No problem found; no action needed",
                        actor, {"problem_type": problem.value if problem else None})
            self._audit.record(actor=actor, action="billing.case.opened", entity_type="billing_case", entity_id=case.id,
                               detail={"claim_id": item.claim_id, "problem_type": case.problem_type})
            (created if problem else no_action).append(case.id)
        if auto_classify:
            for case_id in created:
                self.advance(case_id, BILLING_AGENT)
        return {"queue": queue, "created": len(created), "already_open": len(existing), "no_action": len(no_action)}

    # ------------------------------------------------------------------ automatic progression
    def advance(self, case_id: str, actor: Actor = BILLING_AGENT) -> BillingCase:
        """Run automatic steps until the case reaches a human gate, escalation or the end.
        Safe to call repeatedly: it does nothing in states that need a human."""
        case = self.get_case(case_id)
        item = self._work_item(case)
        for _ in range(6):  # hard cap prevents any workflow loop
            state = CaseState(case.state)
            if state == CaseState.IDENTIFIED:
                self._classify(case, item)
            elif state == CaseState.CLASSIFICATION_CONFIRMED:
                self._retrieve_records(case, item)
            elif state == CaseState.RECORDS_RETRIEVED:
                self._identify_gaps(case, item)
                self._draft_or_stop(case, item)
            elif state == CaseState.DRAFT_REJECTED:
                self._draft(case, item)
            else:
                break
        return case

    # ------------------------------------------------------------------ step 3
    def _classify(self, case: BillingCase, item: ClaimWorkItem) -> None:
        flags: list[str] = []
        untrusted_text = " ".join(filter(None, [item.denial.description if item.denial else None,
                                                item.denial.payer_remark if item.denial else None]))
        if detect_injection(untrusted_text):
            flags.append("suspicious_content")
            self._exceptions.raise_(
                actor=BILLING_AGENT, kind="suspicious_content", severity="high", entity_type="billing_case",
                entity_id=case.id, dedupe_key=f"suspicious:{case.id}",
                summary=f"Payer text on {item.claim_id} contains instruction-like content. It was treated as data only.",
            )
        rule_cat = rule_category(item)
        claim = claim_facts(item) | {"payer_remark": item.denial.payer_remark if item.denial else None,
                                     "status": item.status, "last_worked_on": str(item.last_worked_on)}
        try:
            result = self._llm.structured(
                task="billing_classify", system=prompts.CLASSIFY_SYSTEM,
                user=prompts.classify_user(claim, case.problem_type), tool_name=prompts.CLASSIFY_TOOL,
                tool_description="Return the classification for this billing work item.",
                schema=prompts.CLASSIFY_SCHEMA, prompt_version=prompts.CLASSIFY_PROMPT_VERSION,
                context={"carc_code": item.denial.carc_code if item.denial else None, "problem_type": case.problem_type},
            )
        except LLMError as exc:
            self._escalate(case, f"Classification failed: {exc}", kind="llm_failure", severity="medium", step=3)
            return
        self._log_llm(case, "classify", result)

        try:
            model_cat = Category(str(result.data.get("category")))
            confidence = max(0.0, min(1.0, float(result.data.get("confidence", 0))))
        except (ValueError, TypeError):
            model_cat, confidence = Category.OTHER, 0.0
            flags.append("invalid_model_output")
        if rule_cat and rule_cat != model_cat:
            flags.append("rule_overrides_model")
        if confidence < self._settings.classification_confidence_threshold:
            flags.append("low_confidence")

        case.rule_category = rule_cat.value if rule_cat else None
        case.model_category = model_cat.value
        case.model_confidence = confidence
        case.model_rationale = str(result.data.get("rationale", ""))[:2000]
        case.recommended_action = str(result.data.get("recommended_next_action", ""))[:1000]
        case.flags = flags
        self._transition(case, {CaseState.IDENTIFIED}, CaseState.AWAITING_CLASSIFICATION_REVIEW, BILLING_AGENT,
                         f"Proposed category {proposed_category(case)}; waiting for human review",
                         {"proposed": proposed_category(case), "flags": flags})

    def review_classification(self, case_id: str, actor: Actor, *, decision: str, category: str | None, note: str | None,
                              handling_seconds: int | None = None) -> BillingCase:
        case = self.get_case(case_id)
        self._require(case, {CaseState.AWAITING_CLASSIFICATION_REVIEW})
        if decision == "confirm":
            final = proposed_category(case)
        elif decision == "change":
            try:
                final = Category(category or "").value
            except ValueError as exc:
                raise ValidationFailedError(f"Unknown category '{category}'") from exc
        else:
            raise ValidationFailedError("decision must be 'confirm' or 'change'")
        case.confirmed_category = final
        case.classification_reviewed_by = actor.username
        self._transition(case, {CaseState.AWAITING_CLASSIFICATION_REVIEW}, CaseState.CLASSIFICATION_CONFIRMED, actor,
                         f"Classification {'confirmed' if decision == 'confirm' else 'changed'}: {final}",
                         {"decision": decision, "category": final, "note": note,
                          "handling_seconds": _seconds(handling_seconds), "human": True})
        return self.advance(case.id, BILLING_AGENT)

    # ------------------------------------------------------------------ step 4
    def _retrieve_records(self, case: BillingCase, item: ClaimWorkItem) -> None:
        match = self._matcher.match(mrn=item.patient_mrn, last_name=item.patient_last_name,
                                    first_name=item.patient_first_name, dob=item.patient_dob)
        if not match.matched or match.patient is None:
            self._exceptions.raise_(
                actor=BILLING_AGENT, kind="billing_patient_match", severity="critical", entity_type="billing_case",
                entity_id=case.id, dedupe_key=f"patient_match:{case.id}",
                summary=f"Claim {item.claim_id}: patient could not be matched safely ({match.status.value}). No records were retrieved.",
                detail={"reasons": match.reasons, "candidates": len(match.candidate_ids)},
            )
            self._escalate(case, "Patient on the claim could not be matched safely to Meditab. " + "; ".join(match.reasons),
                           kind=None, severity="critical", step=4)
            return
        patient_id = match.patient.patient_id
        case.meditab_patient_id = patient_id
        category = Category(case.confirmed_category)
        retrieved, unavailable = [], []
        requirements = requirements_for(category, item)
        for req in requirements:
            if req.scope == "claim":
                continue
            record = self._records.get_record(
                patient_id, actor=BILLING_AGENT, purpose=f"billing_case:{case.id}:{req.key}",
                sections=[req.section], scope=self._scope_for(req, item),
            )
            if req.section in record.unavailable_sections():
                unavailable.append(req.key)
            for it in record.items.get(req.section, []):
                if req.exclude_billed_procedure and it.data.get("cpt") in item.cpt_codes:
                    continue
                retrieved.append({"requirement": req.key, "item_id": it.item_id, "section": it.section,
                                  "display": it.display, "source": it.source.model_dump(mode="json")})
        case.retrieved_records = retrieved
        case.unavailable_requirements = unavailable
        self._transition(case, {CaseState.CLASSIFICATION_CONFIRMED}, CaseState.RECORDS_RETRIEVED, BILLING_AGENT,
                         f"Retrieved {len(retrieved)} supporting record(s) from Meditab (minimum necessary)",
                         {"records": len(retrieved), "requirements": [r.key for r in requirements],
                          "unavailable": unavailable})

    @staticmethod
    def _scope_for(req: RequiredEvidence, item: ClaimWorkItem) -> RecordScope:
        doc_types = set(req.doc_types) if req.doc_types else None
        if req.scope == "dos":
            return RecordScope(encounter_ids={item.encounter_id} if item.encounter_id else None,
                               dates={item.date_of_service}, doc_types=doc_types)
        return RecordScope(on_or_before=item.date_of_service, doc_types=doc_types)

    # ------------------------------------------------------------------ step 5
    def _identify_gaps(self, case: BillingCase, item: ClaimWorkItem) -> None:
        category = Category(case.confirmed_category)
        found = {r["requirement"] for r in case.retrieved_records}
        gaps = []
        for req in requirements_for(category, item):
            if req.scope == "claim":
                if req.key == "auth_record" and not item.authorization_number:
                    gaps.append({"key": req.key, "label": req.label, "reason": "Not present on the claim"})
            elif req.key in case.unavailable_requirements:
                gaps.append({"key": req.key, "label": req.label, "reason": "Meditab was unavailable; could not check"})
            elif req.key not in found:
                gaps.append({"key": req.key, "label": req.label, "reason": "Not found in Meditab for this patient"})
        case.gaps = gaps
        self._event(case, 5, case.state, f"{len(gaps)} missing item(s) found" if gaps else "No missing items found",
                    BILLING_AGENT, {"gaps": [g["key"] for g in gaps]})

    # ------------------------------------------------------------------ step 6
    def _draft_or_stop(self, case: BillingCase, item: ClaimWorkItem) -> None:
        category = Category(case.confirmed_category)
        if category in HARD_STOPS:
            case.owner = ROUTING[category]
            self._escalate(case, HARD_STOPS[category], kind="hard_stop_rule", severity="medium", step=6)
            return
        if any(g["reason"].startswith("Meditab was unavailable") for g in case.gaps):
            case.owner = ROUTING[category]
            self._escalate(case, "Required records could not be checked because Meditab was unavailable. Retry later.",
                           kind="source_unavailable", severity="medium", step=5)
            return
        self._draft(case, item)

    def _draft(self, case: BillingCase, item: ClaimWorkItem) -> None:
        if case.draft_version >= self._settings.max_draft_attempts:
            self._escalate(case, f"Draft attempts reached the limit ({self._settings.max_draft_attempts}).",
                           kind="draft_limit", severity="medium", step=6)
            return
        category = Category(case.confirmed_category)
        if category == Category.NO_PAYER_RESPONSE:
            draft_type = "payer_follow_up"
        elif category == Category.CODING_ERROR:
            draft_type = "coding_review"
        elif case.gaps:
            draft_type = "provider_query"
        else:
            draft_type = "appeal_letter"

        evidence = [{"id": f"E{i}", "item_id": r["item_id"], "text": r["display"]}
                    for i, r in enumerate(case.retrieved_records, start=1)]
        evidence_text = {e["id"]: e["text"] for e in evidence}
        claim = claim_facts(item)
        try:
            result = self._llm.structured(
                task="billing_draft", system=prompts.DRAFT_SYSTEM,
                user=prompts.draft_user(draft_type, claim, evidence, case.gaps, case.review_note),
                tool_name=prompts.DRAFT_TOOL, tool_description="Return the draft text and the evidence ids it relies on.",
                schema=prompts.DRAFT_SCHEMA, prompt_version=prompts.DRAFT_PROMPT_VERSION,
                context={"draft_type": draft_type, "claim": claim, "evidence": evidence, "gaps": case.gaps},
            )
        except LLMError as exc:
            self._escalate(case, f"Drafting failed: {exc}", kind="llm_failure", severity="medium", step=6)
            return
        self._log_llm(case, "draft", result)

        text = str(result.data.get("letter_text", ""))
        cited = [str(i) for i in result.data.get("evidence_ids", [])]
        errors, warnings = check_draft(text, cited, evidence_text, " ".join(str(v) for v in claim.values()))
        if errors:
            self._escalate(case, "Draft failed safety checks: " + "; ".join(errors), kind="draft_validation_failed",
                           severity="high", step=6)
            return

        version = case.draft_version + 1
        if not self._once(f"{case.id}:draft:v{version}", case.id, "draft", {"draft_type": draft_type}):
            raise InvalidStateError("This draft version was already created. Reload the case.")
        case.draft_type = draft_type
        case.draft_text = text
        case.draft_evidence = [e for e in evidence if e["id"] in set(cited)]
        case.draft_warnings = warnings
        case.draft_version = version
        case.draft_source = "model"
        case.draft_model = result.model
        case.draft_prompt_version = result.prompt_version
        self._transition(case, {CaseState.RECORDS_RETRIEVED, CaseState.DRAFT_REJECTED}, CaseState.AWAITING_DRAFT_APPROVAL,
                         BILLING_AGENT, f"Drafted {draft_type.replace('_', ' ')} (version {version}); waiting for approval",
                         {"draft_type": draft_type, "version": version, "warnings": len(warnings)})

    def review_draft(self, case_id: str, actor: Actor, *, decision: str, edited_text: str | None, note: str | None,
                     handling_seconds: int | None = None, edit_level: str | None = None) -> BillingCase:
        case = self.get_case(case_id)
        self._require(case, {CaseState.AWAITING_DRAFT_APPROVAL})
        if decision == "reject":
            if not note:
                raise ValidationFailedError("A note is required when rejecting a draft")
            case.review_note = note
            case.draft_reviewed_by = actor.username
            self._transition(case, {CaseState.AWAITING_DRAFT_APPROVAL}, CaseState.DRAFT_REJECTED, actor,
                             "Draft rejected", {"note": note, "version": case.draft_version, "edit_level": "rejected",
                                                "handling_seconds": _seconds(handling_seconds), "human": True})
            return case
        if decision != "approve":
            raise ValidationFailedError("decision must be 'approve' or 'reject'")
        if edited_text is not None and edited_text.strip() and edited_text != case.draft_text:
            case.draft_text = edited_text
            case.draft_source = "human_edited"
        case.draft_reviewed_by = actor.username
        case.review_note = note
        self._transition(case, {CaseState.AWAITING_DRAFT_APPROVAL}, CaseState.APPROVED, actor,
                         f"Draft approved by {actor.username}" + (" (edited)" if case.draft_source == "human_edited" else ""),
                         {"version": case.draft_version, "edited": case.draft_source == "human_edited",
                          "edit_level": _edit_level(edit_level, case.draft_source == "human_edited"),
                          "handling_seconds": _seconds(handling_seconds), "human": True})
        self._route(case)
        return case

    # ------------------------------------------------------------------ step 7
    def _route(self, case: BillingCase) -> None:
        owner = ROUTING[Category(case.confirmed_category)]
        if not self._once(f"{case.id}:route", case.id, "route", {"owner": owner}):
            return
        case.owner = owner
        self._transition(case, {CaseState.APPROVED}, CaseState.ROUTED, BILLING_AGENT,
                         f"Routed to {owner}. Nothing was sent externally.",
                         {"owner": owner, "channel": "platform_task", "external_submission": False})

    # ------------------------------------------------------------------ step 8
    def update_tracking(self, case_id: str, actor: Actor, *, status: str, reference: str | None, note: str | None,
                        handling_seconds: int | None = None) -> BillingCase:
        case = self.get_case(case_id)
        if status == "submitted_by_staff":
            if not reference:
                raise ValidationFailedError("Give a reference for what staff submitted (for example a portal confirmation number)")
            case.external_status, case.external_reference = status, reference
            self._transition(case, {CaseState.ROUTED}, CaseState.SUBMITTED_BY_STAFF, actor,
                             f"Staff recorded submission outside the platform (ref {reference})",
                             {"reference": reference, "handling_seconds": _seconds(handling_seconds), "human": True})
        elif status == "resolved":
            if case.state == CaseState.ESCALATED.value and not (note and note.strip()):
                raise ValidationFailedError("Say how the escalated case was resolved")
            case.external_status = status
            self._transition(case, {CaseState.SUBMITTED_BY_STAFF, CaseState.ROUTED, CaseState.ESCALATED},
                             CaseState.COMPLETED, actor, "Case resolved" + (f": {note}" if note else ""),
                             {"note": note, "handling_seconds": _seconds(handling_seconds), "human": True})
            closed = self._exceptions.resolve_for("billing_case", case.id, actor,
                                                  f"Closed with case {case.claim_id}" + (f": {note}" if note else ""))
            if closed:
                self._event(case, 8, case.state, f"{closed} open exception(s) closed with the case", actor, {"closed": closed})
        else:
            raise ValidationFailedError("status must be 'submitted_by_staff' or 'resolved'")
        return case

    # ------------------------------------------------------------------ helpers
    def get_case(self, case_id: str) -> BillingCase:
        case = self._s.get(BillingCase, case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        return case

    def list_cases(self, queue: str | None = None) -> list[BillingCase]:
        stmt = select(BillingCase).order_by(BillingCase.claim_id)
        if queue:
            stmt = stmt.where(BillingCase.queue == queue)
        return list(self._s.scalars(stmt))

    def events(self, case_id: str) -> list[CaseEvent]:
        return list(self._s.scalars(select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)))

    def work_item(self, case: BillingCase) -> ClaimWorkItem:
        return self._work_item(case)

    def _work_item(self, case: BillingCase) -> ClaimWorkItem:
        item = self._billing.get_work_item(case.claim_id)
        if item is None:
            raise NotFoundError(f"Claim {case.claim_id} is no longer in the billing system")
        return item

    @staticmethod
    def _require(case: BillingCase, allowed: set[CaseState]) -> None:
        if CaseState(case.state) not in allowed:
            raise InvalidStateError(
                f"Case is {case.state}; this action needs {', '.join(sorted(s.value for s in allowed))}")

    def _transition(self, case: BillingCase, allowed: set[CaseState], to: CaseState, actor: Actor,
                    summary: str, detail: dict | None = None, *, step: int | None = None) -> None:
        self._require(case, allowed)
        previous = case.state
        case.state = to.value
        case.updated_at = utcnow_iso()
        try:
            self._s.flush()  # optimistic version check: concurrent edits fail instead of overwriting
        except StaleDataError as exc:
            self._s.rollback()
            raise InvalidStateError("This case was changed by someone else. Reload and try again.") from exc
        self._event(case, step or EVENT_STEP.get(to) or STATE_STEP.get(CaseState(previous), 0), previous, summary, actor, detail)
        self._audit.record(actor=actor, action=f"billing.case.{to.value.lower()}", entity_type="billing_case",
                           entity_id=case.id, patient_ref=case.meditab_patient_id,
                           detail={"from": previous, "to": to.value, "claim_id": case.claim_id})

    def _event(self, case: BillingCase, step: int, from_state: str | None, summary: str, actor: Actor, detail: dict | None) -> None:
        self._s.add(CaseEvent(case_id=case.id, ts=utcnow_iso(), step=step, from_state=from_state, to_state=case.state,
                              actor=actor.username, summary=summary, detail=detail or {}))
        self._s.flush()

    def _escalate(self, case: BillingCase, reason: str, *, kind: str | None, severity: str, step: int) -> None:
        """Stop the case and hand it to a person. `step` is the workflow step where it stopped."""
        case.escalation_reason = reason
        if kind:
            self._exceptions.raise_(actor=BILLING_AGENT, kind=kind, severity=severity, entity_type="billing_case",
                                    entity_id=case.id, dedupe_key=f"{kind}:{case.id}",
                                    summary=f"Claim {case.claim_id}: {reason}", patient_ref=case.meditab_patient_id)
        movable = set(CaseState) - TERMINAL - {CaseState.ESCALATED}
        self._transition(case, movable, CaseState.ESCALATED, BILLING_AGENT, f"Escalated to a person: {reason}",
                         {"kind": kind, "severity": severity, "stopped_at_step": step}, step=step)

    def _once(self, key: str, case_id: str, action: str, result: dict) -> bool:
        """Record an action in the idempotency ledger. Returns False if it already happened.
        The unique constraint on ActionRecord.key is the final guard against races."""
        if self._s.scalars(select(ActionRecord).where(ActionRecord.key == key)).first():
            return False
        self._s.add(ActionRecord(key=key, case_id=case_id, action=action, ts=utcnow_iso(), result=result))
        try:
            self._s.flush()
        except IntegrityError as exc:
            self._s.rollback()
            raise InvalidStateError("This action was already performed by another request. Reload the case.") from exc
        return True

    def _log_llm(self, case: BillingCase, step: str, result: LLMResult) -> None:
        self._audit.record(actor=BILLING_AGENT, action=f"llm.billing_{step}", entity_type="billing_case", entity_id=case.id,
                           patient_ref=case.meditab_patient_id, model=result.model, prompt_version=result.prompt_version,
                           detail={"attempts": result.attempts, "input_tokens": result.input_tokens,
                                   "output_tokens": result.output_tokens})


MAX_HANDLING_SECONDS = 4 * 3600  # ignore implausible timer values (tab left open overnight)


def _seconds(value: int | None) -> int | None:
    """Time a person actively spent on this decision, measured by the UI."""
    if value is None:
        return None
    return max(0, min(int(value), MAX_HANDLING_SECONDS))


def _edit_level(value: str | None, edited: bool) -> str | None:
    """Reviewer's rating for the D1 'usable with minor or no revision' criterion."""
    if value in ("none", "minor", "major"):
        return value
    return None if edited else "none"


def proposed_category(case: BillingCase) -> str | None:
    """Hard rules win over the model."""
    return case.rule_category or case.model_category


def step_progress(case: BillingCase, events: list[CaseEvent]) -> list[dict]:
    """Status of each of the 8 steps, derived from what actually happened (the event log).

    A step is "done" only if work was recorded against it. When a case was escalated, the step
    where it stopped is "blocked" and later steps are "not_reached", even after a person closes it.
    """
    state = CaseState(case.state)
    escalations = [e for e in events if e.to_state == CaseState.ESCALATED.value]
    stopped_at = escalations[-1].step if escalations else None
    done_steps = {e.step for e in events if e.to_state != CaseState.ESCALATED.value}
    if stopped_at is not None:
        # Work recorded against the stopping step before the escalation doesn't make it "done".
        done_steps.discard(stopped_at)
    current = STATE_STEP[state]
    out = []
    for n, label in STEPS:
        if state == CaseState.NO_ACTION:
            status = "done" if n <= 2 else "skipped"
        elif n == stopped_at:
            status = "blocked"
        elif stopped_at is not None and n not in done_steps:
            status = "not_reached"
        elif state == CaseState.COMPLETED:
            status = "done" if n in done_steps else "not_reached"
        elif n in done_steps and n != current:
            status = "done"
        elif n == current:
            status = "waiting_human" if state in HUMAN_GATES or state in {CaseState.ROUTED, CaseState.SUBMITTED_BY_STAFF} else "current"
        elif n < current:
            status = "done"
        else:
            status = "pending"
        out.append({"step": n, "label": label, "status": status})
    return out
