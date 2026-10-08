from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_actor, get_container, get_session, require
from app.audit import verify_chain
from app.container import Container
from app.models import AuditEvent
from app.security import Actor, Permission, permissions_for

router = APIRouter(prefix="/api", tags=["admin"])


class ResolveBody(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


@router.get("/health")
def health(container: Container = Depends(get_container)):
    return {"status": "ok", "llm": container.llm.name, "meditab": type(container.meditab).__name__,
            "billing": type(container.billing).__name__}


@router.get("/me")
def me(actor: Actor = Depends(get_actor)):
    return {"username": actor.username, "role": actor.role.value, "permissions": permissions_for(actor.role)}


@router.get("/exceptions")
def list_exceptions(status: str | None = Query(default=None), actor: Actor = Depends(require(Permission.EXCEPTIONS_READ)),
                    container: Container = Depends(get_container), session: Session = Depends(get_session)):
    return [{"id": e.id, "created_at": e.created_at, "kind": e.kind, "severity": e.severity, "entity_type": e.entity_type,
             "entity_id": e.entity_id, "summary": e.summary, "status": e.status, "resolved_by": e.resolved_by,
             "resolved_at": e.resolved_at, "resolution_note": e.resolution_note}
            for e in container.exceptions(session).list(status)]


@router.post("/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: int, body: ResolveBody, actor: Actor = Depends(require(Permission.EXCEPTIONS_RESOLVE)),
                      container: Container = Depends(get_container), session: Session = Depends(get_session)):
    item = container.exceptions(session).resolve(exception_id, actor, body.note)
    session.commit()
    return {"id": item.id, "status": item.status}


@router.get("/audit")
def audit_log(limit: int = Query(default=200, ge=1, le=1000), actor: Actor = Depends(require(Permission.AUDIT_READ)),
              session: Session = Depends(get_session)):
    rows = session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit))
    return [{"id": r.id, "ts": r.ts, "actor": r.actor, "actor_role": r.actor_role, "action": r.action,
             "entity_type": r.entity_type, "entity_id": r.entity_id, "patient_ref": r.patient_ref, "purpose": r.purpose,
             "model": r.model, "prompt_version": r.prompt_version, "detail": r.detail, "hash": r.hash[:12]} for r in rows]


@router.get("/audit/verify")
def audit_verify(actor: Actor = Depends(require(Permission.AUDIT_READ)), session: Session = Depends(get_session)):
    result = verify_chain(session)
    return {"ok": result.ok, "checked": result.checked, "first_invalid_id": result.first_invalid_id}
