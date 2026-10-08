"""Billing work-queue adapter interface.

ASSUMPTION: which system holds the billing queue (Meditab's billing module, a separate
practice-management system, a clearinghouse or an outsourced RCM vendor) is UNKNOWN and
requires discovery. Adapters are READ-ONLY: they never submit claims or appeals.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

from pydantic import BaseModel


class DenialInfo(BaseModel):
    carc_code: str | None = None  # Claim Adjustment Reason Code
    rarc_code: str | None = None  # Remittance Advice Remark Code
    description: str | None = None
    denial_date: date | None = None
    payer_remark: str | None = None  # free text from the payer: UNTRUSTED


class ClaimWorkItem(BaseModel):
    claim_id: str
    queue: str
    patient_mrn: str
    patient_last_name: str
    patient_first_name: str | None = None
    patient_dob: date
    payer: str
    date_of_service: date
    encounter_id: str | None = None
    cpt_codes: list[str]
    icd10_codes: list[str]
    billed_amount: float
    status: Literal["denied", "rejected", "pending", "paid"]
    submitted_on: date | None = None
    last_worked_on: date | None = None
    authorization_number: str | None = None
    denial: DenialInfo | None = None


class BillingQueueAdapter(ABC):
    @abstractmethod
    def list_queues(self) -> list[str]: ...

    @abstractmethod
    def list_work_items(self, queue: str) -> list[ClaimWorkItem]: ...

    @abstractmethod
    def get_work_item(self, claim_id: str) -> ClaimWorkItem | None: ...
