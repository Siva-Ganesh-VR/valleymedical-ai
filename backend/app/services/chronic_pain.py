"""AI-03 chronic-pain longitudinal view. Fully deterministic: no model involved.

Dimensions from D1: pain, function, sleep, mood, medications, procedures, imaging and prior
treatment response. Treatment response pairs each procedure with the nearest pain score
before and after it. Where a dimension has no data, it says so explicitly.
"""
from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from app.adapters.meditab.base import SourceRef
from app.security import Actor
from app.services.clinical_record import DIMENSION_LABELS, ClinicalRecordService, RecordItem, SectionStatus

RESPONSE_WINDOW_DAYS = 90


class TrendPoint(BaseModel):
    date: str
    value: float
    display_value: str
    instrument: str
    item_id: str
    source: SourceRef


class DimensionTrend(BaseModel):
    dimension: str
    label: str
    status: str  # data | no_data | unavailable
    points: list[TrendPoint]


class TreatmentResponse(BaseModel):
    procedure: RecordItem
    pain_before: TrendPoint | None
    pain_after: TrendPoint | None


class ChronicPainView(BaseModel):
    patient_id: str
    dimensions: list[DimensionTrend]
    medications: list[RecordItem]
    treatment_responses: list[TreatmentResponse]
    imaging: list[RecordItem]
    statuses: list[SectionStatus]
    withheld_documents: int


class ChronicPainService:
    def __init__(self, records: ClinicalRecordService):
        self._records = records

    def build(self, patient_id: str, actor: Actor) -> ChronicPainView:
        record = self._records.get_record(
            patient_id, actor=actor, purpose="chronic_pain_view",
            sections=["observations", "medications", "procedures", "documents"],
        )
        obs_unavailable = "observations" in record.unavailable_sections()
        dims = []
        points_by_dim: dict[str, list[TrendPoint]] = {}
        for dim, label in DIMENSION_LABELS.items():
            pts = sorted(
                (TrendPoint(date=str(i.date), value=i.data["value"], display_value=i.data["display_value"],
                            instrument=i.data["instrument"], item_id=i.item_id, source=i.source)
                 for i in record.items.get("observations", []) if i.data.get("dimension") == dim),
                key=lambda p: p.date,
            )
            points_by_dim[dim] = pts
            status = "unavailable" if obs_unavailable else ("data" if pts else "no_data")
            dims.append(DimensionTrend(dimension=dim, label=label, status=status, points=pts))

        responses = []
        pain = points_by_dim["pain"]
        for proc in sorted(record.items.get("procedures", []), key=lambda i: i.date):
            window = timedelta(days=RESPONSE_WINDOW_DAYS)
            before = [p for p in pain if proc.date - window <= _d(p.date) <= proc.date]
            after = [p for p in pain if proc.date < _d(p.date) <= proc.date + window]
            responses.append(TreatmentResponse(procedure=proc, pain_before=before[-1] if before else None,
                                               pain_after=after[0] if after else None))

        imaging = [d for d in record.items.get("documents", []) if d.data.get("doc_type") == "imaging_report"]
        return ChronicPainView(
            patient_id=patient_id, dimensions=dims, medications=record.items.get("medications", []),
            treatment_responses=responses, imaging=imaging, statuses=record.statuses,
            withheld_documents=len(record.quarantined),
        )


def _d(value: str):
    from datetime import date
    return date.fromisoformat(value)
