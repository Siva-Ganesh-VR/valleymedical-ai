"""Demo workload: moves synthetic cases through the REAL billing agent into a realistic mix of
statuses, so the Billing work page looks like a queue in progress.

Every action goes through the same agent methods, state checks and audit log as a person would use.
The actors are named "demo-seed.*" and Billing insights excludes their decisions from accuracy and
usability figures, so seeded decisions can never be mistaken for evidence.

Cases used in the live demo script (CLM-9001, 9003, 9004, 9005, 9006, 9008, ...) are left at
classification review on purpose.
"""
from __future__ import annotations

from app.agents.billing_agent import BillingAgent, CaseState
from app.security import Actor, Role

DEMO_PREFIX = "demo-seed"
DEMO_BILLER = Actor(f"{DEMO_PREFIX}.biller", Role.BILLER)
DEMO_APPROVER = Actor(f"{DEMO_PREFIX}.approver", Role.BILLING_APPROVER)

# claim -> target status
PLAN: dict[str, str] = {
    "CLM-9002": "AWAITING_DRAFT_APPROVAL",
    "CLM-9009": "AWAITING_DRAFT_APPROVAL",
    "CLM-9011": "AWAITING_DRAFT_APPROVAL",
    "CLM-9012": "AWAITING_DRAFT_APPROVAL",
    "CLM-9014": "AWAITING_DRAFT_APPROVAL",
    "CLM-9021": "DRAFT_REJECTED",
    "CLM-9010": "ROUTED",
    "CLM-9027": "ROUTED",
    "CLM-9018": "SUBMITTED_BY_STAFF",
    "CLM-9022": "SUBMITTED_BY_STAFF",
    "CLM-9029": "COMPLETED",
    "CLM-9015": "COMPLETED",
    "CLM-9017": "COMPLETED",
    "CLM-9016": "ESCALATED",
    "CLM-9028": "ESCALATED",
}
REJECT_NOTE = "Demo: add the diagnosis documented on the problem list before sending to coding."
RESOLVE_NOTES = {
    "CLM-9015": "Demo: front office confirmed coverage ended; patient billed directly.",
    "CLM-9017": "Demo: original claim CLM-9024 was already paid; duplicate closed.",
    "CLM-9029": "Demo: payer processed the claim after the status inquiry.",
}


def load_demo_workload(agent: BillingAgent, queue: str, actor: Actor) -> dict:
    """Idempotent: only moves cases that are still waiting for classification review.
    The queue is read as the requesting user; the decisions are made by the demo actors."""
    agent.sync_queue(queue, actor)
    cases = {c.claim_id: c for c in agent.list_cases(queue)}
    moved, skipped, problems = [], [], []
    for claim, target in PLAN.items():
        case = cases.get(claim)
        if case is None or case.state != CaseState.AWAITING_CLASSIFICATION_REVIEW.value:
            skipped.append(claim)
            continue
        agent.review_classification(case.id, DEMO_BILLER, decision="confirm", category=None, note="Demo workload")
        if target in ("DRAFT_REJECTED", "ROUTED", "SUBMITTED_BY_STAFF") or (target == "COMPLETED" and case.state == CaseState.AWAITING_DRAFT_APPROVAL.value):
            if case.state != CaseState.AWAITING_DRAFT_APPROVAL.value:
                problems.append(f"{claim}: expected a draft, got {case.state}")
                continue
            if target == "DRAFT_REJECTED":
                agent.review_draft(case.id, DEMO_APPROVER, decision="reject", edited_text=None, note=REJECT_NOTE)
            else:
                agent.review_draft(case.id, DEMO_APPROVER, decision="approve", edited_text=None, note="Demo workload")
                if target in ("SUBMITTED_BY_STAFF", "COMPLETED"):
                    agent.update_tracking(case.id, DEMO_BILLER, status="submitted_by_staff",
                                          reference=f"DEMO-PORTAL-{claim[-4:]}", note=None)
        if target == "COMPLETED":
            agent.update_tracking(case.id, DEMO_BILLER, status="resolved", reference=None, note=RESOLVE_NOTES.get(claim, "Demo"))
        if case.state != target:
            problems.append(f"{claim}: ended at {case.state}, expected {target}")
        moved.append(claim)
    return {"moved": moved, "skipped": skipped, "problems": problems}
