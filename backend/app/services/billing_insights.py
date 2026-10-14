"""AI-18 billing measurement, slim (WBS #14, N6).

Every number here is derived from what actually happened in the workflow (case events, human
decisions, reviewer ratings) and is shown with its sample size. Handling-time reduction needs a
baseline from the pre-agent time study (D1 Months 1-2); until one is entered, it says so.

"Worked to completion" is NOT money recovered: payer outcomes are not visible to the POC.
"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.billing.base import BillingQueueAdapter
from app.agents.billing_agent import CaseState, proposed_category
from app.audit import AuditLogger
from app.errors import ValidationFailedError
from app.models import BaselineMeasure, BillingCase, CaseEvent, ExceptionItem, utcnow_iso
from app.security import Actor
from app.services.billing_rules import Category

THRESHOLDS = {"classification": 0.90, "supporting_records": 0.95, "draft_usable": 0.90, "handling_reduction": 0.30}
OPEN_STATES = {s.value for s in CaseState} - {CaseState.COMPLETED.value, CaseState.NO_ACTION.value}
# Example time-study figures for demos only. They are clearly marked synthetic in the UI.
DEMO_BASELINE_MINUTES = {
    "MEDICAL_NECESSITY": 38.0, "MISSING_DOCUMENTATION": 22.0, "CODING_ERROR": 18.0,
    "NO_PAYER_RESPONSE": 12.0, "MISSING_PRIOR_AUTH": 30.0, "TIMELY_FILING": 15.0,
}


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


class BillingInsightsService:
    def __init__(self, session: Session, billing: BillingQueueAdapter, audit: AuditLogger):
        self._s = session
        self._billing = billing
        self._audit = audit

    # ------------------------------------------------------------------ baselines
    def baselines(self) -> list[dict]:
        rows = self._s.scalars(select(BaselineMeasure).order_by(BaselineMeasure.id.desc()))
        latest: dict[str, BaselineMeasure] = {}
        for r in rows:
            latest.setdefault(r.category, r)
        return [{"category": r.category, "minutes_per_case": r.minutes_per_case, "sample_size": r.sample_size,
                 "source": r.source, "synthetic": r.synthetic, "created_by": r.created_by, "created_at": r.created_at}
                for r in sorted(latest.values(), key=lambda r: r.category)]

    def add_baseline(self, actor: Actor, *, category: str, minutes_per_case: float, sample_size: int, source: str,
                     synthetic: bool = False) -> dict:
        try:
            Category(category)
        except ValueError as exc:
            raise ValidationFailedError(f"Unknown category '{category}'") from exc
        if not 0 < minutes_per_case <= 600:
            raise ValidationFailedError("Minutes per case must be between 0 and 600")
        if sample_size < 1:
            raise ValidationFailedError("Sample size must be at least 1")
        self._s.add(BaselineMeasure(category=category, minutes_per_case=minutes_per_case, sample_size=sample_size,
                                    source=source, synthetic=synthetic, created_by=actor.username, created_at=utcnow_iso()))
        self._s.flush()
        self._audit.record(actor=actor, action="billing.baseline.recorded", entity_type="baseline", entity_id=category,
                           detail={"minutes": minutes_per_case, "n": sample_size, "synthetic": synthetic})
        return {"category": category}

    def load_demo_baselines(self, actor: Actor) -> int:
        for cat, minutes in DEMO_BASELINE_MINUTES.items():
            self.add_baseline(actor, category=cat, minutes_per_case=minutes, sample_size=10,
                              source="SYNTHETIC demo figures, not a real time study", synthetic=True)
        return len(DEMO_BASELINE_MINUTES)

    # ------------------------------------------------------------------ metrics
    def _data(self):
        cases = list(self._s.scalars(select(BillingCase)))
        events = list(self._s.scalars(select(CaseEvent).order_by(CaseEvent.id)))
        by_case: dict[str, list[CaseEvent]] = defaultdict(list)
        for e in events:
            by_case[e.case_id].append(e)
        items = {}
        for c in cases:
            item = self._billing.get_work_item(c.claim_id)
            if item:
                items[c.id] = item
        return cases, by_case, items

    @staticmethod
    def _handling_seconds(events: list[CaseEvent]) -> int:
        return sum(int(e.detail.get("handling_seconds") or 0) for e in events if e.detail)

    def metrics(self) -> dict:
        cases, by_case, items = self._data()
        states = Counter(c.state for c in cases)
        worked = [c for c in cases if c.state != CaseState.NO_ACTION.value]

        # Classification: did the proposal (rules + model) match what the reviewer confirmed?
        reviewed = [c for c in cases if c.confirmed_category]
        agree = sum(1 for c in reviewed if proposed_category(c) == c.confirmed_category)
        model_agree = sum(1 for c in reviewed if c.model_category == c.confirmed_category)

        # Supporting records: of cases that reached retrieval, how many had nothing missing?
        retrieved = [c for c in cases if c.meditab_patient_id and any(e.step == 4 and e.to_state == CaseState.RECORDS_RETRIEVED.value
                                                                       for e in by_case[c.id])]
        complete = sum(1 for c in retrieved if not c.gaps)

        # Drafts: reviewer ratings at approval/rejection.
        ratings = Counter()
        for c in cases:
            for e in by_case[c.id]:
                if e.to_state in (CaseState.APPROVED.value, CaseState.DRAFT_REJECTED.value):
                    ratings[(e.detail or {}).get("edit_level") or "unrated"] += 1
        rated = sum(v for k, v in ratings.items() if k != "unrated")
        usable = ratings["none"] + ratings["minor"]

        # Handling time per category, from cases where a person finished their part.
        per_cat: dict[str, list[int]] = defaultdict(list)
        for c in cases:
            if c.state in (CaseState.ROUTED.value, CaseState.SUBMITTED_BY_STAFF.value, CaseState.COMPLETED.value):
                secs = self._handling_seconds(by_case[c.id])
                if secs > 0 and c.confirmed_category:
                    per_cat[c.confirmed_category].append(secs)
        baselines = {b["category"]: b for b in self.baselines()}
        handling = []
        weighted_base = weighted_now = 0.0
        for cat in sorted(set(per_cat) | set(baselines)):
            samples = per_cat.get(cat, [])
            avg_min = round(sum(samples) / len(samples) / 60, 2) if samples else None
            base = baselines.get(cat)
            reduction = round(1 - avg_min / base["minutes_per_case"], 3) if base and avg_min is not None else None
            if base and avg_min is not None:
                weighted_base += base["minutes_per_case"] * len(samples)
                weighted_now += avg_min * len(samples)
            handling.append({"category": cat, "cases": len(samples), "avg_minutes_with_agent": avg_min,
                             "baseline_minutes": base["minutes_per_case"] if base else None,
                             "baseline_sample": base["sample_size"] if base else None,
                             "baseline_synthetic": base["synthetic"] if base else None, "reduction": reduction})
        overall_reduction = round(1 - weighted_now / weighted_base, 3) if weighted_base else None

        # Money: what is at stake, not what was recovered.
        def amount(cs):
            return round(sum(items[c.id].billed_amount for c in cs if c.id in items), 2)
        open_cases = [c for c in worked if c.state in OPEN_STATES]
        appeals = [c for c in cases if c.state in (CaseState.ROUTED.value, CaseState.SUBMITTED_BY_STAFF.value)
                   and c.draft_type == "appeal_letter"]
        completed = [c for c in cases if c.state == CaseState.COMPLETED.value]

        escalations = Counter(e.kind for e in self._s.scalars(select(ExceptionItem).where(ExceptionItem.entity_type == "billing_case")))
        by_category = Counter((c.confirmed_category or proposed_category(c) or "UNCLASSIFIED") for c in worked)

        return {
            "generated_at": utcnow_iso(),
            "thresholds": THRESHOLDS,
            "volume": {"cases": len(cases), "worked": len(worked), "by_state": dict(states),
                       "waiting_for_person": sum(states[s] for s in ("AWAITING_CLASSIFICATION_REVIEW", "AWAITING_DRAFT_APPROVAL", "DRAFT_REJECTED")),
                       "escalated": states.get("ESCALATED", 0), "completed": states.get("COMPLETED", 0),
                       "by_category": dict(by_category)},
            "classification": {"reviewed": len(reviewed), "proposal_agreed": agree, "proposal_accuracy": _rate(agree, len(reviewed)),
                               "model_agreed": model_agree, "model_accuracy": _rate(model_agree, len(reviewed))},
            "supporting_records": {"cases": len(retrieved), "complete": complete, "rate": _rate(complete, len(retrieved))},
            "drafts": {"rated": rated, "usable": usable, "usable_rate": _rate(usable, rated), "ratings": dict(ratings)},
            "handling_time": {"by_category": handling, "overall_reduction": overall_reduction,
                              "baseline_captured": bool(baselines),
                              "baseline_synthetic": any(b["synthetic"] for b in baselines.values())},
            "money": {"at_risk_open": amount(open_cases), "open_cases": len(open_cases),
                      "appeals_with_owner": amount(appeals), "appeal_cases": len(appeals),
                      "worked_to_completion": amount(completed), "completed_cases": len(completed)},
            "escalations": dict(escalations),
        }

    def export_csv(self) -> str:
        cases, by_case, items = self._data()
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["claim_id", "payer", "date_of_service", "billed_amount", "state", "problem_type", "rule_category",
                    "model_category", "model_confidence", "confirmed_category", "proposal_correct", "gaps", "draft_type",
                    "draft_version", "edit_level", "owner", "handling_seconds", "flags", "updated_at"])
        for c in sorted(cases, key=lambda c: c.claim_id):
            item = items.get(c.id)
            rating = next(((e.detail or {}).get("edit_level") for e in reversed(by_case[c.id])
                           if e.to_state in (CaseState.APPROVED.value, CaseState.DRAFT_REJECTED.value)), "")
            w.writerow([c.claim_id, item.payer if item else "", item.date_of_service if item else "",
                        item.billed_amount if item else "", c.state, c.problem_type or "", c.rule_category or "",
                        c.model_category or "", c.model_confidence if c.model_confidence is not None else "",
                        c.confirmed_category or "",
                        "" if not c.confirmed_category else proposed_category(c) == c.confirmed_category,
                        ";".join(g["key"] for g in c.gaps), c.draft_type or "", c.draft_version, rating or "",
                        c.owner or "", self._handling_seconds(by_case[c.id]), ";".join(c.flags), c.updated_at])
        return out.getvalue()
