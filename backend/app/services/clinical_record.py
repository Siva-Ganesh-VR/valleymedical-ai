"""Assembles a patient's record from Meditab with a source reference on every item.

Guarantees:
- Every item carries patient, encounter, date and source (SourceRef).
- Items belonging to another patient are dropped and raised as critical exceptions.
- Documents whose embedded identifiers disagree with the chart are quarantined.
- A section that cannot be read is reported as "unavailable", never silently empty.
- Every read is written to the audit log with its purpose.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Literal

from pydantic import BaseModel

from app.adapters.meditab.base import MeditabAdapter, MeditabUnavailableError, PatientDemographics, SourceRef
from app.audit import AuditLogger
from app.errors import NotFoundError
from app.models import utcnow_iso
from app.security import Actor
from app.services.exceptions import ExceptionService
from app.services.patient_matching import PatientMatcher

SECTIONS = ["encounters", "medications", "allergies", "problems", "labs", "observations", "procedures", "documents"]

DIMENSION_LABELS = {"pain": "Pain score", "function": "Function (disability)", "sleep": "Sleep", "mood": "Mood"}


def fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


class RecordItem(BaseModel):
    item_id: str
    section: str
    display: str
    date: date | None
    data: dict
    source: SourceRef


class SectionStatus(BaseModel):
    section: str
    status: Literal["ok", "unavailable"]
    item_count: int
    message: str | None = None


class QuarantinedDocument(BaseModel):
    document_id: str
    title: str
    reasons: list[str]


class ClinicalRecord(BaseModel):
    patient: PatientDemographics
    items: dict[str, list[RecordItem]]
    statuses: list[SectionStatus]
    quarantined: list[QuarantinedDocument]
    retrieved_at: str

    def all_items(self) -> list[RecordItem]:
        return [i for section in self.items.values() for i in section]

    def unavailable_sections(self) -> list[str]:
        return [s.section for s in self.statuses if s.status == "unavailable"]


class RecordScope(BaseModel):
    """Minimum-necessary filter applied to what a workflow is allowed to read."""

    encounter_ids: set[str] | None = None
    dates: set[date] | None = None
    on_or_before: date | None = None
    doc_types: set[str] | None = None


class ClinicalRecordService:
    def __init__(self, adapter: MeditabAdapter, matcher: PatientMatcher, exceptions: ExceptionService, audit: AuditLogger):
        self._adapter = adapter
        self._matcher = matcher
        self._exceptions = exceptions
        self._audit = audit
        self._fetchers: dict[str, Callable] = {
            "encounters": adapter.list_encounters,
            "medications": adapter.list_medications,
            "allergies": adapter.list_allergies,
            "problems": adapter.list_problems,
            "labs": adapter.list_labs,
            "observations": adapter.list_observations,
            "procedures": adapter.list_procedures,
            "documents": adapter.list_documents,
        }

    def get_record(
        self,
        patient_id: str,
        *,
        actor: Actor,
        purpose: str,
        sections: list[str] | None = None,
        scope: RecordScope | None = None,
    ) -> ClinicalRecord:
        match = self._matcher.match(patient_id=patient_id)
        if not match.matched or match.patient is None:
            raise NotFoundError("Patient not found")
        patient = match.patient
        sections = sections or SECTIONS
        items: dict[str, list[RecordItem]] = {}
        statuses: list[SectionStatus] = []
        quarantined: list[QuarantinedDocument] = []

        for section in sections:
            try:
                raw = self._fetchers[section](patient_id)
            except MeditabUnavailableError as exc:
                statuses.append(SectionStatus(section=section, status="unavailable", item_count=0, message=str(exc)))
                items[section] = []
                continue

            safe = []
            for record in raw:
                if record.patient_id != patient_id:
                    # Defence in depth: an adapter bug must never leak another patient's data.
                    self._exceptions.raise_(
                        actor=actor, kind="cross_patient_item", severity="critical", entity_type="patient",
                        entity_id=patient_id, patient_ref=patient_id,
                        summary=f"Meditab returned a {section} item belonging to another patient; it was withheld.",
                        dedupe_key=f"cross_patient:{section}:{patient_id}", detail={"section": section},
                    )
                    continue
                safe.append(record)

            built: list[RecordItem] = []
            if section == "documents":
                for doc in safe:
                    check = self._matcher.verify_document(patient, doc)
                    if not check.matched:
                        quarantined.append(QuarantinedDocument(document_id=doc.document_id, title=doc.title, reasons=check.reasons))
                        self._exceptions.raise_(
                            actor=actor, kind="document_identity_mismatch", severity="critical", entity_type="document",
                            entity_id=doc.document_id, patient_ref=patient_id,
                            summary=f"Document '{doc.title}' was withheld: its printed identifiers do not match the chart.",
                            dedupe_key=f"doc_mismatch:{doc.document_id}",
                            detail={"chart_patient_id": patient_id, "reasons": check.reasons},
                        )
                        continue
                    built.extend(self._document_items(doc, verified=check.verified))
            else:
                built = [self._build(section, r) for r in safe]

            built = [i for i in built if self._in_scope(i, scope)]
            built.sort(key=lambda i: (i.date or date.min), reverse=True)
            items[section] = built
            statuses.append(SectionStatus(section=section, status="ok", item_count=len(built)))

        self._audit.record(
            actor=actor, action="clinical_record.read", entity_type="patient", entity_id=patient_id,
            patient_ref=patient_id, purpose=purpose,
            detail={
                "sections": sections,
                "counts": {k: len(v) for k, v in items.items()},
                "unavailable": [s.section for s in statuses if s.status == "unavailable"],
                "quarantined": [q.document_id for q in quarantined],
                "scoped": scope is not None,
            },
        )
        return ClinicalRecord(patient=patient, items=items, statuses=statuses, quarantined=quarantined, retrieved_at=utcnow_iso())

    @staticmethod
    def _in_scope(item: RecordItem, scope: RecordScope | None) -> bool:
        if scope is None:
            return True
        if scope.encounter_ids is not None or scope.dates is not None:
            by_enc = scope.encounter_ids is not None and item.source.encounter_id in scope.encounter_ids
            by_date = scope.dates is not None and item.date in scope.dates
            if not (by_enc or by_date):
                return False
        if scope.on_or_before is not None and (item.date is None or item.date > scope.on_or_before):
            return False
        if scope.doc_types is not None and item.section == "documents" and item.data.get("doc_type") not in scope.doc_types:
            return False
        return True

    @staticmethod
    def _build(section: str, r) -> RecordItem:
        if section == "encounters":
            return RecordItem(
                item_id=f"encounters:{r.encounter_id}", section=section, date=r.date,
                display=f"{r.date} {r.type} with {r.provider}: {r.note_text}",
                data=r.model_dump(mode="json"),
                source=SourceRef(record_type="encounter", record_id=r.encounter_id, encounter_id=r.encounter_id, recorded_on=r.date),
            )
        if section == "medications":
            period = f"started {r.start_date}" + (f", stopped {r.end_date}" if r.end_date else "")
            return RecordItem(
                item_id=f"medications:{r.med_id}", section=section, date=r.start_date,
                display=f"{r.name} {r.dose} {r.frequency} ({r.status}, {period})",
                data=r.model_dump(mode="json"),
                source=SourceRef(record_type="medication", record_id=r.med_id, encounter_id=r.encounter_id, recorded_on=r.start_date),
            )
        if section == "allergies":
            return RecordItem(
                item_id=f"allergies:{r.allergy_id}", section=section, date=r.recorded_on,
                display=f"{r.substance}: {r.reaction} ({r.severity}), recorded {r.recorded_on}",
                data=r.model_dump(mode="json"),
                source=SourceRef(record_type="allergy", record_id=r.allergy_id, recorded_on=r.recorded_on),
            )
        if section == "problems":
            return RecordItem(
                item_id=f"problems:{r.problem_id}", section=section, date=r.onset,
                display=f"{r.description} ({r.icd10}), {r.status}, onset {r.onset}",
                data=r.model_dump(mode="json"),
                source=SourceRef(record_type="problem", record_id=r.problem_id, recorded_on=r.onset),
            )
        if section == "labs":
            return RecordItem(
                item_id=f"labs:{r.lab_id}", section=section, date=r.collected_on,
                display=f"{r.test} {r.value} {r.unit} (reference {r.reference_range}) on {r.collected_on}",
                data=r.model_dump(mode="json"),
                source=SourceRef(record_type="lab_result", record_id=r.lab_id, encounter_id=r.encounter_id, recorded_on=r.collected_on),
            )
        if section == "observations":
            value = fmt_num(r.value)
            shown = f"{value}{r.unit}" if r.unit.startswith("/") or r.unit == "%" else f"{value} {r.unit}"
            data = r.model_dump(mode="json") | {"display_value": shown}
            return RecordItem(
                item_id=f"observations:{r.obs_id}", section=section, date=r.recorded_on,
                display=f"{DIMENSION_LABELS.get(r.dimension, r.dimension)} {shown} ({r.instrument}) on {r.recorded_on}",
                data=data,
                source=SourceRef(record_type="observation", record_id=r.obs_id, encounter_id=r.encounter_id, recorded_on=r.recorded_on),
            )
        if section == "procedures":
            outcome = f": {r.outcome_note}" if r.outcome_note else ""
            return RecordItem(
                item_id=f"procedures:{r.procedure_id}", section=section, date=r.performed_on,
                display=f"{r.name} (CPT {r.cpt}) on {r.performed_on}{outcome}",
                data=r.model_dump(mode="json"),
                source=SourceRef(record_type="procedure", record_id=r.procedure_id, encounter_id=r.encounter_id, recorded_on=r.performed_on),
            )
        raise ValueError(f"Unknown section {section}")

    @staticmethod
    def _document_items(doc, *, verified: bool) -> list[RecordItem]:
        """One item per page, so citations can point to a page."""
        out = []
        for page in doc.pages:
            out.append(RecordItem(
                item_id=f"documents:{doc.document_id}#p{page.page}", section="documents", date=doc.document_date,
                display=f"{doc.title} ({doc.document_date}), page {page.page}: {page.text}",
                data={"document_id": doc.document_id, "title": doc.title, "doc_type": doc.doc_type,
                      "page": page.page, "page_count": len(doc.pages), "text": page.text,
                      "identity_verified": verified},
                source=SourceRef(record_type="document", record_id=doc.document_id, encounter_id=doc.encounter_id,
                                 recorded_on=doc.document_date, page=page.page),
            ))
        return out
