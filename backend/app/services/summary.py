"""AI-02 pre-visit summary with citations.

Flow: retrieve record (read-only) -> number evidence items -> model writes statements citing
evidence ids -> deterministic grounding checks -> unsupported statements are removed and shown
as removed. Medications and allergies are ALSO shown verbatim from structured data, so the
clinician never depends on the model for those lists.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.adapters.meditab.base import SourceRef
from app.audit import AuditLogger
from app.llm.client import LLMClient, LLMError
from app.llm import prompts
from app.models import utcnow_iso
from app.security import Actor
from app.services.clinical_record import ClinicalRecord, ClinicalRecordService, RecordItem
from app.services.exceptions import ExceptionService
from app.services.grounding import check_statement

MAX_EVIDENCE = 60
NOTE_CHARS = 600
SUMMARY_DOC_TYPES = {"imaging_report", "therapy_summary"}


class Citation(BaseModel):
    evidence_id: str
    item_id: str
    display: str
    source: SourceRef


class SummaryStatement(BaseModel):
    section: str
    text: str
    citations: list[Citation]


class RemovedStatement(BaseModel):
    section: str
    text: str
    reasons: list[str]


class SummaryResult(BaseModel):
    patient_id: str
    status: str  # "ok" | "failed"
    statements: list[SummaryStatement]
    removed: list[RemovedStatement]
    data_gaps: list[str]
    verified_medications: list[RecordItem]
    verified_allergies: list[RecordItem]
    model: str | None
    prompt_version: str
    generated_at: str
    message: str | None = None


def _evidence_text(item: RecordItem) -> str:
    if item.section == "encounters" and len(item.display) > NOTE_CHARS:
        return item.display[:NOTE_CHARS] + " [note truncated]"
    return item.display


def build_evidence(record: ClinicalRecord) -> list[tuple[str, RecordItem]]:
    picked: list[RecordItem] = []
    picked += record.items.get("problems", [])
    picked += record.items.get("medications", [])
    picked += record.items.get("allergies", [])
    picked += record.items.get("observations", [])
    picked += record.items.get("procedures", [])
    picked += record.items.get("labs", [])[:10]
    picked += record.items.get("encounters", [])[:3]
    picked += [d for d in record.items.get("documents", []) if d.data.get("doc_type") in SUMMARY_DOC_TYPES]
    return [(f"E{i}", item) for i, item in enumerate(picked[:MAX_EVIDENCE], start=1)]


def data_gaps(record: ClinicalRecord) -> list[str]:
    gaps = [f"{s.section.capitalize()} could not be loaded from Meditab; this summary does not include them."
            for s in record.statuses if s.status == "unavailable"]
    for q in record.quarantined:
        gaps.append(f"Document '{q.title}' was withheld because its identifiers do not match this patient.")
    for section in ("allergies", "medications"):
        status = next((s for s in record.statuses if s.section == section), None)
        if status and status.status == "ok" and status.item_count == 0:
            gaps.append(f"No {section} are recorded in Meditab. Confirm with the patient.")
    return gaps


class PreVisitSummaryService:
    def __init__(self, records: ClinicalRecordService, llm: LLMClient, audit: AuditLogger, exceptions: ExceptionService):
        self._records = records
        self._llm = llm
        self._audit = audit
        self._exceptions = exceptions

    def generate(self, patient_id: str, actor: Actor) -> SummaryResult:
        record = self._records.get_record(patient_id, actor=actor, purpose="pre_visit_summary")
        evidence = build_evidence(record)
        evidence_text = {eid: _evidence_text(item) for eid, item in evidence}
        by_id = dict(evidence)
        extra_terms = {i.data["name"] for i in record.items.get("medications", [])} | {
            i.data["substance"] for i in record.items.get("allergies", [])
        }
        base = dict(
            patient_id=patient_id, data_gaps=data_gaps(record),
            verified_medications=[m for m in record.items.get("medications", []) if m.data.get("status") == "active"],
            verified_allergies=record.items.get("allergies", []),
            prompt_version=prompts.PREVISIT_PROMPT_VERSION, generated_at=utcnow_iso(),
        )
        if not evidence:
            return SummaryResult(status="ok", statements=[], removed=[], model=None,
                                 message="No clinical data was available to summarise.", **base)

        prompt_evidence = [{"id": eid, "section": item.section, "date": item.date, "text": evidence_text[eid]}
                           for eid, item in evidence]
        mock_context = {"evidence": [{"id": eid, "section": item.section, "data": item.data} for eid, item in evidence]}
        p = record.patient
        try:
            result = self._llm.structured(
                task="previsit_summary", system=prompts.PREVISIT_SYSTEM,
                user=prompts.previsit_user(f"patient {p.first_name} {p.last_name} (MRN {p.mrn})", prompt_evidence),
                tool_name=prompts.PREVISIT_TOOL, tool_description="Return the summary statements with evidence ids.",
                schema=prompts.PREVISIT_SCHEMA, prompt_version=prompts.PREVISIT_PROMPT_VERSION, context=mock_context,
            )
        except LLMError as exc:
            self._exceptions.raise_(
                actor=actor, kind="llm_failure", severity="medium", entity_type="patient", entity_id=patient_id,
                patient_ref=patient_id, summary="Pre-visit summary could not be generated: model unavailable.",
                dedupe_key=f"llm_failure:previsit:{patient_id}", detail={"error": str(exc)},
            )
            return SummaryResult(status="failed", statements=[], removed=[], model=None,
                                 message="The summary could not be generated. The record below is complete.", **base)

        accepted: list[SummaryStatement] = []
        removed: list[RemovedStatement] = []
        for raw in result.data.get("statements", []):
            text = str(raw.get("text", "")).strip()
            ids = [str(i) for i in raw.get("evidence_ids", [])]
            section = str(raw.get("section", "history"))
            if not text:
                continue
            reasons = check_statement(text, ids, evidence_text, extra_terms)
            if reasons:
                removed.append(RemovedStatement(section=section, text=text, reasons=reasons))
                continue
            accepted.append(SummaryStatement(
                section=section, text=text,
                citations=[Citation(evidence_id=i, item_id=by_id[i].item_id, display=evidence_text[i], source=by_id[i].source)
                           for i in dict.fromkeys(ids)],
            ))

        self._audit.record(
            actor=actor, action="llm.previsit_summary", entity_type="patient", entity_id=patient_id,
            patient_ref=patient_id, purpose="pre_visit_summary", model=result.model, prompt_version=result.prompt_version,
            detail={"evidence_items": len(evidence), "accepted": len(accepted), "removed": len(removed),
                    "input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
        )
        return SummaryResult(status="ok", statements=accepted, removed=removed, model=result.model, **base)
