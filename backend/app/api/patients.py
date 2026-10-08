from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_session, require
from app.container import Container
from app.security import Actor, Permission

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("")
def search_patients(
    q: str = Query(default="", max_length=100),
    actor: Actor = Depends(require(Permission.CLINICAL_READ)),
    container: Container = Depends(get_container),
    session: Session = Depends(get_session),
):
    results = container.meditab.search_patients(q)
    container.audit(session).record(actor=actor, action="patient.search", entity_type="patient_search",
                                    entity_id="search", detail={"query_length": len(q), "results": len(results)})
    session.commit()
    return [p.model_dump(mode="json") for p in results]


@router.get("/{patient_id}/record")
def get_record(
    patient_id: str,
    actor: Actor = Depends(require(Permission.CLINICAL_READ)),
    container: Container = Depends(get_container),
    session: Session = Depends(get_session),
):
    record = container.records(session).get_record(patient_id, actor=actor, purpose="chart_review")
    session.commit()
    return record.model_dump(mode="json")


@router.get("/{patient_id}/chronic-pain")
def chronic_pain(
    patient_id: str,
    actor: Actor = Depends(require(Permission.CLINICAL_READ)),
    container: Container = Depends(get_container),
    session: Session = Depends(get_session),
):
    view = container.chronic_pain(session).build(patient_id, actor)
    session.commit()
    return view.model_dump(mode="json")


@router.post("/{patient_id}/previsit-summary")
def previsit_summary(
    patient_id: str,
    actor: Actor = Depends(require(Permission.CLINICAL_READ)),
    container: Container = Depends(get_container),
    session: Session = Depends(get_session),
):
    result = container.summaries(session).generate(patient_id, actor)
    session.commit()
    return result.model_dump(mode="json")
