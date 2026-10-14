"""Exception queue: anything unsafe, uncertain or failed lands here for a human."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import AuditLogger
from app.errors import InvalidStateError, NotFoundError
from app.models import ExceptionItem, utcnow_iso
from app.security import Actor


class ExceptionService:
    def __init__(self, session: Session, audit: AuditLogger):
        self._session = session
        self._audit = audit

    def raise_(
        self,
        *,
        actor: Actor,
        kind: str,
        severity: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        dedupe_key: str,
        detail: dict | None = None,
        patient_ref: str | None = None,
    ) -> ExceptionItem:
        """Open an exception. Idempotent: an identical open exception is returned, not duplicated."""
        existing = self._session.scalars(
            select(ExceptionItem).where(
                ExceptionItem.dedupe_key == dedupe_key, ExceptionItem.status == "open"
            )
        ).first()
        if existing:
            return existing
        item = ExceptionItem(
            created_at=utcnow_iso(), kind=kind, severity=severity, entity_type=entity_type,
            entity_id=entity_id, summary=summary, detail=detail or {}, dedupe_key=dedupe_key,
            status="open",
        )
        self._session.add(item)
        self._session.flush()
        self._audit.record(
            actor=actor, action="exception.raised", entity_type="exception", entity_id=str(item.id),
            patient_ref=patient_ref, detail={"kind": kind, "severity": severity, "about": f"{entity_type}:{entity_id}"},
        )
        return item

    def list(self, status: str | None = None) -> list[ExceptionItem]:
        stmt = select(ExceptionItem).order_by(ExceptionItem.id.desc())
        if status:
            stmt = stmt.where(ExceptionItem.status == status)
        return list(self._session.scalars(stmt))

    def resolve_for(self, entity_type: str, entity_id: str, actor: Actor, note: str, *, kind: str | None = None) -> int:
        """Close open exceptions about one entity (e.g. when its billing case is resolved), optionally of one kind."""
        stmt = select(ExceptionItem).where(
            ExceptionItem.entity_type == entity_type, ExceptionItem.entity_id == entity_id, ExceptionItem.status == "open")
        if kind:
            stmt = stmt.where(ExceptionItem.kind == kind)
        items = list(self._session.scalars(stmt))
        for item in items:
            self.resolve(item.id, actor, note)
        return len(items)

    def resolve(self, exception_id: int, actor: Actor, note: str) -> ExceptionItem:
        item = self._session.get(ExceptionItem, exception_id)
        if item is None:
            raise NotFoundError(f"Exception {exception_id} not found")
        if item.status != "open":
            raise InvalidStateError("Exception is already resolved")
        item.status = "resolved"
        item.resolved_by = actor.username
        item.resolved_at = utcnow_iso()
        item.resolution_note = note
        self._audit.record(
            actor=actor, action="exception.resolved", entity_type="exception", entity_id=str(item.id),
            detail={"kind": item.kind},
        )
        return item
