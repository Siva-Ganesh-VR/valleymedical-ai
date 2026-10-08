"""Deterministic, fail-closed patient and document identity matching.

Safety-critical (D1 hard gate: zero wrong-patient disclosures). No model is involved:
- Internal ID or MRN must resolve to exactly one patient.
- Any demographics supplied alongside are cross-checked; any disagreement is a CONFLICT.
- Demographics alone never produce an automatic match.
- Documents whose embedded identifiers disagree with the chart are quarantined.
"""
from __future__ import annotations

import re
from datetime import date
from enum import Enum

from pydantic import BaseModel

from app.adapters.meditab.base import ClinicalDocument, MeditabAdapter, PatientDemographics


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z]", "", (value or "").casefold())


class MatchStatus(str, Enum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    UNCONFIRMED = "unconfirmed"
    CONFLICT = "conflict"


class MatchResult(BaseModel):
    status: MatchStatus
    patient: PatientDemographics | None = None
    candidate_ids: list[str] = []
    reasons: list[str] = []
    verified: bool = False  # identifiers independently cross-checked

    @property
    def matched(self) -> bool:
        return self.status == MatchStatus.MATCHED


class PatientMatcher:
    def __init__(self, adapter: MeditabAdapter):
        self._adapter = adapter

    def match(
        self,
        *,
        patient_id: str | None = None,
        mrn: str | None = None,
        last_name: str | None = None,
        first_name: str | None = None,
        dob: date | None = None,
    ) -> MatchResult:
        if patient_id:
            candidate = self._adapter.get_patient(patient_id)
            if candidate is None:
                return MatchResult(status=MatchStatus.NO_MATCH, reasons=["No patient with this internal ID"])
            conflicts = self._cross_check(candidate, mrn=mrn, last_name=last_name, first_name=first_name, dob=dob)
        elif mrn:
            found = self._adapter.find_patients(mrn=mrn)
            if not found:
                return MatchResult(status=MatchStatus.NO_MATCH, reasons=[f"No patient with MRN {mrn}"])
            if len(found) > 1:
                return MatchResult(status=MatchStatus.AMBIGUOUS, candidate_ids=[p.patient_id for p in found],
                                   reasons=["MRN resolves to more than one patient"])
            candidate = found[0]
            conflicts = self._cross_check(candidate, last_name=last_name, first_name=first_name, dob=dob)
        else:
            if not (last_name and dob):
                return MatchResult(status=MatchStatus.NO_MATCH, reasons=["Not enough identifiers to search"])
            found = self._adapter.find_patients(last_name=last_name, first_name=first_name, dob=dob)
            if not found:
                return MatchResult(status=MatchStatus.NO_MATCH, reasons=["No patient matches these demographics"])
            if len(found) > 1:
                return MatchResult(status=MatchStatus.AMBIGUOUS, candidate_ids=[p.patient_id for p in found],
                                   reasons=[f"{len(found)} patients share these demographics"])
            return MatchResult(status=MatchStatus.UNCONFIRMED, candidate_ids=[found[0].patient_id],
                               reasons=["Demographic-only match requires human confirmation"])

        if conflicts:
            return MatchResult(status=MatchStatus.CONFLICT, candidate_ids=[candidate.patient_id], reasons=conflicts)
        checked = any(v is not None for v in (mrn if patient_id else None, last_name, first_name, dob))
        return MatchResult(status=MatchStatus.MATCHED, patient=candidate, candidate_ids=[candidate.patient_id],
                           reasons=["Resolved by unique identifier" + (" and demographics agree" if checked else "")],
                           verified=checked)

    @staticmethod
    def _cross_check(
        p: PatientDemographics,
        *,
        mrn: str | None = None,
        last_name: str | None = None,
        first_name: str | None = None,
        dob: date | None = None,
    ) -> list[str]:
        conflicts = []
        if mrn is not None and mrn != p.mrn:
            conflicts.append("MRN does not match the patient record")
        if dob is not None and dob != p.dob:
            conflicts.append("Date of birth does not match the patient record")
        if last_name is not None and _norm(last_name) != _norm(p.last_name):
            conflicts.append("Last name does not match the patient record")
        if first_name is not None and _norm(first_name) != _norm(p.first_name):
            conflicts.append("First name does not match the patient record")
        return conflicts

    def verify_document(self, patient: PatientDemographics, document: ClinicalDocument) -> MatchResult:
        if document.patient_id != patient.patient_id:
            return MatchResult(status=MatchStatus.CONFLICT, candidate_ids=[document.patient_id],
                               reasons=["Document is filed under a different chart"])
        emb = document.embedded_identifiers
        if emb is None:
            return MatchResult(status=MatchStatus.MATCHED, patient=patient,
                               reasons=["No identifiers printed in the document; relies on chart filing"],
                               verified=False)
        conflicts = self._cross_check(patient, mrn=emb.mrn, last_name=emb.last_name,
                                      first_name=emb.first_name, dob=emb.dob)
        if conflicts:
            return MatchResult(status=MatchStatus.CONFLICT, candidate_ids=[patient.patient_id],
                               reasons=[f"Identifiers printed in the document disagree with the chart: {c.lower()}"
                                        for c in conflicts])
        return MatchResult(status=MatchStatus.MATCHED, patient=patient,
                           reasons=["Identifiers printed in the document match the chart"], verified=True)
