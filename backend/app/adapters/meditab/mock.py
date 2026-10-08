"""Mock Meditab IMS backed by a JSON fixture of SYNTHETIC patients.

No real PHI. Supports simulated outages per patient and section so failure handling can be
demonstrated (fixture key: "simulated_outages").
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.adapters.meditab.base import (
    Allergy,
    ClinicalDocument,
    Encounter,
    LabResult,
    MeditabAdapter,
    MeditabUnavailableError,
    Medication,
    Observation,
    PatientDemographics,
    Problem,
    Procedure,
)

T = TypeVar("T", bound=BaseModel)


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


class MockMeditabAdapter(MeditabAdapter):
    def __init__(self, data: dict):
        self._patients = [PatientDemographics(**p) for p in data.get("patients", [])]
        self._encounters = [Encounter(**x) for x in data.get("encounters", [])]
        self._medications = [Medication(**x) for x in data.get("medications", [])]
        self._allergies = [Allergy(**x) for x in data.get("allergies", [])]
        self._problems = [Problem(**x) for x in data.get("problems", [])]
        self._labs = [LabResult(**x) for x in data.get("labs", [])]
        self._observations = [Observation(**x) for x in data.get("observations", [])]
        self._procedures = [Procedure(**x) for x in data.get("procedures", [])]
        self._documents = [ClinicalDocument(**x) for x in data.get("documents", [])]
        self._outages: dict[str, list[str]] = data.get("simulated_outages", {})

    @classmethod
    def from_file(cls, path: Path) -> "MockMeditabAdapter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _check_available(self, patient_id: str, section: str) -> None:
        if section in self._outages.get(patient_id, []):
            raise MeditabUnavailableError(f"Simulated Meditab outage for section '{section}'")

    @staticmethod
    def _for_patient(items: list[T], patient_id: str) -> list[T]:
        return [i.model_copy() for i in items if getattr(i, "patient_id") == patient_id]

    def search_patients(self, query: str, limit: int = 25) -> list[PatientDemographics]:
        tokens = [_norm(t) for t in query.split() if _norm(t)]
        results = []
        for p in self._patients:
            haystack = _norm(f"{p.first_name} {p.last_name} {p.mrn} {p.dob.isoformat()}")
            if all(t in haystack for t in tokens):
                results.append(p.model_copy())
        results.sort(key=lambda p: (p.last_name, p.first_name, p.mrn))
        return results[:limit]

    def find_patients(
        self,
        *,
        mrn: str | None = None,
        last_name: str | None = None,
        first_name: str | None = None,
        dob: date | None = None,
    ) -> list[PatientDemographics]:
        out = []
        for p in self._patients:
            if mrn is not None and p.mrn != mrn:
                continue
            if last_name is not None and _norm(p.last_name) != _norm(last_name):
                continue
            if first_name is not None and _norm(p.first_name) != _norm(first_name):
                continue
            if dob is not None and p.dob != dob:
                continue
            out.append(p.model_copy())
        return out

    def get_patient(self, patient_id: str) -> PatientDemographics | None:
        return next((p.model_copy() for p in self._patients if p.patient_id == patient_id), None)

    def list_encounters(self, patient_id: str) -> list[Encounter]:
        self._check_available(patient_id, "encounters")
        return self._for_patient(self._encounters, patient_id)

    def list_medications(self, patient_id: str) -> list[Medication]:
        self._check_available(patient_id, "medications")
        return self._for_patient(self._medications, patient_id)

    def list_allergies(self, patient_id: str) -> list[Allergy]:
        self._check_available(patient_id, "allergies")
        return self._for_patient(self._allergies, patient_id)

    def list_problems(self, patient_id: str) -> list[Problem]:
        self._check_available(patient_id, "problems")
        return self._for_patient(self._problems, patient_id)

    def list_labs(self, patient_id: str) -> list[LabResult]:
        self._check_available(patient_id, "labs")
        return self._for_patient(self._labs, patient_id)

    def list_observations(self, patient_id: str) -> list[Observation]:
        self._check_available(patient_id, "observations")
        return self._for_patient(self._observations, patient_id)

    def list_procedures(self, patient_id: str) -> list[Procedure]:
        self._check_available(patient_id, "procedures")
        return self._for_patient(self._procedures, patient_id)

    def list_documents(self, patient_id: str) -> list[ClinicalDocument]:
        self._check_available(patient_id, "documents")
        return self._for_patient(self._documents, patient_id)
