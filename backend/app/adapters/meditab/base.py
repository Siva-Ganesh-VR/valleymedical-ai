"""Meditab IMS adapter interface.

ASSUMPTION: Meditab's real interfaces (vendor API, FHIR, HL7 feeds, reporting DB, exports)
are UNKNOWN and require technical discovery with Meditab and Valley Medical. Everything
outside this package depends only on this interface, so a real adapter can replace the mock
without changing services, agents or the UI. Every adapter must be READ-ONLY.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from pydantic import BaseModel, ConfigDict


class MeditabUnavailableError(Exception):
    """A section could not be read from Meditab (outage, timeout, permission)."""


class SourceRef(BaseModel):
    """Where a fact came from. Attached to every item shown or cited."""

    model_config = ConfigDict(frozen=True)

    system: str = "meditab"
    record_type: str
    record_id: str
    encounter_id: str | None = None
    recorded_on: date | None = None
    page: int | None = None


class PatientDemographics(BaseModel):
    patient_id: str  # Meditab internal identifier
    mrn: str
    first_name: str
    last_name: str
    dob: date
    sex: str


class Encounter(BaseModel):
    encounter_id: str
    patient_id: str
    date: date
    type: str
    provider: str
    note_text: str


class Medication(BaseModel):
    med_id: str
    patient_id: str
    name: str
    dose: str
    frequency: str
    start_date: date
    end_date: date | None = None
    status: str
    encounter_id: str | None = None


class Allergy(BaseModel):
    allergy_id: str
    patient_id: str
    substance: str
    reaction: str
    severity: str
    recorded_on: date


class Problem(BaseModel):
    problem_id: str
    patient_id: str
    description: str
    icd10: str
    status: str
    onset: date


class LabResult(BaseModel):
    lab_id: str
    patient_id: str
    test: str
    value: str
    unit: str
    reference_range: str
    collected_on: date
    encounter_id: str | None = None


class Observation(BaseModel):
    """Scored measures: pain, function, sleep, mood (chronic-pain dimensions)."""

    obs_id: str
    patient_id: str
    dimension: str
    instrument: str
    value: float
    unit: str
    recorded_on: date
    encounter_id: str | None = None


class Procedure(BaseModel):
    procedure_id: str
    patient_id: str
    name: str
    cpt: str
    performed_on: date
    encounter_id: str | None = None
    outcome_note: str = ""


class EmbeddedIdentifiers(BaseModel):
    """Identifiers printed inside a document (header of a PDF, fax cover, etc.)."""

    mrn: str | None = None
    dob: date | None = None
    last_name: str | None = None
    first_name: str | None = None


class DocumentPage(BaseModel):
    page: int
    text: str


class ClinicalDocument(BaseModel):
    document_id: str
    patient_id: str  # chart the document is filed under
    title: str
    doc_type: str
    document_date: date
    encounter_id: str | None = None
    embedded_identifiers: EmbeddedIdentifiers | None = None
    pages: list[DocumentPage]


class MeditabAdapter(ABC):
    @abstractmethod
    def search_patients(self, query: str, limit: int = 25) -> list[PatientDemographics]: ...

    @abstractmethod
    def find_patients(
        self,
        *,
        mrn: str | None = None,
        last_name: str | None = None,
        first_name: str | None = None,
        dob: date | None = None,
    ) -> list[PatientDemographics]: ...

    @abstractmethod
    def get_patient(self, patient_id: str) -> PatientDemographics | None: ...

    @abstractmethod
    def list_encounters(self, patient_id: str) -> list[Encounter]: ...

    @abstractmethod
    def list_medications(self, patient_id: str) -> list[Medication]: ...

    @abstractmethod
    def list_allergies(self, patient_id: str) -> list[Allergy]: ...

    @abstractmethod
    def list_problems(self, patient_id: str) -> list[Problem]: ...

    @abstractmethod
    def list_labs(self, patient_id: str) -> list[LabResult]: ...

    @abstractmethod
    def list_observations(self, patient_id: str) -> list[Observation]: ...

    @abstractmethod
    def list_procedures(self, patient_id: str) -> list[Procedure]: ...

    @abstractmethod
    def list_documents(self, patient_id: str) -> list[ClinicalDocument]: ...
