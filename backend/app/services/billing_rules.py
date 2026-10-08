"""Deterministic billing rules. These override the model.

ILLUSTRATIVE ONLY: the categories, CARC mappings, required evidence and routing below are
placeholders to demonstrate the mechanism. Valley Medical must supply and approve the real
business rules before any pilot (client dependency, D1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.adapters.billing.base import ClaimWorkItem


class Category(str, Enum):
    MEDICAL_NECESSITY = "MEDICAL_NECESSITY"
    MISSING_PRIOR_AUTH = "MISSING_PRIOR_AUTH"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    CODING_ERROR = "CODING_ERROR"
    ELIGIBILITY = "ELIGIBILITY"
    TIMELY_FILING = "TIMELY_FILING"
    DUPLICATE = "DUPLICATE"
    NO_PAYER_RESPONSE = "NO_PAYER_RESPONSE"
    OTHER = "OTHER"


class ProblemType(str, Enum):
    DENIED = "denied"
    INCOMPLETE = "incomplete"
    UNWORKED = "unworked"


# Standard Claim Adjustment Reason Codes -> category (subset, for illustration).
CARC_RULES: dict[str, Category] = {
    "50": Category.MEDICAL_NECESSITY,     # not deemed a medical necessity
    "197": Category.MISSING_PRIOR_AUTH,   # precertification/authorization absent
    "16": Category.MISSING_DOCUMENTATION, # claim lacks information
    "11": Category.CODING_ERROR,          # diagnosis inconsistent with procedure
    "4": Category.CODING_ERROR,           # procedure code inconsistent with modifier
    "27": Category.ELIGIBILITY,           # expenses after coverage terminated
    "31": Category.ELIGIBILITY,           # patient cannot be identified as insured
    "29": Category.TIMELY_FILING,         # time limit for filing has expired
    "18": Category.DUPLICATE,             # exact duplicate claim
}

# Categories where the agent must NOT draft anything; a human takes over.
HARD_STOPS: dict[Category, str] = {
    Category.TIMELY_FILING: "Timely-filing denials need proof of timely submission. A billing lead must decide; the agent will not draft.",
    Category.DUPLICATE: "Possible duplicate claim. Verify the original claim's status before any action; the agent will not draft.",
    Category.ELIGIBILITY: "Coverage or eligibility problem. Front office must verify insurance; an appeal is not appropriate.",
}

# Responsible owner per category (POC uses role names; production uses named people).
ROUTING: dict[Category, str] = {
    Category.MEDICAL_NECESSITY: "Appeals specialist",
    Category.MISSING_PRIOR_AUTH: "Authorization coordinator",
    Category.MISSING_DOCUMENTATION: "Billing specialist",
    Category.CODING_ERROR: "Coding specialist",
    Category.ELIGIBILITY: "Front office lead",
    Category.TIMELY_FILING: "Billing lead",
    Category.DUPLICATE: "Billing lead",
    Category.NO_PAYER_RESPONSE: "Billing specialist",
    Category.OTHER: "Billing lead",
}


@dataclass(frozen=True)
class RequiredEvidence:
    key: str
    label: str
    section: str          # Meditab section, or "claim" for claim fields
    scope: str            # "dos" (date of service only) | "history" (up to date of service) | "claim"
    doc_types: frozenset[str] | None = None
    exclude_billed_procedure: bool = False
    procedural_claims_only: bool = False  # skip when every billed code is an office visit (E/M)

    def applies_to(self, item: ClaimWorkItem) -> bool:
        if self.procedural_claims_only:
            return any(not is_em_code(c) for c in item.cpt_codes)
        return True


def is_em_code(cpt: str) -> bool:
    """Evaluation and management (office visit) codes are in the 99xxx range."""
    return cpt.startswith("99")


DOS_NOTE = RequiredEvidence("dos_note", "Provider note for the date of service", "encounters", "dos")

REQUIRED_EVIDENCE: dict[Category, list[RequiredEvidence]] = {
    Category.MEDICAL_NECESSITY: [
        DOS_NOTE,
        RequiredEvidence("conservative_treatment", "Record of prior conservative treatment", "procedures", "history",
                         exclude_billed_procedure=True),
        RequiredEvidence("imaging", "Imaging report supporting medical necessity", "documents", "history",
                         doc_types=frozenset({"imaging_report"})),
    ],
    Category.MISSING_PRIOR_AUTH: [
        DOS_NOTE,
        RequiredEvidence("auth_record", "Prior authorization number on the claim", "claim", "claim"),
    ],
    Category.MISSING_DOCUMENTATION: [
        DOS_NOTE,
        RequiredEvidence("dos_procedure", "Procedure record for the date of service", "procedures", "dos",
                         procedural_claims_only=True),
    ],
    Category.CODING_ERROR: [
        DOS_NOTE,
        RequiredEvidence("problem_list", "Documented diagnoses on the problem list", "problems", "history"),
    ],
    Category.NO_PAYER_RESPONSE: [],
    Category.OTHER: [DOS_NOTE],
    Category.ELIGIBILITY: [],
    Category.TIMELY_FILING: [],
    Category.DUPLICATE: [],
}

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+|the\s+)?(previous|prior|above)",
    r"you\s+are\s+now",
    r"system\s+prompt",
    r"mark\s+(this\s+claim\s+)?(as\s+)?(approved|paid)",
]


def requirements_for(category: Category, item: ClaimWorkItem) -> list[RequiredEvidence]:
    return [r for r in REQUIRED_EVIDENCE[category] if r.applies_to(item)]


def identify_problem(item: ClaimWorkItem, today: date, unworked_after_days: int) -> ProblemType | None:
    if not item.icd10_codes or not item.cpt_codes:
        return ProblemType.INCOMPLETE
    if item.status in ("denied", "rejected"):
        return ProblemType.DENIED
    if item.status == "pending":
        last = item.last_worked_on or item.submitted_on
        if last is None or (today - last).days > unworked_after_days:
            return ProblemType.UNWORKED
    return None


def rule_category(item: ClaimWorkItem) -> Category | None:
    if not item.icd10_codes or not item.cpt_codes:
        return Category.CODING_ERROR
    if item.denial and item.denial.carc_code in CARC_RULES:
        return CARC_RULES[item.denial.carc_code]
    return None


def detect_injection(text: str | None) -> bool:
    if not text:
        return False
    return any(re.search(p, text, re.I) for p in _INJECTION_PATTERNS)


def case_idempotency_key(item: ClaimWorkItem) -> str:
    d = item.denial
    return f"{item.claim_id}|{item.status}|{d.carc_code if d else ''}|{d.denial_date if d else ''}"


def claim_facts(item: ClaimWorkItem) -> dict:
    """Claim fields shared with the model and used for grounding checks."""
    return {
        "claim_id": item.claim_id,
        "payer": item.payer,
        "date_of_service": str(item.date_of_service),
        "cpt_codes": item.cpt_codes,
        "icd10_codes": item.icd10_codes,
        "billed_amount": item.billed_amount,
        "submitted_on": str(item.submitted_on) if item.submitted_on else None,
        "authorization_number": item.authorization_number,
        "denial_code": item.denial.carc_code if item.denial else None,
        "denial_description": item.denial.description if item.denial else None,
        "denial_date": str(item.denial.denial_date) if item.denial and item.denial.denial_date else None,
    }
